import random

import discord


def pastel_color():
    return discord.Colour.from_hsv(random.random(), 0.28, 0.97)


class SporkEmbed(discord.Embed):
    def __init__(self, **kwargs):
        if kwargs.get('color', None) is None:
            kwargs['color'] = pastel_color()
        elif kwargs.get('colour', None) is None:
            kwargs['colour'] = pastel_color()
        super().__init__(**kwargs)
