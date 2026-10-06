"""Activity counts: the pure counters and helpers first, then the store against Postgres, then the cog offline on
real discord.py objects with an in-memory store. Nothing here ever looks at a message's text."""

import asyncio
import datetime
import itertools
from types import SimpleNamespace

import discord
import pytest
from conftest import requires_db
from discord.ext import commands
from test_brainrot_cog import (
    BOT_ID,
    CHANNEL_ID,
    GUILD_ID,
    NOW,
    OWNER_ID,
    THREAD_ID,
    USER_ID,
    guild_payload,
    user,
)

from exts.stats import Stats
from exts.utils.stats import (
    BASELINE_DAYS,
    GRACE_DAYS,
    HOURS,
    MAX_COMMAND_LENGTH,
    RANKS,
    TOP_LIMIT,
    Batch,
    ChannelCount,
    CommandCount,
    Counters,
    DayCount,
    DaySpan,
    HourCount,
    JoinLeave,
    MemberRank,
    MessageTotal,
    Rank,
    StatsStore,
    day_span,
    fill_days,
    fill_hours,
    fill_join_leaves,
    rank_for,
    started_within,
)

UTC = datetime.UTC
TODAY = datetime.date(2026, 9, 16)
AT = datetime.datetime(2026, 9, 16, 13, 5, tzinfo=UTC)
OTHER_GUILD = 2


def at(day: datetime.date, hour: int = 12) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour=hour), tzinfo=UTC)


# counters


def test_counters_fold_into_every_table_and_reset() -> None:
    counters = Counters()
    counters.record_message(1, 10, 100, AT)
    counters.record_message(1, 10, 100, AT)
    counters.record_message(1, 11, 101, AT.replace(hour=20))
    counters.record_join(1, AT)
    counters.record_leave(1, AT)
    counters.record_leave(1, AT)
    counters.record_command(1, 100, "help", AT)
    counters.record_command(1, 100, "help", AT)
    counters.record_command(1, 101, "whois", AT)
    counters.record_message(OTHER_GUILD, 20, 100, AT)

    batch = counters.drain()

    assert batch.guild_days == ((1, TODAY, 3, 1, 2, 3), (OTHER_GUILD, TODAY, 1, 0, 0, 0))
    assert batch.channel_days == ((1, 10, TODAY, 2), (1, 11, TODAY, 1), (OTHER_GUILD, 20, TODAY, 1))
    assert batch.hour_days == ((1, TODAY, 13, 2), (1, TODAY, 20, 1), (OTHER_GUILD, TODAY, 13, 1))
    assert batch.user_days == ((1, 100, TODAY, 2, 2), (1, 101, TODAY, 1, 1), (OTHER_GUILD, 100, TODAY, 1, 0))
    assert batch.user_channel_days == ((1, 100, 10, TODAY, 2), (1, 101, 11, TODAY, 1), (OTHER_GUILD, 100, 20, TODAY, 1))
    assert batch.user_hour_days == ((1, 100, TODAY, 13, 2), (1, 101, TODAY, 20, 1), (OTHER_GUILD, 100, TODAY, 13, 1))
    assert batch.command_days == ((1, 100, "help", TODAY, 2), (1, 101, "whois", TODAY, 1))
    assert batch.rows == 19 and batch.guild_ids == {1, OTHER_GUILD}

    assert counters.is_empty()
    assert counters.drain() == Batch() and Batch().rows == 0


def test_counters_split_days_and_hours_in_utc() -> None:
    counters = Counters()
    eastern = datetime.timezone(datetime.timedelta(hours=-5))
    counters.record_message(1, 10, 100, datetime.datetime(2026, 9, 16, 22, 30, tzinfo=eastern))  # 03:30 utc next day
    counters.record_message(1, 10, 100, datetime.datetime(2026, 9, 17, 3, 59))  # naive is taken as utc
    counters.record_join(1, datetime.datetime(2026, 9, 16, 23, 59, tzinfo=eastern))

    batch = counters.drain()

    assert batch.hour_days == ((1, datetime.date(2026, 9, 17), 3, 2),)
    assert batch.guild_days == ((1, datetime.date(2026, 9, 17), 2, 1, 0, 0),)


