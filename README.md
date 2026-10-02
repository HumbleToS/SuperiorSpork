# SuperiorSpork
A discord bot made with discord.py that I like using!

## Running it

The bot lives in Docker next to its own Postgres (`compose.yaml`: the
`superiorspork` container and `spork-db`, no published ports). First run:

```bash
cp config.example.py config.py   # fill in TOKEN; point both DSNs at
                                 # postgresql://spork:<password>@db:5432/spork
chmod 600 config.py
setfacl -m u:10001:r config.py   # the container runs as UID 10001
POSTGRES_PASSWORD=<same password> docker compose up -d --build
```

Postgres reads `POSTGRES_PASSWORD` only when its data volume is first
created; after that a plain `docker compose up -d --build bot` deploys a new
build, `docker compose logs -f bot` follows startup, and `docker compose stop`
shuts down cleanly in a second or two.

## Config

`config.py` is the single config/secrets file (gitignored, never in the
image). Every value has a `_value` / `_test_value` pair and the `TESTING`
flag picks which side is live. There is no `.env`.

## Intents

Three privileged intents must be enabled in the Developer Portal:

- **Server Members** — member lists, join dates, mutual servers, join/leave
  counts
- **Message Content** — prefix commands and cleanup's prefix check
- **Presence** — spotify and status counts in whois/serverinfo, online counts
  in the developer tools

## Commands

Default prefix is set in `config.py`; server owners can change theirs with
the `prefix` command (also mentions the bot to see the current one). Slash
commands are published with the owner-only `sync` prefix command — run it
once after adding or changing commands. `jishaku` is loaded for owner
debugging.

`/help` is ephemeral and lists only what you can run where you are, with a
category picker, paged command lists, and a detail view per command
(`/help command:` jumps straight there; `public:` posts it for everyone,
Manage Messages only). The prefix `help` can't be ephemeral, so it goes to
your DMs with a short note in the channel, or posts briefly in-channel when
your DMs are closed (`HELP_PREFIX_MODE`, `HELP_DM_NOTE_SECONDS`,
`HELP_TEMP_SECONDS` in `config.py`). `DASHBOARD_URL`, when set, adds a
dashboard line for Manage Server members.

## Voice recaps

Explicit-consent voice recording with AI recaps and a searchable journal —
a paid feature metered by recorded minutes per month (Free 30 min, tiers via
Discord Premium Apps).

- `record setup` (Manage Server) picks the recorder role, recap channel, and
  retention window; `record start` / `record stop` run a session with a
  visible disclosure card. Recording never starts any other way.
- Consent is per user per server and enforced at capture: audio from anyone
  who hasn't pressed the consent button (or who used `optout`) never touches
  disk. `optin` reverses an opt-out.
- Raw audio is deleted the moment transcription finishes; transcripts and
  recaps live for the retention window (default 90 days) and die with
  `recap delete` or when the bot leaves the server.
- `recap latest` / `recap list` / `recap search` / `journal` read the
  archive; `minutes` shows usage and quota; `privacy` and `report` are the
  compliance surfaces.
- New `config.py` keys: `ANTHROPIC_KEY`, `RECAP_MODEL`, `WHISPER_MODEL`,
  `WHISPER_THREADS`, `MODELS_DIR`, `SKU_TIER_1`, `SKU_TIER_2`,
  `REPORT_CHANNEL_ID`, `PRIVACY_URL`, `TERMS_URL` — see `config.example.py`.

## Internal API

The dashboard at `sprok.umbleh.dev` talks to the bot over a small aiohttp
API (`exts/api.py`) that only exists on the private `spork-internal` Docker
network — no published port, no Traefik route. One bearer token
(`API_TOKEN` in `config.py`; empty keeps the server off) and, per request,
the acting Discord user's id, which the bot checks for Manage Server itself.
Every write calls the same function the matching slash command calls, and
an action log (`brainrot_actions`, numbers and ids only, 30 days) feeds the
dashboard's activity view. The contract is `docs/internal-api.md`.

## Anti-brainrot

An opt-in, per-server heat system for brainrot vocabulary (skibidi, gyatt,
rizz, and friends). Detection is a wordlist, so it costs nothing to run and
is free for every server; only heat numbers, counters, and timestamps are
ever stored, never message text.

- Off by default. `brainrot enable` (Manage Server) checks the bot has what
  it needs and says exactly what's missing; `brainrot channels add` opts
  channels in one at a time (threads and forum posts follow their parent).
- Every offending message is +1 heat with a warning that never pings and
  auto-deletes; three in 30 seconds (or one stuffed message) is spam worth
  +3; heat 5 is a 5-minute timeout (or a muted role, `brainrot config
  mode`), after which the user is a repeat offender for 7 days and the next
  offenses climb 30m → 2h → 24h. Heat cools 1 point an hour.
- Mods are exempt by default (`brainrot config mods` opts them in), plus
  per-role and per-user `brainrot exempt`. `brainrot terms` and
  `brainrot allow` tune the vocabulary per server; `brainrot config` has the
  rest (durations, ladder, warning lifetime, deleting messages, mod log).
- `brainrot pardon` (Moderate Members) clears someone; `brainrot score` and
  `brainrot leaderboard` are public — the leaderboard ranks lifetime
  offenses with cooking-tier titles.

## Activity counts

Every server the bot is in gets activity counts: messages, joins, leaves, and
commands per day, by channel, by hour (UTC), and by member — numbers only,
never message text (the message event is counted, the content is never read).
Counts accumulate in memory and are written in one batched upsert a minute
(`STATS_FLUSH_SECONDS`) and on shutdown; nothing is written per message and
nothing is ever backfilled from history. Daily rows live 90 days; a server's
rows go seven days after the bot leaves it (in case the kick was a mistake),
or immediately with `stats off` (Manage Server), which also stops collection;
`stats on` starts fresh. The query service in `exts/utils/stats.py` returns
plain dataclasses, so a dashboard can reuse it.

## Developer tools

`/dev` is a user-install-only slash group pinned to the ids in
`DEV_OWNER_IDS` (`config.py`; empty fails closed). Once the owner has
user-installed the bot it works in any server and in DMs; server admins never
get it through the guild install, help never lists it, and anyone else gets a
bare "Not available." Every use is written to `dev_audit` (and, with
`DEV_LOG_CHANNEL_ID`, posted as one line), viewable with `/dev audit`.

- `/dev server view` — a mini server viewer: overview, the channel sidebar
  (categories, type icons, locked and age-restricted marks, voice occupancy,
  active threads), the member sidebar grouped by hoisted role, and roles with
  member counts. Paginated, 180 s timeout, mentions only inside the server
  they belong to.
- `/dev server insights` and `/dev user insights` — a snapshot card plus one
  four-panel chart (Pillow, `assets/fonts/Inter`, rendered off the event loop
  and cached five minutes): messages per day, joins vs leaves or activity by
  hour, top channels, and top commands. User activity is always one server at
  a time. Charts say "Tracking since" when history is partial.
- `/dev purge user_id: [guild]` deletes a user's stored counts for data
  deletion requests.
- Every response is ephemeral with a **Share to chat** button that posts a
  static snapshot; sharing another server's card, or a user's, asks first.

