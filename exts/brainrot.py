from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from .utils.brainrot import BrainrotConfig, BrainrotStore
from .utils.cache import TTLCache
from .utils.embeds import pastel_color
from .utils.heat import DECAY_SECONDS, MAX_HEAT, MAX_TIMEOUT_SECONDS, HeatEngine, Outcome, normalize
from .utils.layouts import SporkLayout
from .utils.time import ts
from .utils.wording import plural

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)

SWEEP_SECONDS = 30
RETRY_SECONDS = 600  # how long a failed unmute waits before the sweep tries again
CLEANUP_TIME = datetime.time(hour=4, minute=30, tzinfo=datetime.UTC)
SCORED_TTL = 3600  # an edit to a message older than this can be scored again; the cap keeps memory flat
MAX_CHANNELS = 50
MAX_CUSTOM_TERMS = 100
MAX_EXEMPTIONS = 50
MIN_TERM_LENGTH = 3
MAX_TERM_LENGTH = 40
MAX_LADDER_STEPS = 5
MAX_TIMEOUT_MINUTES = MAX_TIMEOUT_SECONDS // 60
LEADERBOARD_SIZE = 10
PODIUM_SIZE = 3
WatchableChannel = discord.TextChannel | discord.VoiceChannel | discord.ForumChannel | discord.Thread
HEAT_LINES: dict[int, tuple[str, str]] = {
    1: ("Heat rising", "that was a little brainrot."),
    2: ("The rot sets in", "your vocabulary is slipping."),
    3: ("Getting cooked", "touch some grass soon."),
    4: ("Well done", "one more and you're off the stove."),
}
# lifetime offenses needed for each leaderboard title, lowest first
TIERS: tuple[tuple[int, str], ...] = (
    (0, "Raw"),
    (1, "Lightly Seared"),
    (5, "Medium"),
    (15, "Well Done"),
    (30, "Cooked"),
    (60, "Burnt"),
    (100, "Charcoal"),
)
_LADDER_STEP = re.compile(r"(\d+)([mhd]?)")
_UNIT_SECONDS = {"": 60, "m": 60, "h": 3600, "d": 86400}


def heat_bar(heat: int) -> str:
    heat = max(0, min(heat, MAX_HEAT))
    return "▰" * heat + "▱" * (MAX_HEAT - heat)


def duration(seconds: int) -> str:
    if seconds < 3600:
        return f"{plural(max(1, seconds // 60)):minute}"
    if seconds < 2 * 86400:
        return f"{plural(seconds // 3600):hour}"
    return f"{plural(seconds // 86400):day}"


def tier_title(offenses: int) -> str:
    title = TIERS[0][1]
    for threshold, name in TIERS:
        if offenses >= threshold:
            title = name
    return title


def parse_ladder(text: str) -> tuple[int, ...] | None:
    """Reads "30m 2h 24h" style ladders; None when any step is unreadable, too long, or there are too many."""
    steps: list[int] = []
    for raw in re.split(r"[,\s]+", text.strip().lower()):
        if not raw:
            continue
        match = _LADDER_STEP.fullmatch(raw)
        if match is None:
            return None
        seconds = int(match[1]) * _UNIT_SECONDS[match[2]]
        if seconds <= 0 or seconds > MAX_TIMEOUT_SECONDS:
            return None
        steps.append(seconds)
    return tuple(steps) if 0 < len(steps) <= MAX_LADDER_STEPS else None


def format_ladder(ladder: tuple[int, ...]) -> str:
    return " → ".join(duration(seconds) for seconds in ladder)


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
        status = f"strike `{outcome.escalation_level}`"
    else:
        status = f"{heat_bar(outcome.heat)} `{outcome.heat}/{MAX_HEAT}`"
    # two lines on purpose: warnings land in the middle of conversation and must not wall the chat
    return SporkLayout(ui.TextDisplay(f"**{title}** {status}\n{name}, {line}"), accent_colour=pastel_color(guild_id))


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


