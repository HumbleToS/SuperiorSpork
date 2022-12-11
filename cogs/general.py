import re

import discord
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener(name="on_message")
    async def mention_responder(self, message):
        if re.fullmatch(rf"<@!?{self.bot.user.id}>", message.content):  # type: ignore
            em = discord.Embed(
                description=f'Hello! My prefix is `,`',
                color=discord.Color.random(),
            )
            return await message.reply(embed=em)
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
