"""Developer tools: the allowlist and pure viewer builders first, then the audit store against Postgres, then the
/dev cog driven offline on a real guild payload with fake interactions. Every path a non-owner could take is here."""

import datetime
import logging
from types import SimpleNamespace

import discord
import pytest
from conftest import requires_db
from discord import app_commands, ui
from discord.ext import commands
from test_brainrot_cog import BASE, BOT_ID, NOW, user

import config
from exts.dev import ConfirmShareView, Developer, InsightsView, ServerView, ShareButton, TextView
from exts.errorhandler import ErrorHandler
from exts.stats import Stats
from exts.utils.charts import Chart
from exts.utils.devtools import (
    MEMBERS_PER_GROUP,
    THREADS_PER_CHANNEL,
    AuditStore,
    Block,
    NotDevOwner,
    TableSize,
    cached_role_counts,
    channel_blocks,
    colour_square,
    feature_names,
    guild_choices,
    human_size,
    is_dev_owner,
    lifetime_section,
    member_blocks,
    overview_sections,
    owner_ids,
    paginate_blocks,
    parse_snowflake,
    render_page,
    role_blocks,
    storage_sections,
    tally_members,
)
from exts.utils.help import build_index
from exts.utils.search import SearchTotal, search_query
from exts.utils.stats import (
    ChannelCount,
    CommandCount,
    DayCount,
    Footprint,
    GuildActivity,
    GuildFootprint,
    HourCount,
    JoinLeave,
    MemberActivity,
    MemberRank,
)

GUILD_ID = BASE + 500
OTHER_GUILD_ID = BASE + 501
OWNER_ID = BASE + 2
MOD_ID = BASE + 3
USER_ID = BASE + 4
STRANGER_ID = BASE + 77
EVERYONE = GUILD_ID
MEMBERS_ROLE = BASE + 600
MODS_ROLE = BASE + 601
ADMIN_ROLE = BASE + 602
BOT_ROLE = BASE + 603
TEXT_CATEGORY = BASE + 700
VOICE_CATEGORY = BASE + 701
GENERAL = BASE + 710
SECRET = BASE + 711
NEWS = BASE + 712
WELCOME = BASE + 713
LOUNGE = BASE + 714
STAGE = BASE + 715
FORUM = BASE + 716
MEDIA = BASE + 717
VIEW_CHANNEL = discord.Permissions(view_channel=True).value


def role(role_id: int, name: str, position: int, **extra) -> dict:
    return {
        "id": str(role_id),
        "name": name,
        "color": 0,
        "hoist": False,
        "position": position,
        "permissions": "0",
        "managed": False,
        "mentionable": False,
    } | extra


def member(user_id: int, name: str, roles: list[int], bot: bool = False) -> dict:
    return {
        "user": user(user_id, name, bot),
        "roles": [str(r) for r in roles],
        "joined_at": NOW,
        "deaf": False,
        "mute": False,
        "flags": 0,
    }


def channel(channel_id: int, name: str, kind: int, position: int, parent: int | None = None, **extra) -> dict:
    data = {
        "id": str(channel_id),
        "type": kind,
        "name": name,
        "position": position,
        "permission_overwrites": [],
        "nsfw": False,
    }
    if parent is not None:
        data["parent_id"] = str(parent)
    if kind in (2, 13):
        data |= {"bitrate": 64000, "user_limit": 0}
    if kind in (15, 16):
        data |= {"available_tags": [], "default_reaction_emoji": None, "default_sort_order": None}
    return data | extra


def thread(thread_id: int, name: str, parent: int, archived: bool = False) -> dict:
    return {
        "id": str(thread_id),
        "type": 11,
        "name": name,
        "parent_id": str(parent),
        "owner_id": str(USER_ID),
        "guild_id": str(GUILD_ID),
        "message_count": 0,
        "member_count": 1,
        "rate_limit_per_user": 0,
        "thread_metadata": {"archived": archived, "auto_archive_duration": 60, "archive_timestamp": NOW, "locked": False},
    }


def presence(user_id: int, status: str) -> dict:
    return {"user": {"id": str(user_id)}, "status": status, "activities": [], "client_status": {}}


