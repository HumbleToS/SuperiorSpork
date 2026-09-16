"""Drives the Brainrot cog offline: real discord.py objects built from raw payloads, an in-memory store, and
patched network calls. Nothing here talks to Discord or Postgres."""

import asyncio
import datetime
from dataclasses import replace
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

from exts.brainrot import Brainrot
from exts.utils.brainrot import BrainrotConfig
from exts.utils.heat import HeatState

GUILD_ID = 100
CHANNEL_ID = 200
OTHER_CHANNEL_ID = 201
THREAD_ID = 202
BOT_ID = 1
OWNER_ID = 2
MOD_ID = 3
USER_ID = 4
EXEMPT_ID = 5
BOT_ROLE_ID = 300
MOD_ROLE_ID = 301
EXEMPT_ROLE_ID = 302
MUTE_ROLE_ID = 303
NOW = "2026-01-01T00:00:00+00:00"


class FakeStore:
    def __init__(self, config: BrainrotConfig) -> None:
        self.config = config
        self.states: dict[tuple[int, int], HeatState] = {}
        self.mutes: dict[tuple[int, int], tuple[datetime.datetime, int | None]] = {}
        self.purged: list[int] = []

    async def get_config(self, guild_id: int) -> BrainrotConfig:
        return self.config

    async def get_state(self, guild_id: int, user_id: int) -> HeatState:
        await asyncio.sleep(0)  # yield like a real query would, so races have room to happen
        return self.states.get((guild_id, user_id), HeatState())

    async def put_state(self, guild_id: int, user_id: int, state: HeatState) -> None:
        await asyncio.sleep(0)
        self.states[(guild_id, user_id)] = state

    async def set_mute(self, guild_id: int, user_id: int, expires_at: datetime.datetime, role_id: int | None) -> None:
        self.mutes[(guild_id, user_id)] = (expires_at, role_id)

    async def clear_mute(self, guild_id: int, user_id: int) -> None:
        self.mutes.pop((guild_id, user_id), None)

    async def expired_role_mutes(self) -> list[dict]:
        now = discord.utils.utcnow()
        return [
            {"guild_id": g, "user_id": u, "muted_role_id": role_id}
            for (g, u), (expires, role_id) in self.mutes.items()
            if role_id is not None and expires <= now
        ]

    async def pending_role_mute(self, guild_id: int, user_id: int) -> dict | None:
        entry = self.mutes.get((guild_id, user_id))
        if entry is None or entry[1] is None or entry[0] <= discord.utils.utcnow():
            return None
        return {"muted_role_id": entry[1], "mute_expires_at": entry[0]}

    async def purge_guild(self, guild_id: int) -> None:
        self.purged.append(guild_id)


def user(user_id: int, name: str, bot: bool = False) -> dict:
    return {"id": str(user_id), "username": name, "discriminator": "0", "global_name": name, "avatar": None, "bot": bot}


def member(user_id: int, name: str, roles: list[int], bot: bool = False) -> dict:
    return {
        "user": user(user_id, name, bot),
        "roles": [str(r) for r in roles],
        "joined_at": NOW,
        "deaf": False,
        "mute": False,
        "flags": 0,
    }


def role(role_id: int, name: str, position: int, permissions: int = 0) -> dict:
    return {
        "id": str(role_id),
        "name": name,
        "color": 0,
        "hoist": False,
        "position": position,
        "permissions": str(permissions),
        "managed": False,
        "mentionable": False,
    }


def channel(channel_id: int, name: str) -> dict:
    return {"id": str(channel_id), "type": 0, "name": name, "position": 0, "permission_overwrites": [], "nsfw": False}


BOT_PERMS = discord.Permissions(
    view_channel=True, send_messages=True, moderate_members=True, manage_roles=True, manage_messages=True
).value
MOD_PERMS = discord.Permissions(manage_messages=True).value


