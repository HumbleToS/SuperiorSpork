"""Drives the Brainrot cog offline: real discord.py objects built from raw payloads, an in-memory store, and
patched network calls. Nothing here talks to Discord or Postgres."""

import asyncio
import datetime
from dataclasses import replace
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

from exts.brainrot import Brainrot, parse_ladder, tier_title
from exts.utils.brainrot import BrainrotConfig
from exts.utils.heat import DEFAULT_TERMS, HeatEngine, HeatState

# converters only accept snowflake-length ids, so every fixture id sits on a realistic base
BASE = 10**17
GUILD_ID = BASE + 100
CHANNEL_ID = BASE + 200
OTHER_CHANNEL_ID = BASE + 201
THREAD_ID = BASE + 202
BOT_ID = BASE + 1
OWNER_ID = BASE + 2
MOD_ID = BASE + 3
USER_ID = BASE + 4
EXEMPT_ID = BASE + 5
GONE_ID = BASE + 6  # never a member
BOT_ROLE_ID = BASE + 300
MOD_ROLE_ID = BASE + 301
EXEMPT_ROLE_ID = BASE + 302
MUTE_ROLE_ID = BASE + 303
NOW = "2026-01-01T00:00:00+00:00"


class FakeStore:
    def __init__(self, config: BrainrotConfig) -> None:
        self.config = config
        self.states: dict[tuple[int, int], HeatState] = {}
        self.mutes: dict[tuple[int, int], tuple[datetime.datetime, int | None]] = {}
        self.purged: list[int] = []
        self.logged: list[dict] = []

    async def get_config(self, guild_id: int) -> BrainrotConfig:
        return self.config

    async def set_config(self, guild_id: int, column: str, value) -> BrainrotConfig:
        shape = {
            "channel_ids": frozenset,
            "exempt_role_ids": frozenset,
            "exempt_user_ids": frozenset,
            "added_terms": tuple,
            "removed_terms": tuple,
            "allowed_terms": tuple,
            "ladder_seconds": tuple,
        }
        self.config = replace(self.config, **{column: shape.get(column, lambda v: v)(value)})
        return self.config

    def cached_config(self, guild_id: int) -> BrainrotConfig | None:
        return self.config

    def invalidate(self, guild_id: int) -> None:
        pass

    async def get_mute(self, guild_id: int, user_id: int) -> dict | None:
        entry = self.mutes.get((guild_id, user_id))
        if entry is None or entry[0] <= discord.utils.utcnow():
            return None
        return {"mute_expires_at": entry[0], "muted_role_id": entry[1]}

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        rows = [(u, s.lifetime_offenses) for (g, u), s in self.states.items() if g == guild_id and s.lifetime_offenses > 0]
        rows.sort(key=lambda row: (-row[1], row[0]))
        return [{"user_id": u, "lifetime_offenses": n} for u, n in rows[:limit]]

    async def rank(self, guild_id: int, user_id: int) -> int | None:
        mine = self.states.get((guild_id, user_id))
        if mine is None or mine.lifetime_offenses == 0:
            return None
        return 1 + sum(
            1 for (g, _), s in self.states.items() if g == guild_id and s.lifetime_offenses > mine.lifetime_offenses
        )

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

    # the action log and the dashboard reads, in memory

    async def log_action(self, guild_id: int, action: str, source: str, **fields) -> None:
        row = {
            "id": len(self.logged) + 1,
            "guild_id": guild_id,
            "at": discord.utils.utcnow(),
            "action": action,
            "source": source,
            "applied": True,
            "target_user_id": None,
            "actor_user_id": None,
            "heat": None,
            "heat_added": None,
            "duration_seconds": None,
            "escalation_level": None,
            "field": None,
            "before": None,
            "after": None,
        }
        self.logged.append(row | fields)

    async def actions(
        self, guild_id: int, *, page: int, per_page: int, action: str | None = None, source: str | None = None
    ) -> tuple[list[dict], int]:
        rows = [
            row
            for row in reversed(self.logged)
            if row["guild_id"] == guild_id
            and (action is None or row["action"] == action)
            and (source is None or row["source"] == source)
        ]
        start = (page - 1) * per_page
        return rows[start : start + per_page], len(rows)

    async def count_actions_since(self, guild_id: int, since: datetime.datetime) -> int:
        return sum(1 for row in self.logged if row["guild_id"] == guild_id and row["at"] >= since)

    async def prune_actions(self) -> int:
        return 0

    async def offenders(self, guild_id: int, *, page: int, per_page: int, sort: str = "heat") -> tuple[list[dict], int]:
        engine = HeatEngine()
        rows = []
        for (g, u), s in self.states.items():
            if g != guild_id or (sort == "lifetime" and s.lifetime_offenses == 0):
                continue
            mute = self.mutes.get((g, u))
            rows.append(
                {
                    "user_id": u,
                    "heat": s.heat,
                    "heat_updated_at": s.heat_updated_at,
                    "window_started_at": s.window_started_at,
                    "window_count": s.window_count,
                    "lifetime_offenses": s.lifetime_offenses,
                    "repeat_until": s.repeat_until,
                    "escalation_level": s.escalation_level,
                    "mute_expires_at": mute[0] if mute else None,
                    "muted_role_id": mute[1] if mute else None,
                    "heat_now": engine.current_heat(s),
                }
            )
        for row in rows:
            row["rank"] = 1 + sum(1 for other in rows if other["lifetime_offenses"] > row["lifetime_offenses"])
        if sort == "lifetime":
            rows.sort(key=lambda row: (-row["lifetime_offenses"], row["user_id"]))
        else:
            rows.sort(key=lambda row: (-row["heat_now"], -row["lifetime_offenses"], row["user_id"]))
        start = (page - 1) * per_page
        return rows[start : start + per_page], len(rows)

    async def summary(self, guild_id: int) -> dict:
        engine = HeatEngine()
        now = discord.utils.utcnow()
        mine = [s for (g, _), s in self.states.items() if g == guild_id]
        return {
            "hot_users": sum(1 for s in mine if engine.current_heat(s) > 0),
            "muted_now": sum(1 for (g, _), (expires, _) in self.mutes.items() if g == guild_id and expires > now),
            "on_repeat_list": sum(1 for s in mine if s.repeat_until is not None and s.repeat_until > now),
            "lifetime_offenses": sum(s.lifetime_offenses for s in mine),
        }


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
    view_channel=True,
    send_messages=True,
    embed_links=True,
    moderate_members=True,
    manage_roles=True,
    manage_messages=True,
).value
MOD_PERMS = discord.Permissions(manage_messages=True, moderate_members=True).value


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
        self.errors: list[BaseException] = []
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
    for command in bot.walk_commands():
        if command._buckets.valid:
            command._buckets._cache.clear()  # cooldown buckets hang off the decorated callback and outlive cog instances

    calls = Calls()

    async def fake_send(self, *args, **kwargs):
        calls.sent.append(kwargs | {"content": args[0] if args else kwargs.get("content")})
        return SimpleNamespace(delete=fake_delete_sent)

    async def on_command_error(ctx, error):
        calls.errors.append(error)

    bot.add_listener(on_command_error)

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
    monkeypatch.setattr(commands.Context, "send", fake_send)  # keeps ephemeral visible; Context.send would consume it
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

    async def run(content: str, author_id: int = OWNER_ID) -> str | None:
        """Runs a prefix command as the given member and returns the last reply's text (or None for a card)."""
        before = len(calls.sent)
        await bot.process_commands(message(content, author_id=author_id))
        await asyncio.sleep(0)  # command errors are dispatched to listeners as tasks
        assert calls.errors == [], calls.errors
        assert len(calls.sent) > before, "the command sent nothing"
        return calls.sent[-1]["content"]

    try:
        yield SimpleNamespace(bot=bot, cog=cog, guild=guild, calls=calls, message=message, store=cog.store, run=run)
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


