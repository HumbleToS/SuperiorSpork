import random
from typing import Any

import discord


def pastel_color(seed: int | None = None) -> discord.Colour:
    # a seed (user/guild id) gives that thing its own stable pastel
    rand = random.Random(seed) if seed is not None else random
    return discord.Colour.from_hsv(rand.random(), 0.28, 0.97)


class SporkEmbed(discord.Embed):
    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("color") is None and kwargs.get("colour") is None:
            kwargs["colour"] = pastel_color()
        super().__init__(**kwargs)
