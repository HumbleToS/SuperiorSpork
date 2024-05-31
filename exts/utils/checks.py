from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from discord.ext import commands

if TYPE_CHECKING:
    from discord.ext.commands._types import Check


class NotGuildOwner(commands.CheckFailure):
    """Raised if the guild owner did not run the command"""

    pass


def is_guild_owner() -> Check[commands.Context[Any]]:
    """Checks if the guild owner ran the command."""

    async def guild_owner(ctx: commands.Context) -> Literal[True]:
        if ctx.guild is not None and ctx.author == ctx.guild.owner:
            return True
        else:
            raise NotGuildOwner

    return commands.check(guild_owner)