def test_counters_forget_one_guild_and_cap_command_names() -> None:
    counters = Counters()
    counters.record_message(1, 10, 100, AT)
    counters.record_join(1, AT)
    counters.record_leave(1, AT)
    counters.record_command(1, 100, "x" * 500, AT)
    counters.record_message(OTHER_GUILD, 20, 100, AT)
    counters.record_command(OTHER_GUILD, 100, "help", AT)

    counters.forget_guild(1)
    batch = counters.drain()

    assert batch.guild_ids == {OTHER_GUILD}
    assert batch.command_days == ((OTHER_GUILD, 100, "help", TODAY, 1),)

    counters.record_command(1, 100, "x" * 500, AT)
    assert counters.drain().command_days[0][2] == "x" * MAX_COMMAND_LENGTH


# pure helpers


def test_pending_messages_count_one_member_in_one_server() -> None:
    counters = Counters()
    counters.record_message(1, 10, 100, at(TODAY, 9))
    counters.record_message(1, 11, 100, at(TODAY, 21))
    counters.record_message(1, 10, 101, at(TODAY, 9))
    counters.record_message(2, 10, 100, at(TODAY, 9))
    assert counters.pending_messages(1, 100) == 2 and counters.pending_messages(1, 101) == 1
    assert counters.pending_messages(2, 100) == 1 and counters.pending_messages(3, 100) == 0
    counters.drain()
    assert counters.pending_messages(1, 100) == 0


def test_rank_ladder_climbs_and_tops_out() -> None:
    assert [floor for _, floor in RANKS] == sorted(floor for _, floor in RANKS) and RANKS[0][1] == 0
    assert rank_for(0) == Rank("Touches Grass", 0, "Lurker", 100)
    assert rank_for(99) == Rank("Touches Grass", 0, "Lurker", 100)
    assert rank_for(100) == Rank("Lurker", 100, "Occasionally Online", 500)
    assert rank_for(2_499).name == "Chronically Online" and rank_for(2_500).name == "No Life"
    assert rank_for(10_000).name == "Legend"
    assert rank_for(100_000) == Rank("Allergic to Sunlight", 100_000, "Vitamin D Deficient", 150_000)
    assert rank_for(299_999).name == "Married to the Server"
    assert rank_for(300_000) == Rank("Legally Part of the Furniture", 300_000) and rank_for(10**9).next_name is None
    assert MessageTotal(1200, 40, at(TODAY)).estimate(55) == 1215 and MessageTotal(1200, 40, at(TODAY)).estimate(10) == 1200


def test_day_span_and_fills() -> None:
    span = day_span(7, TODAY)
    assert span == DaySpan(datetime.date(2026, 9, 10), TODAY) and span.days == 7
    days = list(span)
    assert days[0] == datetime.date(2026, 9, 10) and days[-1] == TODAY
    assert day_span(0, TODAY).days == 1

    filled = fill_days({TODAY: 4, datetime.date(2026, 9, 12): 1, datetime.date(2000, 1, 1): 9}, span)
    assert len(filled) == 7 and filled[-1] == DayCount(TODAY, 4) and filled[2] == DayCount(datetime.date(2026, 9, 12), 1)
    assert sum(point.count for point in filled) == 5

    joined = fill_join_leaves({TODAY: 2}, {datetime.date(2026, 9, 10): 3}, span)
    assert joined[0] == JoinLeave(datetime.date(2026, 9, 10), 0, 3) and joined[-1] == JoinLeave(TODAY, 2, 0)

    hours = fill_hours({0: 1, 23: 5, 24: 99})
    assert len(hours) == HOURS and hours[0] == HourCount(0, 1) and hours[23] == HourCount(23, 5)
    assert sum(point.count for point in hours) == 6


