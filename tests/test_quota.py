import asyncio
import datetime

from conftest import requires_db

from exts.utils.sessions import SessionStore

pytestmark = requires_db


async def test_concurrent_usage_increments_never_lose_seconds(pool):
    store = SessionStore(pool)

    await asyncio.gather(*(store.add_usage(1, 60) for _ in range(25)))

    assert await store.get_usage(1) == 25 * 60


async def test_usage_is_bucketed_by_calendar_month(pool):
    store = SessionStore(pool)
    last_month = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    await pool.execute("INSERT INTO voice_usage (guild_id, month, seconds_used) VALUES (1, $1, 9999)", last_month)

    await store.add_usage(1, 120)

    assert await store.get_usage(1) == 120  # last month's spend does not count against this month


async def test_usage_is_per_guild(pool):
    store = SessionStore(pool)
    await store.add_usage(1, 300)
    await store.add_usage(2, 60)

    assert await store.get_usage(1) == 300
    assert await store.get_usage(2) == 60


async def test_add_usage_returns_the_new_total_for_quota_checks(pool):
    store = SessionStore(pool)
    assert await store.add_usage(1, 100) == 100
    assert await store.add_usage(1, 50) == 150


async def test_purge_old_usage_keeps_recent_months(pool):
    store = SessionStore(pool)
    ancient = (datetime.date.today().replace(day=1) - datetime.timedelta(days=450)).replace(day=1)
    await pool.execute("INSERT INTO voice_usage (guild_id, month, seconds_used) VALUES (1, $1, 1)", ancient)
    await store.add_usage(1, 60)

    await store.purge_old_usage()

    months = [row["month"] for row in await pool.fetch("SELECT month FROM voice_usage WHERE guild_id = 1")]
    assert len(months) == 1 and months[0] != ancient
