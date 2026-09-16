# Internal API

The contract between the bot and its dashboard. The bot serves this API; the
dashboard is its only client. This file is the source of truth for both
repos: the bot's handlers and the dashboard's zod schemas are both written
from it, and a change here lands in both before it ships.

Status: **draft (Phase 0)**. Finalized at the end of Phase 1.

## Shape

- Served by the bot process from aiohttp, on the bot's event loop, at
  `http://superiorspork:8080/internal/v1`. The host is the bot container's
  name on the private `spork-internal` Docker network (`internal: true`, no
  published ports, no Traefik router). Nothing outside that network can
  reach it.
- The bot owns every read, write, validation, and permission check. The
  dashboard never touches the database. Every mutation here calls the same
  function the matching slash command calls.
- Handlers never block the gateway: no per-request member fetch storms, no
  message content, no bulk Discord API calls.

## Authentication

Every request carries `Authorization: Bearer <API_TOKEN>`. The token lives in
the bot's `config.py` (`API_TOKEN`) and the dashboard's env (`BOT_API_TOKEN`);
they are the same value. The bot compares it in constant time and never logs
it. A missing or wrong token gets **`401` with an empty body**: no envelope, no
hint. When `API_TOKEN` is empty the bot does not start the server at all.

## The acting user

Every user-scoped request carries `X-Acting-User-Id: <discord user id>`, the
Discord ID of the person using the dashboard. For each guild-scoped request
the bot verifies, from its own guild data, that this user is a member of the
guild and either owns it or has **Manage Server**. Otherwise `403 forbidden`.
The lookup is `guild.get_member()` with a `fetch_member()` fallback, cached
for 60 seconds per `(guild, user)`.

The dashboard's own permission check is UX only. This one is the real one.

Endpoints marked *no user* below don't read the header.

## Envelope

Success:

```json
{ "ok": true, "data": ... }
```

Paginated success:

```json
{ "ok": true, "data": [ ... ], "page": { "page": 1, "per_page": 25, "total": 137, "pages": 6 } }
```

Error:

```json
{ "ok": false, "error": { "code": "limit_reached", "message": "That's the limit — 50 channels per server.", "field": "channel_ids" } }
```

`message` is written for the admin and the dashboard shows it verbatim; the
wording is the same the slash command would have replied with. `field` names
the request field that failed when there is one. `problems` (a list of
strings) is added on `not_ready`.

### Error codes

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | malformed JSON, a missing header, an ID that isn't a snowflake, an unknown query value |
| 403 | `forbidden` | the acting user isn't in the guild, or lacks Manage Server and doesn't own it |
| 404 | `guild_not_found` | the bot isn't in that guild |
| 404 | `not_found` | a channel, role, member, or user in the request doesn't exist in this guild |
| 404 | `module_unavailable` | the cog that owns the resource isn't loaded |
| 409 | `not_ready` | `enabled: true` refused; `problems` lists what to fix, in the words of `brainrot enable` |
| 422 | `invalid` | a value failed the same validation the slash command applies |
| 422 | `limit_reached` | a per-server cap was hit (channels, custom terms, exemptions) |
| 503 | `unavailable` | the bot isn't ready (gateway down or still connecting) |
| 500 | `internal` | anything unexpected; logged with a traceback bot-side, no details leak |

Snowflakes are **strings** everywhere in JSON (they overflow a JS number).
Timestamps are ISO 8601 in UTC. Durations are integer seconds. Colours are
`#rrggbb` or `null`.

## Endpoints

### `GET /health` *(no user)*

For the Docker `HEALTHCHECK` and the dashboard's deep health route.

```json
{ "ready": true, "latency_ms": 41, "guilds": 12 }
```

`503 unavailable` when the bot isn't ready or the latency isn't a finite
number.

### `GET /app` *(no user)*

What the dashboard needs to build "Add to server" links without hardcoding
anything the bot already knows.

```json
{
  "application_id": "1227088846655586384",
  "permissions": "1099780063302",
  "invite_url": "https://discord.com/oauth2/authorize?client_id=...&scope=bot%20applications.commands&permissions=...",
  "prefix": ",,"
}
```

`permissions` is the permission integer the bot needs across every module
(Moderate Members and Manage Roles included), as a string. The dashboard
appends `guild_id` and `disable_guild_select=true` to `invite_url`.

### `GET /commands` *(no user)*

Every public command, from the help cog's shared index (`build_index`), so the
dashboard and `/help` can never disagree. Hidden commands and anything that
needs **Bot owner** are excluded. Not guild-scoped: usage strings use the
default prefix.

