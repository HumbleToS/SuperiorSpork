from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


@dataclass(slots=True)
class GuildGraphics:
    guild_id: int
    icon: discord.Asset | None
    splash: discord.Asset | None
    banner: discord.Asset | None

    @classmethod
    def from_guild(cls, guild: discord.Guild | discord.PartialInviteGuild, /) -> GuildGraphics:
        guild_id = guild.id
        icon = guild.icon
        splash = guild.splash
        banner = guild.banner

        return cls(guild_id=guild_id, icon=icon, splash=splash, banner=banner)

    @property
    def has_icon(self) -> bool:
        return self.icon is not None

    @property
    def has_splash(self) -> bool:
        return self.splash is not None

    @property
    def has_banner(self) -> bool:
        return self.banner is not None

    @property
    def has_any_graphics(self) -> bool:
        return self.has_icon or self.has_splash or self.has_banner

    def __str__(self) -> str:
        if not self.has_any_graphics:
            return "This guild has no graphics."

        ret = ""

        if self.icon:
            ret += f"\n**Icon:** [click here]({self.icon.url})"
        if self.splash:
            ret += f"\n**Splash:** [click here]({self.splash.url})"
        if self.banner:
            ret += f"\n**Banner:** [click here]({self.banner.url})"

        return ret.strip()

    def to_text(self) -> str:
        return str(self)
