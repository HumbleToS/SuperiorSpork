# HUMAN-TODO.md

Format: `- [ ] <action> :: <why> :: <blocking or not>`

## For when you're back (post-Phase-6, 2026-07-28)

- [ ] Push the eight local branches and open the stacked PRs — this session has no GitHub credentials: `git push -u origin phase-0-audit phase-1-tooling phase-7-container phase-2-lifecycle phase-3-commands phase-4-ui phase-5-deprecations phase-6-hardening` :: nothing has left this machine :: blocking review
- [ ] Run the owner-only `sync` command once in Discord :: Phase 2 added the hybrid `prefix` command and Phase 3 added parameter descriptions; slash metadata doesn't update until you sync :: blocking the new slash surface only
- [ ] Exercise each command once in Discord (whois, serverinfo, inviteinfo with a good and a bad code, about, cleanup, prefix show/set as owner and as non-owner) :: I verified everything that can be verified without a Discord account — offline load harness, live DB round-trip, deployed startup — but nobody has clicked the commands :: blocking definition-of-done §12
- [ ] Decide: make `about` user-installable (`allowed_installs(users=True)`) :: skipped autonomously because its `ctx.channel.typing()` latency probe can fail in user-install contexts where the bot can't type; needs a small rework first :: not blocking
- [ ] Decide: application emojis to replace the `Status` enum's host-guild emoji :: needs the four emoji image assets and a one-time upload (manual or a startup migration); not doable without the assets :: not blocking
- [ ] Decide: keep the tree-error cog-swap pattern or switch to a `CommandTree` subclass :: CLAUDE.md §7 prefers the subclass; the current swap works and was kept to preserve structure :: not blocking
- [ ] Decide: should `cleanup` become hybrid? :: left prefix-only as a mod utility per the kickoff's "keep prefix commands for admin utilities"; converting is trivial if you want it as a slash :: not blocking
- [ ] Fill CLAUDE.md §1 with the now-known values :: proposal: bot name SuperiorSpork, entry point `bot.py`, package manager pip, Python 3.13, HTTP surface none, behind Traefik no :: not blocking

## Decisions needed

- [x] Confirm ruff `quote-style = "double"` :: double is the dominant style (13/15 files); `exts/utils/embeds.py` is the single-quote exception, normalized in the Phase 1 sweep commit :: decided in Phase 1 per the dominant-pattern rule (CLAUDE.md §3) after the Phase 0 recommendation went unobjected — veto and it's a one-line revert of pyproject + embeds.py
- [ ] Decide whether jishaku should be pinned :: it still installs from unpinned git master (currently 2.7.5); discord.py is now pinned `>=2.7,<3` but a jishaku master break would still hit fresh installs; pinning to a release or commit is a one-line change :: not blocking
- [x] Confirm intent trim (`invites`, `reactions`, `voice_states`, `emojis`) :: trimmed in Phase 2 under your blanket go-ahead — nothing in the visible tree uses them. **Caveat:** `exts/private/` is invisible to the audit; if a private cog listens to reaction/voice/invite/emoji events, re-add that intent in `bot.py` (one line) :: resolved, revisit only if a private cog needs one
- [x] Decide the `guilds(id, prefix)` table's fate :: resolved in Phase 2 — per-guild prefixes are live through the `GuildSettings` accessor (CLAUDE.md §14.1 pattern), with an owner-only hybrid `prefix` command; round-tripped against the deployed database :: resolved
- [x] Confirm switching `config.py` to read env vars :: superseded in Phase 7 — owner decided `config.py` is the single secrets file, no `.env` at all; it is bind-mounted read-only into the container (UID 10001 read ACL), excluded from the build context, and never enters the image; the Postgres password's only home is the DSN in `config.py` (the db volume was initialized with it once, per DEPLOY.md) :: resolved
- [x] Approve renaming class `ErorrHandler` → `ErrorHandler` :: renamed in Phase 6 under your blanket go-ahead; internal-only, nothing references the cog by name string :: resolved
- [ ] `exts/private/` can't be audited from this tree :: any deprecations, bugs, or intent dependencies in private cogs are uncovered by AUDIT.md :: not blocking

- [x] Fill real `TOKEN` and `DB_URL` in the local `config.py` :: resolved in Phase 7 — you supplied the token; both DSN slots now point at the compose-internal `spork-db` (set via `sed`, file contents never read); full boot verified in the container, bot online :: resolved
- [ ] Update `CLAUDE.md` §13 (and the §1 "HTTP surface"/"Behind Traefik" rows): it still says Shape B is decided, but you overrode to **Shape A** on 2026-07-28 — no `/health`, no Traefik; also note `CLAUDE.md` is still untracked in git :: the contract should match the deployed reality or a future phase may "fix" it backwards :: not blocking
- [ ] VPS Docker address pools are effectively full (37 networks) :: `compose up` failed with "all predefined address pools have been fully subnetted"; I pruned the only two unattached networks (`umbleh-apps_client-portal-internal`, `umbleh-apps_crm-internal` — that project recreates them on its next `up`, but may then hit the same wall). Durable fix: widen `default-address-pools` in `/etc/docker/daemon.json` — needs a daemon restart, which restarts every container on the box, so schedule it :: not blocking today, will bite the next new project

## CLAUDE.md `{{CONFIRM}}` tokens still open

- [ ] §1 header: bot name, purpose line, entry point (`bot.py`), package manager (pip today; uv an option), Python version (host is 3.13; ruff says py311 — pick one) :: launch blockers per the contract :: blocking before "done"
- [x] §13 Docker: base image minor version, image/container names :: chosen in Phase 7 — `python:3.13-slim`, image/container `superiorspork`, db `spork-db` on `postgres:17-alpine`; bless or rename :: resolved
- [x] §13.5 Traefik: network/entrypoint/resolver/middleware/hostname :: moot — Shape A has no HTTP surface, so nothing routes through Traefik and no DNS record is needed (the live values were confirmed inspectable — `traefik-public`/`websecure`/`letsencrypt` — should a web surface ever appear) :: resolved
- [ ] Note: CLAUDE.md itself is currently untracked (`??` in git status) — commit it when you're happy with it :: it's the contract the CI token-scan will read :: not blocking

## Dashboard-readiness notes (CLAUDE.md §14.4, log-only)

Note: the Shape A decision also drops the "router-shaped aiohttp health app"
prep from §14.2 — if a dashboard ever becomes real, the bot grows an internal
API then (plus the Traefik/DNS work, for which the live values are known).
The config accessor layer (§14.1) is unaffected and still lands in Phase 2.


- [ ] Pick the eventual dashboard hostname :: changing it later means re-registering the OAuth redirect URI :: not blocking
- [ ] A dashboard will need an OAuth2 redirect URI + client secret in the Developer Portal :: portal work only you can do :: not blocking
- [ ] Confirm datastore owner: recommendation is "bot owns it" (dashboard talks to the bot's internal API; SQLite/Postgres stays single-writer) :: CLAUDE.md §14.3 asks for this in writing :: not blocking
