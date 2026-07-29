from __future__ import annotations

import datetime
import logging
import os
import re
import time
from typing import TYPE_CHECKING

import discord
import psutil
from discord import app_commands, ui
from discord.ext import commands

from config import PREFIX

from .utils.cache import TTLCache
from .utils.checks import is_guild_owner
from .utils.embeds import SporkEmbed
from .utils.emojis import Status
from .utils.guilds import GuildGraphics
from .utils.layouts import SporkLayout, graphics_gallery
from .utils.time import how_old, ts
from .utils.wording import plural

if TYPE_CHECKING:
    from discord.ext.commands import Context

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)


class General(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self._current_process = psutil.Process(os.getpid())
        self._current_process.cpu_percent()  # the first reading is always 0.0, prime it
        self._profile_cache = TTLCache(ttl=900)  # banners/accents barely change; 15 minutes spares the API

    @commands.Cog.listener(name="on_message")
    async def mention_responder(self, message: discord.Message) -> discord.Message | None:
        guild = message.guild
        if not guild:
            return
        if re.fullmatch(rf"<@!?{guild.me.id}>", message.content):
            prefix = await self.bot.settings.get_prefix(guild.id) or PREFIX
            embed = SporkEmbed(
                description=f"Hello! My prefix is `{prefix}`",
            )
            return await message.reply(embed=embed)
        return

    @commands.hybrid_command()
    @commands.guild_only()
    @is_guild_owner()
    @app_commands.describe(new_prefix="The new prefix, leave empty to see the current one")
    async def prefix(self, ctx: GuildContext, new_prefix: str | None = None) -> None:
        """Shows or changes my prefix for this server

        Parameters
        ----------
        new_prefix : str | None, optional
            The new prefix, leave empty to see the current one
        """
        if new_prefix is None:
            current = await self.bot.settings.get_prefix(ctx.guild.id) or PREFIX
            await ctx.send(f"My prefix here is `{current}`")
            return

        if len(new_prefix) > 10:
            await ctx.send("That prefix is too long! Keep it to 10 characters or less.")
            return

        await self.bot.settings.set_prefix(ctx.guild.id, new_prefix)
        await ctx.send(f"My prefix here is now `{new_prefix}`")

    @commands.command(aliases=("cu", "pb"))
    @commands.guild_only()
    @commands.cooldown(1, 5.0, commands.BucketType.user)  # 1 per 5 seconds per user
    async def cleanup(self, ctx: GuildContext, amount: int = 100) -> None:
        """Purges messages from and relating to the bot.

        Parameters
        ----------
        amount : int, optional
            The number of messages to check (1-100), defaults to 100.
        """
        amount = max(min(amount, 100), 1) if not await self.bot.is_owner(ctx.author) else max(min(amount, 1000), 1)

        a = ctx.author
        c = ctx.channel

        _logger.debug(f"Processing cleanup command from {a.id=} {c.id=} {amount=}")

        async with ctx.typing():
            bulk = ctx.channel.permissions_for(ctx.guild.me).manage_messages
            try:
                channel_prefixes = tuple(await self.bot.get_prefix(ctx.message))
                msgs = await ctx.channel.purge(
                    bulk=bulk,
                    limit=amount,
                    check=lambda m: m.author == self.bot.user or (bulk and m.content.startswith(channel_prefixes)),
                )
                await ctx.send(f"Removed {len(msgs)} messages.", delete_after=2.0)

            except (discord.Forbidden, discord.HTTPException):
                await ctx.send("I couldn't process this request. Please check my permissions.")

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    @app_commands.describe(user="A user or guild member, defaults to you")
    async def whois(self, ctx: GuildContext, *, user: discord.Member | discord.User | None = None) -> None:
        """Shows info about a user

        Parameters
        ----------
        user : discord.Member | discord.User | None, optional
            A user or guild member, by default None
        """
        user = user or ctx.author
        await ctx.defer()
        # banner and accent colour only come on a fetch
        fetched = self._profile_cache.get(user.id)
        if fetched is None:
            fetched = await self.bot.fetch_user(user.id)
            self._profile_cache.set(user.id, fetched)
        # Roles and format_date credit: https://github.com/Rapptz/RoboDanny
        roles = [role.name.replace("@", "@\u200b") for role in getattr(user, "roles", [])[:0:-1]]  # top first, no @everyone

        def format_date(datetime: datetime.datetime | None) -> str:
            if datetime is None:
                return "N/A"
            return f"{ts(datetime):F} ({ts(datetime):R})"

        # names render markdown inside a TextDisplay, so escape them
        display_name = discord.utils.escape_markdown(user.display_name)
        username = discord.utils.escape_markdown(str(user))
        if isinstance(user, discord.Member):
            try:
                status = Status[str(user.status)].value
            except KeyError:
                status = Status.offline.value
            title = f"# {display_name}\n{status} {username}"
        else:
            title = f"# {display_name}" if display_name == username else f"# {display_name}\n{username}"

        items: list[ui.Item] = [
            ui.Section(title, accessory=ui.Thumbnail(user.display_avatar.url)),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
        ]

        if isinstance(user, discord.Member):
            spotify = discord.utils.find(lambda activities: isinstance(activities, discord.Spotify), user.activities)
            if isinstance(spotify, discord.Spotify):
                artists = ", ".join(spotify.artists)
                items.append(
                    ui.TextDisplay(
                        f"### Spotify"
                        f"\nListening to [**{spotify.title}** by **{artists}**]({spotify.track_url}) on **{spotify.album}**"
                    )
                )

        items.append(ui.TextDisplay(f"### Joined\n{format_date(getattr(user, 'joined_at', None))}"))
        items.append(ui.TextDisplay(f"### Registered\n{format_date(user.created_at)}"))
        if isinstance(user, discord.Member) and user.premium_since is not None:
            items.append(ui.TextDisplay(f"### Boosting Since\n{format_date(user.premium_since)}"))

        if roles:
            items.append(ui.TextDisplay(f"### Roles\n{', '.join(roles) if len(roles) < 15 else f'{len(roles)} roles'}"))

        items.append(ui.TextDisplay(f"### Mutual Servers\nYou are in `{len(user.mutual_guilds):,}` servers with the bot!"))

        gallery = graphics_gallery(fetched.banner)
        if gallery:
            items.append(gallery)

        items.append(ui.Separator())
        items.append(ui.TextDisplay(f"-# User ID: {user.id}"))
        await ctx.send(view=SporkLayout(*items, accent_colour=fetched.accent_colour))

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    async def serverinfo(self, ctx: GuildContext) -> None:
        """Show general info about the server"""
        guild = ctx.guild
        guild_age = how_old(discord.utils.utcnow() - guild.created_at)
        member_count = guild.member_count or len(guild.members)

        # Last boost, status info, role count inspired by:
        # https://github.com/DuckBot-Discord/DuckBot
        last_boost = max(guild.members, key=lambda m: m.premium_since or guild.created_at)
        if last_boost.premium_since is not None:
            boost = f"\n{last_boost}\n╰ {ts(last_boost.premium_since):R}"
        else:
            boost = "No active boosters"

        # one pass over the member list instead of five; big guilds notice
        bots = online_count = idle_count = dnd_count = offline_count = 0
        for member in guild.members:
            bots += member.bot
            if member.status is discord.Status.online:
                online_count += 1
            elif member.status is discord.Status.idle:
                idle_count += 1
            elif member.status is discord.Status.dnd:
                dnd_count += 1
            elif member.status is discord.Status.offline:
                offline_count += 1

        title = f"# {discord.utils.escape_markdown(guild.name)}\n{plural(member_count):member} are in this server!"
        header = ui.Section(title, accessory=ui.Thumbnail(guild.icon.url)) if guild.icon else ui.TextDisplay(title)

        items: list[ui.Item] = [
            header,
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(
                f"### Info"
                f"\n**Owner:** {guild.owner}"
                f"\n**Role Count:** {len(guild.roles):,}"
                f"\n**File Size Limit:** {guild.filesize_limit // 1048576:,} MB"
            ),
            ui.TextDisplay(
                f"### Boosts"
                f"\n**Level:** {guild.premium_tier} | {plural(guild.premium_subscription_count):Boost}"
                f"\n**Booster Count:** {len(guild.premium_subscribers):,}"
                f"\n**Last Booster:** {boost}"
            ),
            ui.TextDisplay(
                f"### Members"
                f"\n**Total:** {plural(member_count):member} ({plural(bots):bot})"
                f"\n**Member Limit:** {f'{guild.max_members:,}' if guild.max_members else 'N/A'}"
            ),
            ui.TextDisplay(
                f"### Status Counts"
                f"\n{Status.online.value} Online: {online_count:,}"
                f"\n{Status.idle.value} Idle: {idle_count:,}"
                f"\n{Status.dnd.value} DND: {dnd_count:,}"
                f"\n{Status.offline.value} Offline: {offline_count:,}"
            ),
        ]

        graphics = GuildGraphics.from_guild(guild)
        gallery = graphics_gallery(graphics.banner, graphics.splash)
        if gallery:
            items.append(gallery)

        items.append(ui.Separator())
        items.append(ui.TextDisplay(f"-# The server is {guild_age} • Guild ID: {guild.id}"))
        await ctx.send(view=SporkLayout(*items))

    @commands.hybrid_command()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(invite_code="A guilds invite or vanity")
    async def inviteinfo(self, ctx: Context, invite_code: str) -> discord.Message | None:
        """Get information about a guilds invite

        Parameters
        ----------
        invite_code : str
            A guilds invite or vanity
        """
        await ctx.defer()
        try:
            invite = await self.bot.fetch_invite(invite_code, with_counts=True)
        except discord.NotFound:
            return await ctx.send("Could not get information about that invite.")

        if invite.inviter:
            user_info = (
                f"Name and ID: {invite.inviter} `({invite.inviter.id})`\nRegistered on {ts(invite.inviter.created_at):F}"
            )
        else:
            user_info = "I could not fetch any user information, this could be due to a vanity invite."

        items: list[ui.Item] = []

        if isinstance(invite.guild, (discord.PartialInviteGuild, discord.Guild)):
            guild_age = how_old(discord.utils.utcnow() - invite.guild.created_at)

            title = (
                f"# Invite Information"
                f"\nInvite information about [{invite.code}]({invite.url})"
                f"{f' (the vanity is {invite.guild.vanity_url_code})' if invite.guild.vanity_url_code else ''}"
                f" and has been used `{f'{invite.uses:,}' if invite.uses is not None else '0'}` times."
            )
            header = (
                ui.Section(title, accessory=ui.Thumbnail(invite.guild.icon.url))
                if invite.guild.icon
                else ui.TextDisplay(title)
            )
            items.extend((header, ui.Separator(spacing=discord.SeparatorSpacing.large)))

            guild_name = discord.utils.escape_markdown(invite.guild.name)
            items.append(ui.TextDisplay(f"### User Information\n{user_info}"))

            if isinstance(invite.expires_at, datetime.datetime):
                items.append(
                    ui.TextDisplay(f"### The Invites Demise\n{ts(invite.expires_at):F} ({ts(invite.expires_at):R})")
                )

            items.append(
                ui.TextDisplay(
                    f"### {guild_name} Description"
                    f"\n{invite.guild.description if invite.guild.description else 'No guild description found.'}"
                )
            )

            items.append(ui.TextDisplay(f"### Guild Created On\n{ts(invite.guild.created_at):F}\n(That's {guild_age}!)"))
            items.append(ui.TextDisplay(f"### Verification Level\n{f'{invite.guild.verification_level!s}'.capitalize()}"))

            if isinstance(invite.channel, (discord.PartialInviteChannel, discord.abc.GuildChannel)):
                items.append(
                    ui.TextDisplay(
                        f"### Invite Channel"
                        f"\n[#{invite.channel}](https://discord.com/channels/{invite.guild.id}/{invite.channel.id}) `({invite.channel.id})`"
                        f"\n╰ Created on {ts(invite.channel.created_at):F}"
                    )
                )

            items.append(
                ui.TextDisplay(
                    f"### Member Counts"
                    f"\nUsers Online: `{invite.approximate_presence_count:,}`"
                    f"\nMember Count: `{invite.approximate_member_count:,}`"
                    f"\nBooster Count: `{f'{invite.guild.premium_subscription_count:,}' if invite.guild.premium_subscription_count != 0 else ':('}`"
                )
            )

            graphics = GuildGraphics.from_guild(invite.guild)
            gallery = graphics_gallery(graphics.banner, graphics.splash)
            if gallery:
                items.append(gallery)

            items.extend((ui.Separator(), ui.TextDisplay(f"-# {guild_name} | {invite.guild.id}")))
        else:
            items.append(ui.TextDisplay(f"# Invite Information\n### User Information\n{user_info}"))

        await ctx.send(view=SporkLayout(*items))

    @commands.hybrid_command()
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    async def about(self, ctx: Context) -> None:
        """Shows info about the bot"""
        before_check = time.perf_counter()
        await ctx.channel.typing()
        after_check = time.perf_counter()
        api_latency = (after_check - before_check) * 1000
        seconds_running = (discord.utils.utcnow() - self.bot.start_time).total_seconds()
        items: list[ui.Item] = [
            ui.Section(
                f"# Statistics\nRunning since {ts(self.bot.start_time):F}",
                accessory=ui.Thumbnail(self.bot.user.display_avatar.url),
            ),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(
                f"### Bot Information"
                f"\nTotal Guilds: `{len(self.bot.guilds):,}`"
                f"\nTotal Users: `{len(self.bot.users):,}`"
                f"\nTotal Seconds Running: `{int(seconds_running):,}s`"
            ),
            ui.TextDisplay(
                f"### Host Information"
                f"\nCPU Usage: `{self._current_process.cpu_percent()}%`"
                f"\nRAM Usage: `{self._current_process.memory_percent():.2f}%`"
                f"\nRunning on `{self._current_process.num_threads()}` threads"
            ),
            ui.TextDisplay(
                f"### Latencies\nLatency: `{round(self.bot.latency * 1000):,}ms`\nAPI Latency: `{int(api_latency):,}ms`"
            ),
            ui.Separator(),
            ui.TextDisplay(f"-# Made in discord.py {discord.__version__}"),
        ]
        await ctx.send(view=SporkLayout(*items))


async def setup(bot: Spork) -> None:
    await bot.add_cog(General(bot))
