from __future__ import annotations

import asyncio
import datetime
import io
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

import discord
from discord import app_commands, ui
from discord.ext import commands

import config

from .utils.cache import TTLCache
from .utils.charts import RANGE_DAYS, Chart, RangeName, member_chart, render_chart, server_chart
from .utils.devtools import (
    AUDIT_LIMIT,
    NOT_AVAILABLE,
    AuditStore,
    Block,
    cached_role_counts,
    channel_blocks,
    dev_only,
    guild_badge,
    guild_choices,
    is_dev_owner,
    member_blocks,
    overview_sections,
    paginate_blocks,
    parse_snowflake,
    render_page,
    role_blocks,
    tally_members,
)
from .utils.embeds import pastel_color
from .utils.layouts import SporkLayout, graphics_gallery
from .utils.stats import day_span
from .utils.time import ts
from .utils.wording import plural

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bot import Spork

    from .brainrot import Brainrot
    from .stats import Stats

_logger = logging.getLogger(__name__)

VIEW_TIMEOUT = 180.0
CONFIRM_TIMEOUT = 60.0
ROLE_COUNTS_TTL = 300  # role member counts are one api call per server; five minutes is plenty for a viewer
RENDER_TTL = 300  # a rendered chart is reused for shares and repeat looks
PROFILE_TTL = 900  # fetched user profiles (banner, accent), as in whois
CHART_NAME = "insights.png"
Section = Literal["overview", "channels", "members", "roles"]
SECTIONS: tuple[tuple[Section, str], ...] = (
    ("overview", "Overview"),
    ("channels", "Channels"),
    ("members", "Members"),
    ("roles", "Roles"),
)


async def respond(interaction: discord.Interaction, text: str, **kwargs: Any) -> None:
    """An ephemeral reply whether or not the interaction has been answered yet."""
    kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(text, ephemeral=True, **kwargs)


