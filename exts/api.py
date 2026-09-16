from __future__ import annotations

import datetime
import hmac
import logging
import math
from typing import TYPE_CHECKING, Any, Literal, cast

import discord
from aiohttp import web
from discord.ext import commands

import config

from .utils.api import (
    ApiError,
    action_dict,
    boolean,
    channel_dict,
    channel_type,
    choice,
    colour_hex,
    config_dict,
    index_dict,
    integer,
    integers,
    json_body,
    offender_dict,
    ok,
    page_args,
    paged,
    role_dict,
    snowflake,
    snowflakes,
    user_dict,
    words,
)
from .utils.brainrot import (
    ACTION_KINDS,
    ACTION_SOURCES,
    MAX_CHANNELS,
    MAX_CUSTOM_TERMS,
    MAX_EXEMPTIONS,
    MAX_LADDER_STEPS,
    MAX_TERM_LENGTH,
    MAX_WARN_SECONDS,
    MIN_MUTE_SECONDS,
    MIN_TERM_LENGTH,
    TIERS,
    BrainrotError,
    WatchableChannel,
)
from .utils.cache import TTLCache
from .utils.embeds import pastel_color
from .utils.heat import (
    DECAY_SECONDS,
    DEFAULT_TERMS,
    MAX_HEAT,
    MAX_TIMEOUT_SECONDS,
    REPEAT_DAYS,
    SPAM_HITS,
    WINDOW_CAP,
    WINDOW_SECONDS,
    HeatState,
)
from .utils.help import build_index

if TYPE_CHECKING:
    from aiohttp.typedefs import Handler

    from bot import Spork

    from .brainrot import Brainrot
    from .help import Help
    from .utils.brainrot import BrainrotConfig

_logger = logging.getLogger(__name__)

PREFIX = "/internal/v1"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
USER_HEADER = "X-Acting-User-Id"
MANAGER_TTL = 60  # seconds a "this user may manage that guild" answer is trusted, so fetch_member stays rare
SEARCH_LIMIT = 10
CONFIG_FIELDS = frozenset(
    {
        "enabled",
        "mute_mode",
        "mute_role_id",
        "mute_seconds",
        "ladder_seconds",
        "warn_delete_seconds",
        "delete_messages",
        "include_mods",
        "modlog_channel_id",
    }
)
# what the invite link asks for: everything any module needs, so a server never has to re-invite for a feature
INVITE_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    send_messages_in_threads=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    use_external_emojis=True,
    manage_messages=True,
    moderate_members=True,
    manage_roles=True,
    connect=True,
)
_PERMISSION_NAMES = (
    "view_channel",
    "send_messages",
    "embed_links",
    "manage_messages",
    "moderate_members",
    "manage_roles",
    "read_message_history",
)
_STATUS_FOR = {"not_ready": 409, "invalid": 422, "limit_reached": 422, "not_found": 404}
SOURCE: Literal["dashboard"] = "dashboard"