# commands, driven through the prefix path (the slash path runs the same callbacks)


def last_card(rig: SimpleNamespace, index: int = -1) -> str:
    view = rig.calls.sent[index]["view"]
    assert isinstance(view, discord.ui.LayoutView)
    texts = [item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)]
    return "\n".join(texts)


async def test_enable_refuses_until_the_bot_has_what_it_needs(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, enabled=False)
    rig.guild.me._roles.remove(BOT_ROLE_ID)
    reply = await rig.run("t,brainrot enable")
    assert reply is not None and "Not yet" in reply and "Moderate Members" in reply and "missing" in reply
    assert rig.store.config.enabled is False

    rig.guild.me._roles.add(BOT_ROLE_ID)
    reply = await rig.run("t,brainrot enable")
    assert reply is not None and reply.startswith("Anti-brainrot is on!") and rig.store.config.enabled is True
    assert rig.calls.sent[-1]["ephemeral"] is True

    reply = await rig.run("t,brainrot disable")
    assert reply is not None and "off" in reply and rig.store.config.enabled is False


async def test_enable_reports_a_missing_or_misplaced_muted_role(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, enabled=False, mute_mode="role", mute_role_id=None)
    reply = await rig.run("t,brainrot enable")
    assert reply is not None and "muted role isn't set" in reply

    rig.store.config = replace(rig.store.config, mute_role_id=BOT_ROLE_ID)  # at the bot's own top role
    reply = await rig.run("t,brainrot enable")
    assert reply is not None and "below my top role" in reply


