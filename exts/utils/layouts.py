from __future__ import annotations

from typing import Any

import discord
from discord import ui

from .embeds import pastel_color


class SporkLayout(ui.LayoutView):
    """A layout view carrying a single accented container, pastel unless told otherwise."""

    def __init__(
        self, *items: ui.Item[Any], accent_colour: discord.Colour | None = None, timeout: float | None = None
    ) -> None:
        super().__init__(timeout=timeout)
        self.accent_colour = accent_colour or pastel_color()
        self.container = ui.Container(*items, accent_colour=self.accent_colour)
        self.add_item(self.container)

    def replace(self, *items: ui.Item[Any]) -> None:
        """Swaps the container's contents, for views that re-render in place."""
        self.clear_items()
        self.container = ui.Container(*items, accent_colour=self.accent_colour)
        self.add_item(self.container)


def graphics_gallery(*assets: discord.Asset | None) -> ui.MediaGallery | None:
    """Builds a gallery from whichever of the given assets exist, or None."""
    items = [discord.MediaGalleryItem(asset.url) for asset in assets if asset]
    if not items:
        return None
    return ui.MediaGallery(*items)
