import random
from typing import Any

import discord


def pastel_color() -> discord.Colour:
    return discord.Colour.from_hsv(random.random(), 0.28, 0.97)


class SporkEmbed(discord.Embed):
    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get('color', None) is None:
            kwargs['color'] = pastel_color()
        elif kwargs.get('colour', None) is None:
            kwargs['colour'] = pastel_color()
        super().__init__(**kwargs)
