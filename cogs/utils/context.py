from typing import Union

import discord
from discord.ext import commands


class GuildContext(commands.Context):
    prefix: str
    me: discord.Member
    guild: discord.Guild
    author: discord.Member
    channel: Union[discord.VoiceChannel, discord.TextChannel, discord.Thread]
