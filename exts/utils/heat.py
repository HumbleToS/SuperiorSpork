import datetime
import itertools
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, Self

# The default brainrot vocabulary. Slang rots fast: revisit this every few months, drop
# anything that has turned into a normal word, add whatever the kids are saying now.
# Nothing slur-adjacent, nothing that doubles as an ordinary word without context —
# servers extend it with `brainrot terms add` and carve exceptions with `brainrot allow`.
DEFAULT_TERMS: tuple[str, ...] = (
    "skibidi",
    "gyat",
    "rizz",
    "rizzler",
    "rizzed",
    "rizzing",
    "sigma",
    "fanum tax",
    "mewing",
    "mogging",
    "mogged",
    "delulu",
    "bussin",
    "sussy",
    "griddy",
    "goofy ahh",
    "aura farming",
    "looksmaxxing",
    "chat is this real",
    "only in ohio",
)

MAX_HEAT = 5
DECAY_SECONDS = 3600  # 1 point per hour since the last heat change
WINDOW_SECONDS = 30
WINDOW_CAP = 3  # a spam window is worth at most this much heat
SPAM_HITS = 4  # this many term hits in one message is spam on its own
REPEAT_DAYS = 7
DEFAULT_MUTE_SECONDS = 300
DEFAULT_LADDER_SECONDS: tuple[int, ...] = (1800, 7200, 86400)
MAX_TIMEOUT_SECONDS = 28 * 86400  # discord refuses anything longer

OutcomeKind = Literal["heat", "spam", "mute", "escalation", "silent"]


class Row(Protocol):
    """Anything indexable by column name: an asyncpg record, or a dict in the tests."""

    def __getitem__(self, key: str, /) -> Any: ...


_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff\u00ad")  # zero-width joiners, bom, soft hyphen
# a run of three or more lone characters split by short separators: "s k i b i d i", "r.i.z.z"
_SPACED_RUN = re.compile(r"(?<![^\W_])(?:[^\W_][\W_]{1,2}){2,}[^\W_](?![^\W_])")
_SEPARATORS = re.compile(r"[\W_]+")
_MARKUP = re.compile(
    r"```.*?```"  # fenced code
    r"|`[^`\n]*`"  # inline code
    r"|https?://\S+"  # urls
    r"|<a?:\w+:\d+>"  # custom emoji
    r"|<(?:@[!&]?|#)\d+>"  # user, role, channel mentions
    r"|</[\w -]+:\d+>"  # slash command mentions
    r"|<t:-?\d+(?::[tTdDfFR])?>",  # timestamps
    re.DOTALL,
)


def strip_markup(text: str) -> str:
    """Drops the parts of a message that are never someone's own words."""
    return _MARKUP.sub(" ", text)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch) and ch not in _INVISIBLE)
    folded = unicodedata.normalize("NFKC", plain.casefold()).translate(_LEET)
    return _SPACED_RUN.sub(lambda match: _SEPARATORS.sub("", match.group()), folded)


def _word_pattern(word: str) -> str:
    # each letter may repeat, and a doubled letter in the term still needs at least two
    parts: list[str] = []
    for char, run in itertools.groupby(word):
        length = len(list(run))
        parts.append(f"{re.escape(char)}+" if length == 1 else f"{re.escape(char)}{{{length},}}")
    return "".join(parts)


def term_pattern(term: str) -> str:
    words = normalize(term).split()
    body = r"[\W_]*".join(_word_pattern(word) for word in words)
    return rf"(?<![^\W_]){body}(?![^\W_])"


def effective_terms(
    additions: Iterable[str] = (),
    removals: Iterable[str] = (),
    allowed: Iterable[str] = (),
    defaults: Iterable[str] = DEFAULT_TERMS,
) -> set[str]:
    excluded = {normalize(term) for term in removals} | {normalize(term) for term in allowed}
    active = {normalize(term) for term in defaults} | {normalize(term) for term in additions}
    return {term for term in active - excluded if term.strip()}


class TermMatcher:
    """Counts brainrot hits in text; compiled once per guild, never per message."""

    def __init__(self, terms: Iterable[str]) -> None:
        self.terms: tuple[str, ...] = tuple(sorted({normalize(term) for term in terms if term.strip()}))
        self._regex: re.Pattern[str] | None = (
            re.compile("|".join(f"(?:{term_pattern(term)})" for term in self.terms)) if self.terms else None
        )

    def hits(self, text: str) -> int:
        if self._regex is None:
            return 0
        return sum(1 for _ in self._regex.finditer(normalize(strip_markup(text))))


@dataclass(frozen=True)
class HeatSettings:
    mute_seconds: int = DEFAULT_MUTE_SECONDS
    ladder_seconds: tuple[int, ...] = DEFAULT_LADDER_SECONDS


