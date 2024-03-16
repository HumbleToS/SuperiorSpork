import discord
from discord.ext import commands


class GuildContext(commands.Context):
    prefix: str
    me: discord.Member
    guild: discord.Guild
    author: discord.Member
    channel: discord.VoiceChannel | discord.TextChannel | discord.Thread
