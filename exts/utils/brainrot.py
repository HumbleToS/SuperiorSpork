from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import discord
from discord.ext import commands

from .heat import (
    DECAY_SECONDS,
    DEFAULT_LADDER_SECONDS,
    DEFAULT_MUTE_SECONDS,
    HeatSettings,
    HeatState,
    TermMatcher,
    effective_terms,
)

if TYPE_CHECKING:
    import asyncpg

DEFAULT_WARN_DELETE_SECONDS = 30
ACTION_RETENTION_DAYS = 30
MAX_ACTIONS_PER_GUILD = 5000  # the daily cleanup keeps this many newest rows per server
MAX_CHANNELS = 50
MAX_CUSTOM_TERMS = 100
MAX_EXEMPTIONS = 50
MIN_TERM_LENGTH = 3
MAX_TERM_LENGTH = 40
MAX_LADDER_STEPS = 5
MAX_WARN_SECONDS = 600
MIN_MUTE_SECONDS = 60  # the command takes whole minutes
# lifetime offenses needed for each leaderboard title, lowest first
TIERS: tuple[tuple[int, str], ...] = (
    (0, "Raw"),
    (1, "Lightly Seared"),
    (5, "Medium"),
    (15, "Well Done"),
    (30, "Cooked"),
    (60, "Burnt"),
    (100, "Charcoal"),
)

MuteMode = Literal["timeout", "role"]
WatchableChannel = discord.TextChannel | discord.VoiceChannel | discord.ForumChannel | discord.Thread
ConfigValue = int | str | bool | list[int] | list[str] | None
ActionKind = Literal["warning", "spam", "mute", "timeout", "pardon", "config"]
ActionSource = Literal["auto", "command", "dashboard"]
OffenderSort = Literal["heat", "lifetime"]
ACTION_KINDS: frozenset[str] = frozenset({"warning", "spam", "mute", "timeout", "pardon", "config"})
ACTION_SOURCES: frozenset[str] = frozenset({"auto", "command", "dashboard"})

# decayed heat, in SQL, with the engine's formula: one whole point per DECAY_SECONDS since the last change
_HEAT_NOW = f"GREATEST(heat - floor(extract(epoch from ($2::timestamptz - heat_updated_at)) / {DECAY_SECONDS})::integer, 0)"