def test_started_within_and_rank_percent() -> None:
    span = day_span(30, TODAY)
    assert started_within(None, span) is False
    assert started_within(at(span.start), span) is False  # collection predates the whole span
    assert started_within(at(span.start + datetime.timedelta(days=1)), span) is True
    assert started_within(at(TODAY), span) is True

    assert MemberRank(rank=1, ranked=200, messages=50).top_percent == 0.5
    assert MemberRank(rank=200, ranked=200, messages=1).top_percent == 100.0


# the store, against postgres

STATS_TABLES = (
    "stats_guilds",
    "stats_guild_days",
    "stats_channel_days",
    "stats_hour_days",
    "stats_user_days",
    "stats_user_channel_days",
    "stats_user_hour_days",
    "stats_command_days",
)


@pytest.fixture
async def store(pool) -> StatsStore:
    await pool.execute(f"TRUNCATE {', '.join(STATS_TABLES)}, stats_message_totals")
    return StatsStore(pool)


async def seed(store: StatsStore, *, days: int = 3, guild_id: int = 1) -> None:
    """Three days of activity ending today: two users in two channels, a handful of commands, one join, one leave."""
    counters = Counters()
    for offset in range(days):
        day = TODAY - datetime.timedelta(days=offset)
        for _ in range(3):
            counters.record_message(guild_id, 10, 100, at(day, 9))
        counters.record_message(guild_id, 11, 100, at(day, 21))
        counters.record_message(guild_id, 11, 101, at(day, 21))
        counters.record_command(guild_id, 100, "help", at(day))
        counters.record_command(guild_id, 101, "whois", at(day))
        counters.record_command(guild_id, 101, "whois", at(day))
    counters.record_join(guild_id, at(TODAY))
    counters.record_leave(guild_id, at(TODAY - datetime.timedelta(days=1)))
    await store.flush(counters.drain(), at(TODAY))


@requires_db
async def test_flush_adds_up_across_batches_and_keeps_the_first_tracking_date(store: StatsStore) -> None:
    await seed(store)
    counters = Counters()
    counters.record_message(1, 10, 100, at(TODAY, 9))
    counters.record_join(1, at(TODAY))
    await store.flush(counters.drain(), at(TODAY, 23))
    await store.flush(Batch(), at(TODAY, 23))  # nothing to write is not an error

    row = await store.pool.fetchrow("SELECT * FROM stats_guild_days WHERE guild_id = 1 AND day = $1", TODAY)
    assert (row["messages"], row["joins"], row["leaves"], row["commands"]) == (6, 2, 0, 3)
    assert (
        await store.pool.fetchval("SELECT messages FROM stats_hour_days WHERE guild_id = 1 AND day = $1 AND hour = 9", TODAY)
        == 4
    )
    assert await store.tracking_since(1) == at(TODAY)
    assert await store.tracking_since(OTHER_GUILD) is None


@requires_db
async def test_opt_out_deletes_everything_and_opt_in_starts_fresh(store: StatsStore) -> None:
    await seed(store)
    await seed(store, guild_id=OTHER_GUILD)
    assert await store.disabled_guilds() == set()

    await store.set_enabled(1, False, at(TODAY))

    assert await store.disabled_guilds() == {1}
    for table in STATS_TABLES[1:]:
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE guild_id = 1") == 0
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE guild_id = $1", OTHER_GUILD) > 0
    assert await store.tracking_since(1) is None

    later = at(TODAY + datetime.timedelta(days=2))
    await store.set_enabled(1, True, later)
    assert await store.disabled_guilds() == set() and await store.tracking_since(1) == later