@dataclass(frozen=True)
class HeatState:
    heat: int = 0
    heat_updated_at: datetime.datetime | None = None
    window_started_at: datetime.datetime | None = None
    window_count: int = 0
    lifetime_offenses: int = 0
    repeat_until: datetime.datetime | None = None
    escalation_level: int = 0

    @classmethod
    def from_row(cls, row: Row) -> Self:
        return cls(
            heat=row["heat"],
            heat_updated_at=row["heat_updated_at"],
            window_started_at=row["window_started_at"],
            window_count=row["window_count"],
            lifetime_offenses=row["lifetime_offenses"],
            repeat_until=row["repeat_until"],
            escalation_level=row["escalation_level"],
        )


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    heat: int  # the heat to show, so a mute says 5/5 even though the stored heat is 0
    heat_added: int
    timeout_seconds: int | None
    escalation_level: int


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class HeatEngine:
    """The heat ladder, spam windows, mutes, and repeat escalation — no Discord, no IO."""

    def __init__(self, clock: Callable[[], datetime.datetime] = _utcnow) -> None:
        self.clock = clock

    def decayed(self, state: HeatState, now: datetime.datetime | None = None) -> HeatState:
        now = now or self.clock()
        if state.heat <= 0 or state.heat_updated_at is None:
            return replace(state, heat=0)
        lost = int((now - state.heat_updated_at).total_seconds() // DECAY_SECONDS)
        if lost <= 0:
            return state
        # advance by whole hours so the leftover minutes keep counting toward the next point
        return replace(
            state,
            heat=max(0, state.heat - lost),
            heat_updated_at=state.heat_updated_at + datetime.timedelta(seconds=lost * DECAY_SECONDS),
        )

    def current_heat(self, state: HeatState) -> int:
        return self.decayed(state).heat

    def is_repeat(self, state: HeatState, now: datetime.datetime | None = None) -> bool:
        now = now or self.clock()
        return state.repeat_until is not None and now < state.repeat_until

    def apply_offense(self, state: HeatState, settings: HeatSettings, hits: int = 1) -> tuple[HeatState, Outcome]:
        now = self.clock()
        state = replace(self.decayed(state, now), lifetime_offenses=state.lifetime_offenses + 1)
        repeat_until = now + datetime.timedelta(days=REPEAT_DAYS)

        if self.is_repeat(state, now):
            ladder = settings.ladder_seconds or DEFAULT_LADDER_SECONDS
            level = min(state.escalation_level + 1, len(ladder))
            state = replace(
                state,
                heat=0,
                heat_updated_at=now,
                window_started_at=None,
                window_count=0,
                repeat_until=repeat_until,
                escalation_level=level,
            )
            seconds = min(ladder[level - 1], MAX_TIMEOUT_SECONDS)
            return state, Outcome("escalation", heat=0, heat_added=0, timeout_seconds=seconds, escalation_level=level)

        if state.repeat_until is not None:
            state = replace(state, repeat_until=None, escalation_level=0)  # the 7 days passed clean

        if state.window_started_at is None or (now - state.window_started_at).total_seconds() >= WINDOW_SECONDS:
            state = replace(state, window_started_at=now, window_count=0)
        before = min(state.window_count, WINDOW_CAP)
        count = max(state.window_count + 1, WINDOW_CAP) if hits >= SPAM_HITS else state.window_count + 1
        after = min(count, WINDOW_CAP)
        added = after - before
        state = replace(state, window_count=count)
        if added == 0:
            return state, Outcome("silent", heat=state.heat, heat_added=0, timeout_seconds=None, escalation_level=0)

        heat = min(MAX_HEAT, state.heat + added)
        if heat >= MAX_HEAT:
            state = replace(
                state,
                heat=0,
                heat_updated_at=now,
                window_started_at=None,
                window_count=0,
                repeat_until=repeat_until,
                escalation_level=0,
            )
            seconds = min(settings.mute_seconds, MAX_TIMEOUT_SECONDS)
            return state, Outcome("mute", heat=MAX_HEAT, heat_added=added, timeout_seconds=seconds, escalation_level=0)

        state = replace(state, heat=heat, heat_updated_at=now)
        kind: OutcomeKind = "spam" if after >= WINDOW_CAP else "heat"
        return state, Outcome(kind, heat=heat, heat_added=added, timeout_seconds=None, escalation_level=0)

    def pardon(self, state: HeatState, amount: int | None = None) -> HeatState:
        now = self.clock()
        state = self.decayed(state, now)
        if amount is None:
            return replace(
                state,
                heat=0,
                heat_updated_at=now,
                window_started_at=None,
                window_count=0,
                repeat_until=None,
                escalation_level=0,
            )
        return replace(state, heat=max(0, state.heat - amount), heat_updated_at=now)
