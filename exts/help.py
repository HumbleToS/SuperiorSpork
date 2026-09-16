from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands, ui
from discord.ext import commands

import config

from .utils.embeds import pastel_color
from .utils.help import (
    LANDING_LINES,
    SELECT_LIMIT,
    HelpCategory,
    HelpEntry,
    HelpIndex,
    build_index,
    category_lines,
    detail_lines,
    landing_lines,
    paginate,
    runnable_names,
    truncate,
    visible_for,
)
from .utils.layouts import SporkLayout

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bot import Spork

_logger = logging.getLogger(__name__)

VIEW_TIMEOUT = 120.0
LANDING_PAGE = LANDING_LINES - 1  # one line is the header
NOT_YOURS = "This isn't your help menu."


class CategorySelect(ui.Select["HelpView"]):
    def __init__(self, categories: Sequence[HelpCategory]) -> None:
        super().__init__(
            placeholder="Pick a category",
            options=[
                discord.SelectOption(label=category.name, description=truncate(category.blurb, 100), value=category.name)
                for category in categories[:SELECT_LIMIT]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is not None:
            view.show_category(self.values[0])
            await interaction.response.edit_message(view=view)


class CommandSelect(ui.Select["HelpView"]):
    def __init__(self, entries: Sequence[HelpEntry]) -> None:
        super().__init__(
            placeholder="Pick a command",
            options=[
                discord.SelectOption(label=entry.shown_name, description=truncate(entry.description, 100), value=entry.name)
                for entry in entries[:SELECT_LIMIT]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is not None:
            view.show_entry(self.values[0])
            await interaction.response.edit_message(view=view)


class NavButton(ui.Button["HelpView"]):
    def __init__(self, label: str, action: str, *, disabled: bool = False, primary: bool = False) -> None:
        style = discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, disabled=disabled)
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is not None:
            view.navigate(self.action)
            await interaction.response.edit_message(view=view)


class HelpView(SporkLayout):
    """Landing → category → command detail, edited in place, for one invoker only."""

    def __init__(self, index: HelpIndex, invoker_id: int, *, dashboard: str | None, accent: discord.Colour) -> None:
        super().__init__(accent_colour=accent, timeout=VIEW_TIMEOUT)
        self.index = index
        self.invoker_id = invoker_id
        self.dashboard = dashboard
        self.category: HelpCategory | None = None
        self.entry: HelpEntry | None = None
        self.landing_page = 0
        self.category_page = 0
        self.interaction: discord.Interaction | None = None
        self.message: discord.Message | None = None
        self.render()

    # state

    def show_landing(self) -> None:
        self.category = None
        self.entry = None
        self.render()

    def show_category(self, name: str, page: int = 0) -> None:
        self.category = self.index.category(name)
        self.entry = None
        self.category_page = page
        self.render()

    def show_entry(self, name: str) -> bool:
        entry = self.index.entry(name)
        if entry is None:
            return False
        self.entry = entry
        self.category = self.index.category(entry.category)
        self.render()
        return True

    def navigate(self, action: str) -> None:
        if action == "home":
            self.show_landing()
        elif action == "back":
            if self.entry is not None and self.category is not None:
                self.show_category(self.category.name, self.category_page)
            else:
                self.show_landing()
        elif action in ("prev", "next"):
            step = -1 if action == "prev" else 1
            if self.category is not None:
                self.show_category(self.category.name, self.category_page + step)
            else:
                self.landing_page += step
                self.render()

    # rendering

    def render(self) -> None:
        if self.entry is not None:
            items = self._detail_items(self.entry)
        elif self.category is not None:
            items = self._category_items(self.category)
        else:
            items = self._landing_items()
            if self.dashboard:
                items.append(ui.TextDisplay(f"-# Dashboard: {self.dashboard}"))
        self.replace(*items)

    def _landing_items(self) -> list[ui.Item[Any]]:
        pages = paginate(self.index.categories, LANDING_PAGE)
        self.landing_page = max(0, min(self.landing_page, len(pages) - 1))
        categories: list[HelpCategory] = pages[self.landing_page]
        total = len(self.index.entries)
        header = f"**Help** · {total} command{'' if total == 1 else 's'}"
        if len(pages) > 1:
            header += f" · page {self.landing_page + 1}/{len(pages)}"
        lines = landing_lines(HelpIndex(tuple(categories)))
        items: list[ui.Item[Any]] = [
            ui.TextDisplay("\n".join([header, *lines]) if lines else f"{header}\nNothing here for you yet.")
        ]
        if categories:
            items.append(ui.ActionRow(CategorySelect(categories)))
        if len(pages) > 1:
            items.append(
                ui.ActionRow(
                    NavButton("Prev", "prev", disabled=self.landing_page == 0),
                    NavButton("Next", "next", disabled=self.landing_page >= len(pages) - 1),
                )
            )
        return items

    def _category_items(self, category: HelpCategory) -> list[ui.Item[Any]]:
        lines, page, pages = category_lines(category, self.category_page)
        self.category_page = page
        count = len(category.entries)
        header = f"**{category.title}** · {count} command{'' if count == 1 else 's'}"
        if pages > 1:
            header += f" · page {page + 1}/{pages}"
        shown = paginate(category.entries, len(lines) or 1)[page] if lines else []
        items: list[ui.Item[Any]] = [ui.TextDisplay("\n".join([header, *lines]))]
        if shown:
            items.append(ui.ActionRow(CommandSelect(shown)))
        items.append(
            ui.ActionRow(
                NavButton("Back", "home"),
                NavButton("Prev", "prev", disabled=page == 0),
                NavButton("Next", "next", disabled=page >= pages - 1),
            )
        )
        return items

    def _detail_items(self, entry: HelpEntry) -> list[ui.Item[Any]]:
        return [
            ui.TextDisplay("\n".join(detail_lines(entry))),
            ui.ActionRow(NavButton("Back", "back"), NavButton("All commands", "home")),
        ]

    # ownership and expiry

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(NOT_YOURS, ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if isinstance(item, ui.Button | ui.Select):
                item.disabled = True
        try:
            if self.interaction is not None:
                await self.interaction.edit_original_response(view=self)
            elif self.message is not None:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass  # the message is gone (temp help deletes itself); nothing left to disable


class Help(commands.Cog, description="This menu, and how to find any command"):
    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self._ids: dict[str, int] = {}  # root slash command name → id, from the last global sync
        self._guild_ids: dict[int, dict[str, int]] = {}  # the same for guild-scoped syncs
        self._original_sync = bot.tree.sync

    async def cog_load(self) -> None:
        tree = self.bot.tree
        self._original_sync = tree.sync
        tree.sync = self._sync  # mentions need ids, and the owner's sync command is where they come from
        try:
            self.remember(await tree.fetch_commands(), None)
        except (discord.HTTPException, discord.ClientException) as exc:
            _logger.info(f"help could not fetch slash command ids ({exc}); mentions fall back to plain names until a sync")

    async def cog_unload(self) -> None:
        self.bot.tree.sync = self._original_sync

    async def _sync(self, *, guild: discord.abc.Snowflake | None = None) -> list[app_commands.AppCommand]:
        synced = await self._original_sync(guild=guild)
        self.remember(synced, guild)
        return synced

    def remember(self, synced: Sequence[app_commands.AppCommand], guild: discord.abc.Snowflake | None) -> None:
        ids = {command.name: command.id for command in synced}
        if guild is None:
            self._ids = ids
        else:
            self._guild_ids[guild.id] = ids
        _logger.debug(f"help remembered {len(ids)} slash command ids for {'global' if guild is None else guild.id}")

    def ids_for(self, guild_id: int | None) -> dict[str, int]:
        # a guild copy of the tree (sync *) wins over the global ids inside that guild
        return {**self._ids, **self._guild_ids.get(guild_id or 0, {})}

    # the shared path: every entry point ends up here with a context and leaves with a view

    async def index_for(self, ctx: commands.Context[Any]) -> HelpIndex:
        prefix = config.PREFIX
        if ctx.guild is not None:
            prefix = await self.bot.settings.get_prefix(ctx.guild.id) or config.PREFIX
        index = build_index(self.bot, self.ids_for(ctx.guild.id if ctx.guild else None), prefix)
        allowed = await runnable_names(self.bot, ctx, [entry.name for entry in index.entries])
        return visible_for(index, allowed)

    def dashboard_for(self, user: discord.User | discord.Member) -> str | None:
        url = str(getattr(config, "DASHBOARD_URL", "") or "")
        if url and isinstance(user, discord.Member) and user.guild_permissions.manage_guild:
            return url
        return None

    async def view_for(self, ctx: commands.Context[Any]) -> HelpView:
        index = await self.index_for(ctx)
        return HelpView(index, ctx.author.id, dashboard=self.dashboard_for(ctx.author), accent=pastel_color(ctx.author.id))

    @app_commands.command(name="help")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.describe(
        command="Jump straight to one command",
        public="Post it in the channel instead of just to you (needs Manage Messages)",
    )
    async def slash_help(self, interaction: discord.Interaction, command: str | None = None, public: bool = False) -> None:
        """Finds a command fast, without cluttering the channel"""
        ctx = await commands.Context.from_interaction(interaction)
        view = await self.view_for(ctx)
        if command is not None and not view.show_entry(command):
            await interaction.response.send_message(
                f"I couldn't find a command called `{truncate(command, 40)}` that you can use here.", ephemeral=True
            )
            return
        member = interaction.user
        ephemeral = not (public and isinstance(member, discord.Member) and member.guild_permissions.manage_messages)
        await interaction.response.send_message(
            view=view, ephemeral=ephemeral, allowed_mentions=discord.AllowedMentions.none()
        )
        view.interaction = interaction

    @slash_help.autocomplete("command")
    async def command_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        ctx = await commands.Context.from_interaction(interaction)
        index = await self.index_for(ctx)
        wanted = current.casefold().lstrip("/")
        choices = [
            app_commands.Choice(name=entry.shown_name, value=entry.name)
            for entry in index.entries
            if wanted in entry.name.casefold()
        ]
        return choices[:SELECT_LIMIT]


async def setup(bot: Spork) -> None:
    await bot.add_cog(Help(bot))
