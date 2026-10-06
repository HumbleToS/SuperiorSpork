from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image, ImageDraw, ImageFont

from .stats import DaySpan, started_within

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping, Sequence

    from .stats import DayCount, GuildActivity, HourCount, MemberActivity

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
SCALE = 2  # the image ships at twice its logical size, so it stays sharp on phones
SUPERSAMPLE = 2  # drawn larger still, then downsampled, because Pillow's lines are not antialiased
WIDTH, HEIGHT = 900, 640  # logical
PADDING = 20
GAP = 16
TOP_LIMIT = 8
RGB = tuple[int, int, int]

# a solid dark card, legible on both discord themes
BACKGROUND: RGB = (30, 31, 34)
PANEL: RGB = (43, 45, 49)
GRID: RGB = (63, 65, 71)
TEXT: RGB = (219, 222, 225)
MUTED: RGB = (148, 155, 164)
SECOND: RGB = (148, 155, 164)  # the second series (leaves) next to the accent (joins)


@dataclass(frozen=True)
class Series:
    label: str
    values: tuple[int, ...]


@dataclass(frozen=True)
class DailyPanel:
    title: str
    days: tuple[datetime.date, ...]
    series: tuple[Series, ...]  # one, or two to compare
    note: str | None = None  # "Tracking since …", drawn small when the history is partial

    @property
    def empty(self) -> bool:
        return not any(any(series.values) for series in self.series)


@dataclass(frozen=True)
class HoursPanel:
    title: str
    values: tuple[int, ...]  # 24 entries, hour 0 first

    @property
    def empty(self) -> bool:
        return not any(self.values)


@dataclass(frozen=True)
class BarsPanel:
    title: str
    bars: tuple[tuple[str, int], ...]  # label, value; already sorted, at most TOP_LIMIT

    @property
    def empty(self) -> bool:
        return not any(value for _, value in self.bars)


Panel = DailyPanel | HoursPanel | BarsPanel


@dataclass(frozen=True)
class Chart:
    panels: tuple[Panel, Panel, Panel, Panel]
    accent: RGB


# pure helpers


def nice_ceiling(value: int) -> int:
    """The smallest 1, 2, or 5 times a power of ten at or above the value, so gridlines land on round numbers."""
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if step * magnitude >= value:
            return step * magnitude
    return 10 * magnitude


