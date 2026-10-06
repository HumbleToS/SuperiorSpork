from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

import config

from .emojis import Status
from .time import ts
from .wording import plural

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Mapping, Sequence

    import asyncpg

    from .search import SearchTotal
    from .stats import Footprint

DEFAULT_OWNER_IDS = frozenset({739219467455823921})
NOT_AVAILABLE = "Not available."
PAGE_CHARS = 3000  # body budget per page; a whole view may carry 4000 characters across its text items
MEMBERS_PER_GROUP = 15
THREADS_PER_CHANNEL = 3
AUDIT_LIMIT = 25
STORAGE_GUILDS = 10  # servers named on the storage card
CHANNEL_ICONS: dict[discord.ChannelType, str] = {
    discord.ChannelType.text: "#",
    discord.ChannelType.news: "📢",
    discord.ChannelType.voice: "🔊",
    discord.ChannelType.stage_voice: "🎙️",
    discord.ChannelType.forum: "💬",
    discord.ChannelType.media: "🖼️",
}
NOTABLE_FEATURES = (
    "COMMUNITY",
    "DISCOVERABLE",
    "PARTNERED",
    "VERIFIED",
    "VANITY_URL",
    "INVITE_SPLASH",
    "BANNER",
    "ANIMATED_ICON",
    "WELCOME_SCREEN_ENABLED",
    "MEMBER_VERIFICATION_GATE_ENABLED",
    "PREVIEW_ENABLED",
    "AUTO_MODERATION",
    "ROLE_ICONS",
    "TICKETED_EVENTS_ENABLED",
    "MORE_STICKERS",
    "NEWS",
    "THREADS_ENABLED",
    "DEVELOPER_SUPPORT_SERVER",
    "HUB",
    "GUESTS_ENABLED",
)
# hue → the closest coloured square, so a role's colour survives without a custom emoji
_SQUARES: tuple[tuple[int, str], ...] = (
    (15, "🟥"),
    (45, "🟧"),
    (70, "🟨"),
    (170, "🟩"),
    (260, "🟦"),
    (330, "🟪"),
    (360, "🟥"),
)


def owner_ids() -> frozenset[int]:
    """The allowlist from config; anything unreadable counts as empty, and empty fails closed."""
    raw = getattr(config, "DEV_OWNER_IDS", DEFAULT_OWNER_IDS)
    try:
        return frozenset(int(value) for value in raw)
    except (TypeError, ValueError):
        return frozenset()


def is_dev_owner(user_id: int) -> bool:
    ids = owner_ids()
    return bool(ids) and user_id in ids


class NotDevOwner(app_commands.CheckFailure):
    """Raised when anyone outside DEV_OWNER_IDS reaches a /dev command"""

    pass


def dev_only() -> Callable[[Any], Any]:
    """The pinned owner check; pure on purpose, because help runs it to decide what to list."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if is_dev_owner(interaction.user.id):
            return True
        raise NotDevOwner(NOT_AVAILABLE)

    return app_commands.check(predicate)


# the audit log


@dataclass(frozen=True)
class AuditEntry:
    id: int
    at: datetime.datetime
    user_id: int
    command: str
    guild_id: int | None
    target_user_id: int | None
    channel_id: int | None

    @property
    def line(self) -> str:
        parts = [f"{ts(self.at):R}", f"`{self.command}`"]
        if self.guild_id is not None:
            parts.append(f"guild `{self.guild_id}`")
        if self.target_user_id is not None:
            parts.append(f"user `{self.target_user_id}`")
        if self.channel_id is not None:
            parts.append(f"shared to `{self.channel_id}`")
        return " · ".join(parts)


class AuditStore:
    """Every /dev use, as a row: who, what, which server, which user, and where a share went."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def log(
        self,
        user_id: int,
        command: str,
        *,
        guild_id: int | None = None,
        target_user_id: int | None = None,
        channel_id: int | None = None,
    ) -> AuditEntry:
        at = discord.utils.utcnow()
        row_id = await self.pool.fetchval(
            "INSERT INTO dev_audit (at, user_id, command, guild_id, target_user_id, channel_id)"
            " VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            at,
            user_id,
            command,
            guild_id,
            target_user_id,
            channel_id,
        )
        return AuditEntry(row_id, at, user_id, command, guild_id, target_user_id, channel_id)

    async def recent(self, limit: int = AUDIT_LIMIT) -> tuple[AuditEntry, ...]:
        rows = await self.pool.fetch(
            "SELECT id, at, user_id, command, guild_id, target_user_id, channel_id FROM dev_audit"
            " ORDER BY at DESC, id DESC LIMIT $1",
            max(1, min(limit, AUDIT_LIMIT)),
        )
        return tuple(
            AuditEntry(
                row["id"],
                row["at"],
                row["user_id"],
                row["command"],
                row["guild_id"],
                row["target_user_id"],
                row["channel_id"],
            )
            for row in rows
        )


