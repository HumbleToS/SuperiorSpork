from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks, voice_recv

from .utils.capture import ConsentGateSink
from .utils.checks import is_recorder
from .utils.entitlements import DiscordEntitlementProvider
from .utils.layouts import SporkLayout
from .utils.pipeline import Pipeline
from .utils.sessions import DEFAULT_RETENTION_DAYS
from .utils.time import ts
from .utils.wording import plural

if TYPE_CHECKING:
    import re
    import uuid

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)

FLUSH_SECONDS = 30


@dataclass
class ActiveSession:
    session_id: uuid.UUID
    text_channel: discord.abc.Messageable
    voice_client: voice_recv.VoiceRecvClient
    sink: ConsentGateSink
    included: set[int] = field(default_factory=set)
    started_monotonic: float = field(default_factory=time.monotonic)
    flushed_seconds: int = 0

    @property
    def elapsed(self) -> int:
        return int(time.monotonic() - self.started_monotonic)


class ConsentButton(ui.DynamicItem[ui.Button], template=r"spork:consent:(?P<guild_id>\d+)"):
    def __init__(self, guild_id: int) -> None:
        super().__init__(
            ui.Button(
                label="Include my audio",
                style=discord.ButtonStyle.primary,
                custom_id=f"spork:consent:{guild_id}",
            )
        )
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Button,
        match: re.Match[str],
        /,
    ) -> ConsentButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: Spork = interaction.client  # type: ignore
        await bot.sessions.set_consent(self.guild_id, interaction.user.id, "consented")
        cog = bot.get_cog("Voice")
        if isinstance(cog, Voice):
            active = cog.active.get(self.guild_id)
            if active is not None:
                active.included.add(interaction.user.id)
        await interaction.response.send_message(
            "Got it! Your audio can be included in recordings here from now on. `optout` reverses that any time.",
            ephemeral=True,
        )