```json
{
  "prefix": ",,",
  "categories": [
    {
      "name": "Brainrot",
      "blurb": "Heat, mutes, and the leaderboard for brainrot vocabulary",
      "emoji": null,
      "commands": [
        {
          "name": "brainrot pardon",
          "shown_name": "/brainrot pardon",
          "description": "Clears someone's heat, repeat flag, and any mute I applied",
          "details": "Clears someone's heat, repeat flag, and any mute I applied",
          "usage": "/brainrot pardon <member> [amount]",
          "example": "/brainrot pardon member:@someone",
          "permissions": ["Moderate Members"],
          "guild_only": true,
          "cooldown": null,
          "slash": true,
          "slash_id": "1417000000000000000"
        }
      ]
    }
  ]
}
```

Categories are in the order `/help` shows them ("Other" last). `slash_id` is
`null` before the first sync; the dashboard then shows plain text instead of
a command mention.

### `GET /brainrot/defaults` *(no user)*

Constants the anti-brainrot screens need, from the engine itself.

```json
{
  "default_terms": ["skibidi", "gyat", "rizz", "..."],
  "tiers": [ { "min_offenses": 0, "title": "Raw" }, { "min_offenses": 1, "title": "Lightly Seared" }, { "min_offenses": 100, "title": "Charcoal" } ],
  "max_heat": 5,
  "decay_seconds": 3600,
  "window_seconds": 30,
  "window_cap": 3,
  "spam_hits": 4,
  "repeat_days": 7,
  "mute_modes": ["timeout", "role"],
  "limits": {
    "channels": 50,
    "custom_terms": 100,
    "exemptions": 50,
    "term_length": { "min": 3, "max": 40 },
    "ladder_steps": 5,
    "mute_seconds": { "min": 60, "max": 2419200 },
    "warn_delete_seconds": { "min": 0, "max": 600 },
    "max_timeout_seconds": 2419200
  }
}
```

`404 module_unavailable` if the Brainrot cog isn't loaded.

### `GET /guilds`

The guilds the acting user can manage, out of the guilds the bot is in. The
user comes from `X-Acting-User-Id`, or `?user_id=` for this endpoint only.

```json
[
  { "id": "1234", "name": "Kitchen", "icon": "https://cdn.discordapp.com/icons/...png?size=128", "accent": "#f2d9c0", "owner": true }
]
```

`accent` is the bot's own stable pastel for the guild (`pastel_color(guild.id)`),
so the dashboard can match the cards the bot posts. Empty list when the user
manages nothing. Cache-only: the members intent keeps every guild's member
list in memory, so no fetch happens here.

### `GET /guilds/{id}/meta`

Everything a guild-scoped screen needs to render pickers and the permission
health panel.

```json
{
  "id": "1234",
  "name": "Kitchen",
  "icon": "https://...",
  "accent": "#f2d9c0",
  "owner_id": "99",
  "channels": [
    { "id": "1", "name": "general", "type": "text", "position": 0, "category": { "id": "10", "name": "Chat" } },
    { "id": "2", "name": "voice-chat", "type": "voice", "position": 1, "category": null }
  ],
  "roles": [
    { "id": "5", "name": "Muted", "color": "#99aab5", "position": 3, "managed": false, "everyone": false, "assignable": true }
  ],
  "me": {
    "top_role_id": "7",
    "permissions": { "view_channel": true, "send_messages": true, "embed_links": true, "manage_messages": true, "moderate_members": false, "manage_roles": true }
  },
  "brainrot": { "ready": false, "problems": ["I need Moderate Members to time people out"] }
}
```

`type` is one of `text`, `announcement`, `voice`, `stage`, `forum`, `media`.
Threads are not listed. `assignable` is true when the role is below the bot's
top role and not managed — the ones the bot could actually hand out.
`brainrot.problems` is exactly what `brainrot enable` would print
(`readiness()`), against the current config.

### `GET /guilds/{id}/brainrot/config`

```json
{
  "enabled": true,
  "mute_mode": "timeout",
  "mute_role_id": null,
  "mute_seconds": 300,
  "ladder_seconds": [1800, 7200, 86400],
  "warn_delete_seconds": 30,
  "delete_messages": false,
  "include_mods": false,
  "modlog_channel_id": "42",
  "ready": true,
  "problems": [],
  "counts": { "channels": 3, "terms": 21, "added": 2, "removed": 1, "allowed": 1, "exempt_roles": 1, "exempt_users": 0 }
}
```

### `PATCH /guilds/{id}/brainrot/config`

Any subset of:

```json
{
  "enabled": true,
  "mute_mode": "role",
  "mute_role_id": "5",
  "mute_seconds": 600,
  "ladder_seconds": [1800, 7200, 86400],
  "warn_delete_seconds": 0,
  "delete_messages": true,
  "include_mods": false,
  "modlog_channel_id": null
}
```