async def test_admin_commands_need_manage_guild(rig: SimpleNamespace) -> None:
    await rig.bot.process_commands(rig.message("t,brainrot enable", author_id=USER_ID))
    await asyncio.sleep(0)
    assert len(rig.calls.errors) == 1 and isinstance(rig.calls.errors[0], commands.MissingPermissions)


async def test_channels_add_remove_list(rig: SimpleNamespace) -> None:
    reply = await rig.run(f"t,brainrot channels add <#{OTHER_CHANNEL_ID}>")
    assert reply is not None and "Now watching" in reply
    assert rig.store.config.channel_ids == {CHANNEL_ID, OTHER_CHANNEL_ID}
    reply = await rig.run(f"t,brainrot channels add <#{OTHER_CHANNEL_ID}>")
    assert reply is not None and "already" in reply
    reply = await rig.run(f"t,brainrot channels remove <#{CHANNEL_ID}>")
    assert reply is not None and "No longer" in reply and rig.store.config.channel_ids == {OTHER_CHANNEL_ID}
    await rig.run("t,brainrot channels list")
    assert f"<#{OTHER_CHANNEL_ID}>" in last_card(rig)


async def test_terms_add_remove_and_default_removal(rig: SimpleNamespace) -> None:
    reply = await rig.run("t,brainrot terms add Grimace Shake")
    assert reply is not None and "`grimace shake`" in reply
    assert rig.store.config.matcher.hits("GRIMACE shake") == 1

    reply = await rig.run("t,brainrot terms add rizz")
    assert reply is not None and "already" in reply
    reply = await rig.run("t,brainrot terms add ab")
    assert reply is not None and "characters" in reply

    reply = await rig.run("t,brainrot terms remove skibidi")  # a default
    assert reply is not None and "Removed" in reply
    assert "skibidi" in rig.store.config.removed_terms and rig.store.config.matcher.hits("skibidi") == 0
    reply = await rig.run("t,brainrot terms add skibidi")  # lifts the removal instead of duplicating
    assert (
        reply is not None
        and "Added" in reply
        and rig.store.config.removed_terms == ()
        and rig.store.config.added_terms == ("grimace shake",)
    )

    reply = await rig.run("t,brainrot terms remove grimace shake")
    assert reply is not None and rig.store.config.added_terms == ()
    reply = await rig.run("t,brainrot terms remove nonsense")
    assert reply is not None and "isn't on the list" in reply

    await rig.run("t,brainrot terms list")
    card = last_card(rig)
    assert "### Active" in card and "`rizz`" in card and f"{len(DEFAULT_TERMS)} active terms" in card


async def test_allowlist_add_remove_and_autocomplete(rig: SimpleNamespace) -> None:
    reply = await rig.run("t,brainrot allow add Sigma")
    assert reply is not None and "allowed" in reply and rig.store.config.matcher.hits("sigma") == 0
    assert "sigma" not in rig.store.config.terms

    interaction = SimpleNamespace(guild=rig.guild)
    choices = await rig.cog.allowed_autocomplete(interaction, "sig")
    assert [c.value for c in choices] == ["sigma"]
    choices = await rig.cog.term_autocomplete(interaction, "rizz")
    assert "rizz" in [c.value for c in choices] and "sigma" not in [c.value for c in choices]
    assert await rig.cog.term_autocomplete(SimpleNamespace(guild=None), "") == []

    reply = await rig.run("t,brainrot allow remove sigma")
    assert reply is not None and "counts again" in reply and rig.store.config.matcher.hits("sigma") == 1
    await rig.run("t,brainrot allow list")
    assert "None yet" in last_card(rig)