def guild_payload() -> dict:
    return {
        "id": str(GUILD_ID),
        "name": "test",
        "owner_id": str(OWNER_ID),
        "roles": [
            role(GUILD_ID, "@everyone", 0),
            role(EXEMPT_ROLE_ID, "exempt", 1),
            role(MUTE_ROLE_ID, "muted", 2),
            role(MOD_ROLE_ID, "mods", 3, MOD_PERMS),
            role(BOT_ROLE_ID, "bot", 4, BOT_PERMS),
        ],
        "members": [
            member(BOT_ID, "spork", [BOT_ROLE_ID], bot=True),
            member(OWNER_ID, "owner", []),
            member(MOD_ID, "mod", [MOD_ROLE_ID]),
            member(USER_ID, "user", []),
            member(EXEMPT_ID, "exempt", [EXEMPT_ROLE_ID]),
        ],
        "channels": [channel(CHANNEL_ID, "general"), channel(OTHER_CHANNEL_ID, "off-topic")],
        "threads": [
            {
                "id": str(THREAD_ID),
                "type": 11,
                "name": "thread",
                "parent_id": str(CHANNEL_ID),
                "owner_id": str(USER_ID),
                "guild_id": str(GUILD_ID),
                "message_count": 0,
                "member_count": 1,
                "rate_limit_per_user": 0,
                "thread_metadata": {
                    "archived": False,
                    "auto_archive_duration": 60,
                    "archive_timestamp": NOW,
                    "locked": False,
                },
            }
        ],
        "member_count": 5,
        "large": False,
        "unavailable": False,
        "features": [],
        "emojis": [],
        "stickers": [],
        "verification_level": 0,
        "default_message_notifications": 0,
        "explicit_content_filter": 0,
        "mfa_level": 0,
        "nsfw_level": 0,
        "premium_tier": 0,
        "afk_timeout": 300,
        "system_channel_flags": 0,
        "preferred_locale": "en-US",
        "voice_states": [],
        "presences": [],
    }


class Calls:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.timeouts: list[tuple[int, datetime.datetime | None]] = []
        self.roles: list[tuple[str, int, int]] = []
        self.deleted: list[int] = []
        self.delete_delays: list[float | None] = []


@pytest.fixture
def config() -> BrainrotConfig:
    return BrainrotConfig(
        GUILD_ID, enabled=True, channel_ids=frozenset({CHANNEL_ID}), exempt_role_ids=frozenset({EXEMPT_ROLE_ID})
    )