class Voice(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.active: dict[int, ActiveSession] = {}
        self.tiers = DiscordEntitlementProvider(bot)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(ConsentButton)
        self.usage_flush.start()

    async def cog_unload(self) -> None:
        self.usage_flush.cancel()
        self.bot.remove_dynamic_items(ConsentButton)
        for guild_id in list(self.active):
            await self.end_session(guild_id, "the recording module was reloaded")

    @commands.hybrid_group()
    async def record(self, ctx: GuildContext) -> None:
        """Recording controls"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `record start`, `record stop`, or `record setup`.")

    @record.command()
    @commands.guild_only()
    @is_recorder()
    async def start(self, ctx: GuildContext) -> discord.Message | None:
        """Starts recording your voice channel, with a visible notice and per-user consent

        Only users who have acknowledged inclusion are ever captured; everyone
        else's audio is dropped before it touches disk.
        """
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            return await ctx.send("You need to be in a voice channel to start recording.")
        if ctx.guild.id in self.active:
            return await ctx.send("I'm already recording in this server! `record stop` ends it.")
        if ctx.guild.voice_client is not None:
            return await ctx.send("I'm already in a voice channel here doing something else.")

        await ctx.defer()
        tier = await self.tiers.tier_for(ctx.guild.id)
        used = await self.bot.sessions.get_usage(ctx.guild.id)
        if used >= tier.monthly_seconds:
            return await ctx.send("This server is out of recorded minutes for the month — `minutes` has the details.")

        consent = await self.bot.sessions.consent_map(ctx.guild.id)
        included = {user_id for user_id, status in consent.items() if status == "consented"}

        session_id = await self.bot.sessions.create_session(ctx.guild.id, ctx.author.voice.channel.id, ctx.author.id)
        try:
            voice_client = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient, timeout=30.0)
        except (discord.ClientException, OSError, TimeoutError) as exc:
            await self.bot.sessions.fail(session_id, f"could not join the voice channel: {exc}")
            return await ctx.send("I couldn't join your voice channel. Please check my permissions.")

        sink = ConsentGateSink(Pipeline.session_dir(session_id), included)
        voice_client.listen(sink)
        self.active[ctx.guild.id] = ActiveSession(
            session_id=session_id,
            text_channel=ctx.channel,
            voice_client=voice_client,
            sink=sink,
            included=included,
        )
        _logger.info(f"Recording session {session_id} started in guild {ctx.guild.id}")

        settings = await self.bot.settings.get_voice_settings(ctx.guild.id)
        retention = (settings["retention_days"] if settings else None) or DEFAULT_RETENTION_DAYS
        items: list[ui.Item] = [
            ui.TextDisplay(
                f"# Recording started\n{ctx.author.mention} started recording {ctx.author.voice.channel.mention}."
            ),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(
                "### What gets captured"
                "\nAudio only, and only from users who have acknowledged inclusion — press the button below if you"
                " haven't yet. Anyone who hasn't, or who used `optout`, is never captured."
            ),
            ui.TextDisplay(
                "### What happens to it"
                "\nThe audio is transcribed, then the raw audio is deleted. The transcript and an AI recap are kept"
                f" for {plural(retention):day} (`recap delete` removes a session, `privacy` has the full details)."
            ),
            ui.ActionRow(ConsentButton(ctx.guild.id)),
            ui.Separator(),
            ui.TextDisplay(f"-# Session {str(session_id)[:8]}"),
        ]
        return await ctx.send(view=SporkLayout(*items))

    @record.command()
    @commands.guild_only()
    @is_recorder()
    async def stop(self, ctx: GuildContext) -> discord.Message | None:
        """Stops the current recording and queues it for transcription"""
        if ctx.guild.id not in self.active:
            return await ctx.send("Nothing is being recorded here right now.")
        await ctx.defer()
        await self.end_session(ctx.guild.id, "stopped", announce_in=ctx.channel)
        return None

    @record.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(
        role="The role allowed to start and stop recordings",
        channel="Where finished recaps get posted",
        retention_days="How long transcripts and recaps are kept (default 90)",
    )
    async def setup(
        self,
        ctx: GuildContext,
        role: discord.Role,
        channel: discord.TextChannel,
        retention_days: commands.Range[int, 1, 365] | None = None,
    ) -> None:
        """Configures recording for this server

        Parameters
        ----------
        role : discord.Role
            The role allowed to start and stop recordings
        channel : discord.TextChannel
            Where finished recaps get posted
        retention_days : int | None, optional
            How long transcripts and recaps are kept, by default 90
        """
        await self.bot.settings.set_voice_settings(ctx.guild.id, role.id, channel.id, retention_days)
        await ctx.send(
            f"Recording is set up! {role.mention} can record, recaps land in {channel.mention},"
            f" and sessions are kept for {plural(retention_days or DEFAULT_RETENTION_DAYS):day}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def end_session(
        self,
        guild_id: int,
        reason: str,
        announce_in: discord.abc.Messageable | None = None,
    ) -> None:
        active = self.active.pop(guild_id, None)
        if active is None:
            return
        try:
            active.voice_client.stop_listening()
        except Exception as exc:
            _logger.warning(f"stop_listening failed for session {active.session_id}", exc_info=exc)
        active.sink.finalize()
        try:
            await active.voice_client.disconnect(force=True)
        except Exception as exc:
            _logger.warning(f"disconnect failed for session {active.session_id}", exc_info=exc)

        seconds = active.elapsed
        if seconds > active.flushed_seconds:
            await self.bot.sessions.add_usage(guild_id, seconds - active.flushed_seconds)
        await self.bot.sessions.mark_queued(active.session_id, seconds)
        _logger.info(f"Recording session {active.session_id} ended after {seconds}s ({reason})")

        channel = announce_in or active.text_channel
        minutes = max(1, round(seconds / 60))
        items: list[ui.Item] = [
            ui.TextDisplay(f"# Recording stopped\nRecorded about {plural(minutes):minute} — {reason}."),
            ui.Separator(),
            ui.TextDisplay(
                "The recap will land once transcription finishes. The raw audio is deleted the moment that happens."
            ),
            ui.Separator(),
            ui.TextDisplay(f"-# Session {str(active.session_id)[:8]}"),
        ]
        try:
            await channel.send(view=SporkLayout(*items))
        except discord.HTTPException as exc:
            _logger.warning(f"could not post the stop notice for session {active.session_id}", exc_info=exc)

    @commands.hybrid_command()
    @commands.guild_only()
    async def minutes(self, ctx: GuildContext) -> None:
        """Shows this server's recorded minutes, quota, and reset date"""
        tier = await self.tiers.tier_for(ctx.guild.id)
        used = await self.bot.sessions.get_usage(ctx.guild.id)
        today = discord.utils.utcnow().date()
        next_reset = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
        reset_at = datetime.datetime.combine(next_reset, datetime.time(tzinfo=datetime.UTC))
        items: list[ui.Item] = [
            ui.TextDisplay(f"# Recorded Minutes\nThis server is on the **{tier.name}** plan."),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            ui.TextDisplay(
                f"### Usage"
                f"\n`{used // 60:,}` of `{tier.monthly_seconds // 60:,}` minutes used this month"
                f"\n╰ resets {ts(reset_at):R}"
            ),
            ui.Separator(),
            ui.TextDisplay(f"-# Guild ID: {ctx.guild.id}"),
        ]
        await ctx.send(view=SporkLayout(*items))

    @commands.hybrid_command()
    @commands.guild_only()
    async def optout(self, ctx: GuildContext) -> None:
        """Permanently excludes your audio from recordings in this server"""
        await self.bot.sessions.set_consent(ctx.guild.id, ctx.author.id, "opted_out")
        active = self.active.get(ctx.guild.id)
        if active is not None:
            active.included.discard(ctx.author.id)
        await ctx.send(
            "Done — your audio will never be recorded in this server. `optin` reverses this if you change your mind.",
            ephemeral=True,
        )

    @commands.hybrid_command()
    @commands.guild_only()
    async def optin(self, ctx: GuildContext) -> None:
        """Allows your audio to be included in recordings in this server"""
        await self.bot.sessions.set_consent(ctx.guild.id, ctx.author.id, "consented")
        active = self.active.get(ctx.guild.id)
        if active is not None:
            active.included.add(ctx.author.id)
        await ctx.send(
            "Got it — your audio can be included in recordings here. `optout` reverses this any time.",
            ephemeral=True,
        )

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def usage_flush(self) -> None:
        for guild_id, active in list(self.active.items()):
            elapsed = active.elapsed
            delta = elapsed - active.flushed_seconds
            if delta <= 0:
                continue
            active.flushed_seconds = elapsed
            total = await self.bot.sessions.add_usage(guild_id, delta)
            tier = await self.tiers.tier_for(guild_id)
            if total >= tier.monthly_seconds:
                # quota hit mid-session: stop gracefully, still process what we have
                await self.end_session(guild_id, "the server ran out of recorded minutes for this month")

    @usage_flush.before_loop
    async def before_usage_flush(self) -> None:
        await self.bot.wait_until_ready()

    @usage_flush.error
    async def usage_flush_error(self, error: BaseException) -> None:
        _logger.error("usage flush loop errored", exc_info=error)


async def setup(bot: Spork) -> None:
    await bot.add_cog(Voice(bot))