async def test_exempt_roles_and_members(rig: SimpleNamespace) -> None:
    reply = await rig.run(f"t,brainrot exempt add <@&{MOD_ROLE_ID}>")
    assert reply is not None and "exempt now" in reply and MOD_ROLE_ID in rig.store.config.exempt_role_ids
    reply = await rig.run(f"t,brainrot exempt add <@{USER_ID}>")
    assert reply is not None and USER_ID in rig.store.config.exempt_user_ids
    assert rig.calls.sent[-1]["allowed_mentions"].users is False

    await rig.cog.inspect(rig.message("rizz"))  # the exempt member no longer scores
    assert state_of(rig).heat == 0

    reply = await rig.run(f"t,brainrot exempt remove <@{USER_ID}>")
    assert reply is not None and "fair game" in reply and USER_ID not in rig.store.config.exempt_user_ids
    await rig.run("t,brainrot exempt list")
    assert f"<@&{MOD_ROLE_ID}>" in last_card(rig)


async def test_config_setters_and_show(rig: SimpleNamespace) -> None:
    reply = await rig.run("t,brainrot config mode role")
    assert reply is not None and "needs a role" in reply and rig.store.config.mute_mode == "timeout"
    reply = await rig.run(f"t,brainrot config mode role <@&{MUTE_ROLE_ID}>")
    assert reply is not None and rig.store.config.mute_mode == "role" and rig.store.config.mute_role_id == MUTE_ROLE_ID
    reply = await rig.run("t,brainrot config mode timeout")
    assert reply is not None and rig.store.config.mute_mode == "timeout"

    reply = await rig.run("t,brainrot config duration 10")
    assert reply is not None and "10 minutes" in reply and rig.store.config.mute_seconds == 600

    reply = await rig.run("t,brainrot config ladder 1h, 12h 3d")
    assert reply is not None and rig.store.config.ladder_seconds == (3600, 43200, 3 * 86400)
    assert "1 hour → 12 hours → 3 days" in reply
    reply = await rig.run("t,brainrot config ladder 5 weeks")
    assert reply is not None and "couldn't read" in reply

    reply = await rig.run("t,brainrot config warnings 0")
    assert reply is not None and "stay" in reply and rig.store.config.warn_delete_seconds == 0
    reply = await rig.run("t,brainrot config delete yes")
    assert reply is not None and rig.store.config.delete_messages is True
    reply = await rig.run("t,brainrot config mods on")
    assert reply is not None and rig.store.config.include_mods is True
    reply = await rig.run(f"t,brainrot config modlog <#{OTHER_CHANNEL_ID}>")
    assert reply is not None and rig.store.config.modlog_channel_id == OTHER_CHANNEL_ID
    reply = await rig.run("t,brainrot config modlog")
    assert reply is not None and rig.store.config.modlog_channel_id is None

    await rig.run("t,brainrot config show")
    card = last_card(rig)
    assert "Timeout for 10 minutes" in card and "1 hour → 12 hours → 3 days" in card and "Kept" in card
    assert "deleted" in card and "included" in card and "Not set" in card


