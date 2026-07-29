from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from .utils.checks import NotGuildOwner
from .utils.wording import plural

if TYPE_CHECKING:
    from bot import Spork

_logger = logging.getLogger(__name__)


class ErrorHandler(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot

    def cog_load(self) -> None:
        self._original_handler = self.bot.tree.on_error
        tree = self.bot.tree
        tree.on_error = self.on_app_command_error

    def cog_unload(self) -> None:
        tree = self.bot.tree
        tree.on_error = self._original_handler

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            current_cooldown = math.floor(error.retry_after * 100) / 100
            message = f"This command is on cooldown for another {plural(int(current_cooldown)):second}!"
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        else:
            _logger.error(f"Ignoring exception in command {interaction.command}", exc_info=error)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> discord.Message | None:
        if hasattr(ctx.command, "on_error"):
            return

        ignored = (commands.CommandNotFound, commands.NotOwner)
        error = getattr(error, "original", error)
        command_used = ctx.invoked_with

        if isinstance(error, ignored):
            return

        if isinstance(error, commands.CommandOnCooldown):
            current_cooldown = math.floor(error.retry_after * 100) / 100
            return await ctx.send(f"You can do `{command_used}` again in {plural(int(current_cooldown)):second}")
        elif isinstance(error, commands.TooManyArguments):
            return await ctx.send(f"The command `{command_used}` was used with too many arguments")
        elif isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send(f"You're missing the required argument `{error.param.name}`")
        elif isinstance(error, commands.UserInputError):
            return await ctx.send(f"The command `{command_used}` was used incorrectly")
        elif isinstance(error, NotGuildOwner):
            return await ctx.send(f"The command `{command_used}` can only be used by the server owner.")
        elif isinstance(error, commands.NoPrivateMessage):
            return await ctx.send(f"The command `{command_used}` can only be used in a server.")
        elif isinstance(error, commands.CheckFailure):
            return _logger.info(error)
        else:
            _logger.error(f"Ignoring exception in command {ctx.command}", exc_info=error)


async def setup(bot: Spork) -> None:
    await bot.add_cog(ErrorHandler(bot))