def viewer_guild_payload(guild_id: int = GUILD_ID) -> dict:
    extras = [member(BASE + 1000 + i, f"member{i:02d}", [MEMBERS_ROLE]) for i in range(MEMBERS_PER_GROUP + 4)]
    deny_everyone = [{"id": str(guild_id), "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)}]
    return {
        "id": str(guild_id),
        "name": "Spork Lab",
        "owner_id": str(OWNER_ID),
        "roles": [
            role(guild_id, "@everyone", 0),
            role(MEMBERS_ROLE, "Members", 1),
            role(MODS_ROLE, "Mods", 2, hoist=True, mentionable=True, colors={"primary_color": 0x3498DB}),
            role(ADMIN_ROLE, "Admin", 3, hoist=True, permissions=str(discord.Permissions(administrator=True).value)),
            role(BOT_ROLE, "Spork", 4, managed=True, permissions=str(discord.Permissions.all().value)),
        ],
        "members": [
            member(BOT_ID, "spork", [BOT_ROLE], bot=True),
            member(OWNER_ID, "owner", [ADMIN_ROLE]),
            member(MOD_ID, "mod", [MODS_ROLE, MEMBERS_ROLE]),
            member(USER_ID, "user", [MEMBERS_ROLE]),
            *extras,
        ],
        "channels": [
            channel(TEXT_CATEGORY, "Text", 4, 0),
            channel(VOICE_CATEGORY, "Voice", 4, 1),
            channel(WELCOME, "welcome", 0, 0),
            channel(GENERAL, "general", 0, 0, TEXT_CATEGORY),
            channel(SECRET, "secret", 0, 1, TEXT_CATEGORY, permission_overwrites=deny_everyone),
            channel(NEWS, "announcements", 5, 2, TEXT_CATEGORY),
            channel(LOUNGE, "Lounge", 2, 0, VOICE_CATEGORY),
            channel(STAGE, "Stage", 13, 1, VOICE_CATEGORY),
            channel(FORUM, "forum", 15, 3, TEXT_CATEGORY),
            channel(MEDIA, "media", 16, 4, TEXT_CATEGORY, nsfw=True),
        ],
        "threads": [
            *(thread(BASE + 800 + i, f"thread{i}", GENERAL) for i in range(THREADS_PER_CHANNEL + 2)),
            thread(BASE + 899, "old", GENERAL, archived=True),
        ],
        "member_count": 4 + len(extras),
        "large": False,
        "unavailable": False,
        "features": ["COMMUNITY", "DISCOVERABLE", "SOMETHING_NEW"],
        "emojis": [],
        "stickers": [],
        "verification_level": 2,
        "default_message_notifications": 0,
        "explicit_content_filter": 2,
        "mfa_level": 0,
        "nsfw_level": 0,
        "premium_tier": 1,
        "premium_subscription_count": 3,
        "afk_timeout": 300,
        "system_channel_flags": 0,
        "preferred_locale": "en-GB",
        "voice_states": [
            {
                "user_id": str(MOD_ID),
                "channel_id": str(LOUNGE),
                "session_id": "s",
                "deaf": False,
                "mute": False,
                "self_deaf": False,
                "self_mute": False,
                "self_video": False,
                "suppress": False,
            }
        ],
        "presences": [
            presence(OWNER_ID, "online"),
            presence(MOD_ID, "idle"),
            presence(USER_ID, "offline"),
            presence(BOT_ID, "online"),
        ],
    }


# the allowlist


def test_owner_allowlist_is_pinned_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(config, "DEV_OWNER_IDS", raising=False)
    assert owner_ids() == frozenset({739219467455823921})
    assert is_dev_owner(739219467455823921) and not is_dev_owner(OWNER_ID)

    monkeypatch.setattr(config, "DEV_OWNER_IDS", {OWNER_ID, "123"}, raising=False)
    assert is_dev_owner(OWNER_ID) and is_dev_owner(123) and not is_dev_owner(739219467455823921)

    monkeypatch.setattr(config, "DEV_OWNER_IDS", set(), raising=False)
    assert not is_dev_owner(OWNER_ID) and not is_dev_owner(739219467455823921)

    monkeypatch.setattr(config, "DEV_OWNER_IDS", "not a set of ids", raising=False)
    assert not is_dev_owner(OWNER_ID)


# pure builders


def test_pagination_packs_blocks_and_continues_oversized_ones() -> None:
    assert paginate_blocks([]) == [[]] and render_page([]) == "Nothing here."
    small = [Block(f"**H{i}**", ("aaaa", "bbbb")) for i in range(4)]
    pages = paginate_blocks(small, budget=40)
    assert [len(page) for page in pages] == [2, 2]
    assert all(len(render_page(page)) <= 40 for page in pages)

    long_lines = tuple(f"line {i:03d}" for i in range(20))  # 8 chars each
    pages = paginate_blocks([Block("**BIG**", long_lines)], budget=50)
    assert len(pages) > 1
    assert pages[0][0].header == "**BIG**" and pages[1][0].header == "**BIG** (cont.)"
    rendered = [line for page in pages for block in page for line in block.lines]
    assert rendered == list(long_lines)  # every line intact and in order
    assert all(len(render_page(page)) <= 50 for page in pages)


def test_colour_squares_features_snowflakes_and_choices() -> None:
    assert colour_square(discord.Colour.default()) == "⬛"
    assert colour_square(discord.Colour.blue()) == "🟦" and colour_square(discord.Colour.red()) == "🟥"
    assert colour_square(discord.Colour.light_grey()) == "⬜" and colour_square(discord.Colour.from_rgb(101, 67, 33)) == "🟫"
    assert feature_names(["DISCOVERABLE", "COMMUNITY", "MYSTERY"]) == ["community", "discoverable"]
    assert parse_snowflake(" 739219467455823921 ") == 739219467455823921
    assert parse_snowflake("12") is None and parse_snowflake("abc") is None and parse_snowflake("1" * 22) is None

    guilds = [SimpleNamespace(id=BASE + i, name=name) for i, name in enumerate(["Zeta", "alpha", "Alpine", "beta"])]
    assert [choice.name for choice in guild_choices(guilds, "alp")] == [f"alpha ({BASE + 1})", f"Alpine ({BASE + 2})"]
    assert guild_choices(guilds, str(BASE + 3))[0].value == str(BASE + 3)
    assert len(guild_choices(guilds, "")) == 4 and len(guild_choices(guilds * 10, "")) == 25


@pytest.fixture
def guild() -> discord.Guild:
    intents = discord.Intents(guilds=True, members=True, presences=True, voice_states=True)
    bot = commands.Bot(command_prefix="t,", intents=intents)
    state = bot._connection
    state.user = discord.ClientUser(
        state=state, data=user(BOT_ID, "spork", bot=True) | {"verified": True, "mfa_enabled": False}
    )
    state.parse_guild_create(viewer_guild_payload())
    found = bot.get_guild(GUILD_ID)
    assert found is not None and found.chunked
    return found


def test_channel_sidebar(guild: discord.Guild) -> None:
    blocks = channel_blocks(guild, mentions=False)
    assert blocks[0].header is None and blocks[0].lines == ("# welcome",)
    text, voice = blocks[1], blocks[2]
    assert text.header == "**TEXT**" and voice.header == "**VOICE**"
    assert text.lines[0] == "# general"
    assert text.lines[1 : THREADS_PER_CHANNEL + 1] == tuple(f"╰ thread{i}" for i in range(THREADS_PER_CHANNEL))
    assert text.lines[THREADS_PER_CHANNEL + 1] == "╰ +2 more" and "old" not in text.text
    assert "🔒# secret" in text.lines and "📢 announcements" in text.lines
    assert "💬 forum" in text.lines and "🔞🖼️ media" in text.lines
    assert voice.lines == ("🔊 Lounge · 1 connected", "🎙️ Stage")

    mentioned = channel_blocks(guild, mentions=True)
    assert mentioned[1].lines[0] == f"<#{GENERAL}>" and f"<#{BASE + 800}>" in mentioned[1].lines[1]


def test_member_sidebar_groups_by_hoisted_role_and_caps(guild: discord.Guild) -> None:
    blocks = member_blocks(guild, presences=True, per_group=MEMBERS_PER_GROUP)
    assert [block.header for block in blocks] == [
        "**ADMIN · 1**",
        "**MODS · 1**",
        "**ONLINE · 1**",
        f"**OFFLINE · {MEMBERS_PER_GROUP + 5}**",
    ]
    assert blocks[0].lines[0].endswith("👑 owner") and blocks[1].lines[0].endswith(" mod")
    assert blocks[2].lines[0].endswith("spork `APP`")
    offline = blocks[3]
    assert len(offline.lines) == MEMBERS_PER_GROUP + 1 and offline.lines[-1] == "+5 more"
    assert offline.lines[0].endswith(" member00")

    plain = member_blocks(guild, presences=False)
    assert [block.header for block in plain] == ["**ADMIN · 1**", "**MODS · 1**", f"**MEMBERS · {MEMBERS_PER_GROUP + 6}**"]
    assert plain[0].lines == ("👑 owner",) and "<:" not in plain[0].lines[0]


def test_roles_view_lists_top_down_with_markers(guild: discord.Guild) -> None:
    counts = {MODS_ROLE: 4, ADMIN_ROLE: 1}
    blocks = role_blocks(guild, counts, mentions=False)
    lines = blocks[0].lines
    assert lines[0] == "⬛ **Spork** · managed · admin"
    assert lines[1] == "⬛ **Admin** · 1 member · hoisted · admin"
    assert lines[2] == "🟦 **Mods** · 4 members · hoisted · mentionable"
    assert lines[3] == "⬛ **Members**" and len(lines) == 4  # @everyone is not a line

    mentioned = role_blocks(guild, cached_role_counts(guild), mentions=True)[0].lines
    assert mentioned[2].startswith(f"🟦 <@&{MODS_ROLE}> · 1 member")  # cache counts when the api ones are missing
    assert (
        cached_role_counts(guild)[MEMBERS_ROLE] == MEMBERS_PER_GROUP + 6
        and cached_role_counts(guild)[GUILD_ID] == MEMBERS_PER_GROUP + 8
    )


def test_overview_sections_and_tally(guild: discord.Guild) -> None:
    tally = tally_members(guild, presences=True)
    assert (tally.total, tally.humans, tally.bots, tally.online) == (MEMBERS_PER_GROUP + 8, MEMBERS_PER_GROUP + 7, 1, 3)
    assert tally_members(guild, presences=False).online is None

    sections = overview_sections(guild, tally, presences=True, full_members=True, shard_id=None)
    assert sections[0] == f"### Owner\nowner `{OWNER_ID}`"
    assert "**Created:** <t:" in sections[1] and "**I joined:** <t:" in sections[1]
    assert f"**Total:** `{MEMBERS_PER_GROUP + 8}`" in sections[2] and "**Online:** `3`" in sections[2]
    assert "**Level:** `1` · **Boosts:** `3`" in sections[3]
    assert "`4` text · `1` voice · `1` stage · `2` forum · `2` categories" in sections[4]  # media counts as a forum
    assert "**Verification:** medium" in sections[5] and "**Content filter:** all members" in sections[5]
    assert "**Locale:** en-GB" in sections[5] and "**Features:** community, discoverable" in sections[5]
    assert "Shard" not in sections[5] and "Presence unavailable" not in "".join(sections)

    degraded = overview_sections(
        guild, tally_members(guild, presences=False), presences=False, full_members=False, shard_id=2
    )
    assert "(from cache)" in degraded[2] and "Presence unavailable" in degraded[2] and "**Shard:** `2`" in degraded[5]


# the audit store


@pytest.fixture
async def audit(pool) -> AuditStore:
    await pool.execute("TRUNCATE dev_audit")
    return AuditStore(pool)


@requires_db
async def test_audit_rows_come_back_newest_first_and_clamped(audit: AuditStore) -> None:
    first = await audit.log(OWNER_ID, "dev server view", guild_id=GUILD_ID)
    await audit.log(OWNER_ID, "share", guild_id=GUILD_ID, channel_id=GENERAL)
    last = await audit.log(OWNER_ID, "dev purge", target_user_id=USER_ID)

    entries = await audit.recent(10)
    assert [entry.command for entry in entries] == ["dev purge", "share", "dev server view"]
    assert entries[0].id == last.id and entries[-1].id == first.id
    assert entries[0].target_user_id == USER_ID and entries[1].channel_id == GENERAL and entries[2].guild_id == GUILD_ID
    assert "shared to" in entries[1].line and f"user `{USER_ID}`" in entries[0].line
    assert len(await audit.recent(2)) == 2 and len(await audit.recent(999)) == 3 and len(await audit.recent(0)) == 1


# the cog, offline


class FakeResponse:
    def __init__(self, interaction: "FakeInteraction") -> None:
        self.interaction = interaction
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, content=None, *, view=None, files=(), ephemeral=False, allowed_mentions=None):
        if not ephemeral and self.interaction.refuse_public:
            raise discord.HTTPException(
                SimpleNamespace(status=403, reason="Forbidden"), {"message": "Missing Access", "code": 50001}
            )
        self.done = True
        sent = [] if files is discord.utils.MISSING else list(files)
        self.interaction.calls.append(("send", content, view, sent, ephemeral))
        return SimpleNamespace(is_ephemeral=ephemeral or self.interaction.forced_ephemeral)

    async def edit_message(self, *, view=None):
        self.done = True
        self.interaction.calls.append(("edit", None, view, [], True))

    async def defer(self, *, ephemeral=False, thinking=False):
        self.done = True
        self.interaction.calls.append(("defer", None, None, [], ephemeral))


class FakeInteraction:
    def __init__(
        self,
        user_id: int,
        guild_id: int | None = GUILD_ID,
        channel=None,
        *,
        forced_ephemeral: bool = False,
        refuse_public: bool = False,
    ) -> None:
        self.user = SimpleNamespace(id=user_id, display_name="jaden")
        self.guild_id = guild_id
        self.channel = channel
        self.channel_id = channel.id if channel is not None else None
        self.calls: list[tuple] = []
        self.forced_ephemeral = forced_ephemeral
        self.refuse_public = refuse_public
        self.response = FakeResponse(self)
        self.followup = SimpleNamespace(send=self._followup)
        self.command = None

    async def _followup(self, content=None, *, view=None, files=(), ephemeral=False, allowed_mentions=None, wait=False):
        sent = [] if files is discord.utils.MISSING else list(files)
        self.calls.append(("followup", content, view, sent, ephemeral))

    async def edit_original_response(self, *, view=None):
        self.calls.append(("edit_original", None, view, [], True))

    @property
    def sent(self) -> list[tuple]:
        return [call for call in self.calls if call[0] in ("send", "followup")]


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def log(self, user_id, command, *, guild_id=None, target_user_id=None, channel_id=None):
        self.rows.append(
            {
                "user_id": user_id,
                "command": command,
                "guild_id": guild_id,
                "target_user_id": target_user_id,
                "channel_id": channel_id,
            }
        )
        return SimpleNamespace(id=len(self.rows))

    async def recent(self, limit=25):
        return tuple(SimpleNamespace(line=f"`{row['command']}`", **row) for row in reversed(self.rows[-limit:]))


DEPARTED_GUILD_ID = BASE + 777


class FakeStatsStore:
    def __init__(self) -> None:
        self.purged: list[tuple[int, int | None]] = []

    async def disabled_guilds(self) -> set[int]:
        return set()

    async def footprint(self, limit: int = 8) -> Footprint:
        return Footprint(
            guilds=(GuildFootprint(GUILD_ID, 1200, 40), GuildFootprint(DEPARTED_GUILD_ID, 30, 1)),
            servers=3,
            people=42,
            oldest_day=datetime.date(2026, 9, 16),
        )

    async def purge_user(self, user_id: int, guild_id: int | None = None) -> int:
        self.purged.append((user_id, guild_id))
        return 7


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(config, "DEV_OWNER_IDS", {OWNER_ID}, raising=False)
    monkeypatch.setattr(config, "DEV_LOG_CHANNEL_ID", 0, raising=False)
    intents = discord.Intents(
        guilds=True, members=True, presences=True, voice_states=True, message_content=True, messages=True
    )
    bot = commands.Bot(command_prefix="t,", intents=intents)
    await bot._async_setup_hook()
    state = bot._connection
    state.user = discord.ClientUser(
        state=state, data=user(BOT_ID, "spork", bot=True) | {"verified": True, "mfa_enabled": False}
    )
    state.parse_guild_create(viewer_guild_payload())
    other = viewer_guild_payload(OTHER_GUILD_ID) | {"name": "Elsewhere"}
    state.parse_guild_create(other)
    guild = bot.get_guild(GUILD_ID)
    assert guild is not None

    bot.pool = None
    cog = Developer(bot)
    cog.audit = FakeAudit()  # type: ignore[assignment] — in-memory stand-in
    await bot.add_cog(cog)
    stats = Stats(bot)
    stats.store = FakeStatsStore()  # type: ignore[assignment] — in-memory stand-in
    await bot.add_cog(stats)
    stats.flush.cancel()
    stats.cleanup.cancel()

    def command(name: str) -> app_commands.Command:
        found = bot.tree.get_command(name.split(" ")[0])
        for part in name.split(" ")[1:]:
            found = found.get_command(part)
        assert isinstance(found, app_commands.Command)
        return found

    try:
        yield SimpleNamespace(
            bot=bot, cog=cog, guild=guild, other=bot.get_guild(OTHER_GUILD_ID), stats=stats, command=command
        )
    finally:
        await bot.remove_cog(cog.qualified_name)
        await bot.remove_cog(stats.qualified_name)
        await bot.close()


def card_text(view: ui.LayoutView) -> str:
    return "\n".join(item.content for item in view.walk_children() if isinstance(item, ui.TextDisplay))


def buttons(view: ui.LayoutView) -> list[ui.Button]:
    return [item for item in view.walk_children() if isinstance(item, ui.Button)]


async def test_dev_is_user_install_only_and_hidden_from_help(rig: SimpleNamespace) -> None:
    root = rig.bot.tree.get_command("dev")
    assert isinstance(root, app_commands.Group)
    payload = root.to_dict(rig.bot.tree)
    assert payload["integration_types"] == [1] and payload["contexts"] == [0, 1, 2]
    assert root.description == "Developer tools" and root.extras == {"hidden": True}
    for name in ("dev server view", "dev audit", "dev purge"):
        assert rig.command(name).checks, f"{name} has no explicit owner check"
    assert not any(cmd.cog is rig.cog for cmd in rig.bot.walk_commands() if cmd.name != "sync")  # no prefix or hybrid twin

    index = build_index(rig.bot, {}, "t,")
    assert not any(entry.name.startswith("dev") for entry in index.entries)
    # the same index feeds the dashboard's command list, so the owner-only prefix command stays out of it too
    assert rig.bot.get_command("sync").hidden and "Developer" not in [category.name for category in index.categories]


async def test_every_entry_point_refuses_a_stranger(rig: SimpleNamespace, caplog: pytest.LogCaptureFixture) -> None:
    stranger = FakeInteraction(STRANGER_ID)
    view_command = rig.command("dev server view")
    assert await view_command._check_can_run(stranger) is False  # the cog-level check
    with pytest.raises(NotDevOwner):
        await view_command.checks[0](stranger)  # the explicit per-command one help consults

    await rig.cog.cog_app_command_error(stranger, app_commands.CheckFailure("nope"))
    assert stranger.sent == [("send", "Not available.", None, [], True)]

    assert await rig.cog.guild_autocomplete(stranger, "") == []
    owner = FakeInteraction(OWNER_ID)
    assert [choice.value for choice in await rig.cog.guild_autocomplete(owner, "lab")] == [str(GUILD_ID)]

    view = ServerView(rig.cog, rig.guild, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    assert await view.interaction_check(stranger) is False and stranger.sent[-1][1] == "Not available."
    assert await view.interaction_check(FakeInteraction(MOD_ID)) is False
    assert await view.interaction_check(owner) is True

    handler = ErrorHandler(rig.bot)
    with caplog.at_level(logging.INFO):
        await handler.on_app_command_error(stranger, app_commands.CheckFailure("nope"))
    assert caplog.records and all(record.levelno == logging.INFO for record in caplog.records)


async def test_server_view_opens_ephemeral_with_audit_and_navigates(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev server view").callback(rig.cog, interaction, None)
    kind, content, view, files, ephemeral = interaction.calls[0]
    assert kind == "send" and ephemeral and content is None and files == []
    assert isinstance(view, ServerView) and view.interaction is interaction
    assert rig.cog.audit.rows == [
        {"user_id": OWNER_ID, "command": "dev server view", "guild_id": GUILD_ID, "target_user_id": None, "channel_id": None}
    ]

    text = card_text(view)
    assert text.startswith("# Spork Lab\n`") and "### Owner" in text and f"Guild ID: {GUILD_ID}" in text
    assert any(isinstance(item, ui.Section) for item in view.walk_children()) is False  # no icon, so a plain title
    assert [button.label for button in buttons(view)] == ["Prev", "Next", "Share to chat", "Open"]
    assert buttons(view)[-1].url == f"https://discord.com/channels/{GUILD_ID}"
    assert view.mentions is True

    view.show("channels")
    assert f"<#{GENERAL}>" in card_text(view) and "### Channels" in card_text(view)
    view.show("members")
    assert "**ADMIN · 1**" in card_text(view) and "Member list partial" not in card_text(view)
    view.show("roles")
    assert f"<@&{MODS_ROLE}>" in card_text(view) and "Counts from cache" in card_text(view)

    # the select fetches role counts once, through the cache
    calls: list[int] = []

    async def role_member_counts(self):
        calls.append(1)
        return {rig.guild.get_role(MODS_ROLE): 9, discord.Object(id=1): 3}

    monkeypatch.setattr(discord.Guild, "role_member_counts", role_member_counts)
    select = next(item for item in view.walk_children() if isinstance(item, ui.Select))
    select._values = ["roles"]
    pick = FakeInteraction(OWNER_ID)
    await select.callback(pick)
    assert pick.calls[0][0] == "defer" and pick.calls[1][0] == "edit_original"
    assert "9 members" in card_text(view) and "Counts from cache" not in card_text(view)
    assert await rig.cog.role_counts(rig.guild) == {MODS_ROLE: 9, 1: 3} and calls == [1]


async def test_viewer_uses_plain_names_for_another_server_and_paginates(rig: SimpleNamespace) -> None:
    view = ServerView(rig.cog, rig.other, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    assert view.mentions is False
    view.show("channels")
    assert "<#" not in card_text(view) and "# general" in card_text(view)
    view.show("roles")
    assert "<@&" not in card_text(view) and "**Mods**" in card_text(view)

    view._pages["members"] = [[Block("**A**", ("one",))], [Block("**B**", ("two",))], [Block("**C**", ("three",))]]
    view.show("members")
    assert "page 1/3" in card_text(view) and "one" in card_text(view)
    prev, nxt = buttons(view)[:2]
    assert prev.disabled and not nxt.disabled
    click = FakeInteraction(OWNER_ID)
    await nxt.callback(click)
    assert click.calls[0][0] == "edit" and "page 2/3" in card_text(view) and "two" in card_text(view)
    view.page = 99
    view.render()
    assert "page 3/3" in card_text(view)


async def test_missing_intents_degrade_quietly(rig: SimpleNamespace) -> None:
    rig.bot._connection._intents = discord.Intents(guilds=True)
    view = ServerView(rig.cog, rig.guild, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    assert "Presence unavailable" in card_text(view) and "(from cache)" in card_text(view)
    view.show("members")
    text = card_text(view)
    assert "Member list partial" in text and "Presence unavailable" in text and "**MEMBERS ·" in text and "<:" not in text


async def test_share_in_the_same_server_posts_a_static_snapshot(rig: SimpleNamespace) -> None:
    channel = rig.guild.get_channel(GENERAL)
    view = ServerView(rig.cog, rig.guild, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    view.show("channels")
    share = next(button for button in buttons(view) if isinstance(button, ShareButton))
    click = FakeInteraction(OWNER_ID, channel=channel)
    await share.callback(click)

    kind, content, snapshot, _files, ephemeral = click.calls[0]
    assert kind == "send" and not ephemeral and content is None
    assert (
        not isinstance(snapshot, ServerView)
        and buttons(snapshot) == []
        and not any(isinstance(i, ui.Select) for i in snapshot.walk_children())
    )
    text = card_text(snapshot)
    assert "### Channels" in text and text.endswith("-# Shared by jaden")
    assert len(click.calls) == 1  # no confirm, no complaint
    assert rig.cog.audit.rows[-1] == {
        "user_id": OWNER_ID,
        "command": "share",
        "guild_id": GUILD_ID,
        "target_user_id": None,
        "channel_id": GENERAL,
    }


async def test_cross_server_and_sensitive_shares_confirm_first(rig: SimpleNamespace) -> None:
    channel = rig.guild.get_channel(GENERAL)
    view = ServerView(rig.cog, rig.other, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    click = FakeInteraction(OWNER_ID, channel=channel)
    await rig.cog.share(click, view)
    kind, _, confirm, _, ephemeral = click.calls[0]
    assert kind == "send" and ephemeral and isinstance(confirm, ConfirmShareView)
    assert card_text(confirm) == f"This posts info about **Elsewhere** in <#{GENERAL}>. Share?"
    assert confirm.interaction is click

    _yes, no = buttons(confirm)
    cancel = FakeInteraction(OWNER_ID, channel=channel)
    await no.callback(cancel)
    assert cancel.calls[0][0] == "edit" and card_text(cancel.calls[0][2]) == "Not shared."

    confirm = ConfirmShareView(rig.cog, view, "again?")
    confirm.interaction = click
    go = FakeInteraction(OWNER_ID, channel=channel)
    await buttons(confirm)[0].callback(go)
    assert go.calls[0][0] == "send" and not go.calls[0][4] and card_text(go.calls[0][2]).endswith("-# Shared by jaden")
    assert card_text(click.calls[-1][2]) == "Shared." and rig.cog.audit.rows[-1]["command"] == "share"

    audit_view = TextView(
        rig.cog,
        ["### x\ny"],
        "f",
        invoker_id=OWNER_ID,
        subject="the dev audit log",
        subject_guild_id=None,
        sensitive=True,
        accent=discord.Colour.blue(),
    )
    assert audit_view.needs_confirm(FakeInteraction(OWNER_ID, guild_id=None)) is True
    dm = FakeInteraction(OWNER_ID, guild_id=None, channel=SimpleNamespace(id=1))
    await rig.cog.share(dm, audit_view)
    assert "in this DM. Share?" in card_text(dm.calls[0][2])

    # a stranger can't press the confirm buttons either
    assert await confirm.interaction_check(FakeInteraction(STRANGER_ID)) is False


async def test_share_failures_leave_the_card_and_explain(rig: SimpleNamespace) -> None:
    channel = rig.guild.get_channel(GENERAL)
    view = ServerView(rig.cog, rig.guild, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)

    refused = FakeInteraction(OWNER_ID, channel=channel, refuse_public=True)
    await rig.cog.post_snapshot(refused, view)
    assert refused.sent == [("send", "Discord wouldn't let me post that here (Missing Access).", None, [], True)]
    assert not any(row["command"] == "share" for row in rig.cog.audit.rows)

    forced = FakeInteraction(OWNER_ID, channel=channel, forced_ephemeral=True)
    await rig.cog.post_snapshot(forced, view)
    assert forced.calls[0][0] == "send" and forced.calls[0][4] is False
    assert forced.calls[1][0] == "followup" and "Use External Apps" in forced.calls[1][1] and forced.calls[1][4] is True
    assert rig.cog.audit.rows[-1]["command"] == "share"


async def test_timeout_disables_everything_including_share(rig: SimpleNamespace) -> None:
    view = ServerView(rig.cog, rig.guild, invoker_id=OWNER_ID, origin_guild_id=GUILD_ID)
    interaction = FakeInteraction(OWNER_ID)
    view.interaction = interaction
    await view.on_timeout()
    assert interaction.calls == [("edit_original", None, view, [], True)]
    assert all(button.disabled for button in buttons(view) if button.url is None)
    assert all(item.disabled for item in view.walk_children() if isinstance(item, ui.Select))


async def test_guild_targeting(rig: SimpleNamespace) -> None:
    assert rig.cog.target_guild(FakeInteraction(OWNER_ID), None) is rig.guild
    assert rig.cog.target_guild(FakeInteraction(OWNER_ID, guild_id=None), None) is None
    assert rig.cog.target_guild(FakeInteraction(OWNER_ID, guild_id=BASE + 999), None) is None  # a server without the bot
    assert rig.cog.target_guild(FakeInteraction(OWNER_ID), str(OTHER_GUILD_ID)) is rig.other
    assert rig.cog.target_guild(FakeInteraction(OWNER_ID), "nonsense") is None

    dm = FakeInteraction(OWNER_ID, guild_id=None)
    await rig.command("dev server view").callback(rig.cog, dm, None)
    assert dm.sent == [("send", "Pick a server I'm in — `guild` is required here.", None, [], True)]
    assert rig.cog.audit.rows == []

    await rig.command("dev server view").callback(rig.cog, dm, str(OTHER_GUILD_ID))
    assert (
        isinstance(dm.calls[-1][2], ServerView) and dm.calls[-1][2].guild is rig.other and dm.calls[-1][2].mentions is False
    )


async def test_audit_and_purge_commands(rig: SimpleNamespace) -> None:
    await rig.cog.audit.log(OWNER_ID, "dev server view", guild_id=GUILD_ID)
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev audit").callback(rig.cog, interaction, 5)
    view = interaction.calls[0][2]
    assert isinstance(view, TextView) and interaction.calls[0][4] is True and view.sensitive
    text = card_text(view)
    assert "### Dev tool usage" in text and "`dev server view`" in text and "`dev audit`" in text and "2 entries" in text

    purge = FakeInteraction(OWNER_ID)
    await rig.command("dev purge").callback(rig.cog, purge, str(USER_ID), None)
    assert rig.stats.store.purged == [(USER_ID, None)]
    assert "Deleted 7 rows" in card_text(purge.calls[0][2]) and "everywhere" in card_text(purge.calls[0][2])
    assert rig.cog.audit.rows[-1] == {
        "user_id": OWNER_ID,
        "command": "dev purge",
        "guild_id": None,
        "target_user_id": USER_ID,
        "channel_id": None,
    }

    scoped = FakeInteraction(OWNER_ID)
    await rig.command("dev purge").callback(rig.cog, scoped, str(USER_ID), str(OTHER_GUILD_ID))
    assert rig.stats.store.purged[-1] == (USER_ID, OTHER_GUILD_ID) and "in **Elsewhere**" in card_text(scoped.calls[0][2])

    bad = FakeInteraction(OWNER_ID)
    await rig.command("dev purge").callback(rig.cog, bad, "12", None)
    assert bad.sent == [("send", "That doesn't look like a user id.", None, [], True)]
    gone = FakeInteraction(OWNER_ID)
    await rig.command("dev purge").callback(rig.cog, gone, str(USER_ID), "999")
    assert gone.sent[0][1] == "I'm not in that server."


async def test_dev_log_channel_gets_one_line(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict] = []

    class Channel(discord.abc.Messageable):
        id = 1

        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            posted.append(kwargs)

    log_channel = Channel()
    monkeypatch.setattr(config, "DEV_LOG_CHANNEL_ID", 1, raising=False)
    monkeypatch.setattr(rig.bot, "get_channel", lambda channel_id: log_channel if channel_id == 1 else None)
    await rig.cog.record(FakeInteraction(OWNER_ID), "dev server view", guild_id=GUILD_ID, channel_id=GENERAL)
    assert (
        len(posted) == 1
        and card_text(posted[0]["view"])
        == f"`dev server view` · by `{OWNER_ID}` · guild `{GUILD_ID}` · shared to `{GENERAL}`"
    )
    assert posted[0]["allowed_mentions"].everyone is False


# insights: the commands over a fake stats store and a stubbed renderer


def guild_activity_for(guild_id: int, span, *, tracking_since=None):
    return GuildActivity(
        guild_id=guild_id,
        span=span,
        tracking_since=tracking_since,
        messages=tuple(DayCount(day, 5) for day in span),
        active_users=tuple(DayCount(day, 2) for day in span),
        joins_leaves=tuple(JoinLeave(day, 1, 0) for day in span),
        hours=tuple(HourCount(hour, hour) for hour in range(24)),
        top_channels=(ChannelCount(GENERAL, 90), ChannelCount(BASE + 9999, 1)),
    )


class FakeInsightsStore(FakeStatsStore):
    def __init__(self) -> None:
        super().__init__()
        self.tracking: dict[int, datetime.datetime | None] = {}
        self.calls: list[tuple] = []

    async def guild_activity(self, guild_id: int, span) -> GuildActivity:
        self.calls.append(("guild", guild_id, span.days))
        return guild_activity_for(guild_id, span, tracking_since=self.tracking.get(guild_id))

    async def member_activity(self, guild_id: int, user_id: int, span) -> MemberActivity:
        self.calls.append(("member", guild_id, user_id, span.days))
        rank = MemberRank(rank=1, ranked=4, messages=12) if user_id == MOD_ID else None
        return MemberActivity(
            guild_id=guild_id,
            user_id=user_id,
            span=span,
            tracking_since=self.tracking.get(guild_id),
            messages=tuple(DayCount(day, 1) for day in span),
            hours=tuple(HourCount(hour, 0) for hour in range(24)),
            top_channels=(ChannelCount(GENERAL, 12),),
            top_commands=(CommandCount("help", 3),),
            rank=rank,
        )


@pytest.fixture
async def insights(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    store = FakeInsightsStore()
    rig.stats.store = store
    renders: list[Chart] = []

    def fake_render(chart: Chart) -> bytes:
        renders.append(chart)
        return b"png-bytes"

    monkeypatch.setattr("exts.dev.render_chart", fake_render)
    fetched: list[int] = []

    async def fetch_user(user_id: int) -> discord.User:
        fetched.append(user_id)
        if user_id == GONE_ID:
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"), {"message": "Unknown User", "code": 10013}
            )
        return discord.User(
            state=rig.bot._connection, data=user(user_id, f"user{user_id}") | {"banner": None, "accent_color": 0x123456}
        )

    monkeypatch.setattr(rig.bot, "fetch_user", fetch_user)

    # the search endpoint: the first answer is a 202 "index not ready", every later one a total for the author
    searches: list[tuple[str, list[tuple[str, str]]]] = []
    not_ready = [True]

    async def request(route, *, params=None, **kwargs):
        assert route.method == "GET" and route.url.endswith("/messages/search") and not kwargs
        searches.append((route.url, list(params)))
        if not_ready and not_ready.pop():
            return {"message": "Index not yet available. Try again later", "code": 110000, "retry_after": 0.001}
        total = 35 if dict(params)["author_id"] == str(MOD_ID) else 0
        return {"total_results": total, "messages": [{"content": "never read"}], "doing_deep_historical_index": False}

    monkeypatch.setattr(rig.bot.http, "request", request)
    return SimpleNamespace(rig=rig, store=store, renders=renders, fetched=fetched, searches=searches)


GONE_ID = BASE + 4242


def gallery_urls(view: ui.LayoutView) -> list[str]:
    return [
        item.media.url for gallery in view.walk_children() if isinstance(gallery, ui.MediaGallery) for item in gallery.items
    ]


async def test_server_insights_card_chart_and_cache(insights: SimpleNamespace) -> None:
    rig = insights.rig
    insights.store.tracking[GUILD_ID] = discord.utils.utcnow() - datetime.timedelta(days=3)
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev server insights").callback(rig.cog, interaction, None, "7d")

    assert interaction.calls[0][0] == "defer" and interaction.calls[0][4] is True
    kind, _, view, files, ephemeral = interaction.calls[1]
    assert kind == "followup" and ephemeral and isinstance(view, InsightsView) and view.interaction is interaction
    assert [file.filename for file in files] == ["insights.png"] and files[0].fp.read() == b"png-bytes"
    assert gallery_urls(view) == ["attachment://insights.png"]
    text = card_text(view)
    assert text.startswith("# Spork Lab\n`") and "### Members" in text and "### Last 7 days" in text
    assert "**Messages:** `35`" in text and "**Joined:** `7` · **Left:** `0`" in text and "**Busiest day:** <t:" in text
    assert "**Tracking since <t:" in text and text.endswith(f"-# 7d • Guild ID: {GUILD_ID}")
    assert insights.store.calls == [("guild", GUILD_ID, 7)]
    assert rig.cog.audit.rows[-1]["command"] == "dev server insights"

    chart = insights.renders[0]
    assert chart.panels[1].title == "Joins vs leaves" and chart.panels[2].bars[0] == ("#general", 90)
    assert chart.panels[2].bars[1][0] == "deleted …9999"
    assert chart.panels[0].note is not None and chart.panels[0].note.startswith("Tracking since")

    again = FakeInteraction(OWNER_ID)
    await rig.command("dev server insights").callback(rig.cog, again, None, "7d")
    assert len(insights.renders) == 1  # the five-minute render cache
    await rig.command("dev server insights").callback(rig.cog, FakeInteraction(OWNER_ID), None, "30d")
    assert len(insights.renders) == 2 and insights.renders[1].panels[0].days[0] != insights.renders[0].panels[0].days[0]

    # a fresh upload every time it is shared, from the same bytes
    snapshot = view.snapshot("jaden")
    assert gallery_urls(snapshot) == ["attachment://insights.png"] and buttons(snapshot) == []
    assert view.files()[0].fp.read() == b"png-bytes" and view.needs_confirm(FakeInteraction(OWNER_ID)) is False


async def test_server_insights_notes_when_counts_are_off_or_missing(insights: SimpleNamespace) -> None:
    rig = insights.rig
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev server insights").callback(rig.cog, interaction, str(OTHER_GUILD_ID), "90d")
    assert "**No activity counts yet**" in card_text(interaction.calls[1][2])

    rig.stats.disabled.add(OTHER_GUILD_ID)
    off = FakeInteraction(OWNER_ID)
    await rig.command("dev server insights").callback(rig.cog, off, str(OTHER_GUILD_ID), "90d")
    assert "Activity counts are off here" in card_text(off.calls[1][2])
    rig.stats.disabled.clear()

    dm = FakeInteraction(OWNER_ID, guild_id=None)
    await rig.command("dev server insights").callback(rig.cog, dm, None, "30d")
    assert dm.sent == [("send", "Pick a server I'm in — `guild` is required here.", None, [], True)]


async def test_user_insights_resolves_by_id_and_reads_membership(insights: SimpleNamespace) -> None:
    rig = insights.rig
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, interaction, None, str(MOD_ID), None, "30d")

    kind, _, view, files, ephemeral = interaction.calls[1]
    assert kind == "followup" and ephemeral and isinstance(view, InsightsView) and view.sensitive
    assert [file.filename for file in files] == ["insights.png"]
    text = card_text(view)
    assert text.startswith("# mod\nmod · `") and "**Mutual servers:** `2`" in text and "**Flags:** none" in text
    assert "### In Spork Lab" in text and f"**Top role:** <@&{MODS_ROLE}> (2 roles)" in text
    assert "**Timed out:** no" in text and "**Administrator:** no" in text and "**Boosting since:** not boosting" in text
    assert "**Message rank:** top 25% (#1 of 4, `12` messages)" in text
    assert "### Anti-brainrot" not in text  # the cog isn't loaded in this rig
    assert f"User ID: {MOD_ID} • Guild ID: {GUILD_ID}" in text and "No activity counts yet" in text
    assert insights.fetched == [MOD_ID] and insights.store.calls == [("member", GUILD_ID, MOD_ID, 30)]
    assert rig.cog.audit.rows[-1] == {
        "user_id": OWNER_ID,
        "command": "dev user insights",
        "guild_id": GUILD_ID,
        "target_user_id": MOD_ID,
        "channel_id": None,
    }
    assert view.needs_confirm(FakeInteraction(OWNER_ID)) is True and view.subject == "mod in Spork Lab"

    chart = insights.renders[0]
    assert [panel.title for panel in chart.panels] == [
        "Messages per day",
        "Activity by hour (UTC)",
        "Top channels",
        "Commands used",
    ]
    assert chart.accent == discord.Colour(0x123456).to_rgb()

    picked = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(
        rig.cog, picked, rig.guild.get_member(USER_ID), None, str(OTHER_GUILD_ID), "7d"
    )
    text = card_text(picked.calls[1][2])
    assert "### In Elsewhere" in text and "**Top role:** Members (1 role)" in text  # plain name outside the origin server
    assert "**Message rank:** no messages in the last 7 days" in text
    assert insights.fetched == [MOD_ID, USER_ID] and len(insights.renders) == 2


async def test_user_insights_handles_unknown_users_and_non_members(insights: SimpleNamespace) -> None:
    rig = insights.rig
    nothing = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, nothing, None, None, None, "30d")
    assert nothing.sent == [("send", "Pick a user, or give me a user id.", None, [], True)]

    gone = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, gone, None, str(GONE_ID), None, "30d")
    assert gone.sent == [("send", "I can't find that user.", None, [], True)]
    assert rig.cog.audit.rows == []

    async def fetch_member(self, member_id: int):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), {"message": "Unknown Member", "code": 10007})

    stranger_id = BASE + 5151
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(discord.Guild, "fetch_member", fetch_member)
        outsider = FakeInteraction(OWNER_ID)
        await rig.command("dev user insights").callback(rig.cog, outsider, None, str(stranger_id), None, "30d")
    text = card_text(outsider.calls[1][2])
    assert "Not a member right now" in text and "**Message rank:** no messages" in text and "**Mutual servers:** `0`" in text


async def test_user_insights_includes_brainrot_when_the_cog_is_loaded(insights: SimpleNamespace) -> None:
    from test_brainrot_cog import FakeStore

    from exts.brainrot import Brainrot
    from exts.utils.brainrot import BrainrotConfig
    from exts.utils.heat import HeatState

    rig = insights.rig
    cog = Brainrot(rig.bot)
    store = FakeStore(BrainrotConfig(GUILD_ID))
    store.states[(GUILD_ID, MOD_ID)] = HeatState(heat=3, heat_updated_at=discord.utils.utcnow(), lifetime_offenses=17)
    cog.store = store  # type: ignore[assignment] — in-memory stand-in
    await rig.bot.add_cog(cog)
    cog.expire_mutes.cancel()
    cog.cleanup.cancel()
    try:
        interaction = FakeInteraction(OWNER_ID)
        await rig.command("dev user insights").callback(rig.cog, interaction, None, str(MOD_ID), None, "30d")
        assert "### Anti-brainrot\n**Heat:** `3` · **Lifetime offenses:** `17`" in card_text(interaction.calls[1][2])
    finally:
        await rig.bot.remove_cog(cog.qualified_name)


# lifetime counts: the search endpoint asked for totals only, cached, and never allowed to break the card


def test_search_query_and_lifetime_section() -> None:
    assert search_query(author_id=MOD_ID) == [("author_id", str(MOD_ID)), ("include_nsfw", "true"), ("limit", "1")]
    assert lifetime_section(SearchTotal(1500)) == "### Lifetime\n**Messages:** `1,500` in this server"
    assert lifetime_section(SearchTotal(0, indexing=True)) == (
        "### Lifetime\n**Messages:** `0` in this server\n-# discord is still indexing this server's history"
    )
    assert (
        lifetime_section("the search request failed")
        == "### Lifetime\n**Messages:** unavailable — the search request failed"
    )


async def test_user_insights_pulls_the_lifetime_total_from_search_and_caches_it(insights: SimpleNamespace) -> None:
    rig = insights.rig
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, interaction, None, str(MOD_ID), None, "30d")

    text = card_text(interaction.calls[1][2])
    assert "### Lifetime\n**Messages:** `35` in this server\n-# 30d" in text and "never read" not in text
    # one search for the whole server, asked twice because the first answer was the 202; author only, one result
    assert [url.rsplit("/guilds/", 1)[1] for url, _ in insights.searches] == [f"{GUILD_ID}/messages/search"] * 2
    assert all(params == search_query(author_id=MOD_ID) for _, params in insights.searches)

    again = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, again, None, str(MOD_ID), None, "30d")
    assert len(insights.searches) == 2  # the quarter-hour cache
    assert "**Messages:** `35` in this server" in card_text(again.calls[1][2])

    elsewhere = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, elsewhere, None, str(MOD_ID), str(OTHER_GUILD_ID), "30d")
    assert len(insights.searches) == 3 and insights.searches[-1][0].endswith(f"/guilds/{OTHER_GUILD_ID}/messages/search")


