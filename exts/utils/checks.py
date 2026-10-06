from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from discord.ext import commands

if TYPE_CHECKING:
    from discord.ext.commands._types import Check


class NotGuildOwner(commands.CheckFailure):
    """Raised if the guild owner did not run the command"""

    pass


class NotRecorder(commands.CheckFailure):
    """Raised if someone without the recorder role tries to manage recordings"""

    pass


def is_guild_owner() -> Check[commands.Context[Any]]:
    """Checks if the guild owner ran the command."""

    async def guild_owner(ctx: commands.Context) -> Literal[True]:
        if ctx.guild is not None and ctx.author == ctx.guild.owner:
            return True
        else:
            raise NotGuildOwner

    return commands.check(guild_owner)


def is_recorder() -> Check[commands.Context[Any]]:
    """Checks for Manage Server or the configured recorder role."""

    async def recorder(ctx: commands.Context) -> Literal[True]:
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        if ctx.author.guild_permissions.manage_guild:
            return True
        row = await ctx.bot.settings.get_voice_settings(ctx.guild.id)
        role_id = row["recorder_role_id"] if row else None
        if role_id and ctx.author.get_role(role_id):
            return True
        raise NotRecorder

    return commands.check(recorder)