@requires_db
async def test_departed_guilds_are_purged_after_the_grace_period(store: StatsStore) -> None:
    await seed(store)
    await seed(store, guild_id=OTHER_GUILD)
    left = at(TODAY)
    await store.mark_left(1, left)
    await store.mark_left(1, left + datetime.timedelta(days=3))  # a second notice never restarts the clock
    assert await store.present_guilds() == {OTHER_GUILD}

    assert await store.purge_departed(left + datetime.timedelta(days=GRACE_DAYS - 1)) == []
    assert await store.pool.fetchval("SELECT count(*) FROM stats_guild_days WHERE guild_id = 1") == 3

    await store.mark_present(1)  # a rejoin inside the grace period keeps everything
    assert await store.purge_departed(left + datetime.timedelta(days=GRACE_DAYS + 1)) == []
    assert await store.present_guilds() == {1, OTHER_GUILD}

    await store.mark_left(1, left)
    assert await store.purge_departed(left + datetime.timedelta(days=GRACE_DAYS + 1)) == [1]
    for table in STATS_TABLES:
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE guild_id = 1") == 0
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE guild_id = $1", OTHER_GUILD) > 0


@requires_db
async def test_message_totals_round_trip_and_leave_with_the_server_or_the_person(store: StatsStore) -> None:
    assert await store.message_total(1, 100) is None and await store.member_messages_total(1, 100) == 0
    await seed(store)  # user 100 sends four a day for three days
    assert await store.member_messages_total(1, 100) == 12 and await store.member_messages_total(1, 999) == 0

    await store.set_message_total(1, 100, 1200, 12, at(TODAY))
    await store.set_message_total(1, 101, 30, 3, at(TODAY))
    await store.set_message_total(OTHER_GUILD, 100, 7, 0, at(TODAY))
    assert await store.message_total(1, 100) == MessageTotal(1200, 12, at(TODAY))
    await store.set_message_total(1, 100, 1300, 20, at(TODAY + datetime.timedelta(days=1)))
    assert await store.message_total(1, 100) == MessageTotal(1300, 20, at(TODAY + datetime.timedelta(days=1)))

    assert await store.purge_user(100) > 0  # a person's rows go everywhere
    assert await store.message_total(1, 100) is None and await store.message_total(OTHER_GUILD, 100) is None
    assert await store.message_total(1, 101) is not None
    await store.set_enabled(1, False, at(TODAY))  # and a server's with the opt-out
    assert await store.message_total(1, 101) is None


@requires_db
async def test_footprint_counts_rows_per_server_and_people_without_naming_them(store: StatsStore) -> None:
    empty = await store.footprint()
    assert empty.guilds == () and empty.servers == 0 and empty.people == 0 and empty.oldest_day is None

    await seed(store)  # three days: 15 rows a day across the seven tables, two people
    await seed(store, days=1, guild_id=OTHER_GUILD)  # 15 rows, plus the day row the recorded leave adds

    footprint = await store.footprint()

    assert [(entry.guild_id, entry.rows, entry.people) for entry in footprint.guilds] == [(1, 45, 2), (OTHER_GUILD, 16, 2)]
    assert footprint.servers == 2 and footprint.people == 2  # the same two people in both servers count once
    assert footprint.oldest_day == TODAY - datetime.timedelta(days=2)
    assert [entry.guild_id for entry in (await store.footprint(limit=1)).guilds] == [1]


@requires_db
async def test_purge_user_everywhere_or_in_one_guild(store: StatsStore) -> None:
    await seed(store)
    await seed(store, guild_id=OTHER_GUILD)

    deleted = await store.purge_user(100, OTHER_GUILD)
    assert deleted == 3 * 6  # three days: a user row, two channels, two hours, one command
    assert await store.pool.fetchval("SELECT count(*) FROM stats_user_days WHERE user_id = 100 AND guild_id = 1") == 3

    assert await store.purge_user(100) == 3 * 6
    for table in ("stats_user_days", "stats_user_channel_days", "stats_user_hour_days", "stats_command_days"):
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = 100") == 0
        assert await store.pool.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = 101") > 0
    assert await store.pool.fetchval("SELECT messages FROM stats_guild_days WHERE guild_id = 1 AND day = $1", TODAY) == 5
    assert await store.purge_user(999) == 0


