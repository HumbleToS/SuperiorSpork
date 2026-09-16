import datetime

import pytest

from exts.utils.heat import (
    DEFAULT_TERMS,
    MAX_TIMEOUT_SECONDS,
    HeatEngine,
    HeatSettings,
    HeatState,
    TermMatcher,
    effective_terms,
    normalize,
    strip_markup,
)

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
HOUR = 3600
DAY = 86400


class FakeClock:
    def __init__(self, start: datetime.datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += datetime.timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def engine(clock: FakeClock) -> HeatEngine:
    return HeatEngine(clock=clock)


def offend(engine: HeatEngine, state: HeatState, times: int = 1, hits: int = 1) -> tuple[HeatState, list]:
    outcomes = []
    for _ in range(times):
        state, outcome = engine.apply_offense(state, HeatSettings(), hits=hits)
        outcomes.append(outcome)
    return state, outcomes


# heat and decay


def test_one_message_adds_one_heat_regardless_of_distinct_terms(engine: HeatEngine) -> None:
    state, (outcome,) = offend(engine, HeatState(), hits=3)
    assert outcome.kind == "heat" and outcome.heat_added == 1 and outcome.heat == 1
    assert state.heat == 1 and state.lifetime_offenses == 1


def test_heat_decays_one_point_per_hour_never_below_zero(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState(heat=3, heat_updated_at=clock.now)
    clock.advance(59 * 60)
    assert engine.current_heat(state) == 3
    clock.advance(60)
    assert engine.current_heat(state) == 2
    clock.advance(HOUR)
    assert engine.current_heat(state) == 1
    clock.advance(10 * HOUR)
    assert engine.current_heat(state) == 0


def test_decay_keeps_the_leftover_minutes(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState(heat=2, heat_updated_at=clock.now)
    clock.advance(HOUR + 30 * 60)
    decayed = engine.decayed(state)
    assert decayed.heat == 1
    assert decayed.heat_updated_at == T0 + datetime.timedelta(hours=1)  # not "now": the half hour still counts
    clock.advance(29 * 60)
    assert engine.current_heat(decayed) == 1
    clock.advance(60)
    assert engine.current_heat(decayed) == 0


def test_decay_is_applied_before_an_offense_is_added(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState(heat=4, heat_updated_at=clock.now)
    clock.advance(2 * HOUR)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "heat" and outcome.heat == 3  # 4 - 2 + 1, not a mute
    assert state.heat_updated_at == clock.now


# spam windows


def test_window_caps_at_three_and_only_the_third_message_is_spam(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState()
    kinds = []
    for _ in range(5):
        state, (outcome,) = offend(engine, state)
        kinds.append(outcome.kind)
        clock.advance(5)
    assert kinds == ["heat", "heat", "spam", "silent", "silent"]
    assert state.heat == 3
    assert state.lifetime_offenses == 5  # every offending message counts for the leaderboard


def test_single_stuffed_message_fills_the_window(engine: HeatEngine) -> None:
    _, (outcome,) = offend(engine, HeatState(), hits=4)
    assert outcome.kind == "spam" and outcome.heat_added == 3 and outcome.heat == 3


def test_stuffed_message_only_tops_up_a_partly_used_window(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState())
    clock.advance(5)
    state, (outcome,) = offend(engine, state, hits=6)
    assert outcome.kind == "spam" and outcome.heat_added == 2 and state.heat == 3
    clock.advance(5)
    state, (outcome,) = offend(engine, state, hits=6)
    assert outcome.kind == "silent" and outcome.heat_added == 0


def test_window_rolls_over_at_thirty_seconds(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState(), times=3)
    clock.advance(29)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "silent"
    clock.advance(1)  # exactly 30 seconds since the window opened
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "heat" and outcome.heat == 4
    assert state.window_started_at == clock.now and state.window_count == 1


def test_sustained_spam_reaches_a_mute_in_about_a_minute(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState()
    kinds = []
    for _ in range(12):  # one message every 5 seconds for a minute
        state, (outcome,) = offend(engine, state)
        kinds.append(outcome.kind)
        clock.advance(5)
    assert "mute" in kinds
    assert kinds.index("mute") == 7  # 3 heat in window one, the mute lands on the second message of window two


# mutes and repeat offenders


def test_reaching_five_mutes_resets_heat_and_flags_repeat(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState(heat=4, heat_updated_at=clock.now)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "mute"
    assert outcome.heat == 5 and outcome.timeout_seconds == HeatSettings().mute_seconds
    assert state.heat == 0 and state.escalation_level == 0
    assert state.repeat_until == clock.now + datetime.timedelta(days=7)
    assert state.window_started_at is None and state.window_count == 0


def test_repeat_offense_skips_the_ladder_and_escalates(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState(heat=4, heat_updated_at=clock.now))
    clock.advance(10 * 60)
    seconds = []
    for _ in range(4):
        state, (outcome,) = offend(engine, state)
        assert outcome.kind == "escalation" and outcome.heat == 0 and state.heat == 0
        seconds.append(outcome.timeout_seconds)
        clock.advance(DAY)
    assert seconds == [30 * 60, 2 * HOUR, 24 * HOUR, 24 * HOUR]  # 24h is the ceiling of the default ladder
    assert state.escalation_level == 3


def test_each_punishment_refreshes_the_seven_day_window(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState(heat=4, heat_updated_at=clock.now))
    clock.advance(6 * DAY)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "escalation"
    clock.advance(6 * DAY)  # 12 days after the mute, but only 6 since the last punishment
    assert engine.is_repeat(state)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "escalation" and outcome.timeout_seconds == 2 * HOUR


def test_seven_clean_days_fully_reset_the_repeat_flag(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState(heat=4, heat_updated_at=clock.now))
    clock.advance(DAY)
    state, _ = offend(engine, state)  # escalation level 1
    clock.advance(7 * DAY)
    assert not engine.is_repeat(state)
    state, (outcome,) = offend(engine, state)
    assert outcome.kind == "heat" and outcome.heat == 1
    assert state.repeat_until is None and state.escalation_level == 0


def test_configured_ladder_is_clamped_to_discord_maximum(engine: HeatEngine, clock: FakeClock) -> None:
    settings = HeatSettings(mute_seconds=60, ladder_seconds=(60, 40 * DAY))
    state, outcome = engine.apply_offense(HeatState(heat=4, heat_updated_at=clock.now), settings)
    assert outcome.timeout_seconds == 60
    state, outcome = engine.apply_offense(state, settings)
    assert outcome.timeout_seconds == 60
    state, outcome = engine.apply_offense(state, settings)
    assert outcome.timeout_seconds == MAX_TIMEOUT_SECONDS
    state, outcome = engine.apply_offense(state, settings)
    assert outcome.timeout_seconds == MAX_TIMEOUT_SECONDS and outcome.escalation_level == 2


def test_empty_ladder_falls_back_to_the_default(engine: HeatEngine, clock: FakeClock) -> None:
    settings = HeatSettings(ladder_seconds=())
    state, _ = engine.apply_offense(HeatState(heat=4, heat_updated_at=clock.now), settings)
    _, outcome = engine.apply_offense(state, settings)
    assert outcome.timeout_seconds == 30 * 60


# pardons


def test_full_pardon_clears_everything_but_the_lifetime_count(engine: HeatEngine, clock: FakeClock) -> None:
    state, _ = offend(engine, HeatState(heat=4, heat_updated_at=clock.now))
    state, _ = offend(engine, state)
    pardoned = engine.pardon(state)
    assert pardoned.heat == 0 and pardoned.repeat_until is None and pardoned.escalation_level == 0
    assert pardoned.lifetime_offenses == 2


def test_partial_pardon_only_removes_heat(engine: HeatEngine, clock: FakeClock) -> None:
    state = HeatState(heat=3, heat_updated_at=clock.now, repeat_until=clock.now + datetime.timedelta(days=3))
    pardoned = engine.pardon(state, amount=2)
    assert pardoned.heat == 1 and pardoned.repeat_until == state.repeat_until
    assert engine.pardon(state, amount=10).heat == 0


# detection


@pytest.fixture
def matcher() -> TermMatcher:
    return TermMatcher(DEFAULT_TERMS)


@pytest.mark.parametrize(
    "text",
    [
        "rizz",
        "RIZZ",
        "SkIbIdI toilet",
        "rizzzzzz",
        "skibidiiiii",
        "r1zz",
        "5k1b1d1",
        "gy@tt",
        "$igma grindset",
        "r i z z",
        "s k i b i d i",
        "s.k.i.b.i.d.i",
        "r-i-z-z",
        "r_i_z_z",
        "rízz",
        "ｒｉｚｚ",
        "ri\u200bzz",
        "r\u200bi\u200bz\u200bz",
        "fanum tax",
        "fanum-tax",
        "fanumtax",
        "he has zero rizz, honestly",
        "rizz!",
        "(rizz)",
        "skibidi_toilet",
        "goofy ahh",
        "gyat",
        "gyatt",
        "only in ohio",
    ],
)
def test_matches(matcher: TermMatcher, text: str) -> None:
    assert matcher.hits(text) >= 1, text


@pytest.mark.parametrize(
    "text",
    [
        "grizzly bear",
        "rizzo",
        "sigmas",
        "assignment",
        "the bus is late",
        "Ohio is a state",
        "I am in a car",
        "a b c d e",
        "we deployed to prod today",
        "an enigma wrapped in a riddle",
        "the busking musician",
        "",
        "   ",
        "1234567890",
        "this is a perfectly normal sentence with no slang in it",
    ],
)
def test_no_false_positives(matcher: TermMatcher, text: str) -> None:
    assert matcher.hits(text) == 0, text


def test_hits_count_every_occurrence(matcher: TermMatcher) -> None:
    assert matcher.hits("rizz rizz gyat skibidi") == 4
    assert matcher.hits("rizz rizz") == 2


@pytest.mark.parametrize(
    "text",
    [
        "```\nrizz\n```",
        "``` rizz ```",
        "`rizz`",
        "https://rizz.example/skibidi",
        "<:rizz:1234567890>",
        "<a:skibidi:1234567890>",
        "<@1234567890> <@!1234567890> <@&1234567890> <#1234567890>",
        "</brainrot score:1234567890>",
        "<t:1700000000:R>",
    ],
)
def test_markup_is_ignored(matcher: TermMatcher, text: str) -> None:
    assert matcher.hits(text) == 0, text


def test_words_outside_markup_still_count(matcher: TermMatcher) -> None:
    assert matcher.hits("`code` rizz <:rizz:1> https://rizz.example skibidi") == 2
    assert strip_markup("a `b` c") == "a   c"


def test_spaced_join_leaves_normal_words_alone() -> None:
    assert normalize("s k i b i d i toilet") == "skibidi toilet"
    assert normalize("I am in a car") == "i am in a car"
    assert normalize("a b") == "a b"  # two lone letters are not a run


def test_custom_terms_and_allowlist() -> None:
    terms = effective_terms(additions=["Ohio", "grimace shake"], removals=["skibidi"], allowed=["sigma", "RIZZ"])
    matcher = TermMatcher(terms)
    assert matcher.hits("ohio grimace shake") == 2
    assert matcher.hits("skibidi sigma rizz") == 0
    assert matcher.hits("gyat") == 1


def test_empty_matcher_never_matches() -> None:
    assert TermMatcher([]).hits("rizz skibidi") == 0
    assert TermMatcher(["", "  "]).hits("rizz") == 0
