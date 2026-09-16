from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

from .brainrot import tier_title
from .heat import DECAY_SECONDS, MAX_HEAT

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import asyncpg

    from .brainrot import BrainrotConfig
    from .heat import HeatState
    from .help import HelpEntry, HelpIndex

DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100
MAX_SNOWFLAKE = 2**64

_CHANNEL_TYPES: dict[discord.ChannelType, str] = {
    discord.ChannelType.text: "text",
    discord.ChannelType.news: "announcement",
    discord.ChannelType.voice: "voice",
    discord.ChannelType.stage_voice: "stage",
    discord.ChannelType.forum: "forum",
    discord.ChannelType.media: "media",
}


class ApiError(Exception):
    """A refusal the dashboard shows as-is: an http status, a machine code, and one sentence for the admin."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        problems: Sequence[str] = (),
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.problems = list(problems)
        self.data = data  # for a partially applied change: the state as it stands, so the ui can re-render honestly

    def response(self) -> web.Response:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field is not None:
            error["field"] = self.field
        if self.problems:
            error["problems"] = self.problems
        body: dict[str, Any] = {"ok": False, "error": error}
        if self.data is not None:
            body["data"] = self.data
        return web.json_response(body, status=self.status)


# the envelope


def ok(data: Any, status: int = 200) -> web.Response:
    return web.json_response({"ok": True, "data": data}, status=status)


def paged(data: list[Any], page: int, per_page: int, total: int) -> web.Response:
    meta = {"page": page, "per_page": per_page, "total": total, "pages": max(1, math.ceil(total / per_page))}
    return web.json_response({"ok": True, "data": data, "page": meta})


# reading requests


def snowflake(value: object, field: str) -> int:
    """A Discord id from JSON or a query string; ids travel as strings because they overflow a JS number."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ApiError(400, "bad_request", f"{field} must be a Discord ID.", field=field)
    text = str(value)
    if not text.isdigit() or not 0 < int(text) < MAX_SNOWFLAKE:
        raise ApiError(400, "bad_request", f"{field} must be a Discord ID.", field=field)
    return int(text)


def snowflakes(value: object, field: str) -> list[int]:
    """A JSON list of ids, in order, without duplicates."""
    if not isinstance(value, list):
        raise ApiError(400, "bad_request", f"{field} must be a list of Discord IDs.", field=field)
    return list(dict.fromkeys(snowflake(item, field) for item in value))


def words(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ApiError(400, "bad_request", f"{field} must be a list of words.", field=field)
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, "bad_request", f"{field} must be a whole number.", field=field)
    return value


def integers(value: object, field: str) -> list[int]:
    if not isinstance(value, list):
        raise ApiError(400, "bad_request", f"{field} must be a list of whole numbers.", field=field)
    return [integer(item, field) for item in value]


def boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError(400, "bad_request", f"{field} must be true or false.", field=field)
    return value


def page_args(query: Mapping[str, str]) -> tuple[int, int]:
    try:
        page = int(query.get("page", 1))
        per_page = int(query.get("per_page", DEFAULT_PER_PAGE))
    except ValueError:
        raise ApiError(400, "bad_request", "page and per_page must be whole numbers.") from None
    if page < 1 or not 1 <= per_page <= MAX_PER_PAGE:
        raise ApiError(400, "bad_request", f"page starts at 1 and per_page is 1 to {MAX_PER_PAGE}.")
    return page, per_page


def choice(query: Mapping[str, str], key: str, allowed: Sequence[str] | frozenset[str], default: str | None) -> str | None:
    value = query.get(key)
    if value is None or value == "":
        return default
    if value not in allowed:
        raise ApiError(400, "bad_request", f"{key} must be one of {', '.join(sorted(allowed))}.", field=key)
    return value


async def json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "bad_request", "The request body isn't valid JSON.") from None
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "The request body must be a JSON object.")
    return body


# writing responses


def iso(when: datetime.datetime | None) -> str | None:
    return when.isoformat() if when is not None else None


def colour_hex(colour: discord.Colour) -> str:
    return f"#{colour.value:06x}"


def channel_type(channel: discord.abc.GuildChannel | discord.Thread) -> str | None:
    if isinstance(channel, discord.Thread):
        return "thread"
    return _CHANNEL_TYPES.get(channel.type)


def channel_dict(channel: discord.abc.GuildChannel) -> dict[str, Any]:
    category = channel.category
    return {
        "id": str(channel.id),
        "name": channel.name,
        "type": channel_type(channel),
        "position": channel.position,
        "category": {"id": str(category.id), "name": category.name} if category is not None else None,
    }