# lifetime message counts: discord's search index, asked for totals only


def lifetime_section(counts: SearchTotal | str) -> str:
    """The card section: the total, or the reason there is none to show."""
    if isinstance(counts, str):
        return f"### Lifetime\n**Messages:** unavailable — {counts}"
    text = f"### Lifetime\n**Messages:** `{counts.total:,}` in this server"
    if counts.indexing:
        text += "\n-# discord is still indexing this server's history"
    return text


# the storage card: table sizes from the catalog, and the stats footprint per server


@dataclass(frozen=True)
class TableSize:
    name: str
    rows: int
    bytes: int


def _plain_table_name(name: str) -> bool:
    return name.isascii() and name.replace("_", "").isalnum() and name == name.lower()


async def database_size(pool: asyncpg.Pool) -> int:
    return int(await pool.fetchval("SELECT pg_database_size(current_database())"))


async def table_sizes(pool: asyncpg.Pool) -> tuple[TableSize, ...]:
    """Exact row counts and on-disk size for every table in the schema, largest first."""
    names = await pool.fetch("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename")
    sizes: list[TableSize] = []
    for row in names:
        name = row["tablename"]
        if not _plain_table_name(name):
            continue  # the names come from the catalog, and only these plain ones are interpolated below
        rows = await pool.fetchval(f"SELECT count(*) FROM {name}")
        size = await pool.fetchval("SELECT pg_total_relation_size(quote_ident($1)::regclass)", name)
        sizes.append(TableSize(name, int(rows), int(size)))
    return tuple(sorted(sizes, key=lambda table: (-table.bytes, table.name)))


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GB"


def storage_sections(
    database_bytes: int, tables: Sequence[TableSize], footprint: Footprint, names: Mapping[int, str]
) -> list[str]:
    """Two sections: what the database holds by table, and whose activity counts make up the bulk of it."""
    rows = sum(table.rows for table in tables)
    lines = [
        f"### Database\n**On disk:** `{human_size(database_bytes)}` · **Rows:** `{rows:,}` across"
        f" {plural(len(tables)):table}"
    ]
    lines.extend(f"`{table.name}` · `{table.rows:,}` rows · `{human_size(table.bytes)}`" for table in tables)
    oldest = f"{footprint.oldest_day:%Y-%m-%d}" if footprint.oldest_day is not None else "none"
    counts = [
        f"### Activity counts\n**Servers:** `{footprint.servers:,}` · **People:** `{footprint.people:,}`"
        f" · **Oldest day:** {oldest}"
    ]
    for guild in footprint.guilds:
        name = names.get(guild.guild_id, f"`{guild.guild_id}`")
        counts.append(f"{name} · `{guild.rows:,}` rows · {plural(guild.people):person|people}")
    if footprint.servers > len(footprint.guilds):
        counts.append(f"+{footprint.servers - len(footprint.guilds)} more servers")
    return ["\n".join(lines), "\n".join(counts)]