async def test_pardon_clears_everything_and_lifts_the_mute(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    rig.store.config = replace(rig.store.config, modlog_channel_id=OTHER_CHANNEL_ID)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(
        heat=3, heat_updated_at=now, repeat_until=now + datetime.timedelta(days=2), escalation_level=2, lifetime_offenses=7
    )
    rig.store.mutes[(GUILD_ID, USER_ID)] = (now + datetime.timedelta(minutes=5), MUTE_ROLE_ID)
    rig.guild.get_member(USER_ID)._roles.add(MUTE_ROLE_ID)

    reply = await rig.run(f"t,brainrot pardon <@{USER_ID}>", author_id=MOD_ID)
    assert reply is not None and "pardoned" in reply
    state = state_of(rig)
    assert state.heat == 0 and state.repeat_until is None and state.escalation_level == 0 and state.lifetime_offenses == 7
    assert rig.calls.roles == [("remove", USER_ID, MUTE_ROLE_ID)] and (GUILD_ID, USER_ID) not in rig.store.mutes
    assert len(rig.calls.sent) == 2 and "Pardoned" in last_card(rig, -2)  # the mod log card went out first


async def test_partial_pardon_only_removes_heat(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(
        heat=4, heat_updated_at=now, repeat_until=now + datetime.timedelta(days=2)
    )
    reply = await rig.run(f"t,brainrot pardon <@{USER_ID}> 3", author_id=MOD_ID)
    assert reply is not None and "`1/5`" in reply
    assert state_of(rig).heat == 1 and state_of(rig).repeat_until is not None


async def test_every_outcome_and_pardon_lands_in_the_action_log(rig: SimpleNamespace) -> None:
    await rig.cog.inspect(rig.message("rizz"))
    await rig.cog.inspect(rig.message("rizz gyat skibidi sigma"))
    warning, spam = rig.store.logged
    assert warning["action"] == "warning" and warning["source"] == "auto" and warning["target_user_id"] == USER_ID
    assert warning["heat"] == 1 and warning["heat_added"] == 1 and warning["actor_user_id"] is None
    assert spam["action"] == "spam" and spam["heat"] == 3 and spam["applied"] is True
    assert all(row["field"] is None and row["before"] is None for row in rig.store.logged)  # never any text

    await rig.run(f"t,brainrot pardon <@{USER_ID}>", author_id=MOD_ID)
    pardon = rig.store.logged[-1]
    assert pardon["action"] == "pardon" and pardon["source"] == "command" and pardon["actor_user_id"] == MOD_ID
    assert pardon["heat"] == 0 and pardon["heat_added"] == -3

    await rig.run("t,brainrot config duration 10")
    change = rig.store.logged[-1]
    assert change["action"] == "config" and change["source"] == "command" and change["actor_user_id"] == OWNER_ID
    assert (change["field"], change["before"], change["after"]) == ("mute_seconds", "300", "600")
    before = len(rig.store.logged)
    await rig.run("t,brainrot config duration 10")  # the same value again is not a change
    assert len(rig.store.logged) == before


async def test_pardon_needs_moderate_members(rig: SimpleNamespace) -> None:
    await rig.bot.process_commands(rig.message(f"t,brainrot pardon <@{USER_ID}>", author_id=USER_ID))
    await asyncio.sleep(0)
    assert len(rig.calls.errors) == 1 and isinstance(rig.calls.errors[0], commands.MissingPermissions)


async def test_score_card(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=2, heat_updated_at=now, lifetime_offenses=6)
    rig.store.states[(GUILD_ID, EXEMPT_ID)] = HeatState(heat_updated_at=now, lifetime_offenses=20)
    await rig.run(f"t,brainrot score <@{USER_ID}>", author_id=USER_ID)
    card = last_card(rig)
    assert "# user" in card and "Medium" in card
    assert "▰▰▱▱▱ `2/5`" in card and "next point cools" in card
    assert "Clean" in card and "`6` offenses" in card and "#2 on the leaderboard" in card
    assert "ephemeral" not in rig.calls.sent[-1]  # public

    await rig.run("t,brainrot score", author_id=MOD_ID)  # defaults to yourself, no row yet
    card = last_card(rig)
    assert "# mod" in card and "Raw" in card and "▱▱▱▱▱ `0/5`" in card and "fully cooled off" in card


async def test_leaderboard_card(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    for user_id, offenses in ((USER_ID, 35), (EXEMPT_ID, 12), (MOD_ID, 3), (OWNER_ID, 1), (GONE_ID, 2)):
        rig.store.states[(GUILD_ID, user_id)] = HeatState(heat_updated_at=now, lifetime_offenses=offenses)
    await rig.run("t,brainrot leaderboard", author_id=USER_ID)
    card = last_card(rig)
    assert "# Most Cooked" in card
    assert "### #1 user\nCooked • `35` offenses" in card
    assert "### #2 exempt\nMedium • `12` offenses" in card
    assert "### #3 mod\nLightly Seared • `3` offenses" in card
    assert f"**#4** <@{GONE_ID}>" in card and "**#5** owner" in card  # a departed member falls back to a mention
    assert rig.calls.sent[-1]["allowed_mentions"].users is False


async def test_empty_leaderboard(rig: SimpleNamespace) -> None:
    reply = await rig.run("t,brainrot leaderboard", author_id=USER_ID)
    assert reply == "Nobody has been cooked here yet!"


def test_parse_ladder() -> None:
    assert parse_ladder("30m 2h 24h") == (1800, 7200, 86400)
    assert parse_ladder("30, 120, 1440") == (1800, 7200, 86400)
    assert parse_ladder("1d") == (86400,)
    assert parse_ladder("28d") == (28 * 86400,)
    assert parse_ladder("29d") is None
    assert parse_ladder("0m") is None
    assert parse_ladder("") is None
    assert parse_ladder("1h 2h 3h 4h 5h 6h") is None
    assert parse_ladder("soon") is None


def test_tier_titles() -> None:
    assert tier_title(0) == "Raw"
    assert tier_title(1) == "Lightly Seared"
    assert tier_title(4) == "Lightly Seared"
    assert tier_title(5) == "Medium"
    assert tier_title(99) == "Burnt"
    assert tier_title(1000) == "Charcoal"


# hardening: things discord does mid-session


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")


async def test_a_failed_warning_send_never_raises_or_loses_heat(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_reply(self, *args, **kwargs):
        raise forbidden()

    monkeypatch.setattr(discord.Message, "reply", broken_reply)
    await rig.cog.inspect(rig.message("rizz"))
    assert state_of(rig).heat == 1 and rig.calls.sent == []


async def test_owner_opted_in_gets_heat_but_is_never_punished(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, include_mods=True)
    rig.store.states[(GUILD_ID, OWNER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz", author_id=OWNER_ID))
    assert rig.calls.timeouts == [] and len(rig.calls.sent) == 1
    assert state_of(rig, OWNER_ID).heat == 0 and state_of(rig, OWNER_ID).repeat_until is not None


async def test_member_gone_by_the_time_a_role_mute_expires(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_found(self, member_id, /):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")

    monkeypatch.setattr(discord.Guild, "fetch_member", not_found)
    rig.guild._remove_member(rig.guild.get_member(USER_ID))
    rig.store.mutes[(GUILD_ID, USER_ID)] = (discord.utils.utcnow() - datetime.timedelta(seconds=1), MUTE_ROLE_ID)
    await rig.cog.expire_mutes()
    assert rig.calls.roles == [] and (GUILD_ID, USER_ID) not in rig.store.mutes


async def test_a_failed_unmute_is_kept_and_retried_later(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_remove(self, *roles, reason=None, atomic=True):
        raise forbidden()

    monkeypatch.setattr(discord.Member, "remove_roles", broken_remove)
    rig.guild.get_member(USER_ID)._roles.add(MUTE_ROLE_ID)
    rig.store.mutes[(GUILD_ID, USER_ID)] = (discord.utils.utcnow() - datetime.timedelta(seconds=1), MUTE_ROLE_ID)
    await rig.cog.expire_mutes()
    expires, role_id = rig.store.mutes[(GUILD_ID, USER_ID)]
    assert role_id == MUTE_ROLE_ID and 590 <= (expires - discord.utils.utcnow()).total_seconds() <= 600


async def test_role_mute_outlives_a_config_change(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, mute_mode="role", mute_role_id=MUTE_ROLE_ID)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert rig.calls.roles == [("add", USER_ID, MUTE_ROLE_ID)]

    rig.store.config = replace(
        rig.store.config, enabled=False, mute_mode="timeout", mute_role_id=None
    )  # admin changed their mind
    rig.store.mutes[(GUILD_ID, USER_ID)] = (discord.utils.utcnow() - datetime.timedelta(seconds=1), MUTE_ROLE_ID)
    await rig.cog.expire_mutes()
    assert rig.calls.roles[-1] == ("remove", USER_ID, MUTE_ROLE_ID) and (GUILD_ID, USER_ID) not in rig.store.mutes


async def test_missing_mod_log_channel_is_logged_not_raised(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, modlog_channel_id=BASE + 4040)
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=4, heat_updated_at=discord.utils.utcnow())
    await rig.cog.inspect(rig.message("rizz"))
    assert len(rig.calls.timeouts) == 1 and len(rig.calls.sent) == 1  # the warning went out, the mod log was skipped


async def test_prune_forgets_deleted_channels_roles_and_members(rig: SimpleNamespace) -> None:
    rig.store.config = replace(
        rig.store.config,
        channel_ids=frozenset({CHANNEL_ID, BASE + 4040}),
        exempt_role_ids=frozenset({EXEMPT_ROLE_ID, BASE + 4041}),
        exempt_user_ids=frozenset({USER_ID, GONE_ID}),
    )
    reply = await rig.run("t,brainrot prune")
    assert reply == "Pruned 3 entries that no longer exist."
    assert rig.store.config.channel_ids == {CHANNEL_ID}
    assert rig.store.config.exempt_role_ids == {EXEMPT_ROLE_ID} and rig.store.config.exempt_user_ids == {USER_ID}
    reply = await rig.run("t,brainrot prune")
    assert reply is not None and reply.startswith("Nothing to prune")


async def test_deleted_channel_shows_up_in_readiness(rig: SimpleNamespace) -> None:
    rig.store.config = replace(rig.store.config, enabled=False, channel_ids=frozenset({CHANNEL_ID, BASE + 4040}))
    reply = await rig.run("t,brainrot enable")
    assert reply is not None and f"<#{BASE + 4040}> no longer exists" in reply and rig.store.config.enabled is False
