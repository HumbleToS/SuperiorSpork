from __future__ import annotations

import typing  # Any below is the discord.py generic slot for a command's cog and parameters, which help never inspects
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.hybrid import HybridAppCommand

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from discord.ext.commands import Context

LINE_BUDGET = 70
LANDING_LINES = 10
PAGE_SIZE = 8
SELECT_LIMIT = 25  # discord's cap on select menu options
DETAIL_LINES = 12
OTHER_CATEGORY = "Other"


@dataclass(frozen=True)
class HelpEntry:
    """One runnable command, described with no discord.py objects attached."""

    name: str  # qualified, "brainrot terms add"
    category: str
    description: str  # one line
    details: str  # the first paragraph of the docstring
    usage: str
    example: str
    permissions: tuple[str, ...]
    guild_only: bool
    cooldown: str | None
    slash: bool
    slash_id: int | None

    @property
    def mention(self) -> str:
        # a clickable mention needs the root command's id; before the first sync it degrades to plain text
        if self.slash and self.slash_id is not None:
            return f"</{self.name}:{self.slash_id}>"
        return f"/{self.name}" if self.slash else self.usage.split(" ")[0]

    @property
    def shown_name(self) -> str:
        return f"/{self.name}" if self.slash else self.usage.split(" ")[0]


@dataclass(frozen=True)
class HelpCategory:
    name: str
    blurb: str
    emoji: str | None
    entries: tuple[HelpEntry, ...]

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}" if self.emoji else self.name


@dataclass(frozen=True)
class HelpIndex:
    categories: tuple[HelpCategory, ...]

    @property
    def entries(self) -> tuple[HelpEntry, ...]:
        return tuple(entry for category in self.categories for entry in category.entries)

    def category(self, name: str) -> HelpCategory | None:
        return discord.utils.find(lambda c: c.name.casefold() == name.casefold(), self.categories)

    def entry(self, name: str) -> HelpEntry | None:
        wanted = name.casefold().lstrip("/")
        return discord.utils.find(lambda e: e.name.casefold() == wanted, self.entries)


# pure helpers