# the mini server viewer: pure builders that turn a guild into blocks, and a paginator that never cuts a line


@dataclass(frozen=True)
class Block:
    header: str | None
    lines: tuple[str, ...]

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def text(self) -> str:
        lines = list(self.lines)
        if self.header is not None:
            lines.insert(0, self.header)
        return "\n".join(lines)


def paginate_blocks(blocks: Sequence[Block], budget: int = PAGE_CHARS) -> list[list[Block]]:
    """Packs blocks into pages under the budget; an oversized block continues on the next page with its header."""
    pages: list[list[Block]] = [[]]
    used = 0
    for block in blocks:
        for piece in _split_block(block, budget):
            cost = piece.chars + (2 if pages[-1] else 0)  # the blank line between blocks
            if pages[-1] and used + cost > budget:
                pages.append([])
                used = 0
                cost = piece.chars
            pages[-1].append(piece)
            used += cost
    return pages


def _split_block(block: Block, budget: int) -> list[Block]:
    if block.chars <= budget:
        return [block]
    pieces: list[Block] = []
    header = block.header
    lines: list[str] = []
    used = len(header) + 1 if header else 0
    for line in block.lines:
        if lines and used + len(line) + 1 > budget:
            pieces.append(Block(header, tuple(lines)))
            header = f"{block.header} (cont.)" if block.header else None
            lines = []
            used = len(header) + 1 if header else 0
        lines.append(line)
        used += len(line) + 1
    pieces.append(Block(header, tuple(lines)))
    return pieces


def render_page(page: Sequence[Block]) -> str:
    return "\n\n".join(block.text for block in page) or "Nothing here."


def _name(value: str) -> str:
    return discord.utils.escape_markdown(value)


def colour_square(colour: discord.Colour) -> str:
    if colour.value == 0:
        return "⬛"
    hue, saturation, value = colorsys.rgb_to_hsv(colour.r / 255, colour.g / 255, colour.b / 255)
    if saturation < 0.35:
        return "⬜" if value > 0.6 else "⬛"
    degrees = hue * 360
    if value < 0.5:
        return "🟫" if degrees < 60 else "⬛"
    for limit, square in _SQUARES:
        if degrees <= limit:
            return square
    return "🟥"


def feature_names(features: Sequence[str]) -> list[str]:
    return [feature.lower().replace("_", " ") for feature in NOTABLE_FEATURES if feature in features]


def _visible_to_everyone(channel: discord.abc.GuildChannel) -> bool:
    return channel.overwrites_for(channel.guild.default_role).view_channel is not False


def channel_label(channel: discord.abc.GuildChannel | discord.Thread, *, mentions: bool) -> str:
    return channel.mention if mentions else f"{_name(channel.name)}"


def channel_line(channel: discord.abc.GuildChannel, threads: Sequence[discord.Thread], *, mentions: bool) -> list[str]:
    guild = channel.guild
    marks = ""
    if (guild.me is not None and not channel.permissions_for(guild.me).view_channel) or not _visible_to_everyone(channel):
        marks += "🔒"
    if getattr(channel, "nsfw", False):
        marks += "🔞"
    # a mention renders with the client's own type icon, so the text icon is only for plain names
    icon = "" if mentions else f"{CHANNEL_ICONS.get(channel.type, '•')} "
    line = f"{marks}{icon}{channel_label(channel, mentions=mentions)}"
    if isinstance(channel, discord.VoiceChannel | discord.StageChannel) and channel.members:
        line += f" · {plural(len(channel.members)):connected}"
    lines = [line]
    shown = sorted(threads, key=lambda thread: thread.name.casefold())[:THREADS_PER_CHANNEL]
    lines.extend(f"╰ {channel_label(thread, mentions=mentions)}" for thread in shown)
    if len(threads) > THREADS_PER_CHANNEL:
        lines.append(f"╰ +{len(threads) - THREADS_PER_CHANNEL} more")
    return lines


