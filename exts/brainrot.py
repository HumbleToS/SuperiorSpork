from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from discord import ui
from discord.ext import commands, tasks

from .utils.brainrot import BrainrotConfig, BrainrotStore
from .utils.cache import TTLCache
from .utils.embeds import pastel_color
from .utils.heat import MAX_HEAT, HeatEngine, Outcome
from .utils.layouts import SporkLayout
from .utils.time import ts
from .utils.wording import plural

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)

SWEEP_SECONDS = 30
CLEANUP_TIME = datetime.time(hour=4, minute=30, tzinfo=datetime.UTC)
SCORED_TTL = 3600  # an edit to a message older than this can be scored again; the cap keeps memory flat
HEAT_LINES: dict[int, tuple[str, str]] = {
    1: ("Heat rising", "that was a little brainrot"),
    2: ("The rot sets in", "your vocabulary is slipping"),
    3: ("Getting cooked", "touch some grass soon"),
    4: ("Well done", "one more and you're off the stove"),
}


def heat_bar(heat: int) -> str:
    heat = max(0, min(heat, MAX_HEAT))
    return "▰" * heat + "▱" * (MAX_HEAT - heat)


def duration(seconds: int) -> str:
    if seconds < 3600:
        return f"{plural(max(1, seconds // 60)):minute}"
    if seconds < 2 * 86400:
        return f"{plural(seconds // 3600):hour}"
    return f"{plural(seconds // 86400):day}"


def warning_card(name: str, outcome: Outcome, punished: bool, guild_id: int) -> SporkLayout:
    seconds = outcome.timeout_seconds or 0
    if outcome.kind == "mute":
        title = "Cooked"
        line = "that's a full bar. "
        line += f"Muted for {duration(seconds)}, heat back to 0, " if punished else "Heat back to 0, "
        line += "and you're on the repeat list for a week."
    elif outcome.kind == "escalation":
        title = "Repeat offender"
        line = f"still on the repeat list — timed out for {duration(seconds)}." if punished else "still on the repeat list."
    elif outcome.kind == "spam":
        title, line = "Spam detected", "that's three warnings' worth in one go."
    else:
        title, line = HEAT_LINES.get(outcome.heat, HEAT_LINES[1])
    if outcome.kind == "escalation":
        status = f"### Repeat list\nStrike `{outcome.escalation_level}` — the list clears after 7 clean days"
    else:
        status = f"### Heat\n{heat_bar(outcome.heat)} `{outcome.heat}/{MAX_HEAT}`"
    items: list[ui.Item] = [
        ui.TextDisplay(f"# {title}\n{name}, {line}"),
        ui.Separator(spacing=discord.SeparatorSpacing.large),
        ui.TextDisplay(status),
        ui.Separator(),
        ui.TextDisplay("-# Heat cools 1 point an hour • `brainrot score` shows yours"),
    ]
    return SporkLayout(*items, accent_colour=pastel_color(guild_id))


def modlog_card(member: discord.Member, action: str, status: str) -> SporkLayout:
    items: list[ui.Item] = [
        ui.Section(
            f"# Anti-brainrot\n{member.mention} ({discord.utils.escape_markdown(str(member))})",
            accessory=ui.Thumbnail(member.display_avatar.url),
        ),
        ui.Separator(spacing=discord.SeparatorSpacing.large),
        ui.TextDisplay(f"### Action\n{action}"),
        ui.TextDisplay(status),
        ui.Separator(),
        ui.TextDisplay(f"-# User ID: {member.id} • {ts(discord.utils.utcnow()):F}"),
    ]
    return SporkLayout(*items, accent_colour=pastel_color(member.guild.id))


@dataclass
class _Slot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    holders: int = 0