Applied in this order, each through the function the matching slash command
uses: `mute_mode` + `mute_role_id` (`config mode`), `mute_seconds`
(`config duration`), `ladder_seconds` (`config ladder`), `warn_delete_seconds`
(`config warnings`), `delete_messages` (`config delete`), `include_mods`
(`config mods`), `modlog_channel_id` (`config modlog`), and `enabled` last
(`enable` / `disable`, so the readiness check sees the new settings). The
first failure stops the run and returns its error with `field` set; fields
before it stay applied. Response is the `GET` shape.

Validation, same as the commands: `mute_mode: "role"` needs a
`mute_role_id` that exists, isn't `@everyone`, and isn't managed;
`mute_seconds` is `60..2419200` in whole minutes; `ladder_seconds` is 1–5
steps each `1..2419200`; `warn_delete_seconds` is `0..600`;
`modlog_channel_id` is a text channel or thread in the guild, or `null`.
`enabled: true` runs `readiness()` and answers `409 not_ready` with
`problems` when anything is missing.

Every applied field writes one `config` row to the action log and, when a mod
log channel is set, posts one line there:
`Settings changed by @admin via dashboard: mute duration 5 minutes → 10 minutes`.

### `GET /guilds/{id}/brainrot/channels`

```json
{ "channels": [ { "id": "1", "name": "general", "type": "text", "exists": true }, { "id": "3", "name": null, "type": null, "exists": false } ] }
```

### `PUT /guilds/{id}/brainrot/channels`

```json
{ "channel_ids": ["1", "2"] }
```

The bot diffs against the current list: removals first (`channels remove`),
then additions (`channels add`). Each ID must be a text, announcement,
voice, forum, media channel, or thread in this guild. Response is the `GET`
shape. A `limit_reached` or `not_found` stops at that item; earlier items
stay applied, and the response body carries the current state so the UI can
re-render honestly.

### `GET /guilds/{id}/brainrot/terms`

```json
{
  "active": ["skibidi", "gyat", "..."],
  "defaults": ["skibidi", "gyat", "..."],
  "added": ["ohio"],
  "removed": ["sigma"],
  "allowed": ["sigma"]
}
```

`active` is what the matcher compiles: defaults plus `added`, minus `removed`
and `allowed`. Terms are stored normalized (casefolded, accents and leetspeak
folded), so what comes back may differ from what was typed.

### `PUT /guilds/{id}/brainrot/terms`

```json
{ "added": ["ohio", "sybau"], "removed": ["sigma"] }
```

`removed` is the set of default terms toggled off; `added` is the custom
list. Diffed and applied through `terms remove` then `terms add`: dropping a
term from `removed` lifts the removal, adding a default to `added` is a
no-op. Validation: 3–40 characters after normalization, at most 100 custom
terms, no duplicates of an active term. Response is the `GET` shape.

### `GET /guilds/{id}/brainrot/allowlist` · `PUT`

```json
{ "allowed": ["sigma"] }
```

Same diff semantics through `allow add` / `allow remove`; same length and
count limits as terms.

### `GET /guilds/{id}/brainrot/exemptions`

```json
{
  "roles": [ { "id": "5", "name": "Staff", "color": "#5865f2", "exists": true } ],
  "users": [ { "id": "77", "name": "jaden", "avatar": "https://...", "exists": true } ],
  "include_mods": false
}
```

`exists` is false for a role or member that has since left; `name` and
`avatar` are `null` then. `include_mods` is read-only here (it's a config
field) and shown so the screen can explain who is exempt by default.

### `PUT /guilds/{id}/brainrot/exemptions`

```json
{ "role_ids": ["5"], "user_ids": ["77", "78"] }
```

Diffed through `exempt remove` / `exempt add`. Each role must exist in the
guild; each user must be a current member (cache, then one `fetch_member`).
At most 50 of each kind.

### `GET /guilds/{id}/members/search?q=`

For the exemptions and pardon pickers. Resolves from the member cache first
(display name, username, or an exact ID), then one `query_members` gateway
request for prefix matches. Needs no intent the bot doesn't already have.
At most 10 results.

```json
[ { "id": "77", "name": "jaden", "username": "jaden", "avatar": "https://...", "bot": false } ]
```

### `GET /guilds/{id}/members/{user_id}`

One member, cache then `fetch_member`. `404 not_found` if they aren't in the
guild.

### `GET /guilds/{id}/brainrot/summary`

Numbers for the overview card.

```json
{
  "enabled": true,
  "watched_channels": 3,
  "hot_users": 4,
  "muted_now": 1,
  "on_repeat_list": 2,
  "lifetime_offenses": 318,
  "actions_24h": 12
}
```

`hot_users` counts members whose decayed heat is above zero, computed in SQL
with the engine's formula (one point per whole hour since the last change).

### `GET /guilds/{id}/brainrot/offenders?page=&per_page=&sort=`

Paginated. `sort=heat` (default) orders by decayed heat, then lifetime
offenses; `sort=lifetime` is the leaderboard order. `per_page` is `1..100`,
default 25.

