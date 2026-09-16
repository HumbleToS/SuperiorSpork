"""The chart module: pure helpers, the panel builders over typed activity data, and real renders through Pillow
for normal, empty, and partial history. No Discord anywhere."""

import datetime
import io
import time

from PIL import Image

from exts.utils.charts import (
    BACKGROUND,
    FONT_DIR,
    HEIGHT,
    RANGE_DAYS,
    SCALE,
    TOP_LIMIT,
    WIDTH,
    BarsPanel,
    Chart,
    DailyPanel,
    HoursPanel,
    Series,
    day_labels,
    member_chart,
    nice_ceiling,
    render_chart,
    server_chart,
    tracking_note,
    truncate_label,
    y_ticks,
)
from exts.utils.stats import (
    ChannelCount,
    CommandCount,
    DayCount,
    GuildActivity,
    HourCount,
    JoinLeave,
    MemberActivity,
    MemberRank,
    day_span,
)

UTC = datetime.UTC
TODAY = datetime.date(2026, 9, 16)


def at(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour=9), tzinfo=UTC)


def guild_activity(
    days: int = 30, *, silent_days: int = 0, tracking_since: datetime.datetime | None = None
) -> GuildActivity:
    span = day_span(days, TODAY)
    messages = tuple(DayCount(day, 0 if i < silent_days else 10 + i) for i, day in enumerate(span))
    return GuildActivity(
        guild_id=1,
        span=span,
        tracking_since=tracking_since,
        messages=messages,
        active_users=tuple(DayCount(day, 0 if i < silent_days else 2 + i % 3) for i, day in enumerate(span)),
        joins_leaves=tuple(JoinLeave(day, i % 4, i % 2) for i, day in enumerate(span)),
        hours=tuple(HourCount(hour, hour * 3) for hour in range(24)),
        top_channels=tuple(ChannelCount(100 + i, 500 - i * 40) for i in range(12)),
    )


def member_activity(days: int = 7) -> MemberActivity:
    span = day_span(days, TODAY)
    return MemberActivity(
        guild_id=1,
        user_id=2,
        span=span,
        tracking_since=at(span.start),
        messages=tuple(DayCount(day, i) for i, day in enumerate(span)),
        hours=tuple(HourCount(hour, 1 if hour == 21 else 0) for hour in range(24)),
        top_channels=(ChannelCount(100, 9), ChannelCount(999, 1)),
        top_commands=(CommandCount("brainrot terms add a very long term indeed", 4), CommandCount("help", 1)),
        rank=MemberRank(rank=2, ranked=10, messages=21),
    )


# helpers


def test_nice_ceilings_and_ticks() -> None:
    assert [nice_ceiling(v) for v in (0, 1, 2, 3, 7, 10, 11, 45, 99, 100, 101, 2500)] == [
        1,
        1,
        2,
        5,
        10,
        10,
        20,
        50,
        100,
        100,
        200,
        5000,
    ]
    assert y_ticks(400) == (0, 125, 250, 375, 500)
    assert y_ticks(3) == (0, 1, 2, 3, 4)
    assert y_ticks(0) == (0, 1, 2, 3, 4)  # a flat zero series still gets a readable axis


def test_day_labels_keep_the_ends() -> None:
    days = list(day_span(30, TODAY))
    labels = day_labels(days)
    assert 0 in labels and 29 in labels and len(labels) == 6
    assert labels[29] == "16 Sep" and labels[0] == "18 Aug"
    assert day_labels(days[-3:]) == {0: "14 Sep", 1: "15 Sep", 2: "16 Sep"}
    assert day_labels([]) == {}


def test_truncate_and_tracking_note() -> None:
    assert truncate_label("general") == "general"
    assert truncate_label("a-channel-with-a-very-long-name", 12) == "a-channel-w…"
    span = day_span(30, TODAY)
    assert tracking_note(None, span.start, span.end) is None
    assert tracking_note(at(span.start), span.start, span.end) is None  # predates the span: nothing partial
    assert tracking_note(at(TODAY - datetime.timedelta(days=3)), span.start, span.end) == "Tracking since 13 Sep 2026"
    assert RANGE_DAYS == {"7d": 7, "30d": 30, "90d": 90}


