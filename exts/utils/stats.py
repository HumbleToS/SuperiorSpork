from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    import asyncpg

GRACE_DAYS = 7  # a departed server's counts survive this long, in case the kick was an accident
BASELINE_DAYS = 30  # a whois baseline from the search index is trusted this long before one new search refreshes it
DEFAULT_FLUSH_SECONDS = 60
TOP_LIMIT = 8
MAX_COMMAND_LENGTH = 100
HOURS = 24
# the whois ladder: a name and the lifetime message count that earns it, lowest first
RANKS: tuple[tuple[str, int], ...] = (
    ("Touches Grass", 0),
    ("Lurker", 100),
    ("Occasionally Online", 500),
    ("Chronically Online", 1_000),
    ("No Life", 2_500),
    ("Keyboard Warrior", 5_000),
    ("Legend", 10_000),
    ("Terminally Online", 25_000),
    ("Basement Dweller", 50_000),
    ("Allergic to Sunlight", 100_000),
    ("Vitamin D Deficient", 150_000),
    ("Has Not Blinked Since 2019", 200_000),
    ("Married to the Server", 250_000),
    ("Legally Part of the Furniture", 300_000),
)

MessageKey = tuple[int, int, int, datetime.date, int]  # guild, channel, user, day, hour
DayKey = tuple[int, datetime.date]  # guild, day
CommandKey = tuple[int, int, str, datetime.date]  # guild, user, command, day
GuildDayRow = tuple[int, datetime.date, int, int, int, int]  # guild, day, messages, joins, leaves, commands
ChannelDayRow = tuple[int, int, datetime.date, int]  # guild, channel, day, messages
HourDayRow = tuple[int, datetime.date, int, int]  # guild, day, hour, messages
UserDayRow = tuple[int, int, datetime.date, int, int]  # guild, user, day, messages, commands
UserChannelDayRow = tuple[int, int, int, datetime.date, int]  # guild, user, channel, day, messages
UserHourDayRow = tuple[int, int, datetime.date, int, int]  # guild, user, day, hour, messages
CommandDayRow = tuple[int, int, str, datetime.date, int]  # guild, user, command, day, uses


def _utc(at: datetime.datetime) -> datetime.datetime:
    return at.astimezone(datetime.UTC) if at.tzinfo is not None else at.replace(tzinfo=datetime.UTC)


@dataclass(frozen=True)
class Batch:
    """One flush's worth of rows, each tuple in its table's column order. Counts and ids only."""

    guild_days: tuple[GuildDayRow, ...] = ()
    channel_days: tuple[ChannelDayRow, ...] = ()
    hour_days: tuple[HourDayRow, ...] = ()
    user_days: tuple[UserDayRow, ...] = ()
    user_channel_days: tuple[UserChannelDayRow, ...] = ()
    user_hour_days: tuple[UserHourDayRow, ...] = ()
    command_days: tuple[CommandDayRow, ...] = ()

    @property
    def rows(self) -> int:
        return (
            len(self.guild_days)
            + len(self.channel_days)
            + len(self.hour_days)
            + len(self.user_days)
            + len(self.user_channel_days)
            + len(self.user_hour_days)
            + len(self.command_days)
        )

    @property
    def guild_ids(self) -> frozenset[int]:
        return frozenset(row[0] for row in self.guild_days)