```json
[
  {
    "user_id": "77",
    "name": "jaden",
    "avatar": "https://...",
    "in_guild": true,
    "heat": 3,
    "cooling_at": "2026-09-16T07:00:00+00:00",
    "repeat": true,
    "repeat_until": "2026-09-23T06:00:00+00:00",
    "escalation_level": 1,
    "lifetime_offenses": 17,
    "title": "Well Done",
    "rank": 2,
    "muted_until": null
  }
]
```

`heat` has decay applied (`HeatEngine.decayed`), `cooling_at` is when the
next point drops, `title` comes from the same `TIERS` table the leaderboard
command uses, `rank` is the lifetime position (only when `lifetime_offenses
> 0`), and `muted_until` is set only for a mute the bot itself applied.
`name` and `avatar` are `null` when the user isn't cached.

### `POST /guilds/{id}/brainrot/pardon`

```json
{ "user_id": "77", "amount": 0 }
```

`amount` `0` or omitted clears everything (heat, repeat flag, the bot's own
mute); `1..5` takes that much heat off. The target must be a current member.
Runs the same code path as `brainrot pardon`: under the per-user lock, the
engine's `pardon`, then `lift()`, the mod log card, and an action log row
with `actor_user_id` = the acting user and `source: "dashboard"`.

```json
{ "user_id": "77", "heat": 0, "repeat": false, "lifted_mute": true }
```

Note the slash command is gated on Moderate Members; the dashboard as a
whole is gated on Manage Server, so a Moderate-Members-only mod uses the
command, not the dashboard.

### `GET /guilds/{id}/brainrot/actions?page=&per_page=&action=&source=`

Paginated, newest first. `action` filters to one of `warning`, `spam`,
`mute`, `timeout`, `pardon`, `config`; `source` to one of `auto`,
`command`, `dashboard`.

```json
[
  {
    "id": "5120",
    "at": "2026-09-16T06:01:12+00:00",
    "action": "mute",
    "source": "auto",
    "applied": true,
    "target": { "id": "77", "name": "jaden", "avatar": "https://..." },
    "actor": null,
    "heat": 5,
    "heat_added": 1,
    "duration_seconds": 300,
    "escalation_level": 0,
    "field": null,
    "before": null,
    "after": null
  },
  {
    "id": "5121",
    "at": "2026-09-16T06:03:40+00:00",
    "action": "config",
    "source": "dashboard",
    "applied": true,
    "target": null,
    "actor": { "id": "99", "name": "admin", "avatar": null },
    "heat": null,
    "heat_added": null,
    "duration_seconds": null,
    "escalation_level": null,
    "field": "mute_seconds",
    "before": "300",
    "after": "600"
  }
]
```

`actor` is `null` for automatic actions (the bot acted). `applied` is false
when a mute or timeout was earned but not applied (`blocker()` said no, or
Discord refused); the row still exists so the feed shows the event.
`before` / `after` are short rendered values — a number, an ID, a term, or a
mode — never message text. List fields produce one row per item with the
other side `null`.

## The action log

New table `brainrot_actions` in `database/schema.sql`:

| column | type | notes |
|---|---|---|
| `id` | `bigserial` | |
| `guild_id` | `bigint` | |
| `at` | `timestamptz` | |
| `action` | `text` | `warning` `spam` `mute` `timeout` `pardon` `config` |
| `source` | `text` | `auto` `command` `dashboard` |
| `applied` | `boolean` | default true |
| `target_user_id` | `bigint` | null for config |
| `actor_user_id` | `bigint` | null for automatic actions |
| `heat` | `integer` | |
| `heat_added` | `integer` | |
| `duration_seconds` | `integer` | |
| `escalation_level` | `integer` | |
| `field` | `text` | config rows only |
| `before` | `text` | config rows only |
| `after` | `text` | config rows only |

Index on `(guild_id, at DESC)`. Rows older than **30 days** are pruned by the
cog's existing daily `cleanup` loop, which also caps each guild at its newest
5,000 rows so one loud server can't grow the table without bound. Everything
for a guild is deleted with the rest of its data when the bot leaves it.

Rows are written from the same places the mod log is posted from, so the
command path and the dashboard path can't diverge: `_respond` (warnings,
spam, mutes, timeouts — `source: auto`), the shared pardon function
(`command` or `dashboard`), and the shared config setters (`command` or
`dashboard`).

## Pagination

`page` starts at 1, `per_page` is `1..100` (default 25). Out-of-range pages
return an empty `data` with the real `total`. `page.pages` is at least 1.

## Versioning

The path carries `v1`. Additive changes (new fields, new endpoints) don't
bump it; the dashboard's zod schemas must tolerate unknown fields. Renaming
or removing a field does bump it, and both repos move together.
