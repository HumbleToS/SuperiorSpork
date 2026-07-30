import datetime
import uuid

from conftest import requires_db

from exts.utils.sessions import SessionStore

pytestmark = requires_db


async def seed_session(store, pool, guild_id: int, days_old: int, status: str = "done") -> uuid.UUID:
    session_id = await store.create_session(guild_id, 1, 1)
    await pool.execute(
        "UPDATE voice_sessions SET status = $2, started_at = $3, transcript = 'words', recap = 'a recap' WHERE id = $1",
        session_id,
        status,
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_old),
    )
    return session_id


async def test_purge_expired_respects_default_and_guild_override(pool):
    store = SessionStore(pool)
    old_default = await seed_session(store, pool, 1, days_old=100)  # past the 90 day default
    fresh_default = await seed_session(store, pool, 1, days_old=10)
    await pool.execute("INSERT INTO guilds (id, retention_days) VALUES (2, 5)")
    old_override = await seed_session(store, pool, 2, days_old=10)  # past guild 2's 5 day window

    purged = await store.purge_expired()

    assert purged == 2
    remaining = {row["id"] for row in await pool.fetch("SELECT id FROM voice_sessions")}
    assert remaining == {fresh_default}
    assert old_default not in remaining and old_override not in remaining


async def test_purge_expired_never_touches_unprocessed_sessions(pool):
    store = SessionStore(pool)
    await seed_session(store, pool, 1, days_old=365, status="queued")
    await seed_session(store, pool, 1, days_old=365, status="recording")

    assert await store.purge_expired() == 0


async def test_delete_session_is_guild_scoped(pool):
    store = SessionStore(pool)
    session_id = await seed_session(store, pool, 1, days_old=1)

    assert await store.delete_session(guild_id=2, session_id=session_id) is False
    assert await store.delete_session(guild_id=1, session_id=session_id) is True
    assert await pool.fetchval("SELECT count(*) FROM voice_sessions") == 0


async def test_purge_guild_removes_every_trace(pool):
    store = SessionStore(pool)
    await seed_session(store, pool, 1, days_old=1)
    await store.set_consent(1, 42, "consented")
    await store.add_usage(1, 600)
    await pool.execute("INSERT INTO guilds (id, prefix) VALUES (1, '!')")
    await seed_session(store, pool, 2, days_old=1)  # the neighbour guild must survive

    await store.purge_guild(1)

    assert await pool.fetchval("SELECT count(*) FROM voice_sessions WHERE guild_id = 1") == 0
    assert await pool.fetchval("SELECT count(*) FROM voice_consent WHERE guild_id = 1") == 0
    assert await pool.fetchval("SELECT count(*) FROM voice_usage WHERE guild_id = 1") == 0
    assert await pool.fetchval("SELECT count(*) FROM guilds WHERE id = 1") == 0
    assert await pool.fetchval("SELECT count(*) FROM voice_sessions WHERE guild_id = 2") == 1


async def test_short_id_lookup_and_search(pool):
    store = SessionStore(pool)
    session_id = await seed_session(store, pool, 1, days_old=1)
    await pool.execute(
        "UPDATE voice_sessions SET transcript = 'we decided to fight the dragon tomorrow' WHERE id = $1", session_id
    )

    found = await store.get_session(1, str(session_id)[:8])
    assert found is not None and found["id"] == session_id

    hits = await store.search(1, "dragon")
    assert len(hits) == 1 and hits[0]["id"] == session_id
    assert await store.search(1, "spaceship") == []
