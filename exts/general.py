from __future__ import annotations

import datetime
import logging
import os
import re
import time
from typing import TYPE_CHECKING

import discord
import psutil
from discord import app_commands
from discord.ext import commands

from config import PREFIX

from .utils.embeds import SporkEmbed
from .utils.emojis import Status
from .utils.guilds import GuildGraphics
from .utils.time import how_old, ts
from .utils.wording import Plural

if TYPE_CHECKING:
    from discord.ext.commands import Context

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)


class General(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self._current_process = psutil.Process(os.getpid())

    @commands.Cog.listener(name="on_message")
    async def mention_responder(self, message: discord.Message) -> None | discord.Message:
        guild = message.guild
        if not guild:
            return
        if re.fullmatch(rf"<@!?{guild.me.id}>", message.content):
            embed = SporkEmbed(
                description=f"Hello! My prefix is `{PREFIX}`",
            )
            return await message.reply(embed=embed)
        return

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
    async def whois(self, ctx: GuildContext, *, user: discord.Member | discord.User | None = None) -> None:
        """Shows info about a user

        Parameters
        ----------
        user : discord.Member | discord.User | None, optional
            A user or guild member, by default None
        """
        user = user or ctx.author
        embed = SporkEmbed()
        # Roles and format_date credit: https://github.com/Rapptz/RoboDanny
        roles = [role.name.replace("@", "@\u200b") for role in getattr(user, "roles", [])]

        def format_date(datetime: datetime.datetime | None) -> str:
            if datetime is None:
                return "N/A"
            return f"{ts(datetime):F} ({ts(datetime):R})"

        if isinstance(user, discord.Member):
            spotify = discord.utils.find(lambda activities: isinstance(activities, discord.Spotify), user.activities)
            if isinstance(spotify, discord.Spotify):
                artists = ", ".join(spotify.artists)
                embed.add_field(
                    name="Spotify",
                    value=f"Listening to [**{spotify.title}** by **{artists}**]({spotify.track_url}) on **{spotify.album}**",
                    inline=False,
                )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_author(name=user, icon_url=user.display_avatar.url)
        embed.add_field(name="Joined", value=format_date(getattr(user, "joined_at", None)), inline=False)
        embed.add_field(name="Registered", value=format_date(user.created_at), inline=False)

        if roles:
            embed.add_field(name="Roles", value=", ".join(roles) if len(roles) < 15 else f"{len(roles)} roles", inline=False)

        embed.add_field(
            name="Mutual Servers",
            value=f"You are in `{len(user.mutual_guilds):,}` servers with the bot!",
        )
        embed.set_footer(text=f"User ID: {user.id} | Date: {ctx.message.created_at.strftime('%m/%d/%Y')}")
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    @commands.guild_only()
    async def serverinfo(self, ctx: GuildContext) -> None:
        """Show general info about the server"""
        guild = ctx.guild
        guild_age = how_old(discord.utils.utcnow() - guild.created_at)
        bots = sum(member.bot for member in guild.members)

        # Last boost, status info, role count inspired by:
        # https://github.com/DuckBot-Discord/DuckBot
        last_boost = max(guild.members, key=lambda m: m.premium_since or guild.created_at)
        if last_boost.premium_since is not None:
            boost = f"\n{last_boost}" f"\n╰ {ts(last_boost.premium_since):R}"
        else:
            boost = "No active boosters"

        embed = SporkEmbed(
            title=guild.name,
            description=f"__{len(guild.members):,}__ {Plural(len(guild.members)):member} are in this server!",
        )
        embed.add_field(
            name="Info",
            value=f"**Owner:** {guild.owner}"
            f"\n**Role Count:** {len(guild.roles):,}"
            f"\n**File Size limit:** {guild.filesize_limit // 1048576:,}",
            inline=True,
        )
        embed.add_field(
            name="Boosts",
            value=f"**Level:** {guild.premium_tier} | {guild.premium_subscription_count:,} {Plural(guild.premium_subscription_count):Boost}"
            f"\n**Booster Count:** {len(guild.premium_subscribers):,}"
            f"\n**Last Booster:** {boost}",
            inline=True,
        )

        embed.add_field(name="Graphics", value=GuildGraphics.from_guild(guild), inline=True)
        embed.add_field(
            name="Members",
            value=f"**Total:** {len([m for m in guild.members if not m.bot]):,} {Plural(len(guild.members)):member} ({bots:,} {Plural(bots):bot})"
            f"\n**Member Limit:** {guild.max_members:,}",
            inline=True,
        )

        online_count = sum(m.status is discord.Status.online for m in guild.members)
        idle_count = sum(m.status is discord.Status.idle for m in guild.members)
        dnd_count = sum(m.status is discord.Status.dnd for m in guild.members)
        offline_count = sum(m.status is discord.Status.offline for m in guild.members)

        embed.add_field(
            name="Status Counts",
            value=f"{Status.online.value} Online: {online_count:,}"
            f"\n{Status.idle.value} Idle: {idle_count:,}"
            f"\n{Status.dnd.value} DND: {dnd_count:,}"
            f"\n{Status.offline.value} Offline: {offline_count:,}",
            inline=True,
        )
        embed.set_thumbnail(url=guild.icon)
        embed.set_footer(text=f"The server is {guild_age} • Guild ID: {guild.id}")
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def inviteinfo(self, ctx: Context, invite_code: str) -> discord.Message | None:
        """Get information about a guilds invite

        Parameters
        ----------
        invite_code : str
            A guilds invite or vanity
        """
        invite = await self.bot.fetch_invite(invite_code, with_counts=True, with_expiration=True)

        if invite is None:
            return await ctx.send("Could not get information about that invite.")

        embed = discord.Embed(title="Invite Information", color=discord.Color.blue())
        if invite.inviter:
            user_info = f"Name and ID: {invite.inviter} `({invite.inviter.id})`"
            f"\nRegistered on {ts(invite.inviter.created_at):F}"
        else:
            user_info = "I could not fetch any user information, this could be due to a vanity invite."

        embed.add_field(name="User Information", value=user_info, inline=True)

        if isinstance(invite.guild, (discord.PartialInviteGuild, discord.Guild)):
            guild_age = how_old(discord.utils.utcnow() - invite.guild.created_at)

            embed.description = f"Invite information about [{invite.code}]({invite.url})"
            f"{f'(the vanity is {invite.guild.vanity_url_code})' if invite.guild.vanity_url_code else ''} and has been used `{f'{invite.uses:,}' if invite.uses is not None else '0'}` times."

            if isinstance(invite.expires_at, datetime.datetime):
                embed.add_field(
                    name="The Invites Demise",
                    value=f"{ts(invite.expires_at):F} ({ts(invite.expires_at):R})",
                    inline=False,
                )

            embed.add_field(
                name=f"{invite.guild.name} Description",
                value=f"{invite.guild.description if invite.guild.description else 'No guild description found.'}",
                inline=False,
            )

            embed.add_field(
                name="Guild Created On",
                value=f"{ts(invite.guild.created_at):F}\n(That's {guild_age}!)",
                inline=True,
            )

            embed.add_field(name="Verification Level", value=f"{invite.guild.verification_level!s}".capitalize())
            embed.add_field(name="Graphics", value=GuildGraphics.from_guild(invite.guild).to_text().replace("**", ""))

            if isinstance(invite.channel, (discord.PartialInviteChannel, discord.abc.GuildChannel)):
                embed.add_field(
                    name="Invite Channel",
                    value=f"[#{invite.channel}](https://discord.com/channels/{invite.guild.id}/{invite.channel.id}) `({invite.channel.id})`\nCreated on {ts(invite.channel.created_at):F}",
                )

            embed.set_footer(text=f"{invite.guild.name} | {invite.guild.id}")

            embed.add_field(
                name="Member Counts",
                value=f"Users Online: `{invite.approximate_presence_count:,}`\nMember Count: `{invite.approximate_member_count:,}`\nBooster Count: `{f'{invite.guild.premium_subscription_count:,}' if invite.guild.premium_subscription_count != 0 else ':('}`",
            )

        await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def about(self, ctx: Context) -> None:
        """Shows info about the bot"""
        before_check = time.perf_counter()
        await ctx.channel.typing()
        after_check = time.perf_counter()
        api_latency = (after_check - before_check) * 1000
        seconds_running = (discord.utils.utcnow() - self.bot.start_time).seconds
        embed = SporkEmbed(
            title="Statistics",
            description=f"Running since {ts(self.bot.start_time):F}",
        )
        embed.add_field(
            name="Bot Information",
            value=f"Total Guilds: `{len(self.bot.guilds):,}`\n"
            f"Total Users: `{len(self.bot.users):,}`\n"
            f"Total Seconds Running: `{seconds_running:,}s`",
            inline=True,
        )
        embed.add_field(
            name="Host Information",
            value=f"CPU Usage: `{self._current_process.cpu_percent()}%`\n"
            f"RAM Usage: `{self._current_process.memory_percent():.2}%`\n"
            f"Running on `{self._current_process.num_threads()}` threads",
            inline=False,
        )
        embed.add_field(
            name="Latencies",
            value=f"Latency: `{round(self.bot.latency * 1000):,}ms`\nAPI Latency: `{int(api_latency):,}ms`",
            inline=False,
        )
        embed.set_footer(text=f"Made in discord.py {discord.__version__}")
        await ctx.send(embed=embed)


async def setup(bot: Spork) -> None:
    await bot.add_cog(General(bot))
