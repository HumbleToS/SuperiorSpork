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
