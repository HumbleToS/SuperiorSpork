import os
import pathlib

import pytest

TEST_DSN = os.environ.get("SPORK_TEST_DSN")

requires_db = pytest.mark.skipif(TEST_DSN is None, reason="SPORK_TEST_DSN is not set")


@pytest.fixture
async def pool():
    import asyncpg

    pool = await asyncpg.create_pool(TEST_DSN)
    schema = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
    await pool.execute(schema.read_text())
    await pool.execute("TRUNCATE voice_sessions, voice_consent, voice_usage")
    await pool.execute("DELETE FROM guilds")
    yield pool
    await pool.close()