async def test_user_insights_survives_search_being_refused_or_never_indexed(
    insights: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = insights.rig

    async def refused(route, *, params=None, **kwargs):
        raise discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), {"message": "Missing Access", "code": 50001}
        )

    monkeypatch.setattr(rig.bot.http, "request", refused)
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, interaction, None, str(MOD_ID), None, "30d")
    text = card_text(interaction.calls[1][2])
    assert "**Messages:** unavailable — I can't search here (needs Read Message History" in text
    assert "**Message rank:** top 25%" in text  # the rest of the card is untouched

    calls = []

    async def never_ready(route, *, params=None, **kwargs):
        calls.append(params)
        return {"message": "Index not yet available. Try again later", "code": 110000, "retry_after": 0}

    monkeypatch.setattr(rig.bot.http, "request", never_ready)
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, interaction, None, str(USER_ID), None, "30d")
    assert "**Messages:** unavailable — the search index isn't ready for this server yet" in card_text(
        interaction.calls[1][2]
    )
    assert len(calls) == 4  # the first ask plus three waits, then it gives up rather than hammering

    async def broken(route, *, params=None, **kwargs):
        raise discord.HTTPException(SimpleNamespace(status=500, reason="Server Error"), {"message": "boom", "code": 0})

    monkeypatch.setattr(rig.bot.http, "request", broken)
    interaction = FakeInteraction(OWNER_ID)
    await rig.command("dev user insights").callback(rig.cog, interaction, None, str(USER_ID), None, "30d")
    assert "**Messages:** unavailable — the search request failed" in card_text(interaction.calls[1][2])