class Brainrot(commands.Cog, description="Heat, mutes, and the leaderboard for brainrot vocabulary"):
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

    async def lift(self, guild: discord.Guild, user_id: int, role_id: int | None, reason: str) -> bool:
        """Undoes a mute the bot applied: the remembered role, or the native timeout. False means try again later."""
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                return True  # they left; roles drop on leave and discord owns the timeout
            except discord.HTTPException as exc:
                _logger.warning(f"could not look up {user_id} in {guild.id} to lift an anti-brainrot mute", exc_info=exc)
                return False
        try:
            if role_id is not None:
                role = guild.get_role(role_id)
                if role is not None and member.get_role(role_id) is not None:
                    await member.remove_roles(role, reason=reason)
            elif member.is_timed_out():
                await member.timeout(None, reason=reason)
        except discord.HTTPException as exc:
            _logger.warning(f"could not lift an anti-brainrot mute for {user_id} in {guild.id}", exc_info=exc)
            return False
        return True

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
            if guild is not None and not await self.lift(
                guild, row["user_id"], row["muted_role_id"], "Anti-brainrot: mute expired"
            ):
                # keep the record and come back later, so a lost permission never leaves someone muted for good
                retry_at = discord.utils.utcnow() + datetime.timedelta(seconds=RETRY_SECONDS)
                await self.store.set_mute(row["guild_id"], row["user_id"], retry_at, row["muted_role_id"])
                continue
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

    def channel_problems(self, channel: discord.abc.GuildChannel | discord.Thread, config: BrainrotConfig) -> str | None:
        perms = channel.permissions_for(channel.guild.me)
        needed = [
            ("View Channel", perms.view_channel),
            ("Send Messages", perms.send_messages),
            ("Embed Links", perms.embed_links),
        ]
        if config.delete_messages:
            needed.append(("Manage Messages", perms.manage_messages))
        missing = [name for name, granted in needed if not granted]
        return f"{channel.mention}: I'm missing {', '.join(missing)}" if missing else None

    def readiness(self, guild: discord.Guild, config: BrainrotConfig) -> list[str]:
        """Everything that would make the feature fail later, as lines an admin can act on."""
        me = guild.me
        problems: list[str] = []
        role = guild.get_role(config.mute_role_id) if config.mute_mode == "role" and config.mute_role_id else None
        if config.mute_mode == "role":
            if role is None:
                problems.append("the muted role isn't set or no longer exists — `brainrot config mode role @role`")
            else:
                if not me.guild_permissions.manage_roles:
                    problems.append("I need Manage Roles to apply the muted role")
                if role >= me.top_role:
                    problems.append(f"{role.mention} has to sit below my top role")
            if not me.guild_permissions.moderate_members:
                problems.append("I need Moderate Members for repeat-offender timeouts")
        elif not me.guild_permissions.moderate_members:
            problems.append("I need Moderate Members to time people out")
        for channel_id in sorted(config.channel_ids):
            channel = guild.get_channel_or_thread(channel_id)
            if channel is None:
                problems.append(f"<#{channel_id}> no longer exists — `brainrot channels remove` it")
                continue
            problem = self.channel_problems(channel, config)
            if problem is not None:
                problems.append(problem)
        return problems

    @brainrot.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def enable(self, ctx: GuildContext) -> None:
        """Turns anti-brainrot on, after checking I have what I need"""
        config = await self.store.get_config(ctx.guild.id)
        problems = self.readiness(ctx.guild, config)
        if problems:
            lines = "\n".join(f"╰ {problem}" for problem in problems)
            await ctx.send(
                f"Not yet — fix these and run `brainrot enable` again:\n{lines}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await self.store.set_config(ctx.guild.id, "enabled", True)
        if config.channel_ids:
            note = f"Watching {plural(len(config.channel_ids)):channel}."
        else:
            note = "No channels are opted in yet — `brainrot channels add #channel` picks them."
        await ctx.send(f"Anti-brainrot is on! {note}", ephemeral=True)

    @brainrot.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def disable(self, ctx: GuildContext) -> None:
        """Turns anti-brainrot off; settings and the leaderboard are kept"""
        await self.store.set_config(ctx.guild.id, "enabled", False)
        await ctx.send("Anti-brainrot is off. Everything is kept, `brainrot enable` brings it back.", ephemeral=True)

    @brainrot.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def prune(self, ctx: GuildContext) -> None:
        """Forgets watched channels, exempt roles, and exempt members that no longer exist"""
        guild = ctx.guild
        config = await self.store.get_config(guild.id)
        # the add/remove commands resolve real objects, so deleted ones can only be dropped here
        channels = [cid for cid in config.channel_ids if guild.get_channel_or_thread(cid) is not None]
        roles = [rid for rid in config.exempt_role_ids if guild.get_role(rid) is not None]
        users = [uid for uid in config.exempt_user_ids if guild.get_member(uid) is not None]
        dropped = (
            len(config.channel_ids)
            - len(channels)
            + len(config.exempt_role_ids)
            - len(roles)
            + len(config.exempt_user_ids)
            - len(users)
        )
        if not dropped:
            await ctx.send("Nothing to prune — everything still exists.", ephemeral=True)
            return
        for column, kept, before in (
            ("channel_ids", channels, config.channel_ids),
            ("exempt_role_ids", roles, config.exempt_role_ids),
            ("exempt_user_ids", users, config.exempt_user_ids),
        ):
            if len(kept) != len(before):
                await self.store.set_config(guild.id, column, kept)
        await ctx.send(f"Pruned {plural(dropped):entry|entries} that no longer exist.", ephemeral=True)

    # channels

    @brainrot.group()
    async def channels(self, ctx: GuildContext) -> None:
        """Which channels are watched"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `brainrot channels add`, `brainrot channels remove`, or `brainrot channels list`.")

    @channels.command(name="add")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="A channel to watch; threads and forum posts follow their parent")
    async def channels_add(self, ctx: GuildContext, channel: WatchableChannel) -> None:
        """Starts watching a channel

        Parameters
        ----------
        channel : discord.TextChannel | discord.VoiceChannel | discord.ForumChannel | discord.Thread
            A channel to watch; threads and forum posts follow their parent
        """
        config = await self.store.get_config(ctx.guild.id)
        if channel.id in config.channel_ids:
            await ctx.send(f"{channel.mention} is already being watched.", ephemeral=True)
            return
        if len(config.channel_ids) >= MAX_CHANNELS:
            await ctx.send(f"That's the limit — {MAX_CHANNELS} channels per server.", ephemeral=True)
            return
        await self.store.set_config(ctx.guild.id, "channel_ids", [*config.channel_ids, channel.id])
        problem = self.channel_problems(channel, config)
        note = f"\n╰ Heads up: {problem}" if problem else ""
        await ctx.send(f"Now watching {channel.mention}.{note}", ephemeral=True)

    @channels.command(name="remove")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel to stop watching")
    async def channels_remove(self, ctx: GuildContext, channel: WatchableChannel) -> None:
        """Stops watching a channel

        Parameters
        ----------
        channel : discord.TextChannel | discord.VoiceChannel | discord.ForumChannel | discord.Thread
            The channel to stop watching
        """
        config = await self.store.get_config(ctx.guild.id)
        if channel.id not in config.channel_ids:
            await ctx.send(f"{channel.mention} wasn't being watched.", ephemeral=True)
            return
        await self.store.set_config(ctx.guild.id, "channel_ids", [cid for cid in config.channel_ids if cid != channel.id])
        await ctx.send(f"No longer watching {channel.mention}.", ephemeral=True)

    @channels.command(name="list")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def channels_list(self, ctx: GuildContext) -> None:
        """Shows the watched channels"""
        config = await self.store.get_config(ctx.guild.id)
        mentions = (
            ", ".join(f"<#{cid}>" for cid in sorted(config.channel_ids)) or "None yet — `brainrot channels add #channel`"
        )
        items: list[ui.Item] = [
            ui.TextDisplay("# Watched channels"),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Channels\n{mentions}"),
            ui.TextDisplay("### Threads\nThreads and forum posts inside a watched channel are watched too."),
            ui.Separator(),
            ui.TextDisplay(f"-# {'On' if config.enabled else 'Off'} • Guild ID: {ctx.guild.id}"),
        ]
        await ctx.send(view=SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id)), ephemeral=True)

    # terms and the allowlist

    async def term_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        config = await self.store.get_config(interaction.guild.id)
        wanted = normalize(current)
        return [app_commands.Choice(name=term, value=term) for term in config.terms if wanted in term][:25]

    async def allowed_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        config = await self.store.get_config(interaction.guild.id)
        wanted = normalize(current)
        return [app_commands.Choice(name=word, value=word) for word in config.allowed_terms if wanted in word][:25]

    def clean_term(self, term: str) -> str | None:
        cleaned = normalize(term).strip()
        if len(cleaned) < MIN_TERM_LENGTH or len(cleaned) > MAX_TERM_LENGTH:
            return None
        return cleaned

    @brainrot.group()
    async def terms(self, ctx: GuildContext) -> None:
        """The brainrot vocabulary for this server"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `brainrot terms add`, `brainrot terms remove`, or `brainrot terms list`.")

    @terms.command(name="add")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(term="A word or short phrase to add to the list")
    async def terms_add(self, ctx: GuildContext, *, term: str) -> None:
        """Adds a term to this server's list

        Parameters
        ----------
        term : str
            A word or short phrase to add to the list
        """
        cleaned = self.clean_term(term)
        if cleaned is None:
            await ctx.send(f"Terms need to be {MIN_TERM_LENGTH} to {MAX_TERM_LENGTH} characters.", ephemeral=True)
            return
        config = await self.store.get_config(ctx.guild.id)
        if cleaned in config.terms:
            await ctx.send(f"`{cleaned}` is already on the list.", ephemeral=True)
            return
        if len(config.added_terms) >= MAX_CUSTOM_TERMS:
            await ctx.send(f"That's the limit — {MAX_CUSTOM_TERMS} custom terms per server.", ephemeral=True)
            return
        # re-adding a default that was removed here just lifts the removal
        if cleaned in config.removed_terms:
            await self.store.set_config(ctx.guild.id, "removed_terms", [t for t in config.removed_terms if t != cleaned])
        else:
            await self.store.set_config(ctx.guild.id, "added_terms", [*config.added_terms, cleaned])
        if cleaned in config.allowed_terms:
            await self.store.set_config(ctx.guild.id, "allowed_terms", [t for t in config.allowed_terms if t != cleaned])
        await ctx.send(f"Added `{cleaned}` to the list.", ephemeral=True)

    @terms.command(name="remove")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(term="The term to drop from the list")
    @app_commands.autocomplete(term=term_autocomplete)
    async def terms_remove(self, ctx: GuildContext, *, term: str) -> None:
        """Removes a term from this server's list, including a default one

        Parameters
        ----------
        term : str
            The term to drop from the list
        """
        cleaned = normalize(term).strip()
        config = await self.store.get_config(ctx.guild.id)
        if cleaned not in config.terms:
            await ctx.send(f"`{cleaned}` isn't on the list.", ephemeral=True)
            return
        if cleaned in config.added_terms:
            await self.store.set_config(ctx.guild.id, "added_terms", [t for t in config.added_terms if t != cleaned])
        else:
            await self.store.set_config(ctx.guild.id, "removed_terms", [*config.removed_terms, cleaned])
        await ctx.send(f"Removed `{cleaned}` from the list.", ephemeral=True)

    @terms.command(name="list")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def terms_list(self, ctx: GuildContext) -> None:
        """Shows the active terms, this server's additions and removals, and the allowlist"""
        config = await self.store.get_config(ctx.guild.id)

        def joined(words: tuple[str, ...]) -> str:
            return ", ".join(f"`{word}`" for word in words) or "None"

        items: list[ui.Item] = [
            ui.TextDisplay(f"# Brainrot vocabulary\n{plural(len(config.terms)):active term}"),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Active\n{joined(config.terms)}"),
            ui.TextDisplay(f"### Added here\n{joined(config.added_terms)}"),
            ui.TextDisplay(f"### Removed here\n{joined(config.removed_terms)}"),
            ui.TextDisplay(f"### Allowed words\n{joined(config.allowed_terms)}"),
            ui.Separator(),
            ui.TextDisplay(
                f"-# Matching ignores case, accents, leetspeak, and stretched letters • Guild ID: {ctx.guild.id}"
            ),
        ]
        await ctx.send(view=SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id)), ephemeral=True)

    @brainrot.group()
    async def allow(self, ctx: GuildContext) -> None:
        """Words this server uses legitimately"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `brainrot allow add`, `brainrot allow remove`, or `brainrot allow list`.")

    @allow.command(name="add")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(word="A word that should never count here, like sigma in a stats server")
    async def allow_add(self, ctx: GuildContext, *, word: str) -> None:
        """Allowlists a word so it never counts in this server

        Parameters
        ----------
        word : str
            A word that should never count here, like sigma in a stats server
        """
        cleaned = self.clean_term(word)
        if cleaned is None:
            await ctx.send(f"Words need to be {MIN_TERM_LENGTH} to {MAX_TERM_LENGTH} characters.", ephemeral=True)
            return
        config = await self.store.get_config(ctx.guild.id)
        if cleaned in config.allowed_terms:
            await ctx.send(f"`{cleaned}` is already allowed.", ephemeral=True)
            return
        if len(config.allowed_terms) >= MAX_CUSTOM_TERMS:
            await ctx.send(f"That's the limit — {MAX_CUSTOM_TERMS} allowed words per server.", ephemeral=True)
            return
        await self.store.set_config(ctx.guild.id, "allowed_terms", [*config.allowed_terms, cleaned])
        await ctx.send(f"`{cleaned}` is allowed here now.", ephemeral=True)

    @allow.command(name="remove")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(word="The word to take off the allowlist")
    @app_commands.autocomplete(word=allowed_autocomplete)
    async def allow_remove(self, ctx: GuildContext, *, word: str) -> None:
        """Takes a word off the allowlist

        Parameters
        ----------
        word : str
            The word to take off the allowlist
        """
        cleaned = normalize(word).strip()
        config = await self.store.get_config(ctx.guild.id)
        if cleaned not in config.allowed_terms:
            await ctx.send(f"`{cleaned}` isn't on the allowlist.", ephemeral=True)
            return
        await self.store.set_config(ctx.guild.id, "allowed_terms", [t for t in config.allowed_terms if t != cleaned])
        await ctx.send(f"`{cleaned}` counts again.", ephemeral=True)

    @allow.command(name="list")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def allow_list(self, ctx: GuildContext) -> None:
        """Shows the allowlist"""
        config = await self.store.get_config(ctx.guild.id)
        words = ", ".join(f"`{word}`" for word in config.allowed_terms) or "None yet — `brainrot allow add word`"
        items: list[ui.Item] = [
            ui.TextDisplay("# Allowed words"),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Never counted here\n{words}"),
            ui.Separator(),
            ui.TextDisplay(f"-# Guild ID: {ctx.guild.id}"),
        ]
        await ctx.send(view=SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id)), ephemeral=True)

    # exemptions

    @brainrot.group()
    async def exempt(self, ctx: GuildContext) -> None:
        """Roles and members the heat system leaves alone"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `brainrot exempt add`, `brainrot exempt remove`, or `brainrot exempt list`.")

    @exempt.command(name="add")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(target="A role or member to exempt")
    async def exempt_add(self, ctx: GuildContext, target: discord.Role | discord.Member) -> None:
        """Exempts a role or member

        Parameters
        ----------
        target : discord.Role | discord.Member
            A role or member to exempt
        """
        config = await self.store.get_config(ctx.guild.id)
        column = "exempt_role_ids" if isinstance(target, discord.Role) else "exempt_user_ids"
        current = config.exempt_role_ids if isinstance(target, discord.Role) else config.exempt_user_ids
        if target.id in current:
            await ctx.send(
                f"{target.mention} is already exempt.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        if len(current) >= MAX_EXEMPTIONS:
            await ctx.send(f"That's the limit — {MAX_EXEMPTIONS} of each kind per server.", ephemeral=True)
            return
        await self.store.set_config(ctx.guild.id, column, [*current, target.id])
        await ctx.send(f"{target.mention} is exempt now.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @exempt.command(name="remove")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(target="The role or member to stop exempting")
    async def exempt_remove(self, ctx: GuildContext, target: discord.Role | discord.Member) -> None:
        """Removes an exemption

        Parameters
        ----------
        target : discord.Role | discord.Member
            The role or member to stop exempting
        """
        config = await self.store.get_config(ctx.guild.id)
        column = "exempt_role_ids" if isinstance(target, discord.Role) else "exempt_user_ids"
        current = config.exempt_role_ids if isinstance(target, discord.Role) else config.exempt_user_ids
        if target.id not in current:
            await ctx.send(
                f"{target.mention} wasn't exempt.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        await self.store.set_config(ctx.guild.id, column, [item for item in current if item != target.id])
        await ctx.send(
            f"{target.mention} is fair game again.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @exempt.command(name="list")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def exempt_list(self, ctx: GuildContext) -> None:
        """Shows exempt roles and members"""
        config = await self.store.get_config(ctx.guild.id)
        roles = ", ".join(f"<@&{rid}>" for rid in sorted(config.exempt_role_ids)) or "None"
        users = ", ".join(f"<@{uid}>" for uid in sorted(config.exempt_user_ids)) or "None"
        mods = (
            "included" if config.include_mods else "exempt (Administrator, Manage Server, Manage Messages, Moderate Members)"
        )
        items: list[ui.Item] = [
            ui.TextDisplay("# Exemptions"),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Roles\n{roles}"),
            ui.TextDisplay(f"### Members\n{users}"),
            ui.TextDisplay(f"### Moderators\n{mods}"),
            ui.Separator(),
            ui.TextDisplay(f"-# Guild ID: {ctx.guild.id}"),
        ]
        view = SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id))
        await ctx.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    # config

    @brainrot.group()
    async def config(self, ctx: GuildContext) -> None:
        """Mute mode, durations, warnings, and the mod log"""
        if ctx.invoked_subcommand is None:
            await ctx.send(
                "Try `brainrot config show`, or one of `mode`, `duration`, `ladder`, `warnings`, `delete`, `mods`, `modlog`."
            )

    @config.command(name="show")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def config_show(self, ctx: GuildContext) -> None:
        """Shows every anti-brainrot setting"""
        config = await self.store.get_config(ctx.guild.id)
        if config.mute_mode == "role":
            role = f"<@&{config.mute_role_id}>" if config.mute_role_id else "no role set"
            mute = f"Muted role ({role}) for {duration(config.mute_seconds)}"
        else:
            mute = f"Timeout for {duration(config.mute_seconds)}"
        warnings = f"Deleted after {plural(config.warn_delete_seconds):second}" if config.warn_delete_seconds else "Kept"
        modlog = f"<#{config.modlog_channel_id}>" if config.modlog_channel_id else "Not set"
        problems = self.readiness(ctx.guild, config)
        items: list[ui.Item] = [
            ui.TextDisplay(
                f"# Anti-brainrot config\n{'On' if config.enabled else 'Off'} • {plural(len(config.channel_ids)):channel} watched"
            ),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Mute at {MAX_HEAT} heat\n{mute}"),
            ui.TextDisplay(f"### Repeat ladder\n{format_ladder(config.ladder_seconds)}"),
            ui.TextDisplay(
                f"### Warnings\n{warnings}"
                f"\n╰ offending messages are {'deleted' if config.delete_messages else 'kept'}"
                f"\n╰ moderators are {'included' if config.include_mods else 'exempt'}"
            ),
            ui.TextDisplay(f"### Mod log\n{modlog}"),
        ]
        if problems:
            items.append(ui.TextDisplay("### Needs attention\n" + "\n".join(f"╰ {problem}" for problem in problems)))
        items.extend(
            (ui.Separator(), ui.TextDisplay(f"-# {plural(len(config.terms)):active term} • Guild ID: {ctx.guild.id}"))
        )
        view = SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id))
        await ctx.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @config.command(name="mode")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(
        mode="timeout uses Discord's built-in timeout; role applies a muted role", role="The muted role, for role mode"
    )
    async def config_mode(
        self, ctx: GuildContext, mode: Literal["timeout", "role"], role: discord.Role | None = None
    ) -> None:
        """Picks how a full heat bar is punished

        Parameters
        ----------
        mode : Literal["timeout", "role"]
            timeout uses Discord's built-in timeout; role applies a muted role
        role : discord.Role | None, optional
            The muted role, for role mode
        """
        if mode == "role":
            if role is None:
                await ctx.send("Role mode needs a role: `brainrot config mode role @Muted`.", ephemeral=True)
                return
            if role.is_default() or role.managed:
                await ctx.send("That role can't be handed out — pick a regular one.", ephemeral=True)
                return
            await self.store.set_config(ctx.guild.id, "mute_role_id", role.id)
        config = await self.store.set_config(ctx.guild.id, "mute_mode", mode)
        problems = [problem for problem in self.readiness(ctx.guild, config) if "channel" not in problem.lower()]
        note = "\n" + "\n".join(f"╰ {problem}" for problem in problems) if problems else ""
        if mode == "role" and role is not None:
            text = f"Full bars now apply {role.mention}. Repeat offenders still get timeouts.{note}"
        else:
            text = f"Full bars now use a timeout.{note}"
        await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @config.command(name="duration")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(minutes="How long a full-bar mute lasts, in minutes (default 5)")
    async def config_duration(self, ctx: GuildContext, minutes: commands.Range[int, 1, MAX_TIMEOUT_MINUTES]) -> None:
        """Sets how long a full-bar mute lasts

        Parameters
        ----------
        minutes : int
            How long a full-bar mute lasts, in minutes (default 5)
        """
        await self.store.set_config(ctx.guild.id, "mute_seconds", minutes * 60)
        await ctx.send(f"A full bar now means {duration(minutes * 60)}.", ephemeral=True)

    @config.command(name="ladder")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(steps="Timeouts for repeat offenders, like 30m 2h 24h (up to 5 steps, 28d max)")
    async def config_ladder(self, ctx: GuildContext, *, steps: str) -> None:
        """Sets the repeat-offender timeout ladder

        Parameters
        ----------
        steps : str
            Timeouts for repeat offenders, like 30m 2h 24h (up to 5 steps, 28d max)
        """
        ladder = parse_ladder(steps)
        if ladder is None:
            await ctx.send(
                "I couldn't read that — try something like `30m 2h 24h` (minutes, hours, or days; up to 5 steps; 28d max).",
                ephemeral=True,
            )
            return
        await self.store.set_config(ctx.guild.id, "ladder_seconds", list(ladder))
        await ctx.send(f"Repeat offenders now climb {format_ladder(ladder)}.", ephemeral=True)

    @config.command(name="warnings")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(seconds="Seconds before a warning deletes itself; 0 keeps them (default 30)")
    async def config_warnings(self, ctx: GuildContext, seconds: commands.Range[int, 0, 600]) -> None:
        """Sets how long warnings stay in chat

        Parameters
        ----------
        seconds : int
            Seconds before a warning deletes itself; 0 keeps them (default 30)
        """
        await self.store.set_config(ctx.guild.id, "warn_delete_seconds", seconds)
        text = f"Warnings now disappear after {plural(seconds):second}." if seconds else "Warnings now stay in chat."
        await ctx.send(text, ephemeral=True)

    @config.command(name="delete")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(enabled="Whether offending messages get deleted (needs Manage Messages)")
    async def config_delete(self, ctx: GuildContext, enabled: bool) -> None:
        """Sets whether offending messages are deleted

        Parameters
        ----------
        enabled : bool
            Whether offending messages get deleted (needs Manage Messages)
        """
        config = await self.store.set_config(ctx.guild.id, "delete_messages", enabled)
        problems = [problem for problem in self.readiness(ctx.guild, config) if "Manage Messages" in problem]
        note = "\n" + "\n".join(f"╰ {problem}" for problem in problems) if problems else ""
        text = f"Offending messages are now {'deleted' if enabled else 'kept'}.{note}"
        await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @config.command(name="mods")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(included="Whether moderators get heat too (they're exempt by default)")
    async def config_mods(self, ctx: GuildContext, included: bool) -> None:
        """Sets whether moderators are included

        Parameters
        ----------
        included : bool
            Whether moderators get heat too (they're exempt by default)
        """
        await self.store.set_config(ctx.guild.id, "include_mods", included)
        text = "Moderators are fair game now." if included else "Moderators are exempt again."
        await ctx.send(text, ephemeral=True)

    @config.command(name="modlog")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Where mutes, timeouts, and pardons get logged; leave empty to turn it off")
    async def config_modlog(self, ctx: GuildContext, channel: discord.TextChannel | discord.Thread | None = None) -> None:
        """Sets the mod log channel

        Parameters
        ----------
        channel : discord.TextChannel | discord.Thread | None, optional
            Where mutes, timeouts, and pardons get logged; leave empty to turn it off
        """
        await self.store.set_config(ctx.guild.id, "modlog_channel_id", channel.id if channel else None)
        if channel is None:
            await ctx.send("The mod log is off.", ephemeral=True)
            return
        problem = self.channel_problems(channel, BrainrotConfig(ctx.guild.id))
        note = f"\n╰ Heads up: {problem}" if problem else ""
        await ctx.send(f"Mutes, timeouts, and pardons now go to {channel.mention}.{note}", ephemeral=True)

    # moderation and the public surfaces

    @brainrot.command()
    @commands.guild_only()
    @commands.has_guild_permissions(moderate_members=True)
    @app_commands.describe(member="Who to pardon", amount="Heat to remove; 0 or empty clears everything")
    async def pardon(self, ctx: GuildContext, member: discord.Member, amount: commands.Range[int, 0, MAX_HEAT] = 0) -> None:
        """Clears someone's heat, repeat flag, and any mute I applied

        Parameters
        ----------
        member : discord.Member
            Who to pardon
        amount : int, optional
            Heat to remove; 0 or empty clears everything, by default 0
        """
        guild = ctx.guild
        async with self._locked(guild.id, member.id):
            state = await self.store.get_state(guild.id, member.id)
            pardoned = self.engine.pardon(state, amount or None)
            await self.store.put_state(guild.id, member.id, pardoned)
            if not amount:
                mute = await self.store.get_mute(guild.id, member.id)
                if mute is not None:
                    await self.lift(
                        guild, member.id, mute["muted_role_id"], f"Anti-brainrot: pardoned by {ctx.author} ({ctx.author.id})"
                    )
                    await self.store.clear_mute(guild.id, member.id)
        config = await self.store.get_config(guild.id)
        if not amount:
            text = f"{member.mention} is pardoned — heat cleared, off the repeat list, and unmuted if I'd muted them."
            status = f"### Heat\n{heat_bar(0)} `0/{MAX_HEAT}`"
        else:
            text = f"Took {plural(amount):point} off {member.mention} — they're at `{pardoned.heat}/{MAX_HEAT}` now."
            status = f"### Heat\n{heat_bar(pardoned.heat)} `{pardoned.heat}/{MAX_HEAT}`"
        await self.modlog(config, member, f"Pardoned by {ctx.author.mention}", status)
        _logger.info(f"brainrot pardon {guild.id=} {member.id=} by {ctx.author.id} {amount=}")
        await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @brainrot.command()
    @commands.guild_only()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    @app_commands.describe(member="Whose heat to check, defaults to you")
    async def score(self, ctx: GuildContext, member: discord.Member | None = None) -> None:
        """Shows someone's heat, repeat status, and lifetime offenses

        Parameters
        ----------
        member : discord.Member | None, optional
            Whose heat to check, defaults to you
        """
        member = member or ctx.author
        state = await self.store.get_state(ctx.guild.id, member.id)
        decayed = self.engine.decayed(state)
        if decayed.heat > 0 and decayed.heat_updated_at is not None:
            cooling = f"╰ next point cools {ts(decayed.heat_updated_at + datetime.timedelta(seconds=DECAY_SECONDS)):R}"
        else:
            cooling = "╰ fully cooled off"
        if self.engine.is_repeat(state) and state.repeat_until is not None:
            repeat = (
                f"On it — clears {ts(state.repeat_until):R}"
                f"\n╰ strike `{state.escalation_level}`, the next offense is a timeout"
            )
        else:
            repeat = "Clean"
        rank = await self.store.rank(ctx.guild.id, member.id)
        lifetime = f"`{state.lifetime_offenses:,}` offenses"
        if rank is not None:
            lifetime += f"\n╰ #{rank:,} on the leaderboard"
        items: list[ui.Item] = [
            ui.Section(
                f"# {discord.utils.escape_markdown(member.display_name)}\n{tier_title(state.lifetime_offenses)}",
                accessory=ui.Thumbnail(member.display_avatar.url),
            ),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(f"### Heat\n{heat_bar(decayed.heat)} `{decayed.heat}/{MAX_HEAT}`\n{cooling}"),
            ui.TextDisplay(f"### Repeat list\n{repeat}"),
            ui.TextDisplay(f"### Lifetime\n{lifetime}"),
            ui.Separator(),
            ui.TextDisplay(f"-# Heat cools 1 point an hour • User ID: {member.id}"),
        ]
        await ctx.send(view=SporkLayout(*items, accent_colour=pastel_color(member.id)))

    @brainrot.command()
    @commands.guild_only()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    async def leaderboard(self, ctx: GuildContext) -> None:
        """The server's most cooked members, by lifetime offenses"""
        guild = ctx.guild
        rows = await self.store.leaderboard(guild.id, LEADERBOARD_SIZE)
        if not rows:
            await ctx.send("Nobody has been cooked here yet!")
            return

        def name_of(user_id: int) -> str:
            member = guild.get_member(user_id)
            return discord.utils.escape_markdown(member.display_name) if member else f"<@{user_id}>"

        title = f"# Most Cooked\nThe brainrot leaderboard for {discord.utils.escape_markdown(guild.name)}"
        header = ui.Section(title, accessory=ui.Thumbnail(guild.icon.url)) if guild.icon else ui.TextDisplay(title)
        items: list[ui.Item] = [header, ui.Separator(spacing=discord.SeparatorSpacing.large)]
        for place, row in enumerate(rows[:PODIUM_SIZE], start=1):
            offenses = row["lifetime_offenses"]
            noun = "offense" if offenses == 1 else "offenses"
            items.append(
                ui.TextDisplay(f"### #{place} {name_of(row['user_id'])}\n{tier_title(offenses)} • `{offenses:,}` {noun}")
            )
        rest = rows[PODIUM_SIZE:]
        if rest:
            lines = "\n".join(
                f"**#{place}** {name_of(row['user_id'])} • {tier_title(row['lifetime_offenses'])} • `{row['lifetime_offenses']:,}`"
                for place, row in enumerate(rest, start=PODIUM_SIZE + 1)
            )
            items.append(ui.TextDisplay(f"### The rest of the kitchen\n{lines}"))
        items.append(ui.Separator())
        items.append(ui.TextDisplay(f"-# Lifetime offenses • `brainrot score` for the details • Guild ID: {guild.id}"))
        view = SporkLayout(*items, accent_colour=pastel_color(guild.id))
        await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: Spork) -> None:
    await bot.add_cog(Brainrot(bot))