class InternalApi(commands.Cog):
    """The dashboard's only door into the bot: aiohttp on the bot's loop, a private network, one bearer token."""

    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.runner: web.AppRunner | None = None
        self._managers = TTLCache(ttl=MANAGER_TTL, max_size=4096)
        self.app = web.Application(middlewares=[self.authenticate, self.envelope])
        guild = f"{PREFIX}/guilds/{{guild_id}}"
        self.app.add_routes(
            [
                web.get(f"{PREFIX}/health", self.health),
                web.get(f"{PREFIX}/app", self.app_info),
                web.get(f"{PREFIX}/commands", self.commands_index),
                web.get(f"{PREFIX}/brainrot/defaults", self.brainrot_defaults),
                web.get(f"{PREFIX}/guilds", self.guilds),
                web.get(f"{guild}/meta", self.guild_meta),
                web.get(f"{guild}/members/search", self.member_search),
                web.get(f"{guild}/members/{{user_id}}", self.member_get),
                web.get(f"{guild}/brainrot/config", self.config_get),
                web.patch(f"{guild}/brainrot/config", self.config_patch),
                web.get(f"{guild}/brainrot/channels", self.channels_get),
                web.put(f"{guild}/brainrot/channels", self.channels_put),
                web.get(f"{guild}/brainrot/terms", self.terms_get),
                web.put(f"{guild}/brainrot/terms", self.terms_put),
                web.get(f"{guild}/brainrot/allowlist", self.allowlist_get),
                web.put(f"{guild}/brainrot/allowlist", self.allowlist_put),
                web.get(f"{guild}/brainrot/exemptions", self.exemptions_get),
                web.put(f"{guild}/brainrot/exemptions", self.exemptions_put),
                web.get(f"{guild}/brainrot/summary", self.summary),
                web.get(f"{guild}/brainrot/offenders", self.offenders),
                web.post(f"{guild}/brainrot/pardon", self.pardon),
                web.get(f"{guild}/brainrot/actions", self.actions),
            ]
        )

    async def cog_load(self) -> None:
        if not self.token():
            _logger.info("API_TOKEN is empty, so the internal api stays off")
            return
        host = str(getattr(config, "API_HOST", DEFAULT_HOST))
        port = int(getattr(config, "API_PORT", DEFAULT_PORT))
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, host, port).start()
        _logger.info("Internal api listening on %s:%s%s", host, port, PREFIX)

    async def cog_unload(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    @staticmethod
    def token() -> str:
        return str(getattr(config, "API_TOKEN", "") or "")

    # middleware

    @web.middleware
    async def authenticate(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
        token = self.token()
        if not token or scheme != "Bearer" or not hmac.compare_digest(credential.encode(), token.encode()):
            return web.Response(status=401)  # bare on purpose: a wrong door teaches nothing
        return await handler(request)

    @web.middleware
    async def envelope(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        try:
            return await handler(request)
        except ApiError as error:
            return error.response()
        except BrainrotError as error:
            status = _STATUS_FOR.get(error.code, 422)
            return ApiError(status, error.code, str(error), field=error.field, problems=error.problems).response()
        except web.HTTPException as error:
            if error.status >= 500:
                raise
            code = "not_found" if error.status == 404 else "bad_request"
            return ApiError(error.status, code, error.reason or "That request didn't make sense.").response()
        except Exception:
            _logger.exception(f"internal api failed on {request.method} {request.path}")
            return ApiError(500, "internal", "Something broke on my side; it's been logged.").response()

    # who is asking, and about which guild

    def acting_user(self, request: web.Request, *, allow_query: bool = False) -> int:
        value = request.headers.get(USER_HEADER)
        if value is None and allow_query:
            value = request.query.get("user_id")
        if value is None:
            raise ApiError(400, "bad_request", f"{USER_HEADER} is required.", field=USER_HEADER)
        return snowflake(value, USER_HEADER)

    def guild_of(self, request: web.Request) -> discord.Guild:
        guild = self.bot.get_guild(snowflake(request.match_info["guild_id"], "guild_id"))
        if guild is None:
            raise ApiError(404, "guild_not_found", "I'm not in that server.")
        return guild

    async def manager(self, guild: discord.Guild, user_id: int) -> discord.Member:
        """The acting user as a member who owns the guild or has Manage Server, else 403; answers are cached briefly."""
        key = (guild.id, user_id)
        cached = self._managers.get(key)
        if cached is False:
            raise ApiError(403, "forbidden", "You need Manage Server in that server.")
        if isinstance(cached, discord.Member):
            return cached
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                self._managers.set(key, False)
                raise ApiError(403, "forbidden", "You're not in that server.") from None
            except discord.HTTPException as exc:
                _logger.warning(f"could not look up {user_id} in {guild.id} for the internal api", exc_info=exc)
                raise ApiError(503, "unavailable", "Discord didn't answer; try again in a moment.") from exc
        if not (member.id == guild.owner_id or member.guild_permissions.manage_guild):
            self._managers.set(key, False)
            raise ApiError(403, "forbidden", "You need Manage Server in that server.")
        self._managers.set(key, member)
        return member

    async def scoped(self, request: web.Request) -> tuple[discord.Guild, discord.Member]:
        guild = self.guild_of(request)
        return guild, await self.manager(guild, self.acting_user(request))

    async def member_of(self, guild: discord.Guild, user_id: int) -> discord.Member:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                raise ApiError(404, "not_found", "That user isn't in this server.", field="user_id") from None
            except discord.HTTPException as exc:
                raise ApiError(503, "unavailable", "Discord didn't answer; try again in a moment.") from exc
        return member

    def brainrot(self) -> Brainrot:
        cog = self.bot.get_cog("Brainrot")
        if cog is None:
            raise ApiError(404, "module_unavailable", "Anti-brainrot isn't loaded right now.")
        return cast("Brainrot", cog)

    def help(self) -> Help:
        cog = self.bot.get_cog("Help")
        if cog is None:
            raise ApiError(404, "module_unavailable", "Help isn't loaded right now.")
        return cast("Help", cog)

    def user_ref(self, guild: discord.Guild, user_id: int | None) -> dict[str, Any] | None:
        if user_id is None:
            return None
        user = guild.get_member(user_id) or self.bot.get_user(user_id)
        return user_dict(user) or {"id": str(user_id), "name": None, "username": None, "avatar": None, "bot": False}

    @staticmethod
    def guild_dict(guild: discord.Guild) -> dict[str, Any]:
        return {
            "id": str(guild.id),
            "name": guild.name,
            "icon": guild.icon.with_size(128).url if guild.icon else None,
            "accent": colour_hex(pastel_color(guild.id)),
        }

    # the process

    async def health(self, request: web.Request) -> web.Response:
        latency = self.bot.latency
        if not self.bot.is_ready() or not math.isfinite(latency):
            raise ApiError(503, "unavailable", "I'm not connected to Discord right now.")
        return ok({"ready": True, "latency_ms": round(latency * 1000), "guilds": len(self.bot.guilds)})

    async def app_info(self, request: web.Request) -> web.Response:
        application_id = self.bot.application_id or (self.bot.user.id if self.bot.user else None)
        if application_id is None:
            raise ApiError(503, "unavailable", "I don't know my own application id yet.")
        invite = discord.utils.oauth_url(
            application_id, permissions=INVITE_PERMISSIONS, scopes=("bot", "applications.commands")
        )
        return ok(
            {
                "application_id": str(application_id),
                "permissions": str(INVITE_PERMISSIONS.value),
                "invite_url": invite,
                "prefix": config.PREFIX,
            }
        )

    async def commands_index(self, request: web.Request) -> web.Response:
        index = build_index(self.bot, self.help().ids_for(None), config.PREFIX)
        return ok(index_dict(index, config.PREFIX))

    async def brainrot_defaults(self, request: web.Request) -> web.Response:
        self.brainrot()
        return ok(
            {
                "default_terms": list(DEFAULT_TERMS),
                "tiers": [{"min_offenses": threshold, "title": title} for threshold, title in TIERS],
                "max_heat": MAX_HEAT,
                "decay_seconds": DECAY_SECONDS,
                "window_seconds": WINDOW_SECONDS,
                "window_cap": WINDOW_CAP,
                "spam_hits": SPAM_HITS,
                "repeat_days": REPEAT_DAYS,
                "mute_modes": ["timeout", "role"],
                "limits": {
                    "channels": MAX_CHANNELS,
                    "custom_terms": MAX_CUSTOM_TERMS,
                    "exemptions": MAX_EXEMPTIONS,
                    "term_length": {"min": MIN_TERM_LENGTH, "max": MAX_TERM_LENGTH},
                    "ladder_steps": MAX_LADDER_STEPS,
                    "mute_seconds": {"min": MIN_MUTE_SECONDS, "max": MAX_TIMEOUT_SECONDS},
                    "warn_delete_seconds": {"min": 0, "max": MAX_WARN_SECONDS},
                    "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
                },
            }
        )

    # guilds and their furniture

    async def guilds(self, request: web.Request) -> web.Response:
        user_id = self.acting_user(request, allow_query=True)
        data: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member is not None and (guild.owner_id == user_id or member.guild_permissions.manage_guild):
                data.append(self.guild_dict(guild) | {"owner": guild.owner_id == user_id})
        return ok(data)

    async def guild_meta(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        brainrot_config = await cog.store.get_config(guild.id)
        me = guild.me
        channels = sorted(
            (channel for channel in guild.channels if channel_type(channel) is not None),
            key=lambda channel: (channel.category.position if channel.category else -1, channel.position, channel.id),
        )
        permissions = me.guild_permissions
        problems = cog.readiness(guild, brainrot_config)
        return ok(
            self.guild_dict(guild)
            | {
                "owner_id": str(guild.owner_id),
                "channels": [channel_dict(channel) for channel in channels],
                "roles": [role_dict(role, me) for role in guild.roles],
                "me": {
                    "top_role_id": str(me.top_role.id),
                    "permissions": {name: bool(getattr(permissions, name)) for name in _PERMISSION_NAMES},
                },
                "brainrot": {"ready": not problems, "problems": problems},
            }
        )

    async def member_search(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        query = request.query.get("q", "").strip()
        if not query:
            raise ApiError(400, "bad_request", "q is required.", field="q")
        wanted = query.casefold()
        results: list[discord.Member] = []
        if query.isdigit():
            exact = guild.get_member(int(query))
            if exact is not None:
                results.append(exact)
        for member in guild.members:
            if len(results) >= SEARCH_LIMIT:
                break
            if member not in results and (wanted in member.display_name.casefold() or wanted in member.name.casefold()):
                results.append(member)
        if len(results) < SEARCH_LIMIT and not guild.chunked:
            # the cache is partial; one gateway query fills the gap without any extra intent
            try:
                fetched = await guild.query_members(query, limit=SEARCH_LIMIT)
            except (discord.HTTPException, TimeoutError):
                fetched = []
            results.extend(member for member in fetched if member not in results)
        return ok([user_dict(member) for member in results[:SEARCH_LIMIT]])

    async def member_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        member = await self.member_of(guild, snowflake(request.match_info["user_id"], "user_id"))
        return ok(user_dict(member))

    # anti-brainrot config

    async def config_response(self, guild: discord.Guild, cog: Brainrot) -> web.Response:
        brainrot_config = await cog.store.get_config(guild.id)
        return ok(config_dict(brainrot_config, cog.readiness(guild, brainrot_config)))

    async def config_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        return await self.config_response(guild, self.brainrot())

    async def config_patch(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        body = await json_body(request)
        unknown = sorted(set(body) - CONFIG_FIELDS)
        if unknown:
            raise ApiError(400, "bad_request", f"Unknown settings: {', '.join(unknown)}.", field=unknown[0])
        if "mute_mode" in body or "mute_role_id" in body:
            current = await cog.store.get_config(guild.id)
            mode = body.get("mute_mode", current.mute_mode)
            if mode not in ("timeout", "role"):
                raise ApiError(422, "invalid", "mute_mode must be timeout or role.", field="mute_mode")
            role = None
            if mode == "role":
                role_id = body.get("mute_role_id", current.mute_role_id)
                if role_id is None:
                    raise ApiError(422, "invalid", "Role mode needs a muted role.", field="mute_role_id")
                role = guild.get_role(snowflake(role_id, "mute_role_id"))
                if role is None:
                    raise ApiError(404, "not_found", "That role isn't in this server.", field="mute_role_id")
            await cog.set_mode(guild, mode, role, actor=actor, source=SOURCE)
        if "mute_seconds" in body:
            await cog.set_mute_seconds(guild, integer(body["mute_seconds"], "mute_seconds"), actor=actor, source=SOURCE)
        if "ladder_seconds" in body:
            ladder = tuple(integers(body["ladder_seconds"], "ladder_seconds"))
            await cog.set_ladder(guild, ladder, actor=actor, source=SOURCE)
        if "warn_delete_seconds" in body:
            seconds = integer(body["warn_delete_seconds"], "warn_delete_seconds")
            await cog.set_warn_seconds(guild, seconds, actor=actor, source=SOURCE)
        if "delete_messages" in body:
            await cog.set_delete(guild, boolean(body["delete_messages"], "delete_messages"), actor=actor, source=SOURCE)
        if "include_mods" in body:
            await cog.set_mods(guild, boolean(body["include_mods"], "include_mods"), actor=actor, source=SOURCE)
        if "modlog_channel_id" in body:
            channel: discord.TextChannel | discord.Thread | None = None
            if body["modlog_channel_id"] is not None:
                found = guild.get_channel_or_thread(snowflake(body["modlog_channel_id"], "modlog_channel_id"))
                if found is None:
                    raise ApiError(404, "not_found", "That channel isn't in this server.", field="modlog_channel_id")
                if not isinstance(found, discord.TextChannel | discord.Thread):
                    raise ApiError(
                        422, "invalid", "The mod log has to be a text channel or thread.", field="modlog_channel_id"
                    )
                channel = found
            await cog.set_modlog(guild, channel, actor=actor, source=SOURCE)
        if "enabled" in body:
            await cog.set_enabled(guild, boolean(body["enabled"], "enabled"), actor=actor, source=SOURCE)
        return await self.config_response(guild, cog)

    # anti-brainrot lists: the dashboard sends the whole list, the bot diffs and applies it item by item

    @staticmethod
    def channels_dict(guild: discord.Guild, brainrot_config: BrainrotConfig) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for channel_id in sorted(brainrot_config.channel_ids):
            channel = guild.get_channel_or_thread(channel_id)
            items.append(
                {
                    "id": str(channel_id),
                    "name": channel.name if channel is not None else None,
                    "type": channel_type(channel) if channel is not None else None,
                    "exists": channel is not None,
                }
            )
        return {"channels": items}

    async def channels_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        return ok(self.channels_dict(guild, await cog.store.get_config(guild.id)))

    async def channels_put(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        wanted = snowflakes((await json_body(request)).get("channel_ids"), "channel_ids")
        current = await cog.store.get_config(guild.id)
        try:
            for channel_id in sorted(current.channel_ids - set(wanted)):
                await cog.remove_channel(guild, channel_id, actor=actor, source=SOURCE)
            for channel_id in wanted:
                if channel_id in current.channel_ids:
                    continue
                channel = guild.get_channel_or_thread(channel_id)
                if channel is None:
                    raise ApiError(404, "not_found", "That channel isn't in this server.", field="channel_ids")
                if not isinstance(channel, WatchableChannel):
                    message = f"#{channel.name} can't be watched — pick a text, voice, forum, or announcement channel."
                    raise ApiError(422, "invalid", message, field="channel_ids")
                await cog.add_channel(guild, channel, actor=actor, source=SOURCE)
        except (ApiError, BrainrotError) as error:
            raise self.partial(error, self.channels_dict(guild, await cog.store.get_config(guild.id))) from None
        return ok(self.channels_dict(guild, await cog.store.get_config(guild.id)))

    @staticmethod
    def terms_dict(brainrot_config: BrainrotConfig) -> dict[str, Any]:
        return {
            "active": list(brainrot_config.terms),
            "defaults": list(DEFAULT_TERMS),
            "added": list(brainrot_config.added_terms),
            "removed": list(brainrot_config.removed_terms),
            "allowed": list(brainrot_config.allowed_terms),
        }

    async def terms_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        return ok(self.terms_dict(await cog.store.get_config(guild.id)))

    async def terms_put(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        body = await json_body(request)
        current = await cog.store.get_config(guild.id)
        added = words(body.get("added", list(current.added_terms)), "added")
        removed = words(body.get("removed", list(current.removed_terms)), "removed")
        try:
            # removals first, so a term moving between lists never trips the duplicate check
            for term in current.added_terms:
                if term not in added:
                    await cog.remove_term(guild, term, actor=actor, source=SOURCE)
            for term in removed:
                if term not in current.removed_terms:
                    await cog.remove_term(guild, term, actor=actor, source=SOURCE)
            for term in current.removed_terms:
                if term not in removed:
                    await cog.add_term(guild, term, actor=actor, source=SOURCE)
            for term in added:
                if term not in current.added_terms:
                    await cog.add_term(guild, term, actor=actor, source=SOURCE)
        except (ApiError, BrainrotError) as error:
            raise self.partial(error, self.terms_dict(await cog.store.get_config(guild.id))) from None
        return ok(self.terms_dict(await cog.store.get_config(guild.id)))

    async def allowlist_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        return ok({"allowed": list((await cog.store.get_config(guild.id)).allowed_terms)})

    async def allowlist_put(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        allowed = words((await json_body(request)).get("allowed"), "allowed")
        current = await cog.store.get_config(guild.id)
        try:
            for word in current.allowed_terms:
                if word not in allowed:
                    await cog.remove_allowed(guild, word, actor=actor, source=SOURCE)
            for word in allowed:
                if word not in current.allowed_terms:
                    await cog.add_allowed(guild, word, actor=actor, source=SOURCE)
        except (ApiError, BrainrotError) as error:
            state = {"allowed": list((await cog.store.get_config(guild.id)).allowed_terms)}
            raise self.partial(error, state) from None
        return ok({"allowed": list((await cog.store.get_config(guild.id)).allowed_terms)})

    def exemptions_dict(self, guild: discord.Guild, brainrot_config: BrainrotConfig) -> dict[str, Any]:
        roles: list[dict[str, Any]] = []
        for role_id in sorted(brainrot_config.exempt_role_ids):
            role = guild.get_role(role_id)
            roles.append(
                {
                    "id": str(role_id),
                    "name": role.name if role is not None else None,
                    "color": colour_hex(role.colour) if role is not None and role.colour.value else None,
                    "exists": role is not None,
                }
            )
        users: list[dict[str, Any]] = []
        for user_id in sorted(brainrot_config.exempt_user_ids):
            member = guild.get_member(user_id)
            users.append(
                {
                    "id": str(user_id),
                    "name": member.display_name if member is not None else None,
                    "avatar": member.display_avatar.url if member is not None else None,
                    "exists": member is not None,
                }
            )
        return {"roles": roles, "users": users, "include_mods": brainrot_config.include_mods}

    async def exemptions_get(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        return ok(self.exemptions_dict(guild, await cog.store.get_config(guild.id)))

    async def exemptions_put(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        body = await json_body(request)
        current = await cog.store.get_config(guild.id)
        role_ids = snowflakes(body.get("role_ids", [str(rid) for rid in current.exempt_role_ids]), "role_ids")
        user_ids = snowflakes(body.get("user_ids", [str(uid) for uid in current.exempt_user_ids]), "user_ids")
        try:
            for role_id in sorted(current.exempt_role_ids - set(role_ids)):
                await cog.remove_exemption(guild, "role", role_id, actor=actor, source=SOURCE)
            for user_id in sorted(current.exempt_user_ids - set(user_ids)):
                await cog.remove_exemption(guild, "user", user_id, actor=actor, source=SOURCE)
            for role_id in role_ids:
                if role_id in current.exempt_role_ids:
                    continue
                role = guild.get_role(role_id)
                if role is None:
                    raise ApiError(404, "not_found", "That role isn't in this server.", field="role_ids")
                await cog.add_exemption(guild, role, actor=actor, source=SOURCE)
            for user_id in user_ids:
                if user_id in current.exempt_user_ids:
                    continue
                await cog.add_exemption(guild, await self.member_of(guild, user_id), actor=actor, source=SOURCE)
        except (ApiError, BrainrotError) as error:
            raise self.partial(error, self.exemptions_dict(guild, await cog.store.get_config(guild.id))) from None
        return ok(self.exemptions_dict(guild, await cog.store.get_config(guild.id)))

    @staticmethod
    def partial(error: ApiError | BrainrotError, state: dict[str, Any]) -> ApiError:
        """Wraps a refusal from the middle of a list update with the state as it now stands."""
        if isinstance(error, ApiError):
            return ApiError(error.status, error.code, error.message, field=error.field, problems=error.problems, data=state)
        status = _STATUS_FOR.get(error.code, 422)
        return ApiError(status, error.code, str(error), field=error.field, problems=error.problems, data=state)

    # anti-brainrot people

    async def summary(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        brainrot_config = await cog.store.get_config(guild.id)
        row = await cog.store.summary(guild.id)
        since = discord.utils.utcnow() - datetime.timedelta(days=1)
        return ok(
            {
                "enabled": brainrot_config.enabled,
                "watched_channels": len(brainrot_config.channel_ids),
                "hot_users": int(row["hot_users"]),
                "muted_now": int(row["muted_now"]),
                "on_repeat_list": int(row["on_repeat_list"]),
                "lifetime_offenses": int(row["lifetime_offenses"]),
                "actions_24h": await cog.store.count_actions_since(guild.id, since),
            }
        )

    async def offenders(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        page, per_page = page_args(request.query)
        sort = choice(request.query, "sort", ("heat", "lifetime"), "heat")
        rows, total = await cog.store.offenders(
            guild.id, page=page, per_page=per_page, sort="lifetime" if sort == "lifetime" else "heat"
        )
        now = discord.utils.utcnow()
        data: list[dict[str, Any]] = []
        for row in rows:
            member = guild.get_member(row["user_id"])
            user = member or self.bot.get_user(row["user_id"])
            decayed = cog.engine.decayed(HeatState.from_row(row), now)
            data.append(offender_dict(row, decayed, now, user, member is not None))
        return paged(data, page, per_page, total)

    async def pardon(self, request: web.Request) -> web.Response:
        guild, actor = await self.scoped(request)
        cog = self.brainrot()
        body = await json_body(request)
        amount = integer(body.get("amount", 0), "amount")
        if not 0 <= amount <= MAX_HEAT:
            raise ApiError(422, "invalid", f"amount is 0 to {MAX_HEAT}; 0 clears everything.", field="amount")
        member = await self.member_of(guild, snowflake(body.get("user_id"), "user_id"))
        pardoned, lifted = await cog.pardon_member(guild, member, amount, actor=actor, source=SOURCE)
        return ok(
            {
                "user_id": str(member.id),
                "heat": pardoned.heat,
                "repeat": cog.engine.is_repeat(pardoned),
                "lifted_mute": lifted,
            }
        )

    async def actions(self, request: web.Request) -> web.Response:
        guild, _ = await self.scoped(request)
        cog = self.brainrot()
        page, per_page = page_args(request.query)
        action = choice(request.query, "action", ACTION_KINDS, None)
        source = choice(request.query, "source", ACTION_SOURCES, None)
        rows, total = await cog.store.actions(guild.id, page=page, per_page=per_page, action=action, source=source)
        data = [action_dict(row, lambda user_id: self.user_ref(guild, user_id)) for row in rows]
        return paged(data, page, per_page, total)


async def setup(bot: Spork) -> None:
    await bot.add_cog(InternalApi(bot))