def role_dict(role: discord.Role, me: discord.Member) -> dict[str, Any]:
    return {
        "id": str(role.id),
        "name": role.name,
        "color": colour_hex(role.colour) if role.colour.value else None,
        "position": role.position,
        "managed": role.managed,
        "everyone": role.is_default(),
        "assignable": not role.managed and not role.is_default() and role < me.top_role,
    }


def user_dict(user: discord.abc.User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.display_name,
        "username": user.name,
        "avatar": user.display_avatar.url,
        "bot": user.bot,
    }


def entry_dict(entry: HelpEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "shown_name": entry.shown_name,
        "description": entry.description,
        "details": entry.details,
        "usage": entry.usage,
        "example": entry.example,
        "permissions": list(entry.permissions),
        "guild_only": entry.guild_only,
        "cooldown": entry.cooldown,
        "slash": entry.slash,
        "slash_id": str(entry.slash_id) if entry.slash_id is not None else None,
    }


def index_dict(index: HelpIndex, prefix: str) -> dict[str, Any]:
    """The help index without owner-only commands; hidden ones never made it into the index."""
    categories: list[dict[str, Any]] = []
    for category in index.categories:
        entries = [entry_dict(entry) for entry in category.entries if "Bot owner" not in entry.permissions]
        if entries:
            categories.append({"name": category.name, "blurb": category.blurb, "emoji": category.emoji, "commands": entries})
    return {"prefix": prefix, "categories": categories}


def config_dict(config: BrainrotConfig, problems: Sequence[str]) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "mute_mode": config.mute_mode,
        "mute_role_id": str(config.mute_role_id) if config.mute_role_id is not None else None,
        "mute_seconds": config.mute_seconds,
        "ladder_seconds": list(config.ladder_seconds),
        "warn_delete_seconds": config.warn_delete_seconds,
        "delete_messages": config.delete_messages,
        "include_mods": config.include_mods,
        "modlog_channel_id": str(config.modlog_channel_id) if config.modlog_channel_id is not None else None,
        "ready": not problems,
        "problems": list(problems),
        "counts": {
            "channels": len(config.channel_ids),
            "terms": len(config.terms),
            "added": len(config.added_terms),
            "removed": len(config.removed_terms),
            "allowed": len(config.allowed_terms),
            "exempt_roles": len(config.exempt_role_ids),
            "exempt_users": len(config.exempt_user_ids),
        },
    }


def offender_dict(
    row: asyncpg.Record | Mapping[str, Any],
    decayed: HeatState,
    now: datetime.datetime,
    user: discord.abc.User | None,
    in_guild: bool,
) -> dict[str, Any]:
    repeat_until = row["repeat_until"]
    muted_until = row["mute_expires_at"]
    cooling_at = None
    if decayed.heat > 0 and decayed.heat_updated_at is not None:
        cooling_at = decayed.heat_updated_at + datetime.timedelta(seconds=DECAY_SECONDS)
    lifetime = row["lifetime_offenses"]
    return {
        "user_id": str(row["user_id"]),
        "name": user.display_name if user is not None else None,
        "avatar": user.display_avatar.url if user is not None else None,
        "in_guild": in_guild,
        "heat": decayed.heat,
        "max_heat": MAX_HEAT,
        "cooling_at": iso(cooling_at),
        "repeat": repeat_until is not None and now < repeat_until,
        "repeat_until": iso(repeat_until) if repeat_until is not None and now < repeat_until else None,
        "escalation_level": row["escalation_level"],
        "lifetime_offenses": lifetime,
        "title": tier_title(lifetime),
        "rank": row["rank"] if lifetime > 0 else None,
        "muted_until": iso(muted_until) if muted_until is not None and now < muted_until else None,
    }


def action_dict(
    row: asyncpg.Record | Mapping[str, Any], resolve: Callable[[int | None], dict[str, Any] | None]
) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "at": iso(row["at"]),
        "action": row["action"],
        "source": row["source"],
        "applied": row["applied"],
        "target": resolve(row["target_user_id"]),
        "actor": resolve(row["actor_user_id"]),
        "heat": row["heat"],
        "heat_added": row["heat_added"],
        "duration_seconds": row["duration_seconds"],
        "escalation_level": row["escalation_level"],
        "field": row["field"],
        "before": row["before"],
        "after": row["after"],
    }