class Brainrot(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.store = BrainrotStore(bot.pool)
        self.engine = HeatEngine()
        self._slots: dict[tuple[int, int], _Slot] = {}
        self._scored = TTLCache(ttl=SCORED_TTL, max_size=4096)  # message ids only, so an edit never scores twice

    async def cog_load(self) -> None:
        self.expire_mutes.start()
        self.cleanup.start()

    async def cog_unload(self) -> None:
        self.expire_mutes.cancel()
        self.cleanup.cancel()

    @contextlib.asynccontextmanager
    async def _locked(self, guild_id: int, user_id: int) -> AsyncIterator[None]:
        # one lock per (guild, user) while anyone holds or waits on it, dropped the moment nobody does
        key = (guild_id, user_id)
        slot = self._slots.setdefault(key, _Slot())
        slot.holders += 1
        try:
            async with slot.lock:
                yield
        finally:
            slot.holders -= 1
            if slot.holders == 0:
                self._slots.pop(key, None)

    # detection

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self.inspect(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        # edits also fire when discord unfurls an embed; skip when the text is known not to have changed
        before = payload.cached_message
        if before is not None and before.content == payload.message.content:
            return
        await self.inspect(payload.message)

    async def inspect(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or message.author.bot or message.webhook_id is not None or not message.content:
            return
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        config = await self.store.get_config(guild.id)
        if not config.enabled or not self._channel_enabled(config, message.channel):
            return
        if self._scored.get(message.id) is not None:
            return
        member = message.author if isinstance(message.author, discord.Member) else guild.get_member(message.author.id)
        if member is None or self._exempt(config, member):
            return
        hits = config.matcher.hits(message.content)
        if hits == 0 or await self._is_own_command(message):
            return

        self._scored.set(message.id, True)
        async with self._locked(guild.id, member.id):
            state = await self.store.get_state(guild.id, member.id)
            state, outcome = self.engine.apply_offense(state, config.settings, hits)
            await self.store.put_state(guild.id, member.id, state)
            _logger.debug(f"brainrot offense {guild.id=} {member.id=} {hits=} {outcome.kind=} heat={outcome.heat}")
            await self._respond(message, member, config, outcome)

    def _channel_enabled(self, config: BrainrotConfig, channel: discord.abc.MessageableChannel) -> bool:
        if channel.id in config.channel_ids:
            return True
        return isinstance(channel, discord.Thread) and channel.parent_id in config.channel_ids

    def _exempt(self, config: BrainrotConfig, member: discord.Member) -> bool:
        if member.id in config.exempt_user_ids or any(member.get_role(rid) for rid in config.exempt_role_ids):
            return True
        if config.include_mods:
            return False
        perms = member.guild_permissions
        return perms.administrator or perms.manage_guild or perms.manage_messages or perms.moderate_members

    async def _is_own_command(self, message: discord.Message) -> bool:
        ctx = await self.bot.get_context(message)
        command = ctx.command
        if command is None:
            return False
        root = command.root_parent or command
        return root.qualified_name == self.brainrot.qualified_name

    # consequences

    async def _respond(
        self,
        message: discord.Message,
        member: discord.Member,
        config: BrainrotConfig,
        outcome: Outcome,
    ) -> None:
        if config.delete_messages:
            await self._delete(message)
        punished = False
        if outcome.timeout_seconds is not None:
            punished = await self._punish(member, config, outcome)
        if outcome.kind == "silent":
            return  # messages 4+ in a spam window: counted, never answered
        await self._warn(message, member, config, outcome, punished)
        if punished:
            if outcome.kind == "mute":
                action = f"Muted for {duration(outcome.timeout_seconds or 0)} (heat reached {MAX_HEAT})"
                status = f"### Heat\n{heat_bar(MAX_HEAT)} `{MAX_HEAT}/{MAX_HEAT}`"
            else:
                action = f"Timed out for {duration(outcome.timeout_seconds or 0)} (repeat offense)"
                status = f"### Repeat list\nStrike `{outcome.escalation_level}`"
            await self.modlog(config, member, action, status)

    async def _delete(self, message: discord.Message) -> None:
        channel = message.channel
        if not isinstance(channel, discord.abc.GuildChannel | discord.Thread):
            return
        if not channel.permissions_for(channel.guild.me).manage_messages:
            _logger.info(f"Skipped deleting a brainrot message in {channel.id}: missing Manage Messages")
            return
        try:
            await message.delete()
        except discord.HTTPException as exc:
            _logger.debug(f"could not delete brainrot message {message.id}", exc_info=exc)

    async def _warn(
        self,
        message: discord.Message,
        member: discord.Member,
        config: BrainrotConfig,
        outcome: Outcome,
        punished: bool,
    ) -> None:
        name = discord.utils.escape_markdown(member.display_name)
        view = warning_card(name, outcome, punished, member.guild.id)
        mentions = discord.AllowedMentions.none()
        try:
            if config.delete_messages:
                sent = await message.channel.send(view=view, allowed_mentions=mentions)
            else:
                sent = await message.reply(view=view, allowed_mentions=mentions, mention_author=False)
            if config.warn_delete_seconds > 0:
                await sent.delete(delay=config.warn_delete_seconds)  # 0 keeps warnings around
        except discord.HTTPException as exc:
            _logger.debug(f"could not post a brainrot warning in {message.channel.id}", exc_info=exc)

    def mute_role(self, config: BrainrotConfig, guild: discord.Guild) -> discord.Role | None:
        """The configured muted role, or None when the server uses timeouts or the role is gone."""
        if config.mute_mode != "role" or config.mute_role_id is None:
            return None
        role = guild.get_role(config.mute_role_id)
        if role is None:
            # the configured role is gone; a native timeout beats letting the mute silently vanish
            _logger.warning(f"Muted role {config.mute_role_id} is missing in {guild.id}, falling back to a timeout")
        return role

    def blocker(self, member: discord.Member, role: discord.Role | None) -> str | None:
        """Why the bot must not punish this member right now, or None when it can."""
        guild = member.guild
        me = guild.me
        if member.id == guild.owner_id:
            return "they own the server"
        if member.guild_permissions.administrator:
            return "they are an administrator"
        if me.top_role <= member.top_role:
            return "their top role is at or above mine"
        if role is not None:
            if not me.guild_permissions.manage_roles:
                return "I don't have Manage Roles"
            if role >= me.top_role:
                return "the muted role is at or above my top role"
            return None
        if not me.guild_permissions.moderate_members:
            return "I don't have Moderate Members"
        return None

    async def _punish(self, member: discord.Member, config: BrainrotConfig, outcome: Outcome) -> bool:
        guild = member.guild
        seconds = outcome.timeout_seconds or 0
        # role mode only covers the heat mute; repeat offenders always get a native timeout
        role = self.mute_role(config, guild) if outcome.kind == "mute" else None
        blocked = self.blocker(member, role)
        if blocked is not None:
            _logger.info(f"Skipped an anti-brainrot {outcome.kind} for {member.id} in {guild.id}: {blocked}")
            return False
        if outcome.kind == "mute":
            reason = f"Anti-brainrot: heat {MAX_HEAT}/{MAX_HEAT}"
        else:
            reason = f"Anti-brainrot: repeat offense, strike {outcome.escalation_level}"
        until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
        try:
            if role is not None:
                await member.add_roles(role, reason=reason)
                await self.store.set_mute(guild.id, member.id, until, role.id)
            else:
                await member.timeout(until, reason=reason)
                await self.store.set_mute(guild.id, member.id, until, None)
        except discord.HTTPException as exc:
            _logger.warning(f"could not apply an anti-brainrot {outcome.kind} to {member.id} in {guild.id}", exc_info=exc)
            return False
        return True

    async def lift(self, guild: discord.Guild, user_id: int, role_id: int | None, reason: str) -> None:
        """Undoes a mute the bot applied: the remembered role, or the native timeout."""
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return  # they left; roles drop on leave and discord owns the timeout
        try:
            if role_id is not None:
                role = guild.get_role(role_id)
                if role is not None and member.get_role(role_id) is not None:
                    await member.remove_roles(role, reason=reason)
            elif member.is_timed_out():
                await member.timeout(None, reason=reason)
        except discord.HTTPException as exc:
            _logger.warning(f"could not lift an anti-brainrot mute for {user_id} in {guild.id}", exc_info=exc)

    async def modlog(self, config: BrainrotConfig, member: discord.Member, action: str, status: str) -> None:
        if config.modlog_channel_id is None:
            return
        channel = member.guild.get_channel_or_thread(config.modlog_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            _logger.info(f"brainrot mod log channel {config.modlog_channel_id} is gone in {member.guild.id}")
            return
        try:
            await channel.send(view=modlog_card(member, action, status), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            _logger.debug(f"could not post to the brainrot mod log in {member.guild.id}", exc_info=exc)

    # role mutes survive restarts through the database; the sweep is the only thing that ends them

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = await self.store.get_config(member.guild.id)
        if not config.enabled or config.mute_mode != "role":
            return
        row = await self.store.pending_role_mute(member.guild.id, member.id)
        if row is None:
            return
        role = member.guild.get_role(row["muted_role_id"])
        if role is None:
            return
        try:
            await member.add_roles(role, reason="Anti-brainrot: mute still active after rejoining")
        except discord.HTTPException as exc:
            _logger.info(f"could not restore an anti-brainrot mute for {member.id} in {member.guild.id}", exc_info=exc)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.store.purge_guild(guild.id)
        _logger.info(f"Purged anti-brainrot data for departed guild {guild.id}")

    @tasks.loop(seconds=SWEEP_SECONDS)
    async def expire_mutes(self) -> None:
        for row in await self.store.expired_role_mutes():
            guild = self.bot.get_guild(row["guild_id"])
            if guild is not None:
                await self.lift(guild, row["user_id"], row["muted_role_id"], "Anti-brainrot: mute expired")
            await self.store.clear_mute(row["guild_id"], row["user_id"])

    @expire_mutes.before_loop
    async def before_expire_mutes(self) -> None:
        await self.bot.wait_until_ready()

    @expire_mutes.error
    async def expire_mutes_error(self, error: BaseException) -> None:
        _logger.error("brainrot mute sweep errored", exc_info=error)

    @tasks.loop(time=CLEANUP_TIME)
    async def cleanup(self) -> None:
        pruned = await self.store.prune_idle()
        if pruned:
            _logger.info(f"Anti-brainrot cleanup removed {pruned} idle rows")

    @cleanup.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()

    @cleanup.error
    async def cleanup_error(self, error: BaseException) -> None:
        _logger.error("brainrot cleanup loop errored", exc_info=error)

    # commands

    @commands.hybrid_group()
    async def brainrot(self, ctx: GuildContext) -> None:
        """Anti-brainrot: heat, mutes, and the leaderboard"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `brainrot score`, `brainrot leaderboard`, or `brainrot enable`.")


async def setup(bot: Spork) -> None:
    await bot.add_cog(Brainrot(bot))
