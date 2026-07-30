from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

DEFAULT_RETENTION_DAYS = 90


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _month() -> datetime.date:
    return _now().date().replace(day=1)


class SessionStore:
    """Accessor for the voice recap tables. Every query the module runs lives here."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    # sessions and the job queue

    async def create_session(self, guild_id: int, channel_id: int, started_by: int) -> uuid.UUID:
        session_id = uuid.uuid4()
        await self.pool.execute(
            "INSERT INTO voice_sessions (id, guild_id, channel_id, started_by, started_at) VALUES ($1, $2, $3, $4, $5)",
            session_id,
            guild_id,
            channel_id,
            started_by,
            _now(),
        )
        return session_id

    async def mark_queued(self, session_id: uuid.UUID, seconds: int) -> None:
        await self.pool.execute(
            "UPDATE voice_sessions SET status = 'queued', ended_at = $2, seconds_recorded = $3 WHERE id = $1",
            session_id,
            _now(),
            seconds,
        )

    async def claim_next(self) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            """
            UPDATE voice_sessions SET status = 'processing', attempts = attempts + 1
            WHERE id = (
                SELECT id FROM voice_sessions
                WHERE status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= $1)
                ORDER BY ended_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            _now(),
        )

    async def save_transcript(self, session_id: uuid.UUID, transcript: str) -> None:
        await self.pool.execute("UPDATE voice_sessions SET transcript = $2 WHERE id = $1", session_id, transcript)

    async def finish(self, session_id: uuid.UUID, title: str, recap: str) -> None:
        await self.pool.execute(
            "UPDATE voice_sessions SET status = 'done', title = $2, recap = $3, error = NULL WHERE id = $1",
            session_id,
            title,
            recap,
        )

    async def requeue(self, session_id: uuid.UUID, error: str, delay_seconds: int) -> None:
        await self.pool.execute(
            "UPDATE voice_sessions SET status = 'queued', error = $2, next_attempt_at = $3 WHERE id = $1",
            session_id,
            error,
            _now() + datetime.timedelta(seconds=delay_seconds),
        )

    async def fail(self, session_id: uuid.UUID, error: str) -> None:
        await self.pool.execute("UPDATE voice_sessions SET status = 'failed', error = $2 WHERE id = $1", session_id, error)

    async def stale_recording_sessions(self) -> list[asyncpg.Record]:
        return await self.pool.fetch("SELECT * FROM voice_sessions WHERE status = 'recording'")

    async def reset_processing(self) -> None:
        await self.pool.execute("UPDATE voice_sessions SET status = 'queued' WHERE status = 'processing'")

    async def retryable_session_ids(self) -> list[uuid.UUID]:
        rows = await self.pool.fetch("SELECT id FROM voice_sessions WHERE status IN ('queued', 'processing')")
        return [row["id"] for row in rows]

    # reading sessions back out

    async def get_session(self, guild_id: int, short_id: str) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "SELECT * FROM voice_sessions WHERE guild_id = $1 AND id::text LIKE $2 || '%' LIMIT 1",
            guild_id,
            short_id.lower(),
        )

    async def latest(self, guild_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "SELECT * FROM voice_sessions WHERE guild_id = $1 AND status = 'done' ORDER BY started_at DESC LIMIT 1",
            guild_id,
        )

    async def list_page(self, guild_id: int, offset: int, limit: int) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "SELECT * FROM voice_sessions WHERE guild_id = $1 AND status = 'done'"
            " ORDER BY started_at DESC OFFSET $2 LIMIT $3",
            guild_id,
            offset,
            limit,
        )

    async def count_done(self, guild_id: int) -> int:
        return await self.pool.fetchval(
            "SELECT count(*) FROM voice_sessions WHERE guild_id = $1 AND status = 'done'", guild_id
        )

    async def search(self, guild_id: int, query: str, limit: int = 10) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            """
            SELECT id, title, started_at,
                   ts_headline('english', coalesce(recap, left(transcript, 2000), ''),
                               websearch_to_tsquery('english', $2),
                               'MaxFragments=1, MaxWords=30, MinWords=10') AS snippet
            FROM voice_sessions
            WHERE guild_id = $1 AND status = 'done' AND search @@ websearch_to_tsquery('english', $2)
            ORDER BY ts_rank(search, websearch_to_tsquery('english', $2)) DESC
            LIMIT $3
            """,
            guild_id,
            query,
            limit,
        )

    async def delete_session(self, guild_id: int, session_id: uuid.UUID) -> bool:
        deleted = await self.pool.fetchval(
            "DELETE FROM voice_sessions WHERE guild_id = $1 AND id = $2 RETURNING id", guild_id, session_id
        )
        return deleted is not None

    # retention and purge

    async def purge_expired(self, default_days: int = DEFAULT_RETENTION_DAYS) -> int:
        result = await self.pool.execute(
            """
            DELETE FROM voice_sessions
            WHERE status IN ('done', 'failed', 'cancelled')
              AND started_at < $1::timestamptz - make_interval(days => coalesce(
                    (SELECT retention_days FROM guilds WHERE guilds.id = voice_sessions.guild_id), $2))
            """,
            _now(),
            default_days,
        )
        return int(result.split()[-1])

    async def purge_guild(self, guild_id: int) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM voice_sessions WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM voice_consent WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM voice_usage WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM guilds WHERE id = $1", guild_id)

    async def purge_old_usage(self, keep_months: int = 13) -> None:
        await self.pool.execute(
            "DELETE FROM voice_usage WHERE month < $1::date - make_interval(months => $2)", _month(), keep_months
        )

    # consent

    async def consent_map(self, guild_id: int) -> dict[int, str]:
        rows = await self.pool.fetch("SELECT user_id, status FROM voice_consent WHERE guild_id = $1", guild_id)
        return {row["user_id"]: row["status"] for row in rows}

    async def set_consent(self, guild_id: int, user_id: int, status: str) -> None:
        await self.pool.execute(
            "INSERT INTO voice_consent (guild_id, user_id, status, updated_at) VALUES ($1, $2, $3, $4)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET status = $3, updated_at = $4",
            guild_id,
            user_id,
            status,
            _now(),
        )

    async def get_consent(self, guild_id: int, user_id: int) -> str | None:
        return await self.pool.fetchval(
            "SELECT status FROM voice_consent WHERE guild_id = $1 AND user_id = $2", guild_id, user_id
        )

    # usage metering

    async def add_usage(self, guild_id: int, seconds: int) -> int:
        return await self.pool.fetchval(
            "INSERT INTO voice_usage (guild_id, month, seconds_used) VALUES ($1, $2, $3)"
            " ON CONFLICT (guild_id, month) DO UPDATE SET seconds_used = voice_usage.seconds_used + $3"
            " RETURNING seconds_used",
            guild_id,
            _month(),
            seconds,
        )

    async def get_usage(self, guild_id: int) -> int:
        used = await self.pool.fetchval(
            "SELECT seconds_used FROM voice_usage WHERE guild_id = $1 AND month = $2", guild_id, _month()
        )
        return used or 0