# the storage card


def test_human_size_and_storage_sections() -> None:
    assert [human_size(n) for n in (0, 512, 1024, 1536, 5 * 1024**2, 3 * 1024**3, 2048 * 1024**3)] == [
        "0 B",
        "512 B",
        "1.0 KB",
        "1.5 KB",
        "5.0 MB",
        "3.0 GB",
        "2,048.0 GB",
    ]
    tables = (TableSize("stats_user_days", 1200, 900 * 1024), TableSize("guilds", 3, 16 * 1024))
    footprint = Footprint(
        guilds=(GuildFootprint(GUILD_ID, 1200, 40), GuildFootprint(DEPARTED_GUILD_ID, 30, 1)),
        servers=3,
        people=42,
        oldest_day=datetime.date(2026, 9, 16),
    )
    database, counts = storage_sections(1536 * 1024, tables, footprint, {GUILD_ID: "Spork Lab"})
    assert database == (
        "### Database\n**On disk:** `1.5 MB` · **Rows:** `1,203` across 2 tables"
        "\n`stats_user_days` · `1,200` rows · `900.0 KB`\n`guilds` · `3` rows · `16.0 KB`"
    )
    assert counts == (
        "### Activity counts\n**Servers:** `3` · **People:** `42` · **Oldest day:** 2026-09-16"
        f"\nSpork Lab · `1,200` rows · 40 people\n`{DEPARTED_GUILD_ID}` · `30` rows · 1 person\n+1 more servers"
    )
    _, empty = storage_sections(0, (), Footprint((), 0, 0, None), {})
    assert empty == "### Activity counts\n**Servers:** `0` · **People:** `0` · **Oldest day:** none"


