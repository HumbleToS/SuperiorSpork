import asyncio
import datetime

import pytest
from conftest import requires_db

from exts.utils.brainrot import BrainrotStore
from exts.utils.heat import DEFAULT_TERMS, HeatState

pytestmark = requires_db


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@pytest.fixture
async def store(pool) -> BrainrotStore:
    await pool.execute("TRUNCATE brainrot_users, brainrot_guilds, brainrot_actions")
    return BrainrotStore(pool)


async def test_config_defaults_then_round_trips_and_invalidates(store: BrainrotStore) -> None:
    config = await store.get_config(1)
    assert config.enabled is False and config.mute_mode == "timeout" and config.terms
    assert store.cached_config(1) is config

    config = await store.set_config(1, "enabled", True)
    config = await store.set_config(1, "channel_ids", [10, 20])
    config = await store.set_config(1, "added_terms", ["grimace shake"])
    config = await store.set_config(1, "allowed_terms", ["sigma"])
    config = await store.set_config(1, "ladder_seconds", [60, 120])
    config = await store.set_config(1, "mute_mode", "role")
    assert config.enabled and config.channel_ids == {10, 20}
    assert "grimace shake" in config.terms and "sigma" not in config.terms and "rizz" in config.terms
    assert config.ladder_seconds == (60, 120) and config.mute_mode == "role"
    assert config.matcher.hits("sigma grimace shake") == 1

    store.invalidate(1)
    assert store.cached_config(1) is None
    assert (await store.get_config(1)).channel_ids == {10, 20}


async def test_unknown_config_column_is_refused(store: BrainrotStore) -> None:
    with pytest.raises(ValueError):
        await store.set_config(1, "guild_id; DROP TABLE brainrot_guilds", 1)


async def test_state_round_trip_preserves_every_field(store: BrainrotStore) -> None:
    assert await store.get_state(1, 2) == HeatState()
    at = now().replace(microsecond=0)
    state = HeatState(
        heat=3,
        heat_updated_at=at,
        window_started_at=at,
        window_count=2,
        lifetime_offenses=9,
        repeat_until=at + datetime.timedelta(days=7),
        escalation_level=2,
    )
    await store.put_state(1, 2, state)
    assert await store.get_state(1, 2) == state
    await store.put_state(1, 2, HeatState(heat=0, heat_updated_at=at, lifetime_offenses=10))
    assert (await store.get_state(1, 2)).lifetime_offenses == 10


async def test_mutes_are_remembered_by_role_and_swept_when_expired(store: BrainrotStore) -> None:
    await store.put_state(1, 2, HeatState(heat_updated_at=now()))
    await store.put_state(1, 3, HeatState(heat_updated_at=now()))
    await store.put_state(1, 4, HeatState(heat_updated_at=now()))
    await store.set_mute(1, 2, now() - datetime.timedelta(seconds=1), 500)  # expired role mute
    await store.set_mute(1, 3, now() + datetime.timedelta(minutes=5), 500)  # pending role mute
    await store.set_mute(1, 4, now() - datetime.timedelta(seconds=1), None)  # expired native timeout: discord's job

    expired = await store.expired_role_mutes()
    assert [(row["guild_id"], row["user_id"], row["muted_role_id"]) for row in expired] == [(1, 2, 500)]
    assert await store.get_mute(1, 2) is None
    assert (await store.get_mute(1, 3))["muted_role_id"] == 500
    assert (await store.pending_role_mute(1, 3))["muted_role_id"] == 500
    assert await store.pending_role_mute(1, 2) is None

    await store.clear_mute(1, 2)
    assert await store.expired_role_mutes() == []


async def test_leaderboard_and_rank(store: BrainrotStore) -> None:
    for user_id, offenses in ((2, 5), (3, 12), (4, 5), (5, 0)):
        await store.put_state(1, user_id, HeatState(heat_updated_at=now(), lifetime_offenses=offenses))
    await store.put_state(2, 9, HeatState(heat_updated_at=now(), lifetime_offenses=99))  # another guild

    rows = await store.leaderboard(1)
    assert [(row["user_id"], row["lifetime_offenses"]) for row in rows] == [(3, 12), (2, 5), (4, 5)]
    assert await store.rank(1, 3) == 1
    assert await store.rank(1, 2) == 2 and await store.rank(1, 4) == 2
    assert await store.rank(1, 5) is None and await store.rank(1, 404) is None


async def test_prune_only_drops_rows_with_nothing_left_to_remember(store: BrainrotStore) -> None:
    stale = now() - datetime.timedelta(hours=6)
    await store.put_state(1, 2, HeatState(heat=3, heat_updated_at=stale))  # decayed to zero, nothing else
    await store.put_state(1, 3, HeatState(heat=3, heat_updated_at=stale, lifetime_offenses=3))  # leaderboard keeps it
    await store.put_state(1, 4, HeatState(heat=3, heat_updated_at=stale, repeat_until=now() + datetime.timedelta(days=1)))
    await store.put_state(1, 5, HeatState(heat=5, heat_updated_at=now()))  # still hot
    await store.put_state(1, 6, HeatState(heat_updated_at=stale))
    await store.set_mute(1, 6, now() + datetime.timedelta(minutes=1), 500)  # mute pending

    assert await store.prune_idle() == 1
    remaining = {row["user_id"] for row in await store.pool.fetch("SELECT user_id FROM brainrot_users WHERE guild_id = 1")}
    assert remaining == {3, 4, 5, 6}


