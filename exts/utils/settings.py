from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


class GuildSettings:
    """Accessor for per-guild settings stored in the guilds table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool
        self._prefixes: dict[int, str | None] = {}

    async def get_prefix(self, guild_id: int) -> str | None:
        if guild_id in self._prefixes:
            return self._prefixes[guild_id]
        prefix = await self.pool.fetchval("SELECT prefix FROM guilds WHERE id = $1", guild_id)
        self._prefixes[guild_id] = prefix
        return prefix

    async def set_prefix(self, guild_id: int, prefix: str) -> None:
        await self.pool.execute(
            "INSERT INTO guilds (id, prefix) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET prefix = $2",
            guild_id,
            prefix,
        )
        self._prefixes[guild_id] = prefix
