from typing import Any, Literal

from discord.ext import commands


class NotGuildOwner(commands.CheckFailure):
    """Raised if the guild owner did not run the command"""

    pass


def is_guild_owner():  # noqa: ANN201 # Cannot find return type of commands.check
    """Checks if the guild owner ran the command."""

    async def guild_owner(ctx: commands.Context) -> Literal[True]:
        if ctx.guild is not None and ctx.author == ctx.guild.owner:
            return True
        else:
            raise NotGuildOwner

    return commands.check(guild_owner)