def y_ticks(top: int, count: int = 4) -> tuple[int, ...]:
    ceiling = nice_ceiling(top)
    step = max(1, ceiling // count)
    return tuple(step * i for i in range(count + 1))


def day_labels(days: Sequence[datetime.date], slots: int = 6) -> dict[int, str]:
    """Which day indexes get an axis label, and what it says; the first and last always do."""
    if not days:
        return {}
    if len(days) <= slots:
        picks = range(len(days))
    else:
        stride = (len(days) - 1) / (slots - 1)
        picks = sorted({round(i * stride) for i in range(slots)})
    return {index: days[index].strftime("%-d %b") for index in picks}


def truncate_label(text: str, limit: int = 18) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def tracking_note(
    tracking_since: datetime.datetime | None, span_start: datetime.date, span_end: datetime.date
) -> str | None:
    if started_within(tracking_since, DaySpan(span_start, span_end)) and tracking_since is not None:
        return f"Tracking since {tracking_since.date().strftime('%-d %b %Y')}"
    return None


def _daily(points: Sequence[DayCount]) -> tuple[tuple[datetime.date, ...], tuple[int, ...]]:
    return tuple(point.day for point in points), tuple(point.count for point in points)


def _hours(points: Sequence[HourCount]) -> tuple[int, ...]:
    values = [0] * 24
    for point in points:
        if 0 <= point.hour < 24:
            values[point.hour] = point.count
    return tuple(values)


def server_chart(activity: GuildActivity, channel_names: Mapping[int, str], accent: RGB, *, joins_available: bool) -> Chart:
    """Messages per day, joins vs leaves (or active users without the members intent), top channels, by hour."""
    note = tracking_note(activity.tracking_since, activity.span.start, activity.span.end)
    days, messages = _daily(activity.messages)
    if joins_available:
        joins = tuple(point.joins for point in activity.joins_leaves)
        leaves = tuple(point.leaves for point in activity.joins_leaves)
        second: Panel = DailyPanel("Joins vs leaves", days, (Series("Joins", joins), Series("Leaves", leaves)), note)
    else:
        _, active = _daily(activity.active_users)
        second = DailyPanel("Active users per day", days, (Series("Active users", active),), note)
    channels = tuple(
        (truncate_label(channel_names.get(row.channel_id, f"#{row.channel_id}")), row.count)
        for row in activity.top_channels[:TOP_LIMIT]
    )
    return Chart(
        (
            DailyPanel("Messages per day", days, (Series("Messages", messages),), note),
            second,
            BarsPanel("Top channels", channels),
            HoursPanel("Activity by hour (UTC)", _hours(activity.hours)),
        ),
        accent,
    )


def member_chart(activity: MemberActivity, channel_names: Mapping[int, str], accent: RGB) -> Chart:
    """One member in one server: messages per day, by hour, top channels, top commands."""
    note = tracking_note(activity.tracking_since, activity.span.start, activity.span.end)
    days, messages = _daily(activity.messages)
    channels = tuple(
        (truncate_label(channel_names.get(row.channel_id, f"#{row.channel_id}")), row.count)
        for row in activity.top_channels[:TOP_LIMIT]
    )
    commands = tuple((truncate_label(row.command), row.count) for row in activity.top_commands[:TOP_LIMIT])
    return Chart(
        (
            DailyPanel("Messages per day", days, (Series("Messages", messages),), note),
            HoursPanel("Activity by hour (UTC)", _hours(activity.hours)),
            BarsPanel("Top channels", channels),
            BarsPanel("Commands used", commands),
        ),
        accent,
    )


# drawing


class _Canvas:
    """Logical-unit drawing on a supersampled image; every coordinate is scaled once, here."""

    def __init__(self, font_dir: Path) -> None:
        self.scale = SCALE * SUPERSAMPLE
        self.image = Image.new("RGB", (WIDTH * self.scale, HEIGHT * self.scale), BACKGROUND)
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.regular = ImageFont.truetype(str(font_dir / "Inter-Regular.ttf"), 12 * self.scale)
        self.small = ImageFont.truetype(str(font_dir / "Inter-Regular.ttf"), 11 * self.scale)
        self.bold = ImageFont.truetype(str(font_dir / "Inter-SemiBold.ttf"), 14 * self.scale)

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def rect(self, x: float, y: float, w: float, h: float, fill: tuple[int, ...], radius: float = 0) -> None:
        box = (self.px(x), self.px(y), self.px(x + w), self.px(y + h))
        if radius:
            self.draw.rounded_rectangle(box, radius=self.px(radius), fill=fill)
        else:
            self.draw.rectangle(box, fill=fill)

    def line(self, points: Sequence[tuple[float, float]], fill: tuple[int, ...], width: float = 1) -> None:
        scaled = [(self.px(x), self.px(y)) for x, y in points]
        self.draw.line(scaled, fill=fill, width=max(1, self.px(width)), joint="curve")

    def polygon(self, points: Sequence[tuple[float, float]], fill: tuple[int, ...]) -> None:
        self.draw.polygon([(self.px(x), self.px(y)) for x, y in points], fill=fill)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        fill: RGB = TEXT,
        font: ImageFont.FreeTypeFont | None = None,
        anchor: str = "la",
    ) -> None:
        self.draw.text((self.px(x), self.px(y)), value, fill=fill, font=font or self.regular, anchor=anchor)

    def width(self, value: str, font: ImageFont.FreeTypeFont | None = None) -> float:
        return self.draw.textlength(value, font=font or self.regular) / self.scale

    def png(self) -> bytes:
        output = self.image.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        output.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


@dataclass(frozen=True)
class _Frame:
    x: float
    y: float
    w: float
    h: float

    @property
    def plot(self) -> _Frame:
        return _Frame(self.x + 44, self.y + 44, self.w - 60, self.h - 78)


def _panel_frames() -> tuple[_Frame, _Frame, _Frame, _Frame]:
    w = (WIDTH - 2 * PADDING - GAP) / 2
    h = (HEIGHT - 2 * PADDING - GAP) / 2
    return (
        _Frame(PADDING, PADDING, w, h),
        _Frame(PADDING + w + GAP, PADDING, w, h),
        _Frame(PADDING, PADDING + h + GAP, w, h),
        _Frame(PADDING + w + GAP, PADDING + h + GAP, w, h),
    )


def _panel_shell(canvas: _Canvas, frame: _Frame, title: str, empty: bool) -> None:
    canvas.rect(frame.x, frame.y, frame.w, frame.h, PANEL, radius=10)
    canvas.text(frame.x + 16, frame.y + 14, title, font=canvas.bold)
    if empty:
        canvas.text(frame.x + frame.w / 2, frame.y + frame.h / 2, "No data yet", fill=MUTED, anchor="mm", font=canvas.bold)


def _grid(canvas: _Canvas, plot: _Frame, ticks: Sequence[int]) -> None:
    top = ticks[-1] or 1
    for tick in ticks:
        y = plot.y + plot.h - plot.h * tick / top
        canvas.line([(plot.x, y), (plot.x + plot.w, y)], GRID, 1)
        canvas.text(plot.x - 8, y, f"{tick:,}", fill=MUTED, font=canvas.small, anchor="rm")


def _note(canvas: _Canvas, frame: _Frame, note: str | None) -> None:
    if note:
        canvas.text(frame.x + frame.w - 16, frame.y + 18, note, fill=MUTED, font=canvas.small, anchor="rm")


