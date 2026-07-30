from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import discord

import config

from .cache import TTLCache

if TYPE_CHECKING:
    from bot import Spork

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Tier:
    name: str
    monthly_seconds: int
    sku_id: int | None


# every quota tier lives here and nowhere else; final pricing and the Premium
# Apps SKU ids are a launch blocker tracked in VOICE-RECAP-PLAN.md / HUMAN-TODO.md
FREE = Tier("Free", 30 * 60, None)
TIERS = (
    Tier("Tier 1", 5 * 3600, getattr(config, "SKU_TIER_1", 0) or None),
    Tier("Tier 2", 20 * 3600, getattr(config, "SKU_TIER_2", 0) or None),
)


class EntitlementProvider(Protocol):
    async def tier_for(self, guild_id: int) -> Tier: ...


class DiscordEntitlementProvider:
    """Premium Apps entitlements as the primary purchase rail, cached briefly.

    A Stripe implementation can slot in behind the same interface later; it is
    deliberately not built now.
    """

    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self._cache = TTLCache(ttl=300)

    async def tier_for(self, guild_id: int) -> Tier:
        cached = self._cache.get(guild_id)
        if cached is not None:
            return cached

        best = FREE
        if any(tier.sku_id for tier in TIERS):
            try:
                async for entitlement in self.bot.entitlements(guild=discord.Object(guild_id), exclude_ended=True):
                    for candidate in TIERS:
                        if candidate.sku_id == entitlement.sku_id and candidate.monthly_seconds > best.monthly_seconds:
                            best = candidate
            except discord.HTTPException as exc:
                # err on the free tier but do not cache the failure
                _logger.warning(f"entitlement lookup failed for guild {guild_id}", exc_info=exc)
                return best

        self._cache.set(guild_id, best)
        return best