@dataclass
class Counters:
    """Counts accumulated between flushes. Never a message's text: ids, dates, hours, and command names only."""

    messages: Counter[MessageKey] = field(default_factory=Counter)
    joins: Counter[DayKey] = field(default_factory=Counter)
    leaves: Counter[DayKey] = field(default_factory=Counter)
    commands: Counter[CommandKey] = field(default_factory=Counter)

    def record_message(self, guild_id: int, channel_id: int, user_id: int, at: datetime.datetime) -> None:
        at = _utc(at)
        self.messages[(guild_id, channel_id, user_id, at.date(), at.hour)] += 1

    def record_join(self, guild_id: int, at: datetime.datetime) -> None:
        self.joins[(guild_id, _utc(at).date())] += 1

    def record_leave(self, guild_id: int, at: datetime.datetime) -> None:
        self.leaves[(guild_id, _utc(at).date())] += 1

    def record_command(self, guild_id: int, user_id: int, command: str, at: datetime.datetime) -> None:
        self.commands[(guild_id, user_id, command[:MAX_COMMAND_LENGTH], _utc(at).date())] += 1

    def pending_messages(self, guild_id: int, user_id: int) -> int:
        """Messages counted for one member since the last flush."""
        return sum(count for (guild, _, user, _, _), count in self.messages.items() if guild == guild_id and user == user_id)

    def forget_guild(self, guild_id: int) -> None:
        for counter in (self.messages, self.joins, self.leaves, self.commands):
            for key in [key for key in counter if key[0] == guild_id]:
                del counter[key]

    def is_empty(self) -> bool:
        return not (self.messages or self.joins or self.leaves or self.commands)

    def drain(self) -> Batch:
        """Folds everything counted so far into per-table rows and starts over."""
        messages, joins, leaves, commands = self.messages, self.joins, self.leaves, self.commands
        self.messages, self.joins, self.leaves, self.commands = Counter(), Counter(), Counter(), Counter()

        guild_messages: Counter[DayKey] = Counter()
        guild_commands: Counter[DayKey] = Counter()
        channel_days: Counter[tuple[int, int, datetime.date]] = Counter()
        hour_days: Counter[tuple[int, datetime.date, int]] = Counter()
        user_messages: Counter[tuple[int, int, datetime.date]] = Counter()
        user_commands: Counter[tuple[int, int, datetime.date]] = Counter()
        user_channel_days: Counter[tuple[int, int, int, datetime.date]] = Counter()
        user_hour_days: Counter[tuple[int, int, datetime.date, int]] = Counter()
        for (guild_id, channel_id, user_id, day, hour), n in messages.items():
            guild_messages[(guild_id, day)] += n
            channel_days[(guild_id, channel_id, day)] += n
            hour_days[(guild_id, day, hour)] += n
            user_messages[(guild_id, user_id, day)] += n
            user_channel_days[(guild_id, user_id, channel_id, day)] += n
            user_hour_days[(guild_id, user_id, day, hour)] += n
        for (guild_id, user_id, _, day), n in commands.items():
            guild_commands[(guild_id, day)] += n
            user_commands[(guild_id, user_id, day)] += n

        guild_keys = sorted(set(guild_messages) | set(joins) | set(leaves) | set(guild_commands))
        user_keys = sorted(set(user_messages) | set(user_commands))
        return Batch(
            guild_days=tuple(
                (g, d, guild_messages[(g, d)], joins[(g, d)], leaves[(g, d)], guild_commands[(g, d)]) for g, d in guild_keys
            ),
            channel_days=tuple((g, c, d, n) for (g, c, d), n in sorted(channel_days.items())),
            hour_days=tuple((g, d, h, n) for (g, d, h), n in sorted(hour_days.items())),
            user_days=tuple((g, u, d, user_messages[(g, u, d)], user_commands[(g, u, d)]) for g, u, d in user_keys),
            user_channel_days=tuple((g, u, c, d, n) for (g, u, c, d), n in sorted(user_channel_days.items())),
            user_hour_days=tuple((g, u, d, h, n) for (g, u, d, h), n in sorted(user_hour_days.items())),
            command_days=tuple((g, u, c, d, n) for (g, u, c, d), n in sorted(commands.items())),
        )


# plain typed results, so charts and a future dashboard read the same shapes


@dataclass(frozen=True)
class DaySpan:
    start: datetime.date
    end: datetime.date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def __iter__(self) -> Iterator[datetime.date]:
        return (self.start + datetime.timedelta(days=offset) for offset in range(self.days))


@dataclass(frozen=True)
class DayCount:
    day: datetime.date
    count: int


@dataclass(frozen=True)
class JoinLeave:
    day: datetime.date
    joins: int
    leaves: int