# builders


def test_server_chart_panels() -> None:
    activity = guild_activity(silent_days=5, tracking_since=at(TODAY - datetime.timedelta(days=24)))
    names = {100: "#general", 101: "#off-topic"}
    chart = server_chart(activity, names, (1, 2, 3), joins_available=True)
    messages, second, channels, hours = chart.panels
    assert isinstance(messages, DailyPanel) and messages.title == "Messages per day" and len(messages.days) == 30
    assert messages.series[0].values[:6] == (0, 0, 0, 0, 0, 15) and messages.note == "Tracking since 23 Aug 2026"
    assert isinstance(second, DailyPanel) and second.title == "Joins vs leaves"
    assert [series.label for series in second.series] == ["Joins", "Leaves"] and second.note == messages.note
    assert isinstance(channels, BarsPanel) and len(channels.bars) == TOP_LIMIT
    assert (
        channels.bars[0] == ("#general", 500) and channels.bars[1] == ("#off-topic", 460) and channels.bars[2][0] == "#102"
    )
    assert isinstance(hours, HoursPanel) and hours.values[23] == 69 and len(hours.values) == 24
    assert chart.accent == (1, 2, 3)

    without_members = server_chart(activity, names, (1, 2, 3), joins_available=False)
    fallback = without_members.panels[1]
    assert isinstance(fallback, DailyPanel) and fallback.title == "Active users per day" and len(fallback.series) == 1


def test_member_chart_panels() -> None:
    chart = member_chart(member_activity(), {100: "#general"}, (9, 9, 9))
    messages, hours, channels, commands = chart.panels
    assert isinstance(messages, DailyPanel) and messages.series[0].values == (0, 1, 2, 3, 4, 5, 6) and messages.note is None
    assert isinstance(hours, HoursPanel) and hours.values[21] == 1 and sum(hours.values) == 1
    assert isinstance(channels, BarsPanel) and channels.bars == (("#general", 9), ("#999", 1))
    assert (
        isinstance(commands, BarsPanel)
        and commands.bars[0] == ("brainrot terms ad…", 4)
        and commands.title == "Commands used"
    )


# renders


def decode(png: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(png))
    image.load()
    return image


def test_render_normal_data_is_a_sharp_dark_png() -> None:
    chart = server_chart(guild_activity(), {}, (176, 220, 255), joins_available=True)
    started = time.perf_counter()
    png = render_chart(chart)
    elapsed = time.perf_counter() - started
    image = decode(png)
    assert image.format == "PNG" and image.mode == "RGB"
    assert image.size == (WIDTH * SCALE, HEIGHT * SCALE)
    assert image.getpixel((2, 2)) == BACKGROUND  # solid, never transparent
    assert len(png) < 1_000_000 and elapsed < 5
    assert FONT_DIR.joinpath("Inter-Regular.ttf").exists() and FONT_DIR.joinpath("LICENSE-Inter.txt").exists()


def test_render_empty_and_partial_and_odd_shapes() -> None:
    empty = server_chart(guild_activity(7, silent_days=7), {}, (200, 200, 200), joins_available=False)
    assert all(panel.empty for panel in empty.panels[:2]) and empty.panels[3].empty is False
    image = decode(render_chart(empty))
    assert image.size == (WIDTH * SCALE, HEIGHT * SCALE)

    partial = server_chart(
        guild_activity(90, silent_days=80, tracking_since=at(TODAY - datetime.timedelta(days=9))),
        {},
        (200, 200, 200),
        joins_available=True,
    )
    assert partial.panels[0].note == "Tracking since 7 Sep 2026"
    decode(render_chart(partial))

    single_day = Chart(
        (
            DailyPanel("One day", (TODAY,), (Series("m", (5,)),)),
            DailyPanel("Two lines", (TODAY,), (Series("a", (1,)), Series("b", (0,)))),
            BarsPanel("Nothing", ()),
            HoursPanel("Flat", tuple(0 for _ in range(24))),
        ),
        (255, 255, 255),
    )
    assert single_day.panels[2].empty and single_day.panels[3].empty
    decode(render_chart(single_day))
