"""The internal api, driven offline: real cogs on a real guild payload, the in-memory store, an aiohttp test client."""

from types import SimpleNamespace

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer
from discord.ext import commands
from test_brainrot_cog import (
    BASE,
    BOT_ID,
    BOT_ROLE_ID,
    CHANNEL_ID,
    EXEMPT_ROLE_ID,
    GONE_ID,
    GUILD_ID,
    MOD_ID,
    MOD_ROLE_ID,
    MUTE_ROLE_ID,
    OTHER_CHANNEL_ID,
    OWNER_ID,
    THREAD_ID,
    USER_ID,
    FakeStore,
    guild_payload,
    user,
)

import config
from exts.api import USER_HEADER, InternalApi
from exts.help import Help
from exts.utils.brainrot import BrainrotConfig
from exts.utils.heat import HeatState

TOKEN = "secret-token"
V1 = "/internal/v1"


async def _no_prefix(guild_id: int) -> str | None:
    return None


def headers(user_id: int | None = OWNER_ID, token: str | None = TOKEN) -> dict[str, str]:
    given: dict[str, str] = {}
    if token is not None:
        given["Authorization"] = f"Bearer {token}"
    if user_id is not None:
        given[USER_HEADER] = str(user_id)
    return given


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
    bot.settings = SimpleNamespace(get_prefix=_no_prefix)
    monkeypatch.setattr(config, "PREFIX", "t,")
    monkeypatch.setattr(config, "API_TOKEN", "", raising=False)  # empty while loading, so no real socket opens
    for ext in ("exts.brainrot", "exts.general", "exts.dev"):
        await bot.load_extension(ext)
    brainrot = bot.get_cog("Brainrot")
    assert brainrot is not None
    store = FakeStore(BrainrotConfig(GUILD_ID, enabled=True, channel_ids=frozenset({CHANNEL_ID})))
    brainrot.store = store  # type: ignore[attr-defined]
    await bot.add_cog(Help(bot))
    api = InternalApi(bot)
    await bot.add_cog(api)
    monkeypatch.setattr(config, "API_TOKEN", TOKEN, raising=False)

    sent: list[dict] = []

    async def fake_send(self, *args, **kwargs):
        sent.append({"to": self} | kwargs)
        return SimpleNamespace(id=1)

    async def fake_fetch_member(self, member_id: int):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")

    monkeypatch.setattr(discord.abc.Messageable, "send", fake_send)
    monkeypatch.setattr(discord.Guild, "fetch_member", fake_fetch_member)

    async with TestClient(TestServer(api.app)) as client:
        try:
            yield SimpleNamespace(bot=bot, guild=guild, api=api, brainrot=brainrot, store=store, client=client, sent=sent)
        finally:
            await bot.close()


async def body(response) -> dict:
    payload = await response.json()
    assert isinstance(payload, dict) and "ok" in payload
    return payload


# the door


async def test_missing_or_wrong_token_is_a_bare_401(rig: SimpleNamespace) -> None:
    for given in (headers(token=None), headers(token="nope"), {"Authorization": f"Basic {TOKEN}"}):
        response = await rig.client.get(f"{V1}/health", headers=given)
        assert response.status == 401
        assert await response.read() == b""
    # an unknown path is still a closed door, not a 404 that maps the api
    response = await rig.client.get(f"{V1}/nothing", headers=headers(token=None))
    assert response.status == 401


async def test_unknown_route_with_a_token_is_an_enveloped_404(rig: SimpleNamespace) -> None:
    response = await rig.client.get(f"{V1}/nothing", headers=headers())
    assert response.status == 404
    payload = await body(response)
    assert payload["ok"] is False and payload["error"]["code"] == "not_found"