@dataclass(frozen=True)
class HourCount:
    hour: int
    count: int


@dataclass(frozen=True)
class ChannelCount:
    channel_id: int
    count: int


@dataclass(frozen=True)
class CommandCount:
    command: str
    count: int


@dataclass(frozen=True)
class MemberRank:
    rank: int  # 1 is the most active
    ranked: int  # members with at least one message in the span
    messages: int

    @property
    def top_percent(self) -> float:
        return 100 * self.rank / self.ranked


@dataclass(frozen=True)
class GuildActivity:
    guild_id: int
    span: DaySpan
    tracking_since: datetime.datetime | None
    messages: tuple[DayCount, ...]
    active_users: tuple[DayCount, ...]
    joins_leaves: tuple[JoinLeave, ...]
    hours: tuple[HourCount, ...]
    top_channels: tuple[ChannelCount, ...]

    @property
    def total_messages(self) -> int:
        return sum(point.count for point in self.messages)


@dataclass(frozen=True)
class MemberActivity:
    guild_id: int
    user_id: int
    span: DaySpan
    tracking_since: datetime.datetime | None
    messages: tuple[DayCount, ...]
    hours: tuple[HourCount, ...]
    top_channels: tuple[ChannelCount, ...]
    top_commands: tuple[CommandCount, ...]
    rank: MemberRank | None

    @property
    def total_messages(self) -> int:
        return sum(point.count for point in self.messages)


# pure helpers


@dataclass(frozen=True)
class MessageTotal:
    """A member's baseline from the search index, and what the daily tables held for them when it was taken."""

    total: int
    counted: int
    searched_at: datetime.datetime

    def estimate(self, counted_now: int) -> int:
        return self.total + max(0, counted_now - self.counted)


@dataclass(frozen=True)
class Rank:
    name: str
    floor: int
    next_name: str | None = None
    next_floor: int | None = None


def rank_for(total: int) -> Rank:
    """The ladder rung a lifetime message count earns, and the next one up."""
    index = 0
    for position, (_, floor) in enumerate(RANKS):
        if total >= floor:
            index = position
    name, floor = RANKS[index]
    if index + 1 < len(RANKS):
        next_name, next_floor = RANKS[index + 1]
        return Rank(name, floor, next_name, next_floor)
    return Rank(name, floor)


@dataclass(frozen=True)
class GuildFootprint:
    guild_id: int
    rows: int
    people: int


@dataclass(frozen=True)
class Footprint:
    """How much the activity tables hold: the servers with the most rows, and the totals behind them."""

    guilds: tuple[GuildFootprint, ...]
    servers: int
    people: int
    oldest_day: datetime.date | None


def day_span(days: int, today: datetime.date) -> DaySpan:
    """The last `days` days ending today, inclusive."""
    days = max(1, days)
    return DaySpan(today - datetime.timedelta(days=days - 1), today)


def fill_days(counts: Mapping[datetime.date, int], span: DaySpan) -> tuple[DayCount, ...]:
    """A dense series over the span, zero where nothing was counted."""
    return tuple(DayCount(day, counts.get(day, 0)) for day in span)


def fill_join_leaves(
    joins: Mapping[datetime.date, int], leaves: Mapping[datetime.date, int], span: DaySpan
) -> tuple[JoinLeave, ...]:
    return tuple(JoinLeave(day, joins.get(day, 0), leaves.get(day, 0)) for day in span)


def fill_hours(counts: Mapping[int, int]) -> tuple[HourCount, ...]:
    return tuple(HourCount(hour, counts.get(hour, 0)) for hour in range(HOURS))


def started_within(tracking_since: datetime.datetime | None, span: DaySpan) -> bool:
    """Whether collection began inside the span, which is when a chart should say so."""
    return tracking_since is not None and _utc(tracking_since).date() > span.start