@requires_db
async def test_server_queries(store: StatsStore) -> None:
    await seed(store)
    span = day_span(7, TODAY)
    yesterday = TODAY - datetime.timedelta(days=1)

    messages = await store.messages_per_day(1, span)
    assert len(messages) == 7 and messages[-1] == DayCount(TODAY, 5) and messages[0].count == 0

    active = await store.active_users_per_day(1, span)
    assert active[-1] == DayCount(TODAY, 2) and active[0].count == 0

    joins_leaves = await store.joins_leaves_per_day(1, span)
    assert joins_leaves[-1] == JoinLeave(TODAY, 1, 0) and joins_leaves[-2] == JoinLeave(yesterday, 0, 1)

    hours = await store.messages_by_hour(1, span)
    assert len(hours) == HOURS and hours[9] == HourCount(9, 9) and hours[21] == HourCount(21, 6) and hours[0].count == 0

    assert await store.top_channels(1, span) == (ChannelCount(10, 9), ChannelCount(11, 6))
    assert await store.top_channels(1, span, limit=1) == (ChannelCount(10, 9),)
    assert await store.top_channels(1, day_span(7, TODAY - datetime.timedelta(days=30))) == ()

    activity = await store.guild_activity(1, span)
    assert activity.guild_id == 1 and activity.span == span and activity.tracking_since == at(TODAY)
    assert activity.total_messages == 15 and activity.messages == messages and activity.hours == hours
    assert activity.top_channels[0].channel_id == 10 and len(activity.joins_leaves) == 7

    empty = await store.guild_activity(OTHER_GUILD, span)
    assert empty.total_messages == 0 and empty.tracking_since is None and empty.top_channels == ()
    assert len(empty.messages) == 7 and all(point.count == 0 for point in empty.active_users)


@requires_db
async def test_member_queries(store: StatsStore) -> None:
    await seed(store)
    span = day_span(30, TODAY)

    messages = await store.member_messages_per_day(1, 100, span)
    assert len(messages) == 30 and messages[-1] == DayCount(TODAY, 4) and messages[0].count == 0

    hours = await store.member_messages_by_hour(1, 100, span)
    assert hours[9] == HourCount(9, 9) and hours[21] == HourCount(21, 3) and sum(h.count for h in hours) == 12

    assert await store.member_top_channels(1, 100, span) == (ChannelCount(10, 9), ChannelCount(11, 3))
    assert await store.member_top_channels(1, 101, span, limit=TOP_LIMIT) == (ChannelCount(11, 3),)
    assert await store.member_top_commands(1, 101, span) == (CommandCount("whois", 6),)
    assert await store.member_top_commands(1, 100, span) == (CommandCount("help", 3),)

    assert await store.member_rank(1, 100, span) == MemberRank(rank=1, ranked=2, messages=12)
    assert await store.member_rank(1, 101, span) == MemberRank(rank=2, ranked=2, messages=3)
    assert await store.member_rank(1, 999, span) is None
    assert await store.member_rank(OTHER_GUILD, 100, span) is None

    activity = await store.member_activity(1, 101, span)
    assert activity.user_id == 101 and activity.total_messages == 3 and activity.rank is not None
    assert activity.rank.top_percent == 100.0 and activity.top_commands[0].command == "whois"
    assert activity.tracking_since == at(TODAY)

    nobody = await store.member_activity(1, 999, span)
    assert nobody.total_messages == 0 and nobody.rank is None and nobody.top_channels == () and nobody.top_commands == ()


# the cog, offline


