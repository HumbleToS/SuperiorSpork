from discord.ext import commands


class NotGuildOwner(commands.CheckFailure):
    pass


def is_guild_owner():
    async def guild_owner(ctx):
        if ctx.guild is not None and ctx.author == ctx.guild.owner:
            return True
        else:
            raise NotGuildOwner

    return commands.check(guild_owner)
