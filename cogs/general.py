from __future__ import annotations

import datetime
import os
import re
import time
from typing import TYPE_CHECKING, Optional, Union

import discord
import psutil
from discord.ext import commands
from discord.ext.commands import Context

from .utils.embeds import SporkEmbed

if TYPE_CHECKING:
    from bot import Spork


class General(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self._current_process = psutil.Process(os.getpid())

    @commands.Cog.listener(name="on_message")
    async def mention_responder(self, message: discord.Message):
        guild = message.guild
        if not guild:
            return
        if re.fullmatch(rf"<@!?{guild.me.id}>", message.content):
            embed = SporkEmbed(
                description=f"Hello! My prefix is `,,`",
            )
            return await message.reply(embed=embed)
        return

    @commands.hybrid_command()
    @commands.guild_only()
    async def whois(self, ctx: Context, *, user: Optional[Union[discord.Member, discord.User]] = None):
        """Show info about a user"""
        user = user or ctx.author
        embed = SporkEmbed()
        # Roles and format_date credit: https://github.com/Rapptz/RoboDanny
        roles = [role.name.replace('@', '@\u200b') for role in getattr(user, 'roles', [])]

        def format_date(datetime: Optional[datetime.datetime]):
            if datetime is None:
                return 'N/A'
            return f"{discord.utils.format_dt(datetime)} ({discord.utils.format_dt(datetime, style='R')})"

        if isinstance(user, discord.Member):
            spotify = discord.utils.find(lambda activities: isinstance(activities, discord.Spotify), user.activities)
            if spotify:
                artists = ', '.join(spotify.artists)  # type: ignore
                embed.add_field(
                    name='Spotify',
                    value=f'Listening to [**{spotify.title}** by **{artists}**]({spotify.track_url}) on **{spotify.album}**',  # type: ignore
                    inline=False,
                )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_author(name=user, icon_url=user.display_avatar.url)
        embed.add_field(name='Joined', value=format_date(getattr(user, 'joined_at', None)), inline=False)
        embed.add_field(name='Registered', value=format_date(ctx.author.created_at), inline=False)

        if roles:
            embed.add_field(name='Roles', value=', '.join(roles) if len(roles) < 15 else f'{len(roles)} roles', inline=False)

        embed.add_field(
            name='Mutual Servers',
            value=f'You are in `{len(user.mutual_guilds):,}` servers with the bot!',
        )
        embed.set_footer(text=f"User ID: {user.id} | Date: {ctx.message.created_at.strftime('%m/%d/%Y')}")
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def about(self, ctx: Context):
        """Shows info about the bot"""
        before_check = time.perf_counter()
        await ctx.channel.typing()
        after_check = time.perf_counter()
        api_latency = (after_check - before_check) * 1000
        seconds_running = (discord.utils.utcnow() - self.bot.start_time).seconds
        embed = SporkEmbed(
            title="Statistics",
            description=f"Running since {discord.utils.format_dt(self.bot.start_time, style='f')}",
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
            f"RAM Usage: `{self._current_process.memory_percent():.2}`\n"
            f"Running on `{self._current_process.num_threads()}` threads",
            inline=False,
        )
        embed.add_field(
            name="Latencies",
            value=f"Latency: `{round(self.bot.latency * 1000)}ms`\nAPI Latency: `{int(api_latency)}ms`",
            inline=False,
        )
        embed.set_footer(text=f"Made in discord.py {discord.__version__}")
        await ctx.send(embed=embed)


async def setup(bot: Spork):
    await bot.add_cog(General(bot))
