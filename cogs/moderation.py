from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .utils import checks

if TYPE_CHECKING:
    from bot import Spork


class Moderation(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot

    @commands.hybrid_command()
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    @checks.is_guild_owner()
    async def clear(self, ctx: commands.Context):
        """Deletes and recreates a channel"""

        def clear_check(m: discord.Message):
            assert ctx.guild is not None
            return m.author.id == ctx.guild.owner_id and m.channel.id == ctx.channel.id

        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.send("This can only be used in text channels.")

        await ctx.send(
            f"Are you sure you want to clear {ctx.channel.mention}? This will delete the channel and create a new one in its place.\n"
            "Please with respond with yes or no."
        )
        try:
            message = await self.bot.wait_for("message", timeout=15, check=clear_check)
        except asyncio.TimeoutError:
            return await ctx.send("This command has expired!")
        if message.content.lower() == "yes":
            await ctx.channel.delete()
            new_channel = await ctx.channel.clone()
            await new_channel.edit(position=ctx.channel.position)
            await new_channel.send(f"Cleared {new_channel.mention}!", delete_after=30)
        else:
            return await ctx.send("Task cancelled.")


async def setup(bot: Spork):
    await bot.add_cog(Moderation(bot))
