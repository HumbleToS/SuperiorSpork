# HUMAN-TODO.md

Format: `- [ ] <action> :: <why> :: <blocking or not>`

## Decisions needed

- [ ] Confirm ruff `quote-style = "double"` :: double is the dominant style (13/15 files); `exts/utils/embeds.py` is the single-quote exception and would be normalized in the Phase 1 sweep commit; the alternative is `"preserve"` which freezes the inconsistency :: blocking Phase 1
- [ ] Confirm intent trim (`invites`, `reactions`, `voice_states`, `emojis`) :: nothing in the visible tree uses them, but `exts/private/` is gitignored and invisible to the audit — if a private cog uses reaction/voice/invite events, say so :: blocking the intents item in Phase 2
- [ ] Decide the `guilds(id, prefix)` table's fate: wire per-guild prefixes through a config accessor (CLAUDE.md §14.1, recommended) or drop the table :: it's dead schema today; the accessor is the one dashboard-prep item that's expensive to retrofit later :: blocking that Phase 2 item only
- [ ] Confirm switching `config.py` to read env vars (same names, `os.environ`-backed, `.env` + `.env.example`) :: the container deploy pattern requires `env_file`; secrets currently live as literals in the gitignored file (verified never committed) :: blocking Phase 7
- [ ] Approve renaming class `ErorrHandler` → `ErrorHandler` :: internal-only typo, zero user visibility; you said "no errors", so flagging rather than silently renaming :: not blocking
- [ ] `exts/private/` can't be audited from this tree :: any deprecations, bugs, or intent dependencies in private cogs are uncovered by AUDIT.md :: not blocking

## CLAUDE.md `{{CONFIRM}}` tokens still open

- [ ] §1 header: bot name, purpose line, entry point (`bot.py`), package manager (pip today; uv an option), Python version (host is 3.13; ruff says py311 — pick one) :: launch blockers per the contract :: blocking before "done"
- [ ] §13 Docker: base image minor version, image/container names :: needed in Phase 7 :: blocking Phase 7
- [ ] §13.5 Traefik: external network name, entrypoint, cert resolver, auth middleware for `/health`, and the status hostname :: I will not invent these :: blocking Phase 7
- [ ] Note: CLAUDE.md itself is currently untracked (`??` in git status) — commit it when you're happy with it :: it's the contract the CI token-scan will read :: not blocking

## Dashboard-readiness notes (CLAUDE.md §14.4, log-only)

- [ ] Pick the eventual dashboard hostname :: changing it later means re-registering the OAuth redirect URI :: not blocking
- [ ] A dashboard will need an OAuth2 redirect URI + client secret in the Developer Portal :: portal work only you can do :: not blocking
- [ ] Confirm datastore owner: recommendation is "bot owns it" (dashboard talks to the bot's internal API; SQLite/Postgres stays single-writer) :: CLAUDE.md §14.3 asks for this in writing :: not blocking
