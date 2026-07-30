from __future__ import annotations

import datetime
import io
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from .utils.checks import is_recorder
from .utils.embeds import pastel_color
from .utils.layouts import SporkLayout
from .utils.pipeline import Pipeline
from .utils.time import ts
from .utils.wording import plural

if TYPE_CHECKING:
    import asyncpg

    from bot import Spork

    from .utils.context import GuildContext

_logger = logging.getLogger(__name__)

PAGE_SIZE = 5
POLL_SECONDS = 20
RETENTION_TIME = datetime.time(hour=4, tzinfo=datetime.UTC)


def recap_card(row: asyncpg.Record, title: str | None = None, recap: str | None = None) -> SporkLayout:
    title = title or row["title"] or "Voice Session"
    recap = recap or row["recap"] or "No recap was generated."
    if len(recap) > 3200:
        recap = recap[:3200] + "…"
    minutes = max(1, row["seconds_recorded"] // 60)
    items: list[ui.Item] = [
        ui.TextDisplay(f"# {title}\nRecorded {ts(row['started_at']):F}"),
        ui.Separator(spacing=discord.SeparatorSpacing.large),
        ui.TextDisplay(recap),
        ui.Separator(),
        ui.TextDisplay(f"-# Session {str(row['id'])[:8]} • {plural(minutes):minute} recorded"),
    ]
    return SporkLayout(*items, accent_colour=pastel_color(row["guild_id"]))


class PagerRow(ui.ActionRow["SessionPager"]):
    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await self.view.flip(interaction, -1)

    @ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await self.view.flip(interaction, 1)


class SessionPager(ui.LayoutView):
    """Pages through stored sessions, chronological for the journal, newest-first for the list."""

    def __init__(self, bot: Spork, guild_id: int, mode: str) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.mode = mode  # "journal" or "list"
        self.page = 0
        self.pages = 1

    async def render(self) -> None:
        total = await self.bot.sessions.count_done(self.guild_id)
        self.pages = max(1, -(-total // PAGE_SIZE))
        self.page = max(0, min(self.page, self.pages - 1))
        if self.mode == "journal":
            rows = await self.bot.sessions.journal_page(self.guild_id, self.page * PAGE_SIZE, PAGE_SIZE)
            header = "# Campaign Journal\nEvery recorded session, oldest first."
        else:
            rows = await self.bot.sessions.list_page(self.guild_id, self.page * PAGE_SIZE, PAGE_SIZE)
            header = "# Past Sessions\nNewest first. `recap latest` shows the full card."

        items: list[ui.Item] = [ui.TextDisplay(header), ui.Separator(spacing=discord.SeparatorSpacing.large)]
        if not rows:
            items.append(ui.TextDisplay("Nothing here yet — record something first!"))
        for row in rows:
            summary = (row["recap"] or "").split("###")[0].strip()
            if len(summary) > 300:
                summary = summary[:300] + "…"
            items.append(
                ui.TextDisplay(
                    f"### {row['title'] or 'Voice Session'} — {ts(row['started_at']):D}\n{summary}\n-# {str(row['id'])[:8]}"
                )
            )
        items.append(PagerRow())
        items.append(ui.Separator())
        items.append(ui.TextDisplay(f"-# Page {self.page + 1} of {self.pages}"))

        self.clear_items()
        self.add_item(ui.Container(*items, accent_colour=pastel_color(self.guild_id)))

    async def flip(self, interaction: discord.Interaction, delta: int) -> None:
        self.page += delta
        await self.render()
        await interaction.response.edit_message(view=self)


class Recaps(commands.Cog):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.pipeline = Pipeline(bot)
        self.pipeline.on_done = self.post_recap
        self.pipeline.on_failed = self.post_failure

    async def cog_load(self) -> None:
        self.poll_jobs.start()
        self.retention.start()

    async def cog_unload(self) -> None:
        self.poll_jobs.cancel()
        self.retention.cancel()

    async def _recap_channel(self, row: asyncpg.Record) -> discord.abc.Messageable | None:
        settings = await self.bot.settings.get_voice_settings(row["guild_id"])
        channel_id = (settings["recap_channel_id"] if settings else None) or row["channel_id"]
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            _logger.warning(f"no reachable recap channel for session {row['id']}")
        return channel

    async def post_recap(self, row: asyncpg.Record, title: str, recap: str, transcript: str) -> None:
        channel = await self._recap_channel(row)
        if channel is None:
            return
        await channel.send(view=recap_card(row, title, recap))
        transcript_file = discord.File(io.BytesIO(transcript.encode()), filename=f"transcript-{str(row['id'])[:8]}.txt")
        await channel.send(file=transcript_file)

    async def post_failure(self, row: asyncpg.Record, error: str) -> None:
        channel = await self._recap_channel(row)
        if channel is None:
            return
        items: list[ui.Item] = [
            ui.TextDisplay(f"# Recap failed\nSession {str(row['id'])[:8]} couldn't be processed after several tries."),
            ui.Separator(),
            ui.TextDisplay(f"╰ {error[:300]}"),
        ]
        await channel.send(view=SporkLayout(*items))

    @commands.hybrid_group()
    async def recap(self, ctx: GuildContext) -> None:
        """Session recaps"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Try `recap latest`, `recap list`, `recap search`, or `recap delete`.")

    @recap.command()
    @commands.guild_only()
    async def latest(self, ctx: GuildContext) -> None:
        """Shows the most recent session recap"""
        row = await self.bot.sessions.latest(ctx.guild.id)
        if row is None:
            await ctx.send("No sessions have been recorded here yet.")
            return
        await ctx.send(view=recap_card(row))

    @recap.command(name="list")
    @commands.guild_only()
    async def recap_list(self, ctx: GuildContext) -> None:
        """Lists past sessions, newest first"""
        pager = SessionPager(self.bot, ctx.guild.id, "list")
        await pager.render()
        await ctx.send(view=pager)

    @recap.command()
    @commands.guild_only()
    @app_commands.describe(query="What to look for across transcripts and recaps")
    async def search(self, ctx: GuildContext, *, query: str) -> None:
        """Full-text search across this server's transcripts and recaps

        Parameters
        ----------
        query : str
            What to look for across transcripts and recaps
        """
        rows = await self.bot.sessions.search(ctx.guild.id, query)
        if not rows:
            await ctx.send(f"Nothing matched `{query}` here.")
            return
        items: list[ui.Item] = [
            ui.TextDisplay(f"# Search\n{plural(len(rows)):result} for `{query}`"),
            ui.Separator(spacing=discord.SeparatorSpacing.large),
        ]
        items.extend(
            ui.TextDisplay(
                f"### {row['title'] or 'Voice Session'} — {ts(row['started_at']):D}\n{row['snippet']}"
                f"\n-# {str(row['id'])[:8]}"
            )
            for row in rows
        )
        await ctx.send(view=SporkLayout(*items, accent_colour=pastel_color(ctx.guild.id)))

    @recap.command()
    @commands.guild_only()
    @is_recorder()
    @app_commands.describe(session="The session id from a recap card footer (first 8 characters work)")
    async def delete(self, ctx: GuildContext, session: str) -> None:
        """Deletes one session's transcript and recap

        Parameters
        ----------
        session : str
            The session id from a recap card footer (first 8 characters work)
        """
        row = await self.bot.sessions.get_session(ctx.guild.id, session)
        if row is None:
            await ctx.send(f"I couldn't find a session matching `{session}` here.")
            return
        await self.bot.sessions.delete_session(ctx.guild.id, row["id"])
        Pipeline.delete_audio(row["id"])
        await ctx.send(f"Session `{str(row['id'])[:8]}` is gone — transcript, recap, and any leftover audio.")

    @commands.hybrid_command()
    @commands.guild_only()
    async def journal(self, ctx: GuildContext) -> None:
        """The server's cumulative session journal, oldest first"""
        pager = SessionPager(self.bot, ctx.guild.id, "journal")
        await pager.render()
        await ctx.send(view=pager)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        # leaving a guild purges everything it ever stored, active session included
        voice_cog = self.bot.get_cog("Voice")
        active = getattr(voice_cog, "active", {}).pop(guild.id, None)
        if active is not None:
            active.sink.finalize()
            Pipeline.delete_audio(active.session_id)
        await self.bot.sessions.purge_guild(guild.id)
        _logger.info(f"Purged all voice recap data for departed guild {guild.id}")

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll_jobs(self) -> None:
        await self.pipeline.poll_once()

    @poll_jobs.before_loop
    async def before_poll_jobs(self) -> None:
        await self.bot.wait_until_ready()
        await self.pipeline.sweep_orphans()

    @poll_jobs.error
    async def poll_jobs_error(self, error: BaseException) -> None:
        _logger.error("recap pipeline loop errored", exc_info=error)

    @tasks.loop(time=RETENTION_TIME)
    async def retention(self) -> None:
        purged = await self.bot.sessions.purge_expired()
        if purged:
            _logger.info(f"Retention purge removed {purged} expired sessions")
        await self.bot.sessions.purge_old_usage()

    @retention.before_loop
    async def before_retention(self) -> None:
        await self.bot.wait_until_ready()

    @retention.error
    async def retention_error(self, error: BaseException) -> None:
        _logger.error("retention loop errored", exc_info=error)


async def setup(bot: Spork) -> None:
    await bot.add_cog(Recaps(bot))