class FakeStore:
    def __init__(self) -> None:
        self.batches: list[Batch] = []
        self.disabled: set[int] = set()
        self.enabled_calls: list[tuple[int, bool]] = []
        self.left: dict[int, datetime.datetime] = {}
        self.present: list[int] = []
        self.totals: dict[tuple[int, int], MessageTotal] = {}
        self.counted: dict[tuple[int, int], int] = {}

    async def disabled_guilds(self) -> set[int]:
        return set(self.disabled)

    async def flush(self, batch: Batch, at: datetime.datetime) -> None:
        await asyncio.sleep(0)
        self.batches.append(batch)

    async def set_enabled(self, guild_id: int, enabled: bool, at: datetime.datetime) -> None:
        await asyncio.sleep(0)
        self.enabled_calls.append((guild_id, enabled))
        if enabled:
            self.disabled.discard(guild_id)
        else:
            self.disabled.add(guild_id)

    async def mark_left(self, guild_id: int, at: datetime.datetime) -> None:
        self.left.setdefault(guild_id, at)

    async def mark_present(self, guild_id: int) -> None:
        self.present.append(guild_id)
        self.left.pop(guild_id, None)

    async def present_guilds(self) -> set[int]:
        return set()

    async def purge_departed(self, now: datetime.datetime, grace_days: int = GRACE_DAYS) -> list[int]:
        return []

    async def message_total(self, guild_id: int, user_id: int) -> MessageTotal | None:
        return self.totals.get((guild_id, user_id))

    async def set_message_total(self, guild_id: int, user_id: int, total: int, counted: int, at) -> None:
        self.totals[(guild_id, user_id)] = MessageTotal(total, counted, at)

    async def member_messages_total(self, guild_id: int, user_id: int) -> int:
        return self.counted.get((guild_id, user_id), 0)


@pytest.fixture
async def rig() -> SimpleNamespace:
    intents = discord.Intents(guilds=True, members=True, message_content=True, messages=True)
    bot = commands.Bot(command_prefix="t,", intents=intents)
    await bot._async_setup_hook()
    state = bot._connection
    state.user = discord.ClientUser(
        state=state, data=user(BOT_ID, "spork", bot=True) | {"verified": True, "mfa_enabled": False}
    )
    state.parse_guild_create(guild_payload())
    guild = bot.get_guild(GUILD_ID)
    assert guild is not None

    bot.pool = None  # the cog only hands the pool to the store, which we replace
    cog = Stats(bot)
    cog.store = FakeStore()  # type: ignore[assignment] — the in-memory stand-in for this harness
    await bot.add_cog(cog)
    cog.flush.cancel()  # the loops are driven by hand here
    cog.cleanup.cancel()
    bot._ready.set()  # what login would do; lets before_loop hooks run in the harness
    await cog.before_flush()  # what the loop does once the bot is ready: read the opt-out set

    sent: list[dict] = []
    errors: list[BaseException] = []

    async def fake_send(self, *args, **kwargs):
        sent.append(kwargs | {"content": args[0] if args else kwargs.get("content")})
        return SimpleNamespace()

    async def on_command_error(ctx, error):
        errors.append(error)

    bot.add_listener(on_command_error)
    commands.Context.send = fake_send  # type: ignore[method-assign]

    counter = itertools.count(1)

    def message(author_id: int = USER_ID, channel_id: int = CHANNEL_ID, *, content: str = "hi", **extra) -> discord.Message:
        author = guild.get_member(author_id)
        assert author is not None
        data = {
            "id": str(next(counter)),
            "channel_id": str(channel_id),
            "guild_id": str(GUILD_ID),
            "author": user(author.id, author.name, author.bot),
            "member": {"roles": [], "joined_at": NOW, "flags": 0},
            "content": content,
            "timestamp": NOW,
            "edited_timestamp": None,
            "tts": False,
            "mention_everyone": False,
            "mentions": [],
            "mention_roles": [],
            "attachments": [],
            "embeds": [],
            "pinned": False,
            "type": 0,
            "flags": 0,
        } | extra
        target = guild.get_channel_or_thread(channel_id)
        assert target is not None
        return discord.Message(state=state, channel=target, data=data)

    async def run(content: str, author_id: int = OWNER_ID) -> str | None:
        before = len(sent)
        await bot.process_commands(message(author_id, content=content))
        await asyncio.sleep(0)
        assert errors == [], errors
        assert len(sent) > before, "the command sent nothing"
        return sent[-1]["content"]

    try:
        yield SimpleNamespace(
            bot=bot, cog=cog, guild=guild, store=cog.store, message=message, run=run, sent=sent, errors=errors
        )
    finally:
        await bot.remove_cog(cog.qualified_name)
        await bot.close()