class ShareButton(ui.Button["DevView"]):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(label="Share to chat", style=discord.ButtonStyle.secondary, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is not None:
            await view.cog.share(interaction, view)


class NavButton(ui.Button["DevView"]):
    def __init__(self, label: str, step: int, *, disabled: bool) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is not None:
            view.page += self.step
            view.render()
            await interaction.response.edit_message(view=view)


class DevView(SporkLayout):
    """An ephemeral /dev card: answers only the owner, disables itself on timeout, and shares as a static snapshot."""

    def __init__(
        self,
        cog: Developer,
        *,
        invoker_id: int,
        subject: str,
        subject_guild_id: int | None,
        sensitive: bool,
        accent: discord.Colour,
    ) -> None:
        super().__init__(accent_colour=accent, timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.invoker_id = invoker_id
        self.subject = subject  # what a share would be about, for the confirm question
        self.subject_guild_id = subject_guild_id
        self.sensitive = sensitive  # always confirm before sharing
        self.page = 0
        self.interaction: discord.Interaction | None = None

    def body(self) -> list[ui.Item[Any]]:
        raise NotImplementedError

    def controls(self) -> list[ui.ActionRow[Any]]:
        return [ui.ActionRow(ShareButton())]

    def render(self) -> None:
        self.replace(*self.body(), *self.controls())

    def files(self) -> list[discord.File]:
        return []

    def needs_confirm(self, interaction: discord.Interaction) -> bool:
        return self.sensitive or self.subject_guild_id != interaction.guild_id

    def snapshot(self, shared_by: str) -> SporkLayout:
        """The same card with nothing left to click and a line saying who posted it."""
        items = [item for item in self.body() if not isinstance(item, ui.ActionRow)]
        items.extend((ui.Separator(), ui.TextDisplay(f"-# Shared by {discord.utils.escape_markdown(shared_by)}")))
        return SporkLayout(*items, accent_colour=self.accent_colour)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_dev_owner(interaction.user.id) and interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(NOT_AVAILABLE, ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if isinstance(item, ui.Button | ui.Select):
                item.disabled = True
        try:
            if self.interaction is not None:
                await self.interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass  # the ephemeral message was dismissed; nothing left to disable


class TextView(DevView):
    """A one-off card of headed text sections, for audit and purge replies."""

    def __init__(self, cog: Developer, sections: Sequence[str], footer: str, **kwargs: Any) -> None:
        super().__init__(cog, **kwargs)
        self.sections = tuple(sections)
        self.footer = footer
        self.render()

    def body(self) -> list[ui.Item[Any]]:
        items: list[ui.Item[Any]] = [ui.TextDisplay(section) for section in self.sections]
        items.extend((ui.Separator(), ui.TextDisplay(f"-# {self.footer}")))
        return items


class InsightsView(DevView):
    """A snapshot card over one composite chart; the image is re-uploaded from bytes on every send."""

    def __init__(
        self,
        cog: Developer,
        *,
        header: ui.Item[Any],
        sections: Sequence[str],
        footer: str,
        png: bytes,
        gallery: ui.MediaGallery | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(cog, **kwargs)
        self.header = header
        self.sections = tuple(sections)
        self.footer = footer
        self.png = png
        self.gallery = gallery
        self.render()

    def files(self) -> list[discord.File]:
        return [discord.File(io.BytesIO(self.png), filename=CHART_NAME)]

    def body(self) -> list[ui.Item[Any]]:
        items: list[ui.Item[Any]] = [self.header, ui.Separator(spacing=discord.SeparatorSpacing.large)]
        items.extend(ui.TextDisplay(section) for section in self.sections)
        items.append(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{CHART_NAME}")))
        if self.gallery is not None:
            items.append(self.gallery)
        items.extend((ui.Separator(), ui.TextDisplay(f"-# {self.footer}")))
        return items


class SectionSelect(ui.Select["ServerView"]):
    def __init__(self, current: Section) -> None:
        super().__init__(
            placeholder="Pick a view",
            options=[discord.SelectOption(label=label, value=key, default=key == current) for key, label in SECTIONS],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return
        section: Section = "overview"
        for key, _ in SECTIONS:
            if key == self.values[0]:
                section = key
        if section == "roles" and view.role_counts is None:
            await interaction.response.defer()  # one api call for the counts; defer rather than risk the 3 s window
            view.set_role_counts(await view.cog.role_counts(view.guild))
            view.show(section)
            await interaction.edit_original_response(view=view)
            return
        view.show(section)
        await interaction.response.edit_message(view=view)


class ServerView(DevView):
    """The mini server viewer: overview, channel sidebar, member sidebar, and roles, paged in place."""

    def __init__(self, cog: Developer, guild: discord.Guild, *, invoker_id: int, origin_guild_id: int | None) -> None:
        super().__init__(
            cog,
            invoker_id=invoker_id,
            subject=guild.name,
            subject_guild_id=guild.id,
            sensitive=False,
            accent=pastel_color(guild.id),
        )
        self.guild = guild
        self.mentions = origin_guild_id == guild.id  # mentions only resolve inside the server they belong to
        self.presences = cog.bot.intents.presences
        self.full_members = cog.bot.intents.members and guild.chunked
        self.section: Section = "overview"
        self.role_counts: dict[int, int] | None = None
        self._pages: dict[Section, list[list[Block]]] = {}  # built on first visit; the view lives three minutes
        self._tally = tally_members(guild, presences=self.presences)
        self.render()

    def show(self, section: Section, page: int = 0) -> None:
        self.section = section
        self.page = page
        self.render()

    def set_role_counts(self, counts: dict[int, int]) -> None:
        self.role_counts = counts
        self._pages.pop("roles", None)  # a page built from cache counts is stale now

    def pages(self) -> list[list[Block]]:
        if self.section not in self._pages:
            if self.section == "channels":
                blocks = channel_blocks(self.guild, mentions=self.mentions)
            elif self.section == "members":
                blocks = member_blocks(self.guild, presences=self.presences)
            else:
                counts = self.role_counts if self.role_counts is not None else cached_role_counts(self.guild)
                blocks = role_blocks(self.guild, counts, mentions=self.mentions)
            self._pages[self.section] = paginate_blocks(blocks)
        return self._pages[self.section]

    def header(self) -> ui.Item[Any]:
        guild = self.guild
        title = f"# {discord.utils.escape_markdown(guild.name)}{guild_badge(guild)}\n`{guild.id}`"
        return ui.Section(title, accessory=ui.Thumbnail(guild.icon.url)) if guild.icon else ui.TextDisplay(title)

    def body(self) -> list[ui.Item[Any]]:
        items: list[ui.Item[Any]] = [self.header(), ui.Separator(spacing=discord.SeparatorSpacing.large)]
        notes: list[str] = []
        if self.section == "overview":
            shard = self.guild.shard_id if isinstance(self.cog.bot, commands.AutoShardedBot) else None
            sections = overview_sections(
                self.guild, self._tally, presences=self.presences, full_members=self.full_members, shard_id=shard
            )
            items.extend(ui.TextDisplay(section) for section in sections)
            gallery = graphics_gallery(self.guild.banner)
            if gallery:
                items.append(gallery)
        else:
            pages = self.pages()
            self.page = max(0, min(self.page, len(pages) - 1))
            label = dict(SECTIONS)[self.section]
            heading = f"### {label}" + (f" · page {self.page + 1}/{len(pages)}" if len(pages) > 1 else "")
            items.append(ui.TextDisplay(f"{heading}\n{render_page(pages[self.page])}"))
            if self.section == "members":
                if not self.full_members:
                    notes.append("Member list partial")
                if not self.presences:
                    notes.append("Presence unavailable")
            if self.section == "roles" and self.role_counts is None:
                notes.append("Counts from cache")
        footer = f"Guild ID: {self.guild.id}"
        if notes:
            footer += " • " + " • ".join(notes)
        items.extend((ui.Separator(), ui.TextDisplay(f"-# {footer}")))
        return items

    def controls(self) -> list[ui.ActionRow[Any]]:
        pages = len(self.pages()) if self.section != "overview" else 1
        return [
            ui.ActionRow(SectionSelect(self.section)),
            ui.ActionRow(
                NavButton("Prev", -1, disabled=self.page <= 0),
                NavButton("Next", 1, disabled=self.page >= pages - 1),
                ShareButton(),
                ui.Button(label="Open", url=f"https://discord.com/channels/{self.guild.id}"),
            ),
        ]


class ConfirmButton(ui.Button["ConfirmShareView"]):
    def __init__(self, share: bool) -> None:
        style = discord.ButtonStyle.primary if share else discord.ButtonStyle.secondary
        super().__init__(label="Share" if share else "Cancel", style=style)
        self.share = share

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return
        view.stop()
        if self.share:
            await view.cog.post_snapshot(interaction, view.card)
            await view.finish("Shared.")
        else:
            await interaction.response.edit_message(
                view=SporkLayout(ui.TextDisplay("Not shared."), accent_colour=view.accent_colour)
            )


class ConfirmShareView(SporkLayout):
    def __init__(self, cog: Developer, card: DevView, question: str) -> None:
        super().__init__(
            ui.TextDisplay(question),
            ui.ActionRow(ConfirmButton(True), ConfirmButton(False)),
            accent_colour=card.accent_colour,
            timeout=CONFIRM_TIMEOUT,
        )
        self.cog = cog
        self.card = card
        self.interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.card.interaction_check(interaction)

    async def finish(self, text: str) -> None:
        try:
            if self.interaction is not None:
                await self.interaction.edit_original_response(
                    view=SporkLayout(ui.TextDisplay(text), accent_colour=self.accent_colour)
                )
        except discord.HTTPException:
            pass  # the prompt was dismissed already

    async def on_timeout(self) -> None:
        await self.finish("Not shared — the prompt expired.")


class Developer(commands.Cog, description="Owner tools"):
    dev = app_commands.Group(
        name="dev",
        description="Developer tools",
        allowed_installs=app_commands.AppInstallationType(guild=False, user=True),
        allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
        extras={"hidden": True},
    )
    dev_server = app_commands.Group(name="server", description="Developer tools", parent=dev)
    dev_user = app_commands.Group(name="user", description="Developer tools", parent=dev)

    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.audit = AuditStore(bot.pool)
        self._role_counts = TTLCache(ttl=ROLE_COUNTS_TTL)
        self._renders = TTLCache(ttl=RENDER_TTL)
        self._profiles = TTLCache(ttl=PROFILE_TTL)

    # every app command in this cog, every component, and every autocomplete answers to the same allowlist

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return is_dev_owner(interaction.user.id)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await respond(interaction, NOT_AVAILABLE)

    async def guild_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not is_dev_owner(interaction.user.id):
            return []
        return guild_choices(self.bot.guilds, current)

    def target_guild(self, interaction: discord.Interaction, value: str | None) -> discord.Guild | None:
        """The server an argument names, or the current one when the bot is in it; None means ask for one."""
        if value is not None:
            guild_id = parse_snowflake(value)
            return self.bot.get_guild(guild_id) if guild_id is not None else None
        return self.bot.get_guild(interaction.guild_id) if interaction.guild_id is not None else None

    async def record(
        self,
        interaction: discord.Interaction,
        command: str,
        *,
        guild_id: int | None,
        target_user_id: int | None = None,
        channel_id: int | None = None,
    ) -> None:
        await self.audit.log(
            interaction.user.id, command, guild_id=guild_id, target_user_id=target_user_id, channel_id=channel_id
        )
        channel = self.bot.get_channel(getattr(config, "DEV_LOG_CHANNEL_ID", 0) or 0)
        if not isinstance(channel, discord.abc.Messageable):
            return
        parts = [f"`{command}`", f"by `{interaction.user.id}`"]
        if guild_id is not None:
            parts.append(f"guild `{guild_id}`")
        if target_user_id is not None:
            parts.append(f"user `{target_user_id}`")
        if channel_id is not None:
            parts.append(f"shared to `{channel_id}`")
        view = SporkLayout(ui.TextDisplay(" · ".join(parts)), accent_colour=pastel_color(interaction.user.id))
        try:
            await channel.send(view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            _logger.debug("could not post to the dev log channel", exc_info=exc)

    async def role_counts(self, guild: discord.Guild) -> dict[int, int]:
        cached = self._role_counts.get(guild.id)
        if isinstance(cached, dict):
            return cached
        try:
            counts = {role.id: count for role, count in (await guild.role_member_counts()).items()}
        except discord.HTTPException as exc:
            _logger.debug(f"could not fetch role member counts for {guild.id}", exc_info=exc)
            counts = cached_role_counts(guild)
        self._role_counts.set(guild.id, counts)
        return counts

    async def open(self, interaction: discord.Interaction, view: DevView) -> None:
        files = view.files() or discord.utils.MISSING
        mentions = discord.AllowedMentions.none()
        if interaction.response.is_done():  # deferred while the queries and the render ran
            await interaction.followup.send(view=view, files=files, ephemeral=True, allowed_mentions=mentions, wait=True)
        else:
            await interaction.response.send_message(view=view, files=files, ephemeral=True, allowed_mentions=mentions)
        view.interaction = interaction

    # insights: the stats service gives plain data, the chart module draws it off the loop, and the bytes are cached

    def stats(self) -> Stats | None:
        # sibling cogs are looked up by name: load_extension gives each module a fresh class identity
        cog = self.bot.get_cog("Stats")
        return cast("Stats", cog) if cog is not None else None

    def brainrot(self) -> Brainrot | None:
        cog = self.bot.get_cog("Brainrot")
        return cast("Brainrot", cog) if cog is not None else None

    async def render(self, key: tuple[Any, ...], chart: Chart) -> bytes:
        cached = self._renders.get(key)
        if isinstance(cached, bytes):
            return cached
        png = await asyncio.to_thread(render_chart, chart)
        self._renders.set(key, png)
        return png

    async def profile(self, user_id: int) -> discord.User | None:
        """The fetched user, for the banner and accent colour; None when discord won't say."""
        cached = self._profiles.get(user_id)
        if isinstance(cached, discord.User):
            return cached
        try:
            fetched = await self.bot.fetch_user(user_id)
        except discord.HTTPException as exc:
            _logger.debug(f"could not fetch user {user_id}", exc_info=exc)
            return None
        self._profiles.set(user_id, fetched)
        return fetched

    async def member_of(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)  # the one fetch a lookup is allowed
        except discord.HTTPException:
            return None

    @staticmethod
    def channel_names(guild: discord.Guild, channel_ids: Sequence[int]) -> dict[int, str]:
        names: dict[int, str] = {}
        for channel_id in channel_ids:
            channel = guild.get_channel_or_thread(channel_id)
            # a deleted channel keeps a short, distinct label that survives the chart's truncation
            names[channel_id] = f"#{channel.name}" if channel is not None else f"deleted …{str(channel_id)[-4:]}"
        return names

    def tracking_line(self, guild: discord.Guild, tracking_since: datetime.datetime | None) -> str:
        stats = self.stats()
        if stats is not None and not stats.is_enabled(guild.id):
            return "Activity counts are off here (`stats off`)"
        if tracking_since is None:
            return "No activity counts yet"
        return f"Tracking since {ts(tracking_since):D}"

    # sharing: a static copy, posted publicly on purpose, after a confirm when it isn't the server's own card

    async def share(self, interaction: discord.Interaction, view: DevView) -> None:
        if not view.needs_confirm(interaction):
            await self.post_snapshot(interaction, view)
            return
        channel = interaction.channel
        where = channel.mention if isinstance(channel, discord.abc.GuildChannel | discord.Thread) else "this DM"
        question = f"This posts info about **{discord.utils.escape_markdown(view.subject)}** in {where}. Share?"
        confirm = ConfirmShareView(self, view, question)
        await interaction.response.send_message(
            view=confirm, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )
        confirm.interaction = interaction

    async def post_snapshot(self, interaction: discord.Interaction, view: DevView) -> None:
        snapshot = view.snapshot(interaction.user.display_name)
        files = view.files()
        try:
            callback = await interaction.response.send_message(
                view=snapshot, files=files or discord.utils.MISSING, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as exc:
            # user-installed apps can only post where the user could; the ephemeral card stays as it was
            await respond(interaction, f"Discord wouldn't let me post that here ({exc.text or exc.status}).")
            return
        await self.record(interaction, "share", guild_id=view.subject_guild_id, channel_id=interaction.channel_id)
        if callback.is_ephemeral:
            await respond(
                interaction,
                "Discord made that ephemeral — Use External Apps is off for user-installed apps here, so nobody else saw it.",
            )

    # commands

    @dev_server.command(name="view")
    @dev_only()
    @app_commands.describe(guild="A server I'm in, by name or id; defaults to this one")
    @app_commands.autocomplete(guild=guild_autocomplete)
    async def dev_server_view(self, interaction: discord.Interaction, guild: str | None = None) -> None:
        """Mini server viewer"""
        target = self.target_guild(interaction, guild)
        if target is None:
            await respond(interaction, "Pick a server I'm in — `guild` is required here.")
            return
        await self.record(interaction, "dev server view", guild_id=target.id)
        await self.open(
            interaction, ServerView(self, target, invoker_id=interaction.user.id, origin_guild_id=interaction.guild_id)
        )

    @dev_server.command(name="insights")
    @dev_only()
    @app_commands.describe(guild="A server I'm in, by name or id; defaults to this one", days="How far back to look")
    @app_commands.rename(days="range")
    @app_commands.autocomplete(guild=guild_autocomplete)
    async def dev_server_insights(
        self, interaction: discord.Interaction, guild: str | None = None, days: RangeName = "30d"
    ) -> None:
        """Server snapshot and activity graphs"""
        target = self.target_guild(interaction, guild)
        if target is None:
            await respond(interaction, "Pick a server I'm in — `guild` is required here.")
            return
        stats = self.stats()
        if stats is None:
            await respond(interaction, "The stats module isn't loaded.")
            return
        await interaction.response.defer(ephemeral=True)
        await self.record(interaction, "dev server insights", guild_id=target.id)
        span = day_span(RANGE_DAYS[days], discord.utils.utcnow().date())
        activity = await stats.store.guild_activity(target.id, span)
        names = self.channel_names(target, [row.channel_id for row in activity.top_channels])
        accent = pastel_color(target.id)
        chart = server_chart(activity, names, accent.to_rgb(), joins_available=self.bot.intents.members)
        png = await self.render(("server", target.id, days), chart)

        presences = self.bot.intents.presences
        tally = tally_members(target, presences=presences)
        members = f"**Total:** `{tally.total:,}`\n**Humans:** `{tally.humans:,}` · **Bots:** `{tally.bots:,}`"
        if tally.online is not None:
            members += f"\n**Online:** `{tally.online:,}`"
        joins = sum(point.joins for point in activity.joins_leaves)
        leaves = sum(point.leaves for point in activity.joins_leaves)
        busiest = max(activity.messages, key=lambda point: point.count, default=None)
        activity_lines = f"**Messages:** `{activity.total_messages:,}`"
        if self.bot.intents.members:
            activity_lines += f"\n**Joined:** `{joins:,}` · **Left:** `{leaves:,}`"
        if busiest is not None and busiest.count:
            noon = datetime.datetime.combine(busiest.day, datetime.time(hour=12), tzinfo=datetime.UTC)
            activity_lines += f"\n**Busiest day:** {ts(noon):D} (`{busiest.count:,}`)"
        joined = target.me.joined_at if target.me is not None else None
        dates = f"**I joined:** {ts(joined):D}" if joined is not None else "**I joined:** unknown"
        dates += f"\n**{self.tracking_line(target, activity.tracking_since)}**"
        title = f"# {discord.utils.escape_markdown(target.name)}{guild_badge(target)}\n`{target.id}`"
        header = ui.Section(title, accessory=ui.Thumbnail(target.icon.url)) if target.icon else ui.TextDisplay(title)
        sections = [
            f"### Members\n{members}",
            f"### Boosts\n**Level:** `{target.premium_tier}` · **Boosts:** `{target.premium_subscription_count or 0:,}`",
            f"### Channels & roles\n`{len(target.channels) - len(target.categories):,}` channels · `{len(target.roles):,}` roles",
            f"### Last {RANGE_DAYS[days]} days\n{activity_lines}",
            f"### Dates\n{dates}",
        ]
        footer = f"{days} • Guild ID: {target.id}" + ("" if presences else " • Presence unavailable")
        view = InsightsView(
            self,
            header=header,
            sections=sections,
            footer=footer,
            png=png,
            invoker_id=interaction.user.id,
            subject=target.name,
            subject_guild_id=target.id,
            sensitive=False,
            accent=accent,
        )
        await self.open(interaction, view)

    @dev_user.command(name="insights")
    @dev_only()
    @app_commands.describe(
        user="Pick a user",
        user_id="Or their id, when the picker can't find them",
        guild="A server I'm in, by name or id; defaults to this one",
        days="How far back to look",
    )
    @app_commands.rename(days="range")
    @app_commands.autocomplete(guild=guild_autocomplete)
    async def dev_user_insights(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
        user_id: str | None = None,
        guild: str | None = None,
        days: RangeName = "30d",
    ) -> None:
        """User profile, server membership, and activity graphs"""
        target = self.target_guild(interaction, guild)
        if target is None:
            await respond(interaction, "Pick a server I'm in — `guild` is required here.")
            return
        stats = self.stats()
        if stats is None:
            await respond(interaction, "The stats module isn't loaded.")
            return
        if user is None:
            wanted = parse_snowflake(user_id or "")
            if wanted is None:
                await respond(interaction, "Pick a user, or give me a user id.")
                return
            user = self.bot.get_user(wanted) or await self.profile(wanted)
            if user is None:
                await respond(interaction, "I can't find that user.")
                return
        await interaction.response.defer(ephemeral=True)
        await self.record(interaction, "dev user insights", guild_id=target.id, target_user_id=user.id)
        span = day_span(RANGE_DAYS[days], discord.utils.utcnow().date())
        activity = await stats.store.member_activity(target.id, user.id, span)
        fetched = await self.profile(user.id)
        member = await self.member_of(target, user.id)
        accent = (fetched.accent_colour if fetched is not None else None) or pastel_color(user.id)
        names = self.channel_names(target, [row.channel_id for row in activity.top_channels])
        png = await self.render(("user", target.id, user.id, days), member_chart(activity, names, accent.to_rgb()))

        username = discord.utils.escape_markdown(str(user))
        display = discord.utils.escape_markdown(user.display_name)
        flags = [flag.name.replace("_", " ") for flag in user.public_flags.all()]
        if user.bot:
            flags.insert(0, "bot")
        if user.system:
            flags.insert(0, "system")
        profile = (
            f"**Username:** {username}\n**Display name:** {display}"
            f"\n**Created:** {ts(user.created_at):D} ({ts(user.created_at):R})"
            f"\n**Flags:** {', '.join(flags) if flags else 'none'}"
            f"\n**Mutual servers:** `{len(user.mutual_guilds):,}`"
        )
        guild_name = discord.utils.escape_markdown(target.name)
        if member is not None:
            roles = len(member.roles) - 1  # without @everyone
            top_role = (
                member.top_role.mention
                if interaction.guild_id == target.id
                else discord.utils.escape_markdown(member.top_role.name)
            )
            joined_at = f"{ts(member.joined_at):D} ({ts(member.joined_at):R})" if member.joined_at else "unknown"
            timed_out = f"until {ts(member.timed_out_until):R}" if member.is_timed_out() and member.timed_out_until else "no"
            membership = (
                f"**Nickname:** {discord.utils.escape_markdown(member.nick) if member.nick else 'none'}"
                f"\n**Joined:** {joined_at}"
                f"\n**Top role:** {top_role} ({plural(roles):role})"
                f"\n**Boosting since:** {f'{ts(member.premium_since):D}' if member.premium_since else 'not boosting'}"
                f"\n**Timed out:** {timed_out}"
                f"\n**Administrator:** {'yes' if member.guild_permissions.administrator else 'no'}"
            )
        else:
            membership = "Not a member right now"
        rank = activity.rank
        if rank is not None:
            membership += f"\n**Message rank:** top {rank.top_percent:.0f}% (#{rank.rank:,} of {rank.ranked:,}, `{rank.messages:,}` messages)"
        else:
            membership += f"\n**Message rank:** no messages in the last {RANGE_DAYS[days]} days"
        sections = [f"### Profile\n{profile}", f"### In {guild_name}\n{membership}"]
        brainrot = self.brainrot()
        if brainrot is not None:
            state = await brainrot.store.get_state(target.id, user.id)
            heat = brainrot.engine.decayed(state).heat
            sections.append(f"### Anti-brainrot\n**Heat:** `{heat}` · **Lifetime offenses:** `{state.lifetime_offenses:,}`")
        header = ui.Section(f"# {display}\n{username} · `{user.id}`", accessory=ui.Thumbnail(user.display_avatar.url))
        view = InsightsView(
            self,
            header=header,
            sections=sections,
            footer=f"{days} • {self.tracking_line(target, activity.tracking_since)} • User ID: {user.id} • Guild ID: {target.id}",
            png=png,
            gallery=graphics_gallery(fetched.banner if fetched is not None else None),
            invoker_id=interaction.user.id,
            subject=f"{user} in {target.name}",
            subject_guild_id=target.id,
            sensitive=True,
            accent=accent,
        )
        await self.open(interaction, view)

    @dev.command(name="audit")
    @dev_only()
    @app_commands.describe(limit="How many recent entries to show")
    async def dev_audit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, AUDIT_LIMIT] = 10) -> None:
        """Recent dev tool usage"""
        await self.record(interaction, "dev audit", guild_id=None)
        entries = await self.audit.recent(limit)
        lines = "\n".join(f"`{entry.user_id}` · {entry.line}" for entry in entries) or "Nothing yet."
        view = TextView(
            self,
            [f"### Dev tool usage\n{lines}"],
            f"{plural(len(entries)):entry|entries} • newest first",
            invoker_id=interaction.user.id,
            subject="the dev audit log",
            subject_guild_id=None,
            sensitive=True,
            accent=pastel_color(interaction.user.id),
        )
        await self.open(interaction, view)

    @dev.command(name="purge")
    @dev_only()
    @app_commands.describe(user_id="The user whose stored activity counts to delete", guild="One server only, by name or id")
    @app_commands.autocomplete(guild=guild_autocomplete)
    async def dev_purge(self, interaction: discord.Interaction, user_id: str, guild: str | None = None) -> None:
        """Deletes a user's stored activity counts"""
        target_user_id = parse_snowflake(user_id)
        if target_user_id is None:
            await respond(interaction, "That doesn't look like a user id.")
            return
        target = None
        if guild is not None:
            target = self.target_guild(interaction, guild)
            if target is None:
                await respond(interaction, "I'm not in that server.")
                return
        stats = self.stats()
        if stats is None:
            await respond(interaction, "The stats module isn't loaded.")
            return
        deleted = await stats.store.purge_user(target_user_id, target.id if target else None)
        await self.record(interaction, "dev purge", guild_id=target.id if target else None, target_user_id=target_user_id)
        where = f"in **{discord.utils.escape_markdown(target.name)}**" if target else "everywhere"
        view = TextView(
            self,
            [f"### Purged\nDeleted {plural(deleted):row} of activity counts for `{target_user_id}` {where}."],
            f"User ID: {target_user_id}",
            invoker_id=interaction.user.id,
            subject=f"user {target_user_id}",
            subject_guild_id=target.id if target else None,
            sensitive=True,
            accent=pastel_color(target_user_id),
        )
        await self.open(interaction, view)

    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def sync(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[discord.Object],
        spec: Literal["~", "*", "^"] | None = None,
    ) -> None:
        """Syncs command tree.

        Parameters
        -----------
        guilds: list[int]
            The guilds to sync to
        spec: str
            The spec to sync.
            ~ -> Current Guild
            * -> Globals to current guild
            ^ -> Clear globals copied to current guild.
        """
        if not guilds:
            if spec == "~":
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await ctx.bot.tree.sync()
            await ctx.send(f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}")
            return

        ret = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1
        await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")


async def setup(bot: Spork) -> None:
    await bot.add_cog(Developer(bot))