@pytest.fixture
async def rig(config: BrainrotConfig, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    intents = discord.Intents(guilds=True, members=True, message_content=True, messages=True)
    bot = commands.Bot(command_prefix="t,", intents=intents)
    await bot._async_setup_hook()  # what login() does first, so the task loops can wait_until_ready() quietly
    state = bot._connection
    state.user = discord.ClientUser(
        state=state, data=user(BOT_ID, "spork", bot=True) | {"verified": True, "mfa_enabled": False}
    )
    state.parse_guild_create(guild_payload())
    guild = bot.get_guild(GUILD_ID)
    assert guild is not None and guild.me is not None

    bot.pool = None  # the cog only hands the pool to the store, which we replace
    cog = Brainrot(bot)
    cog.store = FakeStore(config)  # type: ignore[assignment] — the in-memory stand-in for this harness
    await bot.add_cog(cog)

    calls = Calls()

    async def fake_send(self, *args, **kwargs):
        calls.sent.append(kwargs)
        return SimpleNamespace(delete=fake_delete_sent)

    async def fake_delete_sent(*, delay: float | None = None):
        calls.delete_delays.append(delay)

    async def fake_reply(self, *args, **kwargs):
        return await fake_send(self, *args, **kwargs)

    async def fake_timeout(self, until, /, *, reason=None):
        calls.timeouts.append((self.id, until))

    async def fake_add_roles(self, *roles, reason=None, atomic=True):
        calls.roles.extend(("add", self.id, r.id) for r in roles)
        self._roles.add(*(r.id for r in roles))

    async def fake_remove_roles(self, *roles, reason=None, atomic=True):
        calls.roles.extend(("remove", self.id, r.id) for r in roles)
        for r in roles:
            self._roles.remove(r.id)

    async def fake_delete(self, *, delay=None):
        calls.deleted.append(self.id)

    monkeypatch.setattr(discord.abc.Messageable, "send", fake_send)
    monkeypatch.setattr(discord.Message, "reply", fake_reply)
    monkeypatch.setattr(discord.Message, "delete", fake_delete)
    monkeypatch.setattr(discord.Member, "timeout", fake_timeout)
    monkeypatch.setattr(discord.Member, "add_roles", fake_add_roles)
    monkeypatch.setattr(discord.Member, "remove_roles", fake_remove_roles)

    counter = iter(range(1000, 100000))

    def message(content: str, author_id: int = USER_ID, channel_id: int = CHANNEL_ID, **extra) -> discord.Message:
        author = guild.get_member(author_id)
        assert author is not None
        data = {
            "id": str(next(counter)),
            "channel_id": str(channel_id),
            "guild_id": str(GUILD_ID),
            "author": user(author.id, author.name, author.bot),
            "member": {"roles": [str(r.id) for r in author.roles if r.id != GUILD_ID], "joined_at": NOW, "flags": 0},
            "content": content,
            "timestamp": NOW,
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
        } | extra
        target = guild.get_channel_or_thread(channel_id)
        assert target is not None
        return discord.Message(state=state, channel=target, data=data)

    try:
        yield SimpleNamespace(bot=bot, cog=cog, guild=guild, calls=calls, message=message, store=cog.store)
    finally:
        await bot.remove_cog(cog.qualified_name)
        await bot.close()


def state_of(rig: SimpleNamespace, user_id: int = USER_ID) -> HeatState:
    return rig.store.states.get((GUILD_ID, user_id), HeatState())


async def test_offense_adds_heat_and_warns_without_pinging(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("zero rizz"))
    assert state_of(rig).heat == 1
    assert len(rig.calls.sent) == 1
    sent = rig.calls.sent[0]
    mentions = sent["allowed_mentions"]
    assert mentions.users is False and mentions.roles is False and mentions.replied_user is False
    assert sent["mention_author"] is False
    assert isinstance(sent["view"], discord.ui.LayoutView)
    assert rig.calls.delete_delays == [30]


async def test_clean_messages_and_disabled_channels_are_ignored(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("a perfectly normal message"))
    await rig.cog.inspect(rig.message("rizz", channel_id=OTHER_CHANNEL_ID))
    assert state_of(rig).heat == 0 and rig.calls.sent == []


async def test_threads_inherit_their_parent_channel(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("rizz", channel_id=THREAD_ID))
    assert state_of(rig).heat == 1


async def test_mods_bots_and_exempt_roles_are_skipped(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("rizz", author_id=MOD_ID))
    await rig.cog.inspect(rig.message("rizz", author_id=OWNER_ID))
    await rig.cog.inspect(rig.message("rizz", author_id=EXEMPT_ID))
    await rig.cog.inspect(rig.message("rizz", author_id=BOT_ID))
    await rig.cog.inspect(rig.message("rizz", webhook_id="999"))
    await rig.cog.inspect(rig.message("rizz", type=7))  # a join system message
    assert rig.store.states == {} and rig.calls.sent == []


async def test_mods_can_be_opted_in(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, include_mods=True)
    await rig.cog.inspect(rig.message("rizz", author_id=MOD_ID))
    assert state_of(rig, MOD_ID).heat == 1


async def test_own_commands_are_never_scored(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("t,brainrot terms add rizz"))
    assert state_of(rig).heat == 0
    await rig.cog.inspect(rig.message("t,whois rizz"))  # only this cog's commands get a pass
    assert state_of(rig).heat == 1


async def test_a_message_is_scored_once_even_when_edited(rig: SimpleNamespace) -> None:
    message = rig.message("rizz")
    await rig.cog.inspect(message)
    edited = rig.message("rizz skibidi", id=str(message.id))
    await rig.cog.on_raw_message_edit(discord.RawMessageUpdateEvent({"id": str(message.id)}, edited))
    assert state_of(rig).heat == 1

    clean = rig.message("hello")
    await rig.cog.inspect(clean)
    now_dirty = rig.message("hello rizz", id=str(clean.id))
    await rig.cog.on_raw_message_edit(discord.RawMessageUpdateEvent({"id": str(clean.id)}, now_dirty))
    assert state_of(rig).heat == 2  # editing brainrot in still counts


async def test_concurrent_burst_is_serialized_and_capped(rig: SimpleNamespace) -> None:
    await asyncio.gather(*(rig.cog.inspect(rig.message("rizz")) for _ in range(8)))
    state = state_of(rig)
    assert state.heat == 3 and state.lifetime_offenses == 8
    assert len(rig.calls.sent) == 3  # two heat warnings and one spam warning, nothing for messages 4+
    assert rig.cog._slots == {}  # idle locks are dropped


async def test_stuffed_message_is_spam_on_its_own(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("rizz gyat skibidi sigma"))
    assert state_of(rig).heat == 3 and len(rig.calls.sent) == 1


async def test_reaching_five_times_out_and_logs_to_the_mod_channel(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, modlog_channel_id=OTHER_CHANNEL_ID)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert len(rig.calls.timeouts) == 1
    user_id, until = rig.calls.timeouts[0]
    assert user_id == USER_ID and until is not None
    assert 290 <= (until - discord.utils.utcnow()).total_seconds() <= 300
    assert state_of(rig).heat == 0 and state_of(rig).repeat_until is not None
    assert rig.store.mutes[(GUILD_ID, USER_ID)][1] is None
    assert len(rig.calls.sent) == 2  # the warning and the mod log card


async def test_role_mode_applies_the_role_and_the_sweep_removes_it(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, mute_mode="role", mute_role_id=MUTE_ROLE_ID)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert rig.calls.roles == [("add", USER_ID, MUTE_ROLE_ID)] and rig.calls.timeouts == []
    assert rig.store.mutes[(GUILD_ID, USER_ID)][1] == MUTE_ROLE_ID

    rig.store.mutes[(GUILD_ID, USER_ID)] = (discord.utils.utcnow() - datetime.timedelta(seconds=1), MUTE_ROLE_ID)
    await rig.cog.expire_mutes()
    assert rig.calls.roles[-1] == ("remove", USER_ID, MUTE_ROLE_ID)
    assert (GUILD_ID, USER_ID) not in rig.store.mutes


async def test_role_mode_falls_back_to_a_timeout_when_the_role_is_gone(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, mute_mode="role", mute_role_id=999)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert rig.calls.roles == [] and len(rig.calls.timeouts) == 1


async def test_repeat_offender_gets_an_escalating_timeout(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat_updated_at=now, repeat_until=now + datetime.timedelta(days=3))
    await rig.cog.inspect(rig.message("rizz"))
    _, until = rig.calls.timeouts[0]
    assert until is not None and 1790 <= (until - now).total_seconds() <= 1801
    assert state_of(rig).escalation_level == 1


async def test_unpunishable_targets_still_get_heat_and_a_warning(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, include_mods=True)
    rig.guild.me._roles.remove(BOT_ROLE_ID)  # the bot loses Moderate Members mid-session
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert rig.calls.timeouts == []
    assert state_of(rig).heat == 0 and state_of(rig).repeat_until is not None
    assert len(rig.calls.sent) == 1


async def test_delete_option_removes_the_message_and_warns_in_channel(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, delete_messages=True)
    message = rig.message("rizz")
    await rig.cog.inspect(message)
    assert rig.calls.deleted == [message.id]
    assert "mention_author" not in rig.calls.sent[0]  # a plain channel send, since the original is gone


async def test_rejoining_restores_a_pending_role_mute(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, mute_mode="role", mute_role_id=MUTE_ROLE_ID)
    rig.store.mutes[(GUILD_ID, USER_ID)] = (discord.utils.utcnow() + datetime.timedelta(minutes=3), MUTE_ROLE_ID)
    await rig.cog.on_member_join(rig.guild.get_member(USER_ID))
    assert rig.calls.roles == [("add", USER_ID, MUTE_ROLE_ID)]


async def test_leaving_a_guild_purges_it(rig: SimpleNamespace) -> None:
    await rig.cog.on_guild_remove(rig.guild)
    assert rig.store.purged == [GUILD_ID]