async def test_messages_are_counted_by_event_only(rig: SimpleNamespace) -> None:
    await rig.cog.on_message(rig.message(content="the text is never read"))
    await rig.cog.on_message(rig.message(channel_id=THREAD_ID))  # a thread counts toward its parent
    await rig.cog.on_message(rig.message(author_id=BOT_ID))
    await rig.cog.on_message(rig.message(webhook_id="123"))
    await rig.cog.on_message(rig.message(type=7))  # a join notice is a system message

    batch = rig.cog.counters.drain()
    day = batch.guild_days[0][1]  # created_at comes from the snowflake, so the fixture ids land on discord's epoch
    assert batch.channel_days == ((GUILD_ID, CHANNEL_ID, day, 2),)
    assert batch.user_days[0][3] == 2
    assert "the text" not in repr(batch)


async def test_joins_leaves_and_commands_are_counted(rig: SimpleNamespace) -> None:
    member = rig.guild.get_member(USER_ID)
    bot_member = rig.guild.get_member(BOT_ID)
    await rig.cog.on_member_join(member)
    await rig.cog.on_member_join(bot_member)  # apps being added aren't community activity
    await rig.cog.on_member_remove(member)

    reply = await rig.run("t,stats", author_id=USER_ID)
    assert reply is not None and "stats on" in reply
    await rig.cog.on_app_command_completion(
        SimpleNamespace(guild_id=GUILD_ID, user=member),
        rig.bot.tree.get_command("help") or SimpleNamespace(qualified_name="help"),
    )

    batch = rig.cog.counters.drain()
    assert batch.guild_days[0][3:6] == (1, 1, 2)
    assert {row[2] for row in batch.command_days} == {"stats", "help"}


async def test_hybrid_slash_use_is_counted_once(rig: SimpleNamespace) -> None:
    command = rig.bot.get_command("stats on")
    assert isinstance(command, commands.HybridCommand) and command.app_command is not None
    await rig.cog.on_app_command_completion(
        SimpleNamespace(guild_id=GUILD_ID, user=rig.guild.get_member(USER_ID)), command.app_command
    )
    assert rig.cog.counters.is_empty()


async def test_nothing_is_counted_before_the_opt_out_set_is_loaded(rig: SimpleNamespace) -> None:
    rig.cog._loaded = False
    await rig.cog.on_message(rig.message())
    assert rig.cog.counters.is_empty()
    rig.store.disabled.add(GUILD_ID)
    await rig.cog.before_flush()
    assert rig.cog._loaded and not rig.cog.is_enabled(GUILD_ID)


async def test_untracked_guilds_are_skipped(rig: SimpleNamespace) -> None:
    rig.cog.disabled.add(GUILD_ID)
    await rig.cog.on_message(rig.message())
    await rig.cog.on_member_join(rig.guild.get_member(USER_ID))
    assert rig.cog.counters.is_empty()
    rig.cog.disabled.clear()

    assert rig.cog.tracked(GUILD_ID + 1) is False  # a server the bot isn't in


async def test_flush_batches_and_writes_on_unload(rig: SimpleNamespace) -> None:
    for _ in range(5):
        await rig.cog.on_message(rig.message())
    assert rig.store.batches == []  # nothing per message

    assert await rig.cog.write() == 6  # guild, channel, hour, user, user-channel, user-hour rows
    assert len(rig.store.batches) == 1 and rig.store.batches[0].guild_days[0][2] == 5
    assert await rig.cog.write() == 0 and len(rig.store.batches) == 1

    await rig.cog.on_message(rig.message())
    await rig.cog.cog_unload()
    assert len(rig.store.batches) == 2 and rig.store.batches[1].guild_days[0][2] == 1


async def test_opt_out_stops_counting_immediately_and_deletes(rig: SimpleNamespace) -> None:
    await rig.cog.on_message(rig.message())
    reply = await rig.run("t,stats off")
    assert reply is not None and "deleted" in reply
    assert rig.store.enabled_calls == [(GUILD_ID, False)] and rig.cog.counters.is_empty()
    assert not rig.cog.is_enabled(GUILD_ID)

    await rig.cog.on_message(rig.message())
    assert rig.cog.counters.is_empty()
    reply = await rig.run("t,stats off")
    assert reply is not None and "already off" in reply

    reply = await rig.run("t,stats on")
    assert reply is not None and "on again" in reply and rig.cog.is_enabled(GUILD_ID)
    await rig.cog.on_message(rig.message())
    assert not rig.cog.counters.is_empty()
    reply = await rig.run("t,stats on")
    assert reply is not None and "already on" in reply


