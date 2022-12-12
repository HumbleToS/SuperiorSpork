import os
import re
import time

import discord
import psutil
from discord.ext import commands
from discord.ext.commands import Context

from bot import Spork
from utils.embeds import SporkEmbed


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

    @commands.command()
    async def about(self, ctx: Context):
        before_check = time.monotonic()
        await ctx.channel.typing()
        after_check = time.monotonic()
        api_latency = (after_check - before_check) * 1000

        embed = SporkEmbed(
            title="Statistics",
            description=f"Running since {discord.utils.format_dt(self.bot.start_time, style='f')}",
        )
        embed.add_field(
            name="Host Information",
            value=f"CPU Usage: `{self._current_process.cpu_percent()}%`\n"
            f"RAM Usage: `{self._current_process.memory_percent():.2}`\n"
            f"Running on `{self._current_process.num_threads()}` threads",
            inline=False,
        )
        embed.add_field(
            name="Bot Latencies",
            value=f"Latency: `{round(self.bot.latency * 1000)}ms`\nAPI Latency: `{int(api_latency)}ms`",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: Spork):
    await bot.add_cog(General(bot))
