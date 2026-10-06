from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from discord.http import Route

if TYPE_CHECKING:
    from discord.http import HTTPClient

SEARCH_LIMIT = 1  # a search is read for its total only; the one message object in the reply is never looked at
INDEX_WAITS = 3  # "index not ready" answers to sleep through before giving up on a server
INDEX_WAIT_CAP = 10.0  # the longest single sleep discord's retry_after is allowed to ask for


@dataclass(frozen=True)
class SearchTotal:
    """What the search index holds for one member of one server."""

    total: int
    indexing: bool = False  # discord is still indexing the server's history, so the number will grow


def search_query(*, author_id: int) -> list[tuple[str, str]]:
    """Query parameters for one search: everything by one author, age-restricted channels included, one result."""
    return [("author_id", str(author_id)), ("include_nsfw", "true"), ("limit", str(SEARCH_LIMIT))]


async def search_total(http: HTTPClient, guild_id: int, author_id: int, *, waits: int = INDEX_WAITS) -> SearchTotal | None:
    """One guild message search, read for its total; None when the index never came ready within `waits` retries.

    Goes through the bot's own http client, so buckets and 429s are handled there. Raises discord.HTTPException
    (Forbidden without Read Message History or the message content intent) like any other request.
    """
    route = Route("GET", "/guilds/{guild_id}/messages/search", guild_id=guild_id)
    params = search_query(author_id=author_id)
    for attempt in range(waits + 1):
        data = await http.request(route, params=params)
        if isinstance(data, dict) and "total_results" in data:
            return SearchTotal(int(data["total_results"]), bool(data.get("doing_deep_historical_index")))
        if attempt == waits:
            break
        # a 202: the server isn't indexed yet, and discord says how long to wait
        retry_after = float(data.get("retry_after", 1.0)) if isinstance(data, dict) else 1.0
        await asyncio.sleep(min(max(retry_after, 0.0), INDEX_WAIT_CAP))
    return None
