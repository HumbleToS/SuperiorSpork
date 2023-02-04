import logging
import math
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from .utils.checks import NotGuildOwner
from .utils.wording import plural

_logger = logging.getLogger(__name__)


class ErorrHandler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def cog_load(self):
        self._original_handler = self.bot.tree.on_error
        tree = self.bot.tree
        tree.on_error = self.on_app_command_error

    def cog_unload(self):
        tree = self.bot.tree
        tree.on_error = self._original_handler

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):

        if isinstance(error, app_commands.CommandOnCooldown):
            current_cooldown = math.floor(error.retry_after * 100) / 100
            return await interaction.response.send_message(
                f"This command is on cooldown for another {current_cooldown} {plural('second', current_cooldown)}!"
            )
        else:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            _logger.exception("Ignoring exception in command %s:\n %s" % (interaction.command, trace))

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):

        if hasattr(ctx.command, "on_error"):
            return

        ignored = (commands.CommandNotFound, commands.NotOwner)
        error = getattr(error, 'original', error)
        command_used = ctx.invoked_with

        if isinstance(error, ignored):
            return

        if isinstance(error, commands.CommandOnCooldown):
            current_cooldown = math.floor(error.retry_after * 100) / 100
            return await ctx.send(
                f"You can do `{command_used}` again in {current_cooldown} {plural('second', current_cooldown)}"
            )
        elif isinstance(error, commands.TooManyArguments):
            return await ctx.send(f"The command `{command_used}` was used with too many arguments")
        elif isinstance(error, commands.UserInputError):
            return await ctx.send(f"The command `{command_used}` was used incorrectly")
        elif isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send(f"You're missing the required argument `{error.param.name}`")
        elif isinstance(error, NotGuildOwner):
            return await ctx.send(f'The command `{command_used}` can only be used by the server owner.')
        else:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            _logger.exception("Ignoring exception in command %s:\n %s" % (ctx.command, trace))


async def setup(bot: commands.Bot):
    await bot.add_cog(ErorrHandler(bot))
