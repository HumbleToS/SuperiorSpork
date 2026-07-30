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
