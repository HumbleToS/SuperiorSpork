"""Help: pure helpers first, then the real cogs loaded offline to check what each kind of invoker gets to see."""

from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands
from test_brainrot_cog import BASE, BOT_ID, MOD_ID, OWNER_ID, USER_ID, guild_payload, user

import config
from exts.help import Help, HelpView
from exts.utils.help import (
    DETAIL_LINES,
    LANDING_LINES,
    LINE_BUDGET,
    PAGE_SIZE,
    HelpCategory,
    HelpEntry,
    HelpIndex,
    category_lines,
    detail_lines,
    landing_lines,
    paginate,
    truncate,
    visible_for,
)

GUILD_ID = BASE + 100
CHANNEL_ID = BASE + 200


def entry(name: str, category: str = "General", **overrides) -> HelpEntry:
    fields = {
        "name": name,
        "category": category,
        "description": f"Does the {name} thing",
        "details": f"Does the {name} thing, at length.",
        "usage": f"/{name}",
        "example": f"/{name}",
        "permissions": (),
        "guild_only": False,
        "cooldown": None,
        "slash": True,
        "slash_id": None,
    }
    return HelpEntry(**(fields | overrides))


def index(*categories: tuple[str, int]) -> HelpIndex:
    return HelpIndex(
        tuple(
            HelpCategory(name, f"About {name}", None, tuple(entry(f"{name.lower()}{i}", name) for i in range(count)))
            for name, count in categories
        )
    )


# pure helpers


def test_truncate_cuts_on_a_word_boundary_with_an_ellipsis() -> None:
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    cut = truncate(text, 40)
    assert cut.endswith("…") and len(cut) <= 40 and not cut[:-1].endswith(" ")
    assert cut == "one two three four five six seven eight…"  # the cut landed on a boundary, so the word stays
    assert truncate("short", 40) == "short"
    assert truncate("x" * 50, 10) == "x" * 9 + "…"  # a single word has nothing to cut on
    assert truncate("spaced   out\ntext", 40) == "spaced out text"
    assert truncate("ends with a comma, here", 18) == "ends with a comma…"