async def test_stats_switch_needs_manage_guild(rig: SimpleNamespace) -> None:
    await rig.bot.process_commands(rig.message(USER_ID, content="t,stats off"))
    await asyncio.sleep(0)
    assert len(rig.errors) == 1 and isinstance(rig.errors[0], commands.MissingPermissions)
    assert rig.store.enabled_calls == []


async def test_leaving_a_guild_drops_pending_counts_and_starts_the_grace_period(rig: SimpleNamespace) -> None:
    await rig.cog.on_message(rig.message())
    await rig.cog.on_guild_remove(rig.guild)
    assert rig.cog.counters.is_empty() and GUILD_ID in rig.store.left

    await rig.cog.on_guild_join(rig.guild)
    assert rig.store.present == [GUILD_ID] and GUILD_ID not in rig.store.left


# lifetime totals for whois: one search baseline, then the collector's counts on top


async def test_lifetime_messages_searches_once_then_counts_on_top(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cog, guild, store = rig.cog, rig.guild, rig.cog.store
    searches: list[list[tuple[str, str]]] = []
    answer = {"total_results": 1200, "messages": [{"content": "never read"}], "doing_deep_historical_index": False}

    async def request(route, *, params=None, **kwargs):
        assert route.url.endswith(f"/guilds/{GUILD_ID}/messages/search")
        searches.append(list(params))
        return answer

    monkeypatch.setattr(rig.bot.http, "request", request)
    store.counted[(GUILD_ID, USER_ID)] = 40

    assert await cog.lifetime_messages(guild, USER_ID) == 1200
    assert searches == [[("author_id", str(USER_ID)), ("include_nsfw", "true"), ("limit", "1")]]
    baseline = store.totals[(GUILD_ID, USER_ID)]
    assert baseline.total == 1200 and baseline.counted == 40

    store.counted[(GUILD_ID, USER_ID)] = 55  # flushed since
    cog.counters.record_message(GUILD_ID, CHANNEL_ID, USER_ID, at(TODAY))  # and two still in memory
    cog.counters.record_message(GUILD_ID, CHANNEL_ID, USER_ID, at(TODAY))
    assert await cog.lifetime_messages(guild, USER_ID) == 1217 and len(searches) == 1

    # a baseline past its month is refreshed with one search, and the counted mark moves with it
    store.totals[(GUILD_ID, USER_ID)] = MessageTotal(
        1200, 40, discord.utils.utcnow() - datetime.timedelta(days=BASELINE_DAYS + 1)
    )
    answer = answer | {"total_results": 1400}
    assert await cog.lifetime_messages(guild, USER_ID) == 1400 and len(searches) == 2
    assert store.totals[(GUILD_ID, USER_ID)].counted == 57

    # an index that isn't ready is asked exactly once (no waiting in a public command) and the estimate stands in
    answer = {"message": "Index not yet available", "code": 110000, "retry_after": 5}
    store.totals[(GUILD_ID, USER_ID)] = MessageTotal(
        1400, 57, discord.utils.utcnow() - datetime.timedelta(days=BASELINE_DAYS + 1)
    )
    assert await cog.lifetime_messages(guild, USER_ID) == 1400 and len(searches) == 3

    async def refused(route, *, params=None, **kwargs):
        raise discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), {"message": "Missing Access", "code": 50001}
        )

    monkeypatch.setattr(rig.bot.http, "request", refused)
    assert await cog.lifetime_messages(guild, USER_ID) == 1400  # still the estimate
    assert await cog.lifetime_messages(guild, OWNER_ID) is None  # nothing stored, nothing to show
