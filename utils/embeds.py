import random

from discord import Colour, Embed


def pastel_color():
    return Colour.from_hsv(random.random(), 0.28, 0.97)


class SporkEmbed(Embed):
    def __init__(self, **kwargs):
        if kwargs.get('color', None) is None:
            kwargs['color'] = pastel_color()
        super().__init__(**kwargs)