_DAILY_TABLES = (
    "stats_guild_days",
    "stats_channel_days",
    "stats_hour_days",
    "stats_user_days",
    "stats_user_channel_days",
    "stats_user_hour_days",
    "stats_command_days",
)
_TOTALS_TABLE = "stats_message_totals"
_GUILD_TABLES = (*_DAILY_TABLES, _TOTALS_TABLE)  # everything keyed by server, for the opt-out and the departed sweep
_USER_TABLES = ("stats_user_days", "stats_user_channel_days", "stats_user_hour_days", "stats_command_days", _TOTALS_TABLE)


class StatsStore:
    """Accessor for the stats tables: batched upserts in, plain typed data out. Every query lives here."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    # writes

    async def flush(self, batch: Batch, at: datetime.datetime) -> None:
        if not batch.rows:
            return
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.executemany(
                "INSERT INTO stats_guilds (guild_id, tracking_since) VALUES ($1, $2)"
                " ON CONFLICT (guild_id) DO UPDATE SET tracking_since = coalesce(stats_guilds.tracking_since, $2)",
                [(guild_id, at) for guild_id in sorted(batch.guild_ids)],
            )
            await connection.executemany(
                "INSERT INTO stats_guild_days (guild_id, day, messages, joins, leaves, commands)"
                " VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (guild_id, day) DO UPDATE SET"
                " messages = stats_guild_days.messages + $3, joins = stats_guild_days.joins + $4,"
                " leaves = stats_guild_days.leaves + $5, commands = stats_guild_days.commands + $6",
                batch.guild_days,
            )
            await connection.executemany(
                "INSERT INTO stats_channel_days (guild_id, channel_id, day, messages) VALUES ($1, $2, $3, $4)"
                " ON CONFLICT (guild_id, channel_id, day) DO UPDATE SET messages = stats_channel_days.messages + $4",
                batch.channel_days,
            )
            await connection.executemany(
                "INSERT INTO stats_hour_days (guild_id, day, hour, messages) VALUES ($1, $2, $3, $4)"
                " ON CONFLICT (guild_id, day, hour) DO UPDATE SET messages = stats_hour_days.messages + $4",
                batch.hour_days,
            )
            await connection.executemany(
                "INSERT INTO stats_user_days (guild_id, user_id, day, messages, commands) VALUES ($1, $2, $3, $4, $5)"
                " ON CONFLICT (guild_id, user_id, day) DO UPDATE SET"
                " messages = stats_user_days.messages + $4, commands = stats_user_days.commands + $5",
                batch.user_days,
            )
            await connection.executemany(
                "INSERT INTO stats_user_channel_days (guild_id, user_id, channel_id, day, messages)"
                " VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, user_id, channel_id, day)"
                " DO UPDATE SET messages = stats_user_channel_days.messages + $5",
                batch.user_channel_days,
            )
            await connection.executemany(
                "INSERT INTO stats_user_hour_days (guild_id, user_id, day, hour, messages) VALUES ($1, $2, $3, $4, $5)"
                " ON CONFLICT (guild_id, user_id, day, hour) DO UPDATE SET messages = stats_user_hour_days.messages + $5",
                batch.user_hour_days,
            )
            await connection.executemany(
                "INSERT INTO stats_command_days (guild_id, user_id, command, day, uses) VALUES ($1, $2, $3, $4, $5)"
                " ON CONFLICT (guild_id, user_id, command, day) DO UPDATE SET uses = stats_command_days.uses + $5",
                batch.command_days,
            )

    async def disabled_guilds(self) -> set[int]:
        rows = await self.pool.fetch("SELECT guild_id FROM stats_guilds WHERE NOT enabled")
        return {row["guild_id"] for row in rows}

    async def tracking_since(self, guild_id: int) -> datetime.datetime | None:
        return await self.pool.fetchval("SELECT tracking_since FROM stats_guilds WHERE guild_id = $1", guild_id)

    async def set_enabled(self, guild_id: int, enabled: bool, at: datetime.datetime) -> None:
        """Turning a server off also deletes everything stored for it; turning it on starts a fresh tracking date."""
        async with self.pool.acquire() as connection, connection.transaction():
            if not enabled:
                for table in _GUILD_TABLES:
                    # table names are interpolated, which is safe only because they come from the tuples above
                    await connection.execute(f"DELETE FROM {table} WHERE guild_id = $1", guild_id)
            await connection.execute(
                "INSERT INTO stats_guilds (guild_id, enabled, tracking_since) VALUES ($1, $2, $3)"
                " ON CONFLICT (guild_id) DO UPDATE SET enabled = $2,"
                " tracking_since = CASE WHEN $2 THEN coalesce(stats_guilds.tracking_since, $3) ELSE NULL END",
                guild_id,
                enabled,
                at if enabled else None,
            )

    async def mark_left(self, guild_id: int, at: datetime.datetime) -> None:
        await self.pool.execute(
            "INSERT INTO stats_guilds (guild_id, left_at) VALUES ($1, $2)"
            " ON CONFLICT (guild_id) DO UPDATE SET left_at = coalesce(stats_guilds.left_at, $2)",
            guild_id,
            at,
        )

    async def mark_present(self, guild_id: int) -> None:
        await self.pool.execute("UPDATE stats_guilds SET left_at = NULL WHERE guild_id = $1", guild_id)

    async def present_guilds(self) -> set[int]:
        rows = await self.pool.fetch("SELECT guild_id FROM stats_guilds WHERE left_at IS NULL")
        return {row["guild_id"] for row in rows}

    async def purge_departed(self, now: datetime.datetime, grace_days: int = GRACE_DAYS) -> list[int]:
        """Drops every server whose grace period has run out; returns the ids it purged."""
        cutoff = now - datetime.timedelta(days=grace_days)
        rows = await self.pool.fetch("SELECT guild_id FROM stats_guilds WHERE left_at < $1 ORDER BY guild_id", cutoff)
        purged = [row["guild_id"] for row in rows]
        for guild_id in purged:
            await self.purge_guild(guild_id)
        return purged

    async def purge_guild(self, guild_id: int) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            for table in (*_GUILD_TABLES, "stats_guilds"):
                await connection.execute(f"DELETE FROM {table} WHERE guild_id = $1", guild_id)

    async def purge_user(self, user_id: int, guild_id: int | None = None) -> int:
        """Deletes a user's rows everywhere, or in one server; returns how many rows went."""
        deleted = 0
        async with self.pool.acquire() as connection, connection.transaction():
            for table in _USER_TABLES:
                if guild_id is None:
                    status = await connection.execute(f"DELETE FROM {table} WHERE user_id = $1", user_id)
                else:
                    status = await connection.execute(
                        f"DELETE FROM {table} WHERE user_id = $1 AND guild_id = $2",
                        user_id,
                        guild_id,
                    )
                deleted += int(status.rsplit(" ", 1)[-1])
        return deleted

    # lifetime totals behind whois ranks: one search baseline per member, refreshed rarely, counted on top of

    async def message_total(self, guild_id: int, user_id: int) -> MessageTotal | None:
        row = await self.pool.fetchrow(
            f"SELECT total, counted, searched_at FROM {_TOTALS_TABLE} WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return MessageTotal(row["total"], row["counted"], row["searched_at"]) if row is not None else None

    async def set_message_total(self, guild_id: int, user_id: int, total: int, counted: int, at: datetime.datetime) -> None:
        await self.pool.execute(
            f"INSERT INTO {_TOTALS_TABLE} (guild_id, user_id, total, counted, searched_at) VALUES ($1, $2, $3, $4, $5)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET total = $3, counted = $4, searched_at = $5",
            guild_id,
            user_id,
            total,
            counted,
            at,
        )

    async def member_messages_total(self, guild_id: int, user_id: int) -> int:
        """Every message the collector has counted for one member of one server, flushed so far."""
        total = await self.pool.fetchval(
            "SELECT coalesce(sum(messages), 0) FROM stats_user_days WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        return int(total)

    # what is stored, and for whom

    async def footprint(self, limit: int = TOP_LIMIT) -> Footprint:
        """Rows per server across every daily table, with how many people each covers, largest first."""
        per_table = " UNION ALL ".join(
            f"SELECT guild_id, count(*) AS n FROM {table} GROUP BY guild_id" for table in _GUILD_TABLES
        )
        rows = await self.pool.fetch(
            f"SELECT counted.guild_id, sum(counted.n)::bigint AS rows, coalesce(people.people, 0)::bigint AS people"
            f" FROM ({per_table}) AS counted"
            " LEFT JOIN (SELECT guild_id, count(DISTINCT user_id) AS people FROM stats_user_days GROUP BY guild_id)"
            " AS people USING (guild_id)"
            " GROUP BY counted.guild_id, people.people ORDER BY rows DESC, counted.guild_id LIMIT $1",
            limit,
        )
        servers = await self.pool.fetchval("SELECT count(DISTINCT guild_id) FROM stats_guild_days")
        people = await self.pool.fetchval("SELECT count(DISTINCT user_id) FROM stats_user_days")
        oldest = await self.pool.fetchval("SELECT min(day) FROM stats_guild_days")
        return Footprint(
            guilds=tuple(GuildFootprint(row["guild_id"], row["rows"], row["people"]) for row in rows),
            servers=int(servers),
            people=int(people),
            oldest_day=oldest,
        )

    # server queries

    async def messages_per_day(self, guild_id: int, span: DaySpan) -> tuple[DayCount, ...]:
        rows = await self.pool.fetch(
            "SELECT day, messages FROM stats_guild_days WHERE guild_id = $1 AND day BETWEEN $2 AND $3",
            guild_id,
            span.start,
            span.end,
        )
        return fill_days({row["day"]: row["messages"] for row in rows}, span)

    async def active_users_per_day(self, guild_id: int, span: DaySpan) -> tuple[DayCount, ...]:
        rows = await self.pool.fetch(
            "SELECT day, count(*) AS n FROM stats_user_days"
            " WHERE guild_id = $1 AND day BETWEEN $2 AND $3 AND messages > 0 GROUP BY day",
            guild_id,
            span.start,
            span.end,
        )
        return fill_days({row["day"]: row["n"] for row in rows}, span)

    async def joins_leaves_per_day(self, guild_id: int, span: DaySpan) -> tuple[JoinLeave, ...]:
        rows = await self.pool.fetch(
            "SELECT day, joins, leaves FROM stats_guild_days WHERE guild_id = $1 AND day BETWEEN $2 AND $3",
            guild_id,
            span.start,
            span.end,
        )
        joins = {row["day"]: row["joins"] for row in rows}
        leaves = {row["day"]: row["leaves"] for row in rows}
        return fill_join_leaves(joins, leaves, span)

    async def messages_by_hour(self, guild_id: int, span: DaySpan) -> tuple[HourCount, ...]:
        rows = await self.pool.fetch(
            "SELECT hour, sum(messages) AS n FROM stats_hour_days"
            " WHERE guild_id = $1 AND day BETWEEN $2 AND $3 GROUP BY hour",
            guild_id,
            span.start,
            span.end,
        )
        return fill_hours({row["hour"]: row["n"] for row in rows})

    async def top_channels(self, guild_id: int, span: DaySpan, limit: int = TOP_LIMIT) -> tuple[ChannelCount, ...]:
        rows = await self.pool.fetch(
            "SELECT channel_id, sum(messages) AS n FROM stats_channel_days"
            " WHERE guild_id = $1 AND day BETWEEN $2 AND $3 GROUP BY channel_id ORDER BY n DESC, channel_id LIMIT $4",
            guild_id,
            span.start,
            span.end,
            limit,
        )
        return tuple(ChannelCount(row["channel_id"], row["n"]) for row in rows)

    async def guild_activity(self, guild_id: int, span: DaySpan) -> GuildActivity:
        return GuildActivity(
            guild_id=guild_id,
            span=span,
            tracking_since=await self.tracking_since(guild_id),
            messages=await self.messages_per_day(guild_id, span),
            active_users=await self.active_users_per_day(guild_id, span),
            joins_leaves=await self.joins_leaves_per_day(guild_id, span),
            hours=await self.messages_by_hour(guild_id, span),
            top_channels=await self.top_channels(guild_id, span),
        )

    # member queries, always for one server at a time

    async def member_messages_per_day(self, guild_id: int, user_id: int, span: DaySpan) -> tuple[DayCount, ...]:
        rows = await self.pool.fetch(
            "SELECT day, messages FROM stats_user_days WHERE guild_id = $1 AND user_id = $2 AND day BETWEEN $3 AND $4",
            guild_id,
            user_id,
            span.start,
            span.end,
        )
        return fill_days({row["day"]: row["messages"] for row in rows}, span)

    async def member_messages_by_hour(self, guild_id: int, user_id: int, span: DaySpan) -> tuple[HourCount, ...]:
        rows = await self.pool.fetch(
            "SELECT hour, sum(messages) AS n FROM stats_user_hour_days"
            " WHERE guild_id = $1 AND user_id = $2 AND day BETWEEN $3 AND $4 GROUP BY hour",
            guild_id,
            user_id,
            span.start,
            span.end,
        )
        return fill_hours({row["hour"]: row["n"] for row in rows})

    async def member_top_channels(
        self, guild_id: int, user_id: int, span: DaySpan, limit: int = TOP_LIMIT
    ) -> tuple[ChannelCount, ...]:
        rows = await self.pool.fetch(
            "SELECT channel_id, sum(messages) AS n FROM stats_user_channel_days"
            " WHERE guild_id = $1 AND user_id = $2 AND day BETWEEN $3 AND $4"
            " GROUP BY channel_id ORDER BY n DESC, channel_id LIMIT $5",
            guild_id,
            user_id,
            span.start,
            span.end,
            limit,
        )
        return tuple(ChannelCount(row["channel_id"], row["n"]) for row in rows)

    async def member_top_commands(
        self, guild_id: int, user_id: int, span: DaySpan, limit: int = TOP_LIMIT
    ) -> tuple[CommandCount, ...]:
        rows = await self.pool.fetch(
            "SELECT command, sum(uses) AS n FROM stats_command_days"
            " WHERE guild_id = $1 AND user_id = $2 AND day BETWEEN $3 AND $4"
            " GROUP BY command ORDER BY n DESC, command LIMIT $5",
            guild_id,
            user_id,
            span.start,
            span.end,
            limit,
        )
        return tuple(CommandCount(row["command"], row["n"]) for row in rows)

    async def member_rank(self, guild_id: int, user_id: int, span: DaySpan) -> MemberRank | None:
        """Where the member sits among everyone who spoke in the span; None if they didn't."""
        row = await self.pool.fetchrow(
            "WITH totals AS ("
            " SELECT user_id, sum(messages) AS n FROM stats_user_days"
            " WHERE guild_id = $1 AND day BETWEEN $3 AND $4 GROUP BY user_id HAVING sum(messages) > 0)"
            " SELECT (SELECT n FROM totals WHERE user_id = $2) AS messages,"
            " (SELECT count(*) FROM totals) AS ranked,"
            " (SELECT count(*) FROM totals WHERE n > (SELECT n FROM totals WHERE user_id = $2)) + 1 AS rank",
            guild_id,
            user_id,
            span.start,
            span.end,
        )
        if row is None or row["messages"] is None:
            return None
        return MemberRank(rank=row["rank"], ranked=row["ranked"], messages=row["messages"])

    async def member_activity(self, guild_id: int, user_id: int, span: DaySpan) -> MemberActivity:
        return MemberActivity(
            guild_id=guild_id,
            user_id=user_id,
            span=span,
            tracking_since=await self.tracking_since(guild_id),
            messages=await self.member_messages_per_day(guild_id, user_id, span),
            hours=await self.member_messages_by_hour(guild_id, user_id, span),
            top_channels=await self.member_top_channels(guild_id, user_id, span),
            top_commands=await self.member_top_commands(guild_id, user_id, span),
            rank=await self.member_rank(guild_id, user_id, span),
        )