def truncate(text: str, limit: int = LINE_BUDGET) -> str:
    """Cuts on a word boundary with an ellipsis, never mid-word unless the first word alone is too long."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if text[limit - 1].isalnum() and " " in cut:
        cut = cut[: cut.rfind(" ")]  # the cut landed inside a word, back off to the previous one
    return cut.rstrip(" ,;:—-") + "…"


def paginate(items: Sequence[Any], size: int) -> list[list[Any]]:
    size = max(1, size)
    return [list(items[i : i + size]) for i in range(0, len(items), size)] or [[]]


def visible_for(index: HelpIndex, allowed: Collection[str]) -> HelpIndex:
    """Keeps only the named commands, and drops categories left empty."""
    kept: list[HelpCategory] = []
    for category in index.categories:
        entries = tuple(entry for entry in category.entries if entry.name in allowed)
        if entries:
            kept.append(replace(category, entries=entries))
    return HelpIndex(tuple(kept))


def landing_lines(index: HelpIndex) -> list[str]:
    lines: list[str] = []
    for category in index.categories:
        count = len(category.entries)
        tail = f" · {count} command{'' if count == 1 else 's'}"
        lines.append(truncate(f"**{category.title}** — {category.blurb}", LINE_BUDGET - len(tail)) + tail)
    return lines


def category_lines(category: HelpCategory, page: int) -> tuple[list[str], int, int]:
    """Lines for one page of a category, plus the page number (clamped) and page count."""
    pages = paginate(category.entries, PAGE_SIZE)
    page = max(0, min(page, len(pages) - 1))
    lines: list[str] = []
    for entry in pages[page]:
        # the mention markup is long but renders as just the name, so budget on what the user sees
        room = LINE_BUDGET - len(entry.shown_name) - 3
        lines.append(f"{entry.mention} — {truncate(entry.description, room)}")
    return lines, page, len(pages)


def detail_lines(entry: HelpEntry) -> list[str]:
    lines = [f"**{entry.shown_name}**", truncate(entry.details, LINE_BUDGET * 3), "", f"**Usage** `{entry.usage}`"]
    if entry.example:
        lines.append(f"**Example** `{entry.example}`")
    if entry.permissions:
        lines.append(f"**Needs** {', '.join(entry.permissions)}")
    if entry.cooldown:
        lines.append(f"**Cooldown** {entry.cooldown}")
    if entry.guild_only:
        lines.append("-# Servers only")
    return lines[:DETAIL_LINES]


# building the index from the live command registry


def _first_paragraph(text: str) -> str:
    paragraph = text.strip().split("\n\n", 1)[0]
    return " ".join(line.strip() for line in paragraph.splitlines())


def _placeholder(param: commands.Parameter) -> str:
    annotation = param.converter
    origin = typing.get_origin(annotation)
    if origin is Literal:
        return str(typing.get_args(annotation)[0])
    if type(annotation).__name__ == "Range":  # commands.Range is Annotated to the type checker, so no isinstance
        low = getattr(annotation, "min", None)
        return str(max(int(low), 1) if isinstance(low, (int, float)) else 1)
    options = typing.get_args(annotation) if origin is not None else (annotation,)
    for option in options:
        if isinstance(option, type):
            if issubclass(option, (discord.Member, discord.User)):
                return "@someone"
            if issubclass(option, discord.Role):
                return "@role"
            if issubclass(option, (discord.abc.GuildChannel, discord.Thread)):
                return "#channel"
            if issubclass(option, bool):
                return "true"
            if issubclass(option, int):
                return "5"
    return param.displayed_name or param.name


def example_for(command: commands.Command[Any, ..., Any], slash: bool, prefix: str) -> str:
    """A representative invocation: every required parameter, or the optional ones when nothing is required."""
    params = list(command.clean_params.values())
    required = [p for p in params if p.required]
    chosen = required or params
    if slash:
        args = " ".join(f"{p.displayed_name or p.name}:{_placeholder(p)}" for p in chosen)
        return f"/{command.qualified_name}{' ' + args if args else ''}"
    args = " ".join(_placeholder(p) for p in chosen)
    return f"{prefix}{command.qualified_name}{' ' + args if args else ''}"


_OPTION_PLACEHOLDERS = {
    discord.AppCommandOptionType.user: "@someone",
    discord.AppCommandOptionType.role: "@role",
    discord.AppCommandOptionType.mentionable: "@someone",
    discord.AppCommandOptionType.channel: "#channel",
    discord.AppCommandOptionType.boolean: "true",
    discord.AppCommandOptionType.integer: "5",
    discord.AppCommandOptionType.number: "5",
}


def app_example_for(command: app_commands.Command[Any, ..., Any]) -> str:
    params = list(command.parameters)
    required = [p for p in params if p.required]
    chosen = required or params
    args = " ".join(
        f"{p.display_name}:{p.choices[0].value if p.choices else _OPTION_PLACEHOLDERS.get(p.type, p.display_name)}"
        for p in chosen
    )
    return f"/{command.qualified_name}{' ' + args if args else ''}"


def build_app_entry(command: app_commands.Command[Any, ..., Any], ids: Mapping[str, int]) -> HelpEntry:
    """A slash-only command (no prefix twin), described from the tree instead of the registry."""
    root = command.root_parent or command
    signature = " ".join(f"<{p.display_name}>" if p.required else f"[{p.display_name}]" for p in command.parameters)
    binding = command.binding
    contexts = command.allowed_contexts
    return HelpEntry(
        name=command.qualified_name,
        category=binding.qualified_name if isinstance(binding, commands.Cog) else OTHER_CATEGORY,
        description=truncate(command.description or "No description yet.", LINE_BUDGET),
        details=command.description or "No description yet.",
        usage=f"/{command.qualified_name}{' ' + signature if signature else ''}",
        example=str(command.extras.get("example") or app_example_for(command)),
        permissions=(),
        guild_only=contexts is not None and not (contexts.dm_channel or contexts.private_channel),
        cooldown=None,
        slash=True,
        slash_id=ids.get(root.name),
    )


_PERMISSION_NAMES = {"manage_guild": "Manage Server"}  # where discord's client wording differs from the api flag


def _permission_name(flag: str) -> str:
    return _PERMISSION_NAMES.get(flag, flag.replace("_", " ").title())


def _closure_permissions(check: object) -> list[str]:
    for cell in getattr(check, "__closure__", None) or ():
        value: object = cell.cell_contents
        if isinstance(value, dict):
            flags = {str(flag): bool(wanted) for flag, wanted in value.items()}
            if flags and all(flag in discord.Permissions.VALID_FLAGS for flag in flags):
                return [_permission_name(flag) for flag, wanted in flags.items() if wanted]
    return []


def permissions_for(command: commands.Command[Any, ..., Any]) -> tuple[tuple[str, ...], bool]:
    """Reads the human meaning of a command's checks, and whether one of them is guild_only."""
    names: list[str] = []
    guild_only = False
    for check in command.checks:
        qualname = getattr(check, "__qualname__", "")
        if qualname.startswith(("has_guild_permissions", "has_permissions")):
            names.extend(_closure_permissions(check))
        elif qualname.startswith("is_owner"):
            names.append("Bot owner")
        elif qualname.startswith("guild_only"):
            guild_only = True
        elif qualname.endswith("guild_owner"):
            names.append("Server owner")
        elif qualname.endswith("recorder"):
            names.append("Recorder role or Manage Server")
    return tuple(dict.fromkeys(names)), guild_only