async def test_purge_guild_leaves_the_neighbours_alone(store: BrainrotStore) -> None:
    await store.set_config(1, "enabled", True)
    await store.set_config(2, "enabled", True)
    await store.put_state(1, 2, HeatState(heat_updated_at=now(), lifetime_offenses=1))
    await store.put_state(2, 2, HeatState(heat_updated_at=now(), lifetime_offenses=1))
    await store.log_action(1, "warning", "auto", target_user_id=2, heat=1)
    await store.log_action(2, "warning", "auto", target_user_id=2, heat=1)

    await store.purge_guild(1)

    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_actions WHERE guild_id = 1") == 0
    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_actions WHERE guild_id = 2") == 1
    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_users WHERE guild_id = 1") == 0
    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_guilds WHERE guild_id = 1") == 0
    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_users WHERE guild_id = 2") == 1
    assert store.cached_config(1) is None and (await store.get_config(1)).enabled is False
    assert (await store.get_config(2)).enabled is True


async def test_concurrent_writes_to_one_row_never_error(store: BrainrotStore) -> None:
    # the cog serializes per user with a lock; the store itself must still be safe under overlapping upserts
    await asyncio.gather(*(store.put_state(1, 2, HeatState(heat_updated_at=now(), lifetime_offenses=i)) for i in range(20)))
    assert (await store.get_state(1, 2)).lifetime_offenses in range(20)
    assert len(DEFAULT_TERMS) == len((await store.get_config(1)).terms)


async def test_offenders_order_by_decayed_heat_then_lifetime(store: BrainrotStore) -> None:
    at = now()
    await store.put_state(1, 10, HeatState(heat=4, heat_updated_at=at - datetime.timedelta(hours=3), lifetime_offenses=4))
    await store.put_state(1, 20, HeatState(heat=2, heat_updated_at=at, lifetime_offenses=30))
    await store.put_state(1, 30, HeatState(heat=0, heat_updated_at=at, lifetime_offenses=9))
    await store.put_state(2, 40, HeatState(heat=5, heat_updated_at=at, lifetime_offenses=1))

    rows, total = await store.offenders(1, page=1, per_page=10)
    assert total == 3 and [row["user_id"] for row in rows] == [20, 10, 30]  # 4 heat cooled to 1 over three hours
    assert [row["rank"] for row in rows] == [1, 3, 2]
    rows, total = await store.offenders(1, page=1, per_page=2, sort="lifetime")
    assert total == 3 and [row["user_id"] for row in rows] == [20, 30]
    rows, _ = await store.offenders(1, page=2, per_page=2, sort="lifetime")
    assert [row["user_id"] for row in rows] == [10]
    rows, total = await store.offenders(1, page=9, per_page=2)
    assert rows == [] and total == 3


async def test_summary_counts_hot_muted_and_repeat(store: BrainrotStore) -> None:
    at = now()
    await store.put_state(1, 10, HeatState(heat=2, heat_updated_at=at, lifetime_offenses=2))
    await store.put_state(1, 20, HeatState(heat=3, heat_updated_at=at - datetime.timedelta(hours=5), lifetime_offenses=3))
    await store.put_state(
        1, 30, HeatState(heat_updated_at=at, repeat_until=at + datetime.timedelta(days=1), lifetime_offenses=5)
    )
    await store.set_mute(1, 30, at + datetime.timedelta(minutes=5), None)

    row = await store.summary(1)
    assert (row["hot_users"], row["muted_now"], row["on_repeat_list"], row["lifetime_offenses"]) == (1, 1, 1, 10)
    empty = await store.summary(2)
    assert (empty["hot_users"], empty["lifetime_offenses"]) == (0, 0)


async def test_action_log_pages_filters_and_prunes(store: BrainrotStore) -> None:
    await store.log_action(1, "warning", "auto", target_user_id=10, heat=1, heat_added=1)
    await store.log_action(1, "mute", "auto", target_user_id=10, heat=5, duration_seconds=300, applied=False)
    await store.log_action(1, "pardon", "command", target_user_id=10, actor_user_id=99, heat=0)
    await store.log_action(1, "config", "dashboard", actor_user_id=99, field="mute_seconds", before="300", after="600")
    await store.log_action(2, "warning", "auto", target_user_id=11, heat=1)

    rows, total = await store.actions(1, page=1, per_page=2)
    assert total == 4 and [row["action"] for row in rows] == ["config", "pardon"]  # newest first
    assert rows[0]["field"] == "mute_seconds" and rows[0]["before"] == "300" and rows[0]["source"] == "dashboard"
    rows, total = await store.actions(1, page=1, per_page=10, source="auto")
    assert total == 2 and [row["applied"] for row in rows] == [False, True]  # the mute (newer) was blocked
    rows, total = await store.actions(1, page=1, per_page=10, action="pardon")
    assert total == 1 and rows[0]["actor_user_id"] == 99
    assert await store.count_actions_since(1, now() - datetime.timedelta(minutes=1)) == 4
    assert await store.count_actions_since(1, now() + datetime.timedelta(minutes=1)) == 0

    await store.pool.execute("UPDATE brainrot_actions SET at = at - interval '40 days' WHERE guild_id = 2")
    assert await store.prune_actions() == 1
    assert await store.pool.fetchval("SELECT count(*) FROM brainrot_actions") == 4
