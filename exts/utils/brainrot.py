from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .heat import DEFAULT_LADDER_SECONDS, DEFAULT_MUTE_SECONDS, HeatSettings, HeatState, TermMatcher, effective_terms

if TYPE_CHECKING:
    import asyncpg

DEFAULT_WARN_DELETE_SECONDS = 30

MuteMode = Literal["timeout", "role"]
ConfigValue = int | str | bool | list[int] | list[str] | None

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
        if row is None:
            return HeatState()
        return HeatState(
            heat=row["heat"],
            heat_updated_at=row["heat_updated_at"],
            window_started_at=row["window_started_at"],
            window_count=row["window_count"],
            lifetime_offenses=row["lifetime_offenses"],
            repeat_until=row["repeat_until"],
            escalation_level=row["escalation_level"],
        )

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
            await conn.execute("DELETE FROM brainrot_users WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM brainrot_guilds WHERE guild_id = $1", guild_id)
        self.invalidate(guild_id)
