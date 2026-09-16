# SuperiorSpork
A discord bot made with discord.py that I like using!

## Running it

The bot lives in Docker next to its own Postgres — see [DEPLOY.md](DEPLOY.md)
for the full story. The short version:

```bash
cp config.example.py config.py   # fill in TOKEN and the DSNs
chmod 600 config.py
setfacl -m u:10001:r config.py
docker compose up -d --build
```

## Config

`config.py` is the single config/secrets file (gitignored, never in the
image). Every value has a `_value` / `_test_value` pair and the `TESTING`
flag picks which side is live. There is no `.env`.

## Intents

Three privileged intents must be enabled in the Developer Portal:

- **Server Members** — member lists, join dates, mutual servers
- **Message Content** — prefix commands and cleanup's prefix check
- **Presence** — spotify and status counts in whois/serverinfo

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