def channel_blocks(guild: discord.Guild, *, mentions: bool) -> list[Block]:
    """The sidebar: uncategorized channels first, then each category in position order, threads under their parent."""
    threads: dict[int, list[discord.Thread]] = {}
    for thread in guild.threads:
        if thread.parent_id is not None and not thread.archived:
            threads.setdefault(thread.parent_id, []).append(thread)
    blocks: list[Block] = []
    for category, channels in guild.by_category():
        lines: list[str] = []
        for channel in channels:
            lines.extend(channel_line(channel, threads.get(channel.id, ()), mentions=mentions))
        if not lines:
            continue
        header = f"**{_name(category.name).upper()}**" if category is not None else None
        blocks.append(Block(header, tuple(lines)))
    return blocks


def _status_dot(member: discord.Member) -> str:
    try:
        return Status[str(member.status)].value
    except KeyError:
        return Status.offline.value


def member_line(member: discord.Member, *, presences: bool) -> str:
    parts: list[str] = []
    if presences:
        parts.append(_status_dot(member))
    if member.id == member.guild.owner_id:
        parts.append("👑")
    parts.append(_name(member.display_name))
    if member.bot:
        parts.append("`APP`")
    return " ".join(parts)


def member_blocks(guild: discord.Guild, *, presences: bool, per_group: int = MEMBERS_PER_GROUP) -> list[Block]:
    """The member sidebar: hoisted roles top-down with a count each, then everyone else, capped per group."""
    grouped: dict[int | str, list[discord.Member]] = {}
    for member in guild.members:  # one pass; a big server notices anything more
        hoisted = next((role for role in reversed(member.roles) if role.hoist and not role.is_default()), None)
        if hoisted is not None:
            key: int | str = hoisted.id
        elif presences:
            key = "offline" if member.status is discord.Status.offline else "online"
        else:
            key = "members"
        grouped.setdefault(key, []).append(member)

    def order(member: discord.Member) -> tuple[int, str]:
        offline = presences and member.status is discord.Status.offline
        return (1 if offline else 0, member.display_name.casefold())

    blocks: list[Block] = []
    keys: list[tuple[int | str, str]] = [
        (role.id, _name(role.name).upper()) for role in reversed(guild.roles) if role.hoist and not role.is_default()
    ]
    keys.extend((("online", "ONLINE"), ("offline", "OFFLINE")) if presences else (("members", "MEMBERS"),))
    for key, title in keys:
        members = grouped.get(key)
        if not members:
            continue
        members.sort(key=order)
        lines = [member_line(member, presences=presences) for member in members[:per_group]]
        if len(members) > per_group:
            lines.append(f"+{len(members) - per_group:,} more")
        blocks.append(Block(f"**{title} · {len(members):,}**", tuple(lines)))
    return blocks


def role_line(role: discord.Role, count: int | None, *, mentions: bool) -> str:
    label = role.mention if mentions else f"**{_name(role.name)}**"
    parts = [f"{colour_square(role.colour)} {label}"]
    if count is not None:
        parts.append(f"{plural(count):member}")
    if role.hoist:
        parts.append("hoisted")
    if role.mentionable:
        parts.append("mentionable")
    if role.managed:
        parts.append("managed")
    if role.permissions.administrator:
        parts.append("admin")
    return " · ".join(parts)


def cached_role_counts(guild: discord.Guild) -> dict[int, int]:
    """Member counts per role from the member cache, in one pass rather than one per role."""
    counts: dict[int, int] = dict.fromkeys((role.id for role in guild.roles), 0)
    for member in guild.members:
        for role in member.roles:
            counts[role.id] = counts.get(role.id, 0) + 1
    return counts