def _legend(canvas: _Canvas, frame: _Frame, entries: Sequence[tuple[str, RGB]]) -> None:
    x = frame.x + frame.w - 16
    for label, colour in reversed(entries):
        x -= canvas.width(label, canvas.small)
        canvas.text(x, frame.y + 18, label, fill=MUTED, font=canvas.small, anchor="lm")
        x -= 14
        canvas.rect(x, frame.y + 14, 8, 8, colour, radius=2)
        x -= 12


def _draw_daily(canvas: _Canvas, frame: _Frame, panel: DailyPanel, accent: RGB) -> None:
    _panel_shell(canvas, frame, panel.title, panel.empty)
    if panel.empty:
        _note(canvas, frame, panel.note)
        return
    plot = frame.plot
    top = max(max(series.values) for series in panel.series)
    ticks = y_ticks(top)
    _grid(canvas, plot, ticks)
    count = len(panel.days)
    step = plot.w / max(1, count - 1)
    scale = plot.h / (ticks[-1] or 1)
    colours = (accent, SECOND)
    for series, colour in zip(panel.series, colours, strict=False):
        points = [(plot.x + i * step, plot.y + plot.h - value * scale) for i, value in enumerate(series.values)]
        if count == 1:
            points = [(plot.x, points[0][1]), (plot.x + plot.w, points[0][1])]
        if colour is accent:
            base = plot.y + plot.h
            canvas.polygon([(points[0][0], base), *points, (points[-1][0], base)], (*accent, 56))
        canvas.line(points, colour, 2)
    for index, label in day_labels(panel.days).items():
        # the first and last labels hug their edge so nothing runs past the panel
        anchor = "la" if index == 0 else "ra" if index == count - 1 else "ma"
        canvas.text(plot.x + index * step, plot.y + plot.h + 8, label, fill=MUTED, font=canvas.small, anchor=anchor)
    if len(panel.series) > 1:
        _legend(canvas, frame, [(series.label, colour) for series, colour in zip(panel.series, colours, strict=False)])
    else:
        _note(canvas, frame, panel.note)


def _draw_hours(canvas: _Canvas, frame: _Frame, panel: HoursPanel, accent: RGB) -> None:
    _panel_shell(canvas, frame, panel.title, panel.empty)
    if panel.empty:
        return
    plot = frame.plot
    ticks = y_ticks(max(panel.values))
    _grid(canvas, plot, ticks)
    slot = plot.w / 24
    scale = plot.h / (ticks[-1] or 1)
    for hour, value in enumerate(panel.values):
        x = plot.x + hour * slot + slot * 0.15
        height = value * scale
        if height > 0:
            canvas.rect(x, plot.y + plot.h - height, slot * 0.7, height, accent, radius=2)
        if hour % 6 == 0 or hour == 23:
            canvas.text(
                plot.x + hour * slot + slot / 2,
                plot.y + plot.h + 8,
                f"{hour:02d}",
                fill=MUTED,
                font=canvas.small,
                anchor="ma",
            )


def _draw_bars(canvas: _Canvas, frame: _Frame, panel: BarsPanel, accent: RGB) -> None:
    _panel_shell(canvas, frame, panel.title, panel.empty)
    if panel.empty:
        return
    bars = panel.bars[:TOP_LIMIT]
    top = max(value for _, value in bars) or 1
    label_w = 120.0
    inner = _Frame(frame.x + 16, frame.y + 44, frame.w - 32, frame.h - 60)
    row = inner.h / TOP_LIMIT
    bar_x = inner.x + label_w + 12
    bar_w = inner.w - label_w - 12 - 56
    for i, (label, value) in enumerate(bars):
        y = inner.y + i * row
        canvas.text(inner.x + label_w, y + row / 2, label, fill=TEXT, font=canvas.small, anchor="rm")
        width = bar_w * value / top
        canvas.rect(bar_x, y + row * 0.22, max(width, 2), row * 0.56, accent, radius=3)
        canvas.text(bar_x + width + 8, y + row / 2, f"{value:,}", fill=MUTED, font=canvas.small, anchor="lm")


def render_chart(chart: Chart, font_dir: Path = FONT_DIR) -> bytes:
    """Draws the four panels and returns a PNG. CPU-bound: call it through asyncio.to_thread."""
    canvas = _Canvas(font_dir)
    for panel, frame in zip(chart.panels, _panel_frames(), strict=True):
        if isinstance(panel, DailyPanel):
            _draw_daily(canvas, frame, panel, chart.accent)
        elif isinstance(panel, HoursPanel):
            _draw_hours(canvas, frame, panel, chart.accent)
        else:
            _draw_bars(canvas, frame, panel, chart.accent)
    return canvas.png()


RangeName = Literal["7d", "30d", "90d"]
RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
