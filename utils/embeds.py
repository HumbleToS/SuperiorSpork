import random

import discord
from discord import Colour


def pastel_color():
    return Colour.from_hsv(random.random(), 0.28, 0.97)


class SporkEmbed(discord.Embed):
    def __init__(self, **kwargs):
        self.color = pastel_color()
        super().__init__(color=self.color, **kwargs)