async def test_storage_card_names_servers_but_no_person(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_database_size(pool) -> int:
        return 1536 * 1024

    async def fake_table_sizes(pool) -> tuple[TableSize, ...]:
        return (TableSize("stats_user_days", 1200, 900 * 1024), TableSize("dev_audit", 9, 16 * 1024))

    monkeypatch.setattr("exts.dev.database_size", fake_database_size)
    monkeypatch.setattr("exts.dev.table_sizes", fake_table_sizes)
    interaction = FakeInteraction(OWNER_ID, None)  # from a DM, like most owner tooling
    await rig.command("dev storage").callback(rig.cog, interaction)

    kind, _, view, files, ephemeral = interaction.calls[1]
    assert kind == "followup" and ephemeral and isinstance(view, TextView) and view.sensitive and files == []
    text = card_text(view)
    assert "### Database\n**On disk:** `1.5 MB` · **Rows:** `1,209` across 2 tables" in text
    assert "`stats_user_days` · `1,200` rows · `900.0 KB`" in text
    assert "**Servers:** `3` · **People:** `42` · **Oldest day:** 2026-09-16" in text
    assert "Spork Lab · `1,200` rows · 40 people" in text and "left …0777 · `30` rows · 1 person" in text
    assert "+1 more servers" in text and "nothing here names a person" in text
    assert str(MOD_ID) not in text and str(USER_ID) not in text and str(OWNER_ID) not in text
    assert rig.cog.audit.rows[-1] == {
        "user_id": OWNER_ID,
        "command": "dev storage",
        "guild_id": None,
        "target_user_id": None,
        "channel_id": None,
    }

    stranger = FakeInteraction(USER_ID, None)
    assert await rig.cog.interaction_check(stranger) is False