def role_blocks(guild: discord.Guild, counts: Mapping[int, int], *, mentions: bool) -> list[Block]:
    """Every role but @everyone, top-down, with a member count each."""
    lines = [
        role_line(role, counts.get(role.id), mentions=mentions) for role in reversed(guild.roles) if not role.is_default()
    ]
    return [Block(None, tuple(lines))] if lines else []


@dataclass(frozen=True)
class MemberTally:
    total: int
    humans: int
    bots: int
    online: int | None  # None without the presences intent


def tally_members(guild: discord.Guild, *, presences: bool) -> MemberTally:
    bots = online = 0
    for member in guild.members:
        bots += member.bot
        if presences and member.status is not discord.Status.offline:
            online += 1
    cached = len(guild.members)
    total = guild.member_count or cached
    return MemberTally(total=total, humans=cached - bots, bots=bots, online=online if presences else None)


def overview_sections(
    guild: discord.Guild, tally: MemberTally, *, presences: bool, full_members: bool, shard_id: int | None
) -> list[str]:
    """The overview card's text sections, each a heading plus its lines."""
    owner = guild.owner
    owner_text = f"{_name(str(owner))} `{owner.id}`" if owner is not None else f"`{guild.owner_id}`"
    joined = guild.me.joined_at if guild.me is not None else None
    members = f"**Total:** `{tally.total:,}`\n**Humans:** `{tally.humans:,}` · **Bots:** `{tally.bots:,}`"
    if not full_members:
        members += " (from cache)"
    if tally.online is not None:
        members += f"\n**Online:** `{tally.online:,}`"
    kinds = {
        "text": len(guild.text_channels),
        "voice": len(guild.voice_channels),
        "stage": len(guild.stage_channels),
        "forum": len(guild.forums),
        "categories": len(guild.categories),
    }
    channels = " · ".join(f"`{count}` {kind}" for kind, count in kinds.items() if count)
    features = ", ".join(feature_names(guild.features)) or "none of note"
    sections = [
        f"### Owner\n{owner_text}",
        f"### Dates\n**Created:** {ts(guild.created_at):D} ({ts(guild.created_at):R})"
        + (f"\n**I joined:** {ts(joined):D} ({ts(joined):R})" if joined is not None else ""),
        f"### Members\n{members}",
        f"### Boosts\n**Level:** `{guild.premium_tier}` · **Boosts:** `{guild.premium_subscription_count or 0:,}`",
        f"### Channels\n{channels or 'none'}"
        f"\n**Roles:** `{len(guild.roles):,}`"
        f"\n**Emoji:** `{len(guild.emojis)}/{guild.emoji_limit}` · **Stickers:** `{len(guild.stickers)}/{guild.sticker_limit}`",
        f"### Settings\n**Verification:** {str(guild.verification_level).replace('_', ' ')}"
        f"\n**Content filter:** {str(guild.explicit_content_filter).replace('_', ' ')}"
        f"\n**Locale:** {guild.preferred_locale.value}"
        f"\n**Features:** {features}" + (f"\n**Shard:** `{shard_id}`" if shard_id is not None else ""),
    ]
    if not presences:
        sections[2] += "\n-# Presence unavailable"
    return sections


def guild_badge(guild: discord.Guild) -> str:
    if "VERIFIED" in guild.features:
        return " ✅"
    if "PARTNERED" in guild.features:
        return " 🤝"
    return ""


def parse_snowflake(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isdigit() and 15 <= len(value) <= 21 else None


def guild_choices(guilds: Sequence[discord.Guild], current: str, limit: int = 25) -> list[app_commands.Choice[str]]:
    """Servers matching the typed text by name or id, name first; the value is always the id."""
    wanted = current.casefold().strip()
    matches = [guild for guild in guilds if not wanted or wanted in guild.name.casefold() or wanted in str(guild.id)]
    matches.sort(key=lambda guild: guild.name.casefold())
    return [app_commands.Choice(name=f"{guild.name} ({guild.id})"[:100], value=str(guild.id)) for guild in matches[:limit]]