async def test_health_reports_the_gateway(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    response = await rig.client.get(f"{V1}/health", headers=headers(user_id=None))
    assert response.status == 503 and (await body(response))["error"]["code"] == "unavailable"
    monkeypatch.setattr(commands.Bot, "is_ready", lambda self: True)
    monkeypatch.setattr(commands.Bot, "latency", property(lambda self: 0.042))
    response = await rig.client.get(f"{V1}/health", headers=headers(user_id=None))
    assert response.status == 200
    assert (await body(response))["data"] == {"ready": True, "latency_ms": 42, "guilds": 1}


async def test_app_describes_the_invite(rig: SimpleNamespace) -> None:
    data = (await body(await rig.client.get(f"{V1}/app", headers=headers(user_id=None))))["data"]
    assert data["application_id"] == str(BOT_ID) and data["prefix"] == "t,"
    permissions = discord.Permissions(int(data["permissions"]))
    assert permissions.moderate_members and permissions.manage_roles and permissions.manage_messages
    assert f"client_id={BOT_ID}" in data["invite_url"] and "applications.commands" in data["invite_url"]


# commands


async def test_commands_come_from_the_help_index_without_owner_only(rig: SimpleNamespace) -> None:
    data = (await body(await rig.client.get(f"{V1}/commands", headers=headers(user_id=None))))["data"]
    assert data["prefix"] == "t,"
    names = {command["name"]: command for category in data["categories"] for command in category["commands"]}
    assert "sync" not in names  # owner-only
    assert names["help"]["slash"] is True and names["help"]["usage"].startswith("/help")  # the slash-only one is public
    pardon = names["brainrot pardon"]
    assert pardon["permissions"] == ["Moderate Members"] and pardon["guild_only"] is True and pardon["slash"] is True
    assert pardon["usage"].startswith("/brainrot pardon") and pardon["slash_id"] is None  # nothing synced offline
    brainrot = next(category for category in data["categories"] if category["name"] == "Brainrot")
    assert brainrot["blurb"] == "Heat, mutes, and the leaderboard for brainrot vocabulary"
    assert all("Bot owner" not in command["permissions"] for command in names.values())


async def test_brainrot_defaults(rig: SimpleNamespace) -> None:
    data = (await body(await rig.client.get(f"{V1}/brainrot/defaults", headers=headers(user_id=None))))["data"]
    assert "skibidi" in data["default_terms"] and data["max_heat"] == 5
    assert data["tiers"][0] == {"min_offenses": 0, "title": "Raw"} and data["tiers"][-1]["title"] == "Charcoal"
    assert data["limits"]["channels"] == 50 and data["limits"]["term_length"] == {"min": 3, "max": 40}


# who may do what


async def test_guilds_lists_only_what_the_user_can_manage(rig: SimpleNamespace) -> None:
    data = (await body(await rig.client.get(f"{V1}/guilds", headers=headers(OWNER_ID))))["data"]
    assert [g["id"] for g in data] == [str(GUILD_ID)] and data[0]["owner"] is True and data[0]["accent"].startswith("#")
    for user_id in (MOD_ID, USER_ID, GONE_ID):
        data = (await body(await rig.client.get(f"{V1}/guilds", headers=headers(user_id))))["data"]
        assert data == []
    # this one endpoint also takes the user as a query parameter
    response = await rig.client.get(f"{V1}/guilds", params={"user_id": str(OWNER_ID)}, headers=headers(user_id=None))
    assert len((await body(response))["data"]) == 1
    response = await rig.client.get(f"{V1}/guilds", headers=headers(user_id=None))
    assert response.status == 400


async def test_guild_scoped_requests_are_checked_by_the_bot(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/config"
    assert (await rig.client.get(url, headers=headers(OWNER_ID))).status == 200
    for user_id in (MOD_ID, USER_ID):  # moderate members / nothing: neither is Manage Server
        response = await rig.client.get(url, headers=headers(user_id))
        assert response.status == 403 and (await body(response))["error"]["code"] == "forbidden"
    response = await rig.client.get(url, headers=headers(GONE_ID))  # not a member, fetch_member says so
    assert response.status == 403 and "not in that server" in (await body(response))["error"]["message"]
    response = await rig.client.get(url, headers=headers(user_id=None))
    assert response.status == 400 and (await body(response))["error"]["field"] == USER_HEADER
    response = await rig.client.get(f"{V1}/guilds/{BASE + 999}/brainrot/config", headers=headers())
    assert response.status == 404 and (await body(response))["error"]["code"] == "guild_not_found"
    response = await rig.client.get(f"{V1}/guilds/abc/brainrot/config", headers=headers())
    assert response.status == 400


async def test_manager_answers_are_cached(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/config"
    await rig.client.get(url, headers=headers(OWNER_ID))
    await rig.client.get(url, headers=headers(USER_ID))
    assert isinstance(rig.api._managers.get((GUILD_ID, OWNER_ID)), discord.Member)
    assert rig.api._managers.get((GUILD_ID, USER_ID)) is False


# furniture


async def test_meta_has_channels_roles_and_health(rig: SimpleNamespace) -> None:
    data = (await body(await rig.client.get(f"{V1}/guilds/{GUILD_ID}/meta", headers=headers())))["data"]
    assert data["id"] == str(GUILD_ID) and data["owner_id"] == str(OWNER_ID)
    channels = {c["id"]: c for c in data["channels"]}
    assert channels[str(CHANNEL_ID)]["type"] == "text" and str(THREAD_ID) not in channels
    roles = {r["id"]: r for r in data["roles"]}
    assert roles[str(GUILD_ID)]["everyone"] is True and roles[str(GUILD_ID)]["assignable"] is False
    assert roles[str(MUTE_ROLE_ID)]["assignable"] is True and roles[str(BOT_ROLE_ID)]["assignable"] is False
    assert data["me"]["permissions"]["moderate_members"] is True
    assert data["brainrot"] == {"ready": True, "problems": []}


async def test_member_search_and_lookup(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/members"
    data = (await body(await rig.client.get(f"{url}/search", params={"q": "mod"}, headers=headers())))["data"]
    assert [m["id"] for m in data] == [str(MOD_ID)] and data[0]["username"] == "mod"
    data = (await body(await rig.client.get(f"{url}/search", params={"q": str(USER_ID)}, headers=headers())))["data"]
    assert data[0]["id"] == str(USER_ID)
    assert (await rig.client.get(f"{url}/search", headers=headers())).status == 400
    data = (await body(await rig.client.get(f"{url}/{USER_ID}", headers=headers())))["data"]
    assert data["name"] == "user" and data["bot"] is False
    response = await rig.client.get(f"{url}/{GONE_ID}", headers=headers())
    assert response.status == 404 and (await body(response))["error"]["code"] == "not_found"


# config


async def test_config_patch_applies_through_the_shared_setters(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/config"
    data = (await body(await rig.client.get(url, headers=headers())))["data"]
    assert data["enabled"] is True and data["mute_seconds"] == 300 and data["counts"]["channels"] == 1

    response = await rig.client.patch(
        url, json={"mute_seconds": 600, "warn_delete_seconds": 0, "include_mods": True}, headers=headers()
    )
    data = (await body(response))["data"]
    assert response.status == 200
    assert data["mute_seconds"] == 600 and data["warn_delete_seconds"] == 0 and data["include_mods"] is True
    assert rig.store.config.mute_seconds == 600  # the cog's own store, not a copy
    rows = [row for row in rig.store.logged if row["action"] == "config"]
    assert {(row["field"], row["before"], row["after"]) for row in rows} == {
        ("mute_seconds", "300", "600"),
        ("warn_delete_seconds", "30", "0"),
        ("include_mods", "false", "true"),
    }
    assert all(row["source"] == "dashboard" and row["actor_user_id"] == OWNER_ID for row in rows)

    # a value the slash command would refuse is refused here with the same code
    response = await rig.client.patch(url, json={"mute_seconds": 30}, headers=headers())
    assert response.status == 422
    error = (await body(response))["error"]
    assert error["code"] == "invalid" and error["field"] == "mute_seconds"

    response = await rig.client.patch(url, json={"ladder_seconds": [60, 120, 180, 240, 300, 360]}, headers=headers())
    assert response.status == 422 and (await body(response))["error"]["field"] == "ladder_seconds"

    response = await rig.client.patch(url, json={"nonsense": 1}, headers=headers())
    assert response.status == 400

    response = await rig.client.patch(url, json={"mute_mode": "role"}, headers=headers())
    assert response.status == 422 and (await body(response))["error"]["field"] == "mute_role_id"

    response = await rig.client.patch(url, json={"mute_mode": "role", "mute_role_id": str(MUTE_ROLE_ID)}, headers=headers())
    data = (await body(response))["data"]
    assert data["mute_mode"] == "role" and data["mute_role_id"] == str(MUTE_ROLE_ID) and data["ready"] is True

    response = await rig.client.patch(url, json={"modlog_channel_id": str(OTHER_CHANNEL_ID)}, headers=headers())
    assert (await body(response))["data"]["modlog_channel_id"] == str(OTHER_CHANNEL_ID)
    # from here on dashboard changes echo into the mod log as a one-line card
    response = await rig.client.patch(url, json={"delete_messages": True}, headers=headers())
    assert response.status == 200
    assert rig.sent and rig.sent[-1]["to"].id == OTHER_CHANNEL_ID and "view" in rig.sent[-1]


async def test_enable_is_refused_with_the_readiness_problems(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/config"
    await rig.client.patch(url, json={"enabled": False}, headers=headers())
    # the bot's own role as the muted role: set_mode allows it, readiness does not
    await rig.client.patch(url, json={"mute_mode": "role", "mute_role_id": str(BOT_ROLE_ID)}, headers=headers())
    response = await rig.client.patch(url, json={"enabled": True}, headers=headers())
    assert response.status == 409
    error = (await body(response))["error"]
    assert error["code"] == "not_ready" and any("below my top role" in problem for problem in error["problems"])
    assert rig.store.config.enabled is False


# lists


async def test_channels_put_diffs_against_the_current_list(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/channels"
    data = (await body(await rig.client.get(url, headers=headers())))["data"]
    assert data["channels"] == [{"id": str(CHANNEL_ID), "name": "general", "type": "text", "exists": True}]

    response = await rig.client.put(url, json={"channel_ids": [str(OTHER_CHANNEL_ID), str(THREAD_ID)]}, headers=headers())
    data = (await body(response))["data"]
    assert response.status == 200
    assert [c["id"] for c in data["channels"]] == sorted([str(OTHER_CHANNEL_ID), str(THREAD_ID)])
    assert rig.store.config.channel_ids == {OTHER_CHANNEL_ID, THREAD_ID}
    changes = [(row["before"], row["after"]) for row in rig.store.logged if row["field"] == "channel_ids"]
    assert changes == [(str(CHANNEL_ID), None), (None, str(OTHER_CHANNEL_ID)), (None, str(THREAD_ID))]

    # an unknown channel stops the run; what was applied before it stays, and the body says so
    response = await rig.client.put(url, json={"channel_ids": [str(CHANNEL_ID), str(BASE + 555)]}, headers=headers())
    payload = await body(response)
    assert response.status == 404 and payload["error"]["code"] == "not_found"
    assert [c["id"] for c in payload["data"]["channels"]] == [str(CHANNEL_ID)]
    assert (await rig.client.put(url, json={"channel_ids": "no"}, headers=headers())).status == 400


async def test_terms_put_moves_words_between_the_lists(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/terms"
    response = await rig.client.put(url, json={"added": ["ohio", "Sybau"], "removed": ["sigma"]}, headers=headers())
    data = (await body(response))["data"]
    assert response.status == 200
    assert data["added"] == ["ohio", "sybau"] and data["removed"] == ["sigma"]
    assert "ohio" in data["active"] and "sigma" not in data["active"] and "skibidi" in data["active"]
    assert "sigma" in data["defaults"]

    response = await rig.client.put(url, json={"added": ["ohio"], "removed": []}, headers=headers())
    data = (await body(response))["data"]
    assert data["added"] == ["ohio"] and data["removed"] == [] and "sigma" in data["active"]

    response = await rig.client.put(url, json={"added": ["ohio", "no"], "removed": []}, headers=headers())
    payload = await body(response)
    assert response.status == 422 and payload["error"]["field"] == "added" and "3 to 40" in payload["error"]["message"]
    assert payload["data"]["added"] == ["ohio"]


async def test_allowlist_put(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/allowlist"
    data = (await body(await rig.client.put(url, json={"allowed": ["sigma", "griddy"]}, headers=headers())))["data"]
    assert data["allowed"] == ["sigma", "griddy"]
    terms = (await body(await rig.client.get(f"{V1}/guilds/{GUILD_ID}/brainrot/terms", headers=headers())))["data"]
    assert "sigma" not in terms["active"] and "griddy" not in terms["active"]
    data = (await body(await rig.client.put(url, json={"allowed": ["griddy"]}, headers=headers())))["data"]
    assert data["allowed"] == ["griddy"]


async def test_exemptions_put(rig: SimpleNamespace) -> None:
    url = f"{V1}/guilds/{GUILD_ID}/brainrot/exemptions"
    data = (await body(await rig.client.get(url, headers=headers())))["data"]
    assert data == {"roles": [], "users": [], "include_mods": False}

    payload = {"role_ids": [str(EXEMPT_ROLE_ID), str(MOD_ROLE_ID)], "user_ids": [str(USER_ID)]}
    data = (await body(await rig.client.put(url, json=payload, headers=headers())))["data"]
    assert [r["id"] for r in data["roles"]] == sorted([str(EXEMPT_ROLE_ID), str(MOD_ROLE_ID)])
    assert data["roles"][0]["exists"] is True and data["users"] == [
        {"id": str(USER_ID), "name": "user", "avatar": rig.guild.get_member(USER_ID).display_avatar.url, "exists": True}
    ]

    response = await rig.client.put(
        url, json={"role_ids": [str(EXEMPT_ROLE_ID)], "user_ids": [str(GONE_ID)]}, headers=headers()
    )
    payload = await body(response)
    assert response.status == 404 and payload["error"]["field"] == "user_id"
    assert [r["id"] for r in payload["data"]["roles"]] == [str(EXEMPT_ROLE_ID)]  # the removals before it stuck
    assert payload["data"]["users"] == []


# people


async def test_offenders_summary_pardon_and_actions(rig: SimpleNamespace) -> None:
    now = discord.utils.utcnow()
    rig.store.states[(GUILD_ID, USER_ID)] = HeatState(heat=3, heat_updated_at=now, lifetime_offenses=7)
    rig.store.states[(GUILD_ID, MOD_ID)] = HeatState(heat=0, heat_updated_at=now, lifetime_offenses=20)
    base = f"{V1}/guilds/{GUILD_ID}/brainrot"

    payload = await body(await rig.client.get(f"{base}/offenders", headers=headers()))
    assert payload["page"] == {"page": 1, "per_page": 25, "total": 2, "pages": 1}
    first, second = payload["data"]
    assert first["user_id"] == str(USER_ID) and first["heat"] == 3 and first["title"] == "Medium" and first["rank"] == 2
    assert first["name"] == "user" and first["in_guild"] is True and first["cooling_at"] is not None
    assert second["user_id"] == str(MOD_ID) and second["title"] == "Well Done" and second["rank"] == 1

    payload = await body(
        await rig.client.get(f"{base}/offenders", params={"sort": "lifetime", "per_page": "1"}, headers=headers())
    )
    assert payload["data"][0]["user_id"] == str(MOD_ID) and payload["page"]["pages"] == 2
    assert (await rig.client.get(f"{base}/offenders", params={"sort": "zzz"}, headers=headers())).status == 400
    assert (await rig.client.get(f"{base}/offenders", params={"per_page": "0"}, headers=headers())).status == 400

    data = (await body(await rig.client.get(f"{base}/summary", headers=headers())))["data"]
    assert data["hot_users"] == 1 and data["lifetime_offenses"] == 27 and data["watched_channels"] == 1

    response = await rig.client.post(f"{base}/pardon", json={"user_id": str(USER_ID)}, headers=headers())
    data = (await body(response))["data"]
    assert response.status == 200
    assert data == {"user_id": str(USER_ID), "heat": 0, "repeat": False, "lifted_mute": False}
    assert rig.store.states[(GUILD_ID, USER_ID)].heat == 0
    pardon = rig.store.logged[-1]
    assert pardon["action"] == "pardon" and pardon["source"] == "dashboard"
    assert pardon["target_user_id"] == USER_ID and pardon["actor_user_id"] == OWNER_ID and pardon["heat_added"] == -3

    response = await rig.client.post(f"{base}/pardon", json={"user_id": str(GONE_ID)}, headers=headers())
    assert response.status == 404
    response = await rig.client.post(f"{base}/pardon", json={"user_id": str(USER_ID), "amount": 9}, headers=headers())
    assert response.status == 422 and (await body(response))["error"]["field"] == "amount"

    payload = await body(await rig.client.get(f"{base}/actions", headers=headers()))
    assert payload["page"]["total"] == 1 and payload["data"][0]["action"] == "pardon"
    assert payload["data"][0]["actor"]["id"] == str(OWNER_ID) and payload["data"][0]["target"]["name"] == "user"
    payload = await body(await rig.client.get(f"{base}/actions", params={"action": "config"}, headers=headers()))
    assert payload["data"] == [] and payload["page"]["pages"] == 1
    assert (await rig.client.get(f"{base}/actions", params={"source": "aliens"}, headers=headers())).status == 400