def cooldown_for(command: commands.Command[Any, ..., Any]) -> str | None:
    cooldown = command.cooldown
    if cooldown is None:
        return None
    per = int(cooldown.per) if float(cooldown.per).is_integer() else cooldown.per
    return f"{cooldown.rate} every {per} second{'' if per == 1 else 's'}"


def _is_slash(command: commands.Command[Any, ..., Any]) -> bool:
    return isinstance(command, commands.HybridCommand | commands.HybridGroup) and command.app_command is not None


def build_entry(command: commands.Command[Any, ..., Any], ids: Mapping[str, int], prefix: str) -> HelpEntry:
    slash = _is_slash(command)
    root = command.root_parent or command
    permissions, guild_only = permissions_for(command)
    for parent in command.parents:
        parent_permissions, parent_guild_only = permissions_for(parent)
        permissions = tuple(dict.fromkeys(permissions + parent_permissions))
        guild_only = guild_only or parent_guild_only
    signature = command.signature
    usage = f"{'/' if slash else prefix}{command.qualified_name}{' ' + signature if signature else ''}"
    cog = command.cog
    return HelpEntry(
        name=command.qualified_name,
        category=cog.qualified_name if cog is not None else OTHER_CATEGORY,
        description=truncate(command.short_doc or "No description yet.", LINE_BUDGET),
        details=_first_paragraph(command.help or command.short_doc or "No description yet."),
        usage=usage,
        example=str(command.extras.get("example") or example_for(command, slash, prefix)),
        permissions=permissions,
        guild_only=guild_only,
        cooldown=cooldown_for(command),
        slash=slash,
        slash_id=ids.get(root.qualified_name) if slash else None,
    )


def build_index(bot: commands.Bot, ids: Mapping[str, int], prefix: str) -> HelpIndex:
    """Every listable command, grouped by cog. Rebuilt on demand, so it can never drift from the registry."""
    grouped: dict[str, list[HelpEntry]] = {}
    for command in bot.walk_commands():
        if command.hidden or any(parent.hidden for parent in command.parents):
            continue
        if isinstance(command, commands.Group) and command.commands:
            continue  # the leaves carry the behavior; a bare group only prints "try …"
        entry = build_entry(command, ids, prefix)
        grouped.setdefault(entry.category, []).append(entry)
    for app_command in bot.tree.walk_commands():
        if isinstance(app_command, app_commands.Command) and not isinstance(app_command, HybridAppCommand):
            entry = build_app_entry(app_command, ids)
            grouped.setdefault(entry.category, []).append(entry)

    categories: list[HelpCategory] = []
    for name, entries in grouped.items():
        cog = bot.get_cog(name)
        blurb = _first_paragraph(cog.description) if cog is not None and cog.description else "Commands"
        emoji = getattr(cog, "help_emoji", None)
        categories.append(
            HelpCategory(
                name=name,
                blurb=blurb,
                emoji=emoji if isinstance(emoji, str) and emoji else None,
                entries=tuple(sorted(entries, key=lambda entry: entry.name)),
            )
        )
    categories.sort(key=lambda category: (category.name == OTHER_CATEGORY, category.name.casefold()))
    return HelpIndex(tuple(categories))


async def _passes(command: commands.Command[Any, ..., Any], ctx: Context[Any]) -> bool:
    try:
        return await command.can_run(ctx)
    except commands.CommandError:
        return False


async def _app_passes(command: app_commands.Command[Any, ..., Any], ctx: Context[Any]) -> bool:
    contexts = command.allowed_contexts
    if ctx.guild is None and contexts is not None and not (contexts.dm_channel or contexts.private_channel):
        return False
    if not command.checks:
        return True
    if ctx.interaction is None:
        return False  # app checks need an interaction; without one, stay conservative
    try:
        # the private check runner is the only entry point discord.py offers for app command checks
        return await command._check_can_run(ctx.interaction)
    except app_commands.AppCommandError:
        return False


async def runnable_names(bot: commands.Bot, ctx: Context[Any], names: Iterable[str]) -> set[str]:
    """The subset of commands this invoker could actually run here: every check on the command and its parents."""
    allowed: set[str] = set()
    for name in names:
        command = bot.get_command(name)
        if command is None:
            app_command = bot.tree.get_command(name.split(" ")[0])
            for part in name.split(" ")[1:]:
                app_command = app_command.get_command(part) if isinstance(app_command, app_commands.Group) else None
            if isinstance(app_command, app_commands.Command) and await _app_passes(app_command, ctx):
                allowed.add(name)
            continue
        chain = [*command.parents, command]
        results = [await _passes(link, ctx) for link in chain]
        if all(results):
            allowed.add(name)
    return allowed
