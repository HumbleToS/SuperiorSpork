from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands.hybrid import HybridAppCommand

import config

from .utils.stats import DEFAULT_FLUSH_SECONDS, GRACE_DAYS, RETENTION_DAYS, Counters, StatsStore
from .utils.wording import plural

if TYPE_CHECKING:
    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)

CLEANUP_TIME = datetime.time(hour=4, minute=45, tzinfo=datetime.UTC)


class Stats(commands.Cog, description="Activity counts for this server, and the switch to turn them off"):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.store = StatsStore(bot.pool)
        self.counters = Counters()
        self.disabled: set[int] = set()
        self._lock = asyncio.Lock()  # a flush must never land after `stats off` deleted the server's rows

    async def cog_load(self) -> None:
        self.disabled = await self.store.disabled_guilds()
        seconds = getattr(config, "STATS_FLUSH_SECONDS", DEFAULT_FLUSH_SECONDS)
        self.flush.change_interval(seconds=float(seconds) if isinstance(seconds, int | float) else DEFAULT_FLUSH_SECONDS)
        self.flush.start()
        self.cleanup.start()

    async def cog_unload(self) -> None:
        self.flush.cancel()
        self.cleanup.cancel()
        await self.write()  # whatever the last interval counted goes out with the process

    def tracked(self, guild_id: int) -> bool:
        return guild_id not in self.disabled and self.bot.get_guild(guild_id) is not None

    # counting: the events only, never the text

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or message.author.bot or message.webhook_id is not None or message.is_system():
            return
        if not self.tracked(guild.id):
            return
        channel = message.channel
        # a thread counts toward the channel it lives in, the way the sidebar shows it
        channel_id = (channel.parent_id or channel.id) if isinstance(channel, discord.Thread) else channel.id
        self.counters.record_message(guild.id, channel_id, message.author.id, message.created_at)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot and self.tracked(member.guild.id):
            self.counters.record_join(member.guild.id, discord.utils.utcnow())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not member.bot and self.tracked(member.guild.id):
            self.counters.record_leave(member.guild.id, discord.utils.utcnow())

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context[Any]) -> None:
        # hybrids arrive here for both prefix and slash use, so the slash-side listener skips them
        if ctx.guild is None or ctx.command is None or not self.tracked(ctx.guild.id):
            return
        self.counters.record_command(ctx.guild.id, ctx.author.id, ctx.command.qualified_name, discord.utils.utcnow())

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command[Any, ..., Any] | app_commands.ContextMenu
    ) -> None:
        if isinstance(command, HybridAppCommand) or interaction.guild_id is None or not self.tracked(interaction.guild_id):
            return
        self.counters.record_command(
            interaction.guild_id, interaction.user.id, command.qualified_name, discord.utils.utcnow()
        )

    # the batched write: one transaction per interval, and once more on the way out

    async def write(self) -> int:
        async with self._lock:
            if self.counters.is_empty():
                return 0
            batch = self.counters.drain()
            await self.store.flush(batch, discord.utils.utcnow())
        _logger.debug(f"stats flushed {batch.rows} rows for {len(batch.guild_ids)} guilds")
        return batch.rows

    @tasks.loop(seconds=DEFAULT_FLUSH_SECONDS)
    async def flush(self) -> None:
        await self.write()

    @flush.before_loop
    async def before_flush(self) -> None:
        await self.bot.wait_until_ready()

    @flush.error
    async def flush_error(self, error: BaseException) -> None:
        _logger.error("stats flush loop errored", exc_info=error)

    # retention, and servers the bot has left

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.store.mark_present(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        async with self._lock:
            self.counters.forget_guild(guild.id)
        await self.store.mark_left(guild.id, discord.utils.utcnow())
        _logger.info(f"Stats for departed guild {guild.id} are kept for {GRACE_DAYS} days")

    @tasks.loop(time=CLEANUP_TIME)
    async def cleanup(self) -> None:
        now = discord.utils.utcnow()
        # a server left while the bot was offline never fired on_guild_remove; start its grace period now
        for guild_id in await self.store.present_guilds():
            if self.bot.get_guild(guild_id) is None:
                await self.store.mark_left(guild_id, now)
        purged = await self.store.purge_departed(now)
        if purged:
            _logger.info(f"Stats cleanup purged {len(purged)} departed guilds")
        pruned = await self.store.prune(now.date(), RETENTION_DAYS)
        if pruned:
            _logger.info(f"Stats cleanup removed {pruned} rows older than {RETENTION_DAYS} days")

    @cleanup.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()

    @cleanup.error
    async def cleanup_error(self, error: BaseException) -> None:
        _logger.error("stats cleanup loop errored", exc_info=error)

    # the service layer: one path for the commands and anything else that flips a server

    def is_enabled(self, guild_id: int) -> bool:
        return guild_id not in self.disabled

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        async with self._lock:
            if enabled:
                self.disabled.discard(guild_id)
            else:
                self.disabled.add(guild_id)
                self.counters.forget_guild(guild_id)
            await self.store.set_enabled(guild_id, enabled, discord.utils.utcnow())
        _logger.info(f"stats {'on' if enabled else 'off'} for guild {guild_id}")

    # commands

    @commands.hybrid_group()
    async def stats(self, ctx: GuildContext) -> None:
        """Activity counts for this server: on by default, `stats off` deletes them"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `stats on` or `stats off`.")

    @stats.command(name="on")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def stats_on(self, ctx: GuildContext) -> None:
        """Turns activity counts back on for this server (they're on by default)"""
        if self.is_enabled(ctx.guild.id):
            await ctx.send("Activity counts are already on here. `stats off` turns them off.", ephemeral=True)
            return
        await self.set_enabled(ctx.guild.id, True)
        await ctx.send("Activity counts are on again — tracking starts fresh from today.", ephemeral=True)

    @stats.command(name="off")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def stats_off(self, ctx: GuildContext) -> None:
        """Turns activity counts off for this server and deletes what was stored"""
        if not self.is_enabled(ctx.guild.id):
            await ctx.send("Activity counts are already off here. `stats on` turns them back on.", ephemeral=True)
            return
        await self.set_enabled(ctx.guild.id, False)
        await ctx.send(
            f"Activity counts are off and everything stored for this server is deleted. That covered the last"
            f" {plural(RETENTION_DAYS):day} at most — only numbers, never messages. `stats on` brings them back.",
            ephemeral=True,
        )


async def setup(bot: Spork) -> None:
    await bot.add_cog(Stats(bot))