class BrainrotError(commands.CommandError):
    """A refusal the admin can act on; the message is what the slash command would have replied."""

    def __init__(self, code: str, message: str, *, field: str | None = None, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.problems = problems or []


_CONFIG_COLUMNS = frozenset(
    {
        "enabled",
        "channel_ids",
        "added_terms",
        "removed_terms",
        "allowed_terms",
        "exempt_role_ids",
        "exempt_user_ids",
        "mute_mode",
        "mute_role_id",
        "mute_seconds",
        "ladder_seconds",
        "warn_delete_seconds",
        "delete_messages",
        "include_mods",
        "modlog_channel_id",
    }
)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def tier_title(offenses: int) -> str:
    title = TIERS[0][1]
    for threshold, name in TIERS:
        if offenses >= threshold:
            title = name
    return title


@dataclass
class BrainrotConfig:
    guild_id: int
    enabled: bool = False
    channel_ids: frozenset[int] = frozenset()
    added_terms: tuple[str, ...] = ()
    removed_terms: tuple[str, ...] = ()
    allowed_terms: tuple[str, ...] = ()
    exempt_role_ids: frozenset[int] = frozenset()
    exempt_user_ids: frozenset[int] = frozenset()
    mute_mode: MuteMode = "timeout"
    mute_role_id: int | None = None
    mute_seconds: int = DEFAULT_MUTE_SECONDS
    ladder_seconds: tuple[int, ...] = DEFAULT_LADDER_SECONDS
    warn_delete_seconds: int = DEFAULT_WARN_DELETE_SECONDS
    delete_messages: bool = False
    include_mods: bool = False
    modlog_channel_id: int | None = None
    matcher: TermMatcher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # compiled once per config load, so the message hot path never touches a regex compiler
        self.matcher = TermMatcher(effective_terms(self.added_terms, self.removed_terms, self.allowed_terms))

    @classmethod
    def from_row(cls, guild_id: int, row: asyncpg.Record | None) -> BrainrotConfig:
        if row is None:
            return cls(guild_id)
        mode = row["mute_mode"]
        return cls(
            guild_id,
            enabled=row["enabled"],
            channel_ids=frozenset(row["channel_ids"]),
            added_terms=tuple(row["added_terms"]),
            removed_terms=tuple(row["removed_terms"]),
            allowed_terms=tuple(row["allowed_terms"]),
            exempt_role_ids=frozenset(row["exempt_role_ids"]),
            exempt_user_ids=frozenset(row["exempt_user_ids"]),
            mute_mode=mode if mode in ("timeout", "role") else "timeout",
            mute_role_id=row["mute_role_id"],
            mute_seconds=row["mute_seconds"],
            ladder_seconds=tuple(row["ladder_seconds"]),
            warn_delete_seconds=row["warn_delete_seconds"],
            delete_messages=row["delete_messages"],
            include_mods=row["include_mods"],
            modlog_channel_id=row["modlog_channel_id"],
        )

    @property
    def terms(self) -> tuple[str, ...]:
        return self.matcher.terms

    @property
    def settings(self) -> HeatSettings:
        return HeatSettings(mute_seconds=self.mute_seconds, ladder_seconds=self.ladder_seconds)


class BrainrotStore:
    """Accessor for the anti-brainrot tables. Every query the module runs lives here."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool
        self._configs: dict[int, BrainrotConfig] = {}

    # per-guild config, cached and invalidated on write

    async def get_config(self, guild_id: int) -> BrainrotConfig:
        cached = self._configs.get(guild_id)
        if cached is not None:
            return cached
        row = await self.pool.fetchrow("SELECT * FROM brainrot_guilds WHERE guild_id = $1", guild_id)
        config = BrainrotConfig.from_row(guild_id, row)
        self._configs[guild_id] = config
        return config

    def cached_config(self, guild_id: int) -> BrainrotConfig | None:
        return self._configs.get(guild_id)

    def invalidate(self, guild_id: int) -> None:
        self._configs.pop(guild_id, None)

    async def set_config(self, guild_id: int, column: str, value: ConfigValue) -> BrainrotConfig:
        if column not in _CONFIG_COLUMNS:
            raise ValueError(f"not a brainrot config column: {column}")
        await self.pool.execute(  # the column name is interpolated, which is safe only because of the whitelist above
            f"INSERT INTO brainrot_guilds (guild_id, {column}) VALUES ($1, $2)"
            f" ON CONFLICT (guild_id) DO UPDATE SET {column} = $2",
            guild_id,
            value,
        )
        self.invalidate(guild_id)
        return await self.get_config(guild_id)

    # per-user heat state

    async def get_state(self, guild_id: int, user_id: int) -> HeatState:
        row = await self.pool.fetchrow(
            "SELECT heat, heat_updated_at, window_started_at, window_count, lifetime_offenses, repeat_until,"
            " escalation_level FROM brainrot_users WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return HeatState.from_row(row) if row is not None else HeatState()

    async def put_state(self, guild_id: int, user_id: int, state: HeatState) -> None:
        await self.pool.execute(
            "INSERT INTO brainrot_users (guild_id, user_id, heat, heat_updated_at, window_started_at, window_count,"
            " lifetime_offenses, repeat_until, escalation_level) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET heat = $3, heat_updated_at = $4, window_started_at = $5,"
            " window_count = $6, lifetime_offenses = $7, repeat_until = $8, escalation_level = $9",
            guild_id,
            user_id,
            state.heat,
            state.heat_updated_at or _now(),
            state.window_started_at,
            state.window_count,
            state.lifetime_offenses,
            state.repeat_until,
            state.escalation_level,
        )

    # mutes the bot applied, so it can undo exactly those and nothing else

    async def set_mute(self, guild_id: int, user_id: int, expires_at: datetime.datetime, role_id: int | None) -> None:
        await self.pool.execute(
            "UPDATE brainrot_users SET mute_expires_at = $3, muted_role_id = $4 WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
            expires_at,
            role_id,
        )

    async def clear_mute(self, guild_id: int, user_id: int) -> None:
        await self.pool.execute(
            "UPDATE brainrot_users SET mute_expires_at = NULL, muted_role_id = NULL WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def get_mute(self, guild_id: int, user_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "SELECT mute_expires_at, muted_role_id FROM brainrot_users"
            " WHERE guild_id = $1 AND user_id = $2 AND mute_expires_at > $3",
            guild_id,
            user_id,
            _now(),
        )

    async def expired_role_mutes(self) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "SELECT guild_id, user_id, muted_role_id FROM brainrot_users"
            " WHERE muted_role_id IS NOT NULL AND mute_expires_at <= $1",
            _now(),
        )

    async def pending_role_mute(self, guild_id: int, user_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "SELECT muted_role_id, mute_expires_at FROM brainrot_users"
            " WHERE guild_id = $1 AND user_id = $2 AND muted_role_id IS NOT NULL AND mute_expires_at > $3",
            guild_id,
            user_id,
            _now(),
        )

    # leaderboard and housekeeping

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "SELECT user_id, lifetime_offenses FROM brainrot_users WHERE guild_id = $1 AND lifetime_offenses > 0"
            " ORDER BY lifetime_offenses DESC, user_id LIMIT $2",
            guild_id,
            limit,
        )

    async def rank(self, guild_id: int, user_id: int) -> int | None:
        return await self.pool.fetchval(
            "SELECT (SELECT count(*) + 1 FROM brainrot_users AS others"
            " WHERE others.guild_id = me.guild_id AND others.lifetime_offenses > me.lifetime_offenses)"
            " FROM brainrot_users AS me WHERE me.guild_id = $1 AND me.user_id = $2 AND me.lifetime_offenses > 0",
            guild_id,
            user_id,
        )

    async def prune_idle(self) -> int:
        # rows with nothing left to remember: no lifetime count, heat decayed away, no repeat flag, no mute
        result = await self.pool.execute(
            "DELETE FROM brainrot_users WHERE lifetime_offenses = 0 AND mute_expires_at IS NULL"
            " AND (repeat_until IS NULL OR repeat_until < $1)"
            " AND heat_updated_at + make_interval(hours => heat) <= $1",
            _now(),
        )
        return int(result.split()[-1])

    async def purge_guild(self, guild_id: int) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM brainrot_actions WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM brainrot_users WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM brainrot_guilds WHERE guild_id = $1", guild_id)
        self.invalidate(guild_id)

    # dashboard reads: every user with any history, ordered and counted in SQL

    async def offenders(
        self, guild_id: int, *, page: int, per_page: int, sort: OffenderSort = "heat"
    ) -> tuple[list[asyncpg.Record], int]:
        if sort == "lifetime":
            where, order, args = "guild_id = $1 AND lifetime_offenses > 0", "lifetime_offenses DESC, user_id", [guild_id]
        else:
            where = "guild_id = $1"
            order = f"{_HEAT_NOW} DESC, lifetime_offenses DESC, user_id"
            args = [guild_id, _now()]
        limit = len(args) + 1
        rows = await self.pool.fetch(
            f"SELECT user_id, heat, heat_updated_at, window_started_at, window_count, lifetime_offenses, repeat_until,"
            f" escalation_level, mute_expires_at, muted_role_id,"
            f" rank() OVER (ORDER BY lifetime_offenses DESC) AS rank"
            f" FROM brainrot_users WHERE {where} ORDER BY {order} LIMIT ${limit} OFFSET ${limit + 1}",
            *args,
            per_page,
            (page - 1) * per_page,
        )
        total = await self.pool.fetchval(f"SELECT count(*) FROM brainrot_users WHERE {where}", guild_id)
        return rows, int(total or 0)

    async def summary(self, guild_id: int) -> asyncpg.Record:
        return await self.pool.fetchrow(
            f"SELECT count(*) FILTER (WHERE {_HEAT_NOW} > 0) AS hot_users,"
            " count(*) FILTER (WHERE mute_expires_at > $2) AS muted_now,"
            " count(*) FILTER (WHERE repeat_until > $2) AS on_repeat_list,"
            " coalesce(sum(lifetime_offenses), 0) AS lifetime_offenses"
            " FROM brainrot_users WHERE guild_id = $1",
            guild_id,
            _now(),
        )

    # the action log: what happened, to whom, by whom; never what was said

    async def log_action(
        self,
        guild_id: int,
        action: ActionKind,
        source: ActionSource,
        *,
        target_user_id: int | None = None,
        actor_user_id: int | None = None,
        applied: bool = True,
        heat: int | None = None,
        heat_added: int | None = None,
        duration_seconds: int | None = None,
        escalation_level: int | None = None,
        field: str | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        await self.pool.execute(
            "INSERT INTO brainrot_actions (guild_id, at, action, source, applied, target_user_id, actor_user_id, heat,"
            " heat_added, duration_seconds, escalation_level, field, before, after)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
            guild_id,
            _now(),
            action,
            source,
            applied,
            target_user_id,
            actor_user_id,
            heat,
            heat_added,
            duration_seconds,
            escalation_level,
            field,
            before,
            after,
        )

    async def actions(
        self, guild_id: int, *, page: int, per_page: int, action: str | None = None, source: str | None = None
    ) -> tuple[list[asyncpg.Record], int]:
        where = "guild_id = $1 AND ($2::text IS NULL OR action = $2) AND ($3::text IS NULL OR source = $3)"
        rows = await self.pool.fetch(
            f"SELECT * FROM brainrot_actions WHERE {where} ORDER BY at DESC, id DESC LIMIT $4 OFFSET $5",
            guild_id,
            action,
            source,
            per_page,
            (page - 1) * per_page,
        )
        total = await self.pool.fetchval(f"SELECT count(*) FROM brainrot_actions WHERE {where}", guild_id, action, source)
        return rows, int(total or 0)

    async def count_actions_since(self, guild_id: int, since: datetime.datetime) -> int:
        count = await self.pool.fetchval(
            "SELECT count(*) FROM brainrot_actions WHERE guild_id = $1 AND at >= $2", guild_id, since
        )
        return int(count or 0)

    async def prune_actions(self) -> int:
        cutoff = _now() - datetime.timedelta(days=ACTION_RETENTION_DAYS)
        async with self.pool.acquire() as conn, conn.transaction():
            aged = await conn.execute("DELETE FROM brainrot_actions WHERE at < $1", cutoff)
            capped = await conn.execute(
                "DELETE FROM brainrot_actions WHERE id IN (SELECT id FROM (SELECT id, row_number() OVER"
                " (PARTITION BY guild_id ORDER BY at DESC, id DESC) AS n FROM brainrot_actions) AS ranked WHERE n > $1)",
                MAX_ACTIONS_PER_GUILD,
            )
        return int(aged.split()[-1]) + int(capped.split()[-1])