def test_paginate() -> None:
    assert paginate([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert paginate([], 8) == [[]]
    assert paginate([1], 0) == [[1]]


def test_visible_for_drops_hidden_entries_and_empty_categories() -> None:
    full = index(("General", 3), ("Admin", 2), ("Owner", 1))
    seen = visible_for(full, {"general0", "general2", "admin1"})
    assert [c.name for c in seen.categories] == ["General", "Admin"]
    assert [e.name for e in seen.entries] == ["general0", "general2", "admin1"]
    assert visible_for(full, set()).categories == ()


def test_landing_lines_stay_inside_the_budget() -> None:
    wide = HelpIndex(
        (
            HelpCategory(
                "Something Long",
                "A blurb that goes on and on and on and on and keeps going past the edge",
                None,
                (entry("a"),) * 12,
            ),
        )
    )
    lines = landing_lines(wide)
    assert len(lines) == 1 and len(lines[0]) <= LINE_BUDGET
    assert lines[0].endswith("· 12 commands") and "…" in lines[0]
    assert landing_lines(index(("Solo", 1)))[0].endswith("· 1 command")


def test_category_lines_page_size_and_rendered_width() -> None:
    category = HelpCategory(
        "Big",
        "blurb",
        None,
        tuple(
            entry(f"brainrot terms verylongname{i}", "Big", description="a " * 60, slash_id=12345678901234567)
            for i in range(20)
        ),
    )
    lines, page, pages = category_lines(category, 0)
    assert len(lines) == PAGE_SIZE and pages == 3 and page == 0
    for line in lines:
        rendered = line.replace(line.split(" — ")[0], "/" + line.split(":")[0][2:])  # what discord shows for the mention
        assert len(rendered) <= LINE_BUDGET, rendered
        assert line.startswith("</brainrot terms verylongname") and ":12345678901234567> — " in line
    _, page, _ = category_lines(category, 99)
    assert page == 2  # clamped
    lines, _, _ = category_lines(category, 2)
    assert len(lines) == 4


def test_detail_lines_budget_and_content() -> None:
    full = entry(
        "brainrot pardon",
        "Brainrot",
        details="Clears someone's heat, repeat flag, and any mute I applied",
        usage="/brainrot pardon <member> [amount]",
        example="/brainrot pardon member:@someone",
        permissions=("Moderate Members",),
        guild_only=True,
        cooldown="1 every 5 seconds",
    )
    lines = detail_lines(full)
    assert len(lines) <= DETAIL_LINES
    assert lines[0] == "**/brainrot pardon**"
    assert "**Usage** `/brainrot pardon <member> [amount]`" in lines
    assert "**Example** `/brainrot pardon member:@someone`" in lines
    assert "**Needs** Moderate Members" in lines and "**Cooldown** 1 every 5 seconds" in lines
    assert lines[-1] == "-# Servers only"
    assert len(detail_lines(entry("bare"))) == 5  # name, details, blank, usage, example


def test_mention_falls_back_to_plain_text_without_an_id() -> None:
    assert entry("whois").mention == "/whois"
    assert entry("whois", slash_id=42).mention == "</whois:42>"
    assert entry("brainrot score", slash_id=42).mention == "</brainrot score:42>"
    prefix_only = entry("cleanup", slash=False, usage="t,cleanup [amount]")
    assert prefix_only.mention == "t,cleanup" and prefix_only.shown_name == "t,cleanup"


# the real cogs, offline


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    intents = discord.Intents(guilds=True, members=True, message_content=True, messages=True)
    bot = commands.Bot(command_prefix="t,", intents=intents, owner_id=OWNER_ID)
    await bot._async_setup_hook()
    state = bot._connection
    state.user = discord.ClientUser(
        state=state, data=user(BOT_ID, "spork", bot=True) | {"verified": True, "mfa_enabled": False}
    )
    state.parse_guild_create(guild_payload())
    guild = bot.get_guild(GUILD_ID)
    assert guild is not None

    bot.pool = None
    bot.settings = SimpleNamespace(get_prefix=_no_prefix)  # what Spork exposes; no database here
    monkeypatch.setattr(config, "PREFIX", "t,")
    for ext in ("exts.brainrot", "exts.general", "exts.dev"):
        await bot.load_extension(ext)
    cog = Help(bot)  # added directly: load_extension re-executes the module, which would split the class identity
    await bot.add_cog(cog)

    counter = iter(range(1000, 100000))

    async def context(author_id: int, dm: bool = False) -> commands.Context:
        author = guild.get_member(author_id)
        assert author is not None
        data = {
            "id": str(BASE + next(counter)),
            "channel_id": str(CHANNEL_ID),
            "author": user(author.id, author.name),
            "content": "t,help",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "edited_timestamp": None,
            "tts": False,
            "mention_everyone": False,
            "mentions": [],
            "mention_roles": [],
            "attachments": [],
            "embeds": [],
            "pinned": False,
            "type": 0,
            "flags": 0,
        }
        if dm:
            channel = discord.DMChannel(
                me=state.user, state=state, data={"id": str(BASE + 900), "recipients": [data["author"]]}
            )
        else:
            data |= {
                "guild_id": str(GUILD_ID),
                "member": {
                    "roles": [str(r.id) for r in author.roles if r.id != GUILD_ID],
                    "joined_at": "2026-01-01T00:00:00+00:00",
                    "flags": 0,
                },
            }
            channel = guild.get_channel(CHANNEL_ID)
        message = discord.Message(state=state, channel=channel, data=data)
        return await bot.get_context(message)

    try:
        yield SimpleNamespace(bot=bot, cog=cog, guild=guild, context=context)
    finally:
        await bot.close()


async def _no_prefix(guild_id: int) -> str | None:
    return None


def texts(view: HelpView) -> list[str]:
    return [item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)]


def names(index: HelpIndex) -> set[str]:
    return {e.name for e in index.entries}


async def test_owner_sees_everything_including_owner_only(rig: SimpleNamespace) -> None:
    index = await rig.cog.index_for(await rig.context(OWNER_ID))
    # "Other" holds discord.py's stock prefix help until the next phase replaces it
    assert [c.name for c in index.categories] == ["Brainrot", "Developer", "General", "Help", "Other"]
    assert "sync" in names(index) and "brainrot config mode" in names(index) and "help" in names(index)
    assert "brainrot" not in names(index) and "brainrot config" not in names(index)  # bare groups are not listed
    assert len(index.category("Brainrot").entries) == 26


async def test_regular_member_sees_only_what_they_can_run(rig: SimpleNamespace) -> None:
    index = await rig.cog.index_for(await rig.context(USER_ID))
    assert [c.name for c in index.categories] == ["Brainrot", "General", "Help", "Other"]
    assert {e.name for e in index.category("Brainrot").entries} == {"brainrot score", "brainrot leaderboard"}
    general = {e.name for e in index.category("General").entries}
    assert "prefix" not in general  # server owner only
    assert {"whois", "serverinfo", "cleanup", "about", "privacy", "report", "inviteinfo"} <= general


async def test_moderator_sees_pardon_but_not_config(rig: SimpleNamespace) -> None:
    index = await rig.cog.index_for(await rig.context(MOD_ID))
    brainrot = {e.name for e in index.category("Brainrot").entries}
    assert "brainrot pardon" in brainrot and "brainrot config mode" not in brainrot and "brainrot enable" not in brainrot


async def test_dms_hide_guild_only_commands(rig: SimpleNamespace) -> None:
    index = await rig.cog.index_for(await rig.context(USER_ID, dm=True))
    assert index.category("Brainrot") is None
    assert {e.name for e in index.category("General").entries} == {"about", "privacy", "report", "inviteinfo"}
    assert index.entry("help") is not None  # /help allows DMs


async def test_entries_carry_usage_example_permissions_and_cooldown(rig: SimpleNamespace) -> None:
    index = await rig.cog.index_for(await rig.context(OWNER_ID))
    pardon = index.entry("brainrot pardon")
    assert pardon is not None
    assert pardon.usage == "/brainrot pardon <member> [amount=0]"
    assert pardon.example == "/brainrot pardon member:@someone"
    assert pardon.permissions == ("Moderate Members",) and pardon.guild_only is True
    whois = index.entry("whois")
    assert whois is not None and whois.cooldown == "1 every 5 seconds" and whois.example == "/whois user:@someone"
    cleanup = index.entry("cleanup")
    assert (
        cleanup is not None
        and cleanup.slash is False
        and cleanup.usage == "t,cleanup [amount=100]"
        and cleanup.example == "t,cleanup 5"
    )
    mode = index.entry("brainrot config mode")
    assert (
        mode is not None and mode.example == "/brainrot config mode mode:timeout" and mode.permissions == ("Manage Server",)
    )
    sync = index.entry("sync")
    assert sync is not None and sync.permissions == ("Bot owner",)
    help_entry = index.entry("help")
    assert help_entry is not None and help_entry.category == "Help" and help_entry.usage == "/help [command] [public]"


async def test_mentions_use_synced_ids_and_fall_back_before_a_sync(rig: SimpleNamespace) -> None:
    ctx = await rig.context(OWNER_ID)
    before = await rig.cog.index_for(ctx)
    assert before.entry("whois").mention == "/whois"
    rig.cog.remember([SimpleNamespace(name="whois", id=111), SimpleNamespace(name="brainrot", id=222)], None)
    after = await rig.cog.index_for(ctx)
    assert after.entry("whois").mention == "</whois:111>"
    assert after.entry("brainrot score").mention == "</brainrot score:222>"
    assert after.entry("cleanup").mention == "t,cleanup"
    rig.cog.remember([SimpleNamespace(name="whois", id=333)], SimpleNamespace(id=GUILD_ID))  # a guild copy wins there
    assert (await rig.cog.index_for(ctx)).entry("whois").mention == "</whois:333>"


async def test_views_respect_the_size_rules(rig: SimpleNamespace) -> None:
    view = await rig.cog.view_for(await rig.context(OWNER_ID))
    landing = texts(view)[0].split("\n")
    assert len(landing) <= LANDING_LINES and landing[0].startswith("**Help** · ")
    assert all(len(line) <= LINE_BUDGET for line in landing[1:])
    assert any(isinstance(item, discord.ui.Select) for item in view.walk_children())

    view.show_category("Brainrot")
    page = texts(view)[0].split("\n")
    assert len(page) <= PAGE_SIZE + 1 and "page 1/4" in page[0]
    selects = [item for item in view.walk_children() if isinstance(item, discord.ui.Select)]
    assert len(selects[0].options) == PAGE_SIZE
    view.navigate("next")
    assert "page 2/4" in texts(view)[0]
    view.navigate("prev")
    view.navigate("prev")  # clamps at the first page
    assert "page 1/4" in texts(view)[0]

    assert view.show_entry("brainrot score") is True
    detail = texts(view)[0].split("\n")
    assert len(detail) <= DETAIL_LINES and detail[0] == "**/brainrot score**"
    view.navigate("back")
    assert "**Brainrot**" in texts(view)[0]
    view.navigate("home")
    assert texts(view)[0].startswith("**Help**")
    assert view.show_entry("nope") is False


async def test_dashboard_line_only_for_manage_guild_and_only_when_configured(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import config

    monkeypatch.setattr(config, "DASHBOARD_URL", "https://spork.umbleh.dev", raising=False)
    owner_view = await rig.cog.view_for(await rig.context(OWNER_ID))
    assert texts(owner_view)[-1] == "-# Dashboard: https://spork.umbleh.dev"
    member_view = await rig.cog.view_for(await rig.context(USER_ID))
    assert not any("Dashboard" in text for text in texts(member_view))
    monkeypatch.setattr(config, "DASHBOARD_URL", "", raising=False)
    assert not any("Dashboard" in text for text in texts(await rig.cog.view_for(await rig.context(OWNER_ID))))


async def test_only_the_invoker_can_use_the_components(rig: SimpleNamespace) -> None:
    view = await rig.cog.view_for(await rig.context(USER_ID))
    replies: list[dict] = []

    async def send_message(content: str, *, ephemeral: bool = False) -> None:
        replies.append({"content": content, "ephemeral": ephemeral})

    stranger = SimpleNamespace(user=SimpleNamespace(id=MOD_ID), response=SimpleNamespace(send_message=send_message))
    assert await view.interaction_check(stranger) is False
    assert replies == [{"content": "This isn't your help menu.", "ephemeral": True}]
    owner = SimpleNamespace(user=SimpleNamespace(id=USER_ID), response=SimpleNamespace(send_message=send_message))
    assert await view.interaction_check(owner) is True and len(replies) == 1


async def test_timeout_disables_every_component(rig: SimpleNamespace) -> None:
    view = await rig.cog.view_for(await rig.context(USER_ID))
    edits: list[HelpView] = []

    async def edit(*, view: HelpView) -> None:
        edits.append(view)

    view.message = SimpleNamespace(edit=edit)
    await view.on_timeout()
    controls = [item for item in view.walk_children() if isinstance(item, discord.ui.Button | discord.ui.Select)]
    assert controls and all(item.disabled for item in controls) and edits == [view]
