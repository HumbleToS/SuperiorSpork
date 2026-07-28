# AUDIT.md

Phase 0 discovery pass. No code was changed. Line numbers reference the tree at
commit `cbfaaa5`.

---

## 1. Versions

| What | Value |
|---|---|
| discord.py in requirements | `git+https://github.com/Rapptz/discord.py` — unpinned master |
| discord.py that installs today | **2.8.0a** (alpha snapshot; whatever master is at install time) |
| discord.py target | pin `discord.py>=2.7,<3` (stable). Nothing in the code needs anything newer than 2.4-era APIs (`allowed_installs`/`allowed_contexts`), so the downgrade from the alpha is safe. |
| jishaku | `git+https://github.com/Gorialis/jishaku` — unpinned master |
| Other deps | `asyncpg`, `psutil` — unpinned, no lockfile |
| Python (host) | 3.13.3; ruff `target-version` says py311 |
| ruff baseline | `check`: 4 errors (all auto-fixable). `format --check`: 2 files would change. 3 dead codes in config (ANN101, ANN102, UP038 removed from ruff). |

Import smoke test passes: `import bot` succeeds and extension discovery finds
`exts.dev`, `exts.errorhandler`, `exts.general` (`exts/utils/` is correctly
skipped — see §2 note). The bot was **not** booted against Discord in this
phase (needs the real token/DB; will be exercised from Phase 1 on).

---

## 2. Inventory

**Entry point:** `bot.py` — `Spork(commands.Bot)`, run via `asyncio.run(main())`.
`main()` owns one `aiohttp.ClientSession` and one `asyncpg` pool via
`async with`, passed into the bot. Prefix: `when_mentioned_or(config.PREFIX)`,
`case_insensitive=True`, dnd status + watching activity.

**Cogs (3 + jishaku):**

| Cog | File | Contents |
|---|---|---|
| `Developer` | `exts/dev.py` | `sync` (prefix, owner-only, guild-only) — the standard umbra sync command |
| `ErorrHandler` (typo, see B9) | `exts/errorhandler.py` | `on_command_error` listener; swaps `tree.on_error` to its own `on_app_command_error` in `cog_load`, restores in `cog_unload` |
| `General` | `exts/general.py` | everything user-facing |
| jishaku | loaded in `setup_hook` | owner debugging, `JISHAKU_NO_UNDERSCORE` / `NO_DM_TRACEBACK` set in `config.py` |

**Commands:**

| Command | Kind | Checks / limits |
|---|---|---|
| `sync` | prefix | `guild_only`, `is_owner` |
| `cleanup` (aliases `cu`, `pb`) | prefix | `guild_only`, cooldown 1/5s/user, amount capped 100 (1000 for owner) |
| `whois` | hybrid | `guild_only` |
| `serverinfo` | hybrid | `guild_only` |
| `inviteinfo` | hybrid | `allowed_installs(guilds, users)`, `allowed_contexts(guilds, dms, private_channels)` |
| `about` | hybrid | none |

**Listeners / event overrides:**
- `General.mention_responder` (`on_message`) — replies with the prefix when the bot is bare-mentioned.
- `ErorrHandler.on_command_error` — central prefix-command error handler.
- `tree.on_error` monkeypatch — central app-command error handler.
- `Spork.on_message_edit` — re-runs `process_commands` on every edit (see B7).

**Task loops:** none. **Views / modals:** none. **Voice:** none (no ffmpeg/opus
needed in the image). **HTTP surface:** none today (Shape B planned).

**Helpers (`exts/utils/`, namespace package):**
- `checks.py` — `NotGuildOwner` + `is_guild_owner()` (defined, currently applied to no command).
- `context.py` — `GuildContext` typing shim.
- `embeds.py` — `SporkEmbed` (random pastel default colour).
- `emojis.py` — `Status` enum of 4 custom emoji from a host guild.
- `guilds.py` — `GuildGraphics` dataclass (icon/splash/banner links).
- `time.py` — `ts` format-spec wrapper over `format_dt`; `how_old()`.
- `wording.py` — `plural` format-spec helper.

**Structural constraint worth knowing:** extension discovery in
`exts/__init__.py` uses `pkgutil.iter_modules`, which skips `exts/utils/`
only because it has **no `__init__.py`**. Adding one would make the loader try
`load_extension("exts.utils")` and crash at startup. Documented in
CONVENTIONS.md; do not "fix" the missing `__init__.py`.

**Database:** `database/schema.sql` (`guilds(id, prefix)`) is executed at every
startup (idempotent). Nothing else reads or writes the pool. The per-guild
prefix feature the table implies was never wired up — see §8.

---

## 3. Confirmed bugs

Per your note: you want zero errors in this source. These are the defects I can
prove from reading; each is assigned to a phase in §9. None are fixed yet —
Phase 0 is audit-only.

| # | Where | Bug | User impact |
|---|---|---|---|
| B1 | `exts/general.py:205-206` | Second f-string is a standalone expression, not part of the assignment — the string is built and thrown away | `inviteinfo` never shows the inviter's "Registered on …" line |
| B2 | `exts/general.py:215-216` | Same orphaned-f-string pattern on `embed.description` | `inviteinfo` never shows the vanity/uses sentence |
| B3 | `exts/utils/time.py:19` | `time.seconds // 36001` — typo for `3600` | the "X days and Y hours old" ages in `serverinfo`/`inviteinfo` report wrong hours almost always (usually 0) |
| B4 | `exts/errorhandler.py:65-68` | `NotGuildOwner` is a `CheckFailure` subclass, and the `CheckFailure` branch comes first — the `NotGuildOwner` branch is unreachable | latent today (no command uses `is_guild_owner()` yet), but the owner-only message can never be sent |
| B5 | `bot.py:30` | `RotatingFileHandler("logs/…")` is constructed eagerly, even in TESTING mode — crashes with `FileNotFoundError` if `logs/` doesn't exist (fresh clone, fresh container) | startup blocker on any clean deploy |
| B6 | `exts/utils/embeds.py:13-16` | Passing `color=` explicitly makes the `elif` set `colour=` to a random pastel, and `Embed` prefers `colour` — the caller's colour is clobbered. Intended logic is "pastel only when neither was given" | latent (no call site passes a colour yet) |
| B7 | `bot.py:79-80` | `on_message_edit` re-runs `process_commands` with no guard — fires on embed-unfurl edits too (`before.content == after.content`), which can double-run a command the user never re-sent | duplicate command responses |
| B8 | `exts/general.py:198` | Invalid invite code → `fetch_invite` raises `NotFound`, which no handler maps to a user message. Also the `invite is None` check at 200 is dead (`fetch_invite` raises, never returns None) | prefix use: silence; slash use: "The application did not respond" |

Smaller display defects, same spirit: `exts/general.py:277` `:.2` formats RAM
as 2 *significant digits* (`0.42%`) instead of `:.2f`; `psutil.cpu_percent()`
first call always reports `0.0%` (`exts/general.py:276`); `plural` output has
no thousands separators while every neighbouring number uses `:,`
(`exts/utils/wording.py:13-14`); `ts` with an empty format spec would emit
malformed `<t:…:>` markup (`exts/utils/time.py:13-15`, currently unreachable —
every call site passes a spec).

---

## 4. Deprecated / removed APIs in use

| Where | What | Status |
|---|---|---|
| `bot.py:49` | `Intents(emojis=True)` | deprecated alias → `expressions` |
| `exts/general.py:198` | `fetch_invite(..., with_expiration=True)` | parameter deprecated (expiration is always included now) |

Swept for and **not** present: `pins()` eager-await, `TextInput.label`,
guild-creation client methods, pin/unpin permission checks (the
`manage_messages` check at `exts/general.py:69` gates **purge**, which still
correctly needs `manage_messages` — unaffected by the `pin_messages` split),
hardcoded upload limits (`serverinfo` reads `guild.filesize_limit`
dynamically), `audioop`/voice (no voice code).

---

## 5. Event-loop-blocking calls

| Where | What | Severity |
|---|---|---|
| `bot.py:72-74` | `Path.open()/read()` of `schema.sql` in `setup_hook` | startup-only, one small file — acceptable; noted for completeness |
| `bot.py:30` | `RotatingFileHandler` does blocking file writes on the loop thread | standard stdlib-logging practice; acceptable |
| `exts/general.py:276-278` | `psutil` per-process reads (`/proc` lookups) | microseconds, non-blocking variants already used |

No `requests`, no `time.sleep`, no heavy CPU on the loop. This codebase is
clean here.

---

## 6. Swallowed exceptions

| Where | What | Verdict |
|---|---|---|
| `exts/dev.py:56-57` | `except discord.HTTPException: pass` in the per-guild sync loop | semi-intentional (failures are counted in the `X/Y` reply); a `debug` log would be better |
| `exts/errorhandler.py:49,53-54` | `CommandNotFound`, `NotOwner` ignored | intentional, standard |
| `exts/errorhandler.py:65-66` | generic `CheckFailure` → info-log only, user gets silence | intentional-ish; UX gap, revisit in Phase 6 |
| `exts/general.py:79-80` | `Forbidden`/`HTTPException` in `cleanup` | not swallowed — user gets a message |

No bare `except: pass` anywhere.

---

## 7. Command tree sync

Exactly one place: the owner-only `sync` prefix command
(`exts/dev.py:16-60`). **No sync runs at startup.** This is already the
pattern CLAUDE.md §6 mandates — nothing to fix, just don't regress it.

---

## 8. Mutable config location (Phase 7 pre-report)

Mutable config lives in **module globals**: `config.py` constants
(`TESTING`/`TOKEN`/`DB_URL`/`PREFIX`) imported at module level (`bot.py:13`,
`exts/general.py:15`). Secrets are literals in that gitignored file — verified
**never committed** in git history — but they are not env vars, which
containerization requires (`env_file`).

Flagged **high-value** per CLAUDE.md §14.1: the `guilds(id, prefix)` table
already exists but nothing reads it. The natural move is a small accessor
(`get_prefix`-style lookup with cache + invalidation) backed by that table,
which is also the one thing that makes an eventual dashboard cheap. Proposed
for Phase 2 scope, decision logged in HUMAN-TODO.md.

---

## 9. Ranked modernization backlog

Tags: value `high-value | medium | cosmetic`, risk `safe | behavior-changing`.
"Behavior-changing" here mostly means *a user can see the difference* — for
the bug fixes, the difference is the point.

| # | Item | Value | Risk | Phase |
|---|---|---|---|---|
| 1 | Fix B1/B2 orphaned f-strings (ruff **B018** flags these once `B` is selected) | high-value | behavior-changing (restores intended output) | 1 |
| 2 | Fix B3 `36001` → `3600` | high-value | behavior-changing (correct ages) | 2 |
| 3 | Fix B5 eager log-file handler (crash on clean deploy; container logs to stdout anyway) | high-value | safe | 7 |
| 4 | Pin `discord.py>=2.7,<3` (+ pin jishaku release, asyncpg, psutil) | high-value | safe | 1 |
| 5 | Config → env-var backed (`.env` for the container), keep `config.py` shape | high-value | safe (deploy-only) | 7 |
| 6 | SIGTERM handler in entry point + graceful shutdown | high-value | safe | 7 |
| 7 | Shape B health server (`aiohttp.web.Application`, `/health` only) started in `setup_hook`, stopped in overridden `close()` | high-value | safe | 7 |
| 8 | Config accessor layer over the unused `guilds` table (per-guild prefix live) | high-value | behavior-changing (per-guild prefixes become real) | 2 |
| 9 | Fix B8: catch `NotFound` in `inviteinfo`, drop dead `None` check | high-value | behavior-changing (user finally gets an error message) | 2 |
| 10 | Fix B7: guard `on_message_edit` with `before.content != after.content` | high-value | behavior-changing (no more unfurl double-runs) | 2 |
| 11 | Fix B4 unreachable `NotGuildOwner` branch (reorder isinstance chain) | medium | safe today (latent) | 2 |
| 12 | Fix B6 `SporkEmbed` colour clobber | medium | safe today (latent) | 2 |
| 13 | Trim unused intents: `invites`, `reactions`, `voice_states`, `emojis` — nothing in the visible tree uses them (private exts invisible, needs your confirm); comment the three privileged ones with why | medium | safe (pending confirm) | 2 |
| 14 | `Intents.emojis` → `Intents.expressions` | cosmetic | safe | 2 (rides along with 13) |
| 15 | Drop `with_expiration=` from `fetch_invite` | cosmetic | safe | 5 |
| 16 | `app_commands.describe`/`Range` on hybrid params (`whois` user, `inviteinfo` invite_code); `defer()` in `inviteinfo` (does a network fetch) | medium | safe | 3 |
| 17 | Cooldown reply in app-command handler: guard `interaction.response.is_done()`, send ephemeral | medium | behavior-changing (ephemeral) | 3 |
| 18 | `cog_app_command_error` / `CommandTree` subclass vs current `tree.on_error` swap — current pattern works; propose keeping the cog swap, subclass only if you prefer it | medium | safe | 3 |
| 19 | `serverinfo`: `guild.member_count` instead of `len(guild.members)` (chunk-independent accuracy) | medium | behavior-changing (numbers may differ) | 5 |
| 20 | Application emojis for the `Status` enum (stop depending on a host guild's slots) | medium | safe | 5 |
| 21 | `Guild.role_member_counts()`, polls, forwarding, `bulk_ban` | — | — | skipped: no surface in this bot benefits; one-sentence rule failed |
| 22 | Components V2 for `serverinfo`/`inviteinfo` (Thumbnail/MediaGallery for guild art) | medium | behavior-changing (visual) | 4 — only if it genuinely reads better; embeds may win |
| 23 | Display polish: `:.2f` RAM, prime `cpu_percent`, thousands separators in `plural` | cosmetic | behavior-changing (visible text) | 4 |
| 24 | Rename `ErorrHandler` → `ErrorHandler` (B9, class name typo; internal-only) | cosmetic | safe | 6 |
| 25 | Ruff config repair: drop removed codes, `TCH`→`TC`, add `E`/`N`/`B`/`ASYNC`, narrow global `F401` ignore to per-file, remove contradictory `flake8-quotes` single-quote setting, fix the 4 baseline errors + unused `Optional` (`exts/dev.py:3`) | high-value | safe | 1 |
| 26 | Log exceptions via `exc_info=error` instead of manually formatted tracebacks inside f-strings | cosmetic | safe | 6 |
| 27 | README rewrite (setup, env vars, intents, sync procedure) | medium | safe | 6 |

## 10. Proposed phase plan

Execution order per your instruction (7 runs right after 1):

- **Phase 1 — tooling & dependency floor.** Backlog 1, 4, 25. Ruff config per
  CLAUDE.md §5 with `quote-style = "double"` (pending your confirm — see
  HUMAN-TODO), formatter sweep as its own commit (touches 2 files), pre-commit
  + CI (check, format-check, import smoke, `{{CONFIRM}}` scan). The B018 fix
  (backlog 1) is user-visible and will be called out in the PR.
- **Phase 7 — containerization & deploy.** Backlog 3, 5, 6, 7. Dockerfile
  (py3.13-slim, UID 10001, no voice deps — audit found no voice), compose
  Shape B, `.dockerignore`, `.env.example`, DEPLOY.md, Traefik labels with
  `{{CONFIRM}}` tokens for network/entrypoint/resolver/middleware. Verified
  against CLAUDE.md §13.8 line by line.
- **Phase 2 — lifecycle & core correctness.** Backlog 2, 8, 9, 10, 11, 12, 13,
  14. Session/pool lifecycle and no-startup-sync are already correct; this
  phase is the remaining confirmed bugs + intents + the config accessor.
- **Phase 3 — command layer.** Backlog 16, 17, 18. No command renames planned;
  anything that would rename gets asked first.
- **Phase 4 — UI layer.** Backlog 22, 23. Smallest phase; no views/modals
  exist today, so this is "only where V2 genuinely reads better."
- **Phase 5 — deprecation sweep & platform.** Backlog 15, 19, 20. Backlog 21
  intentionally skipped with reasons.
- **Phase 6 — hardening & docs.** Backlog 24, 26, 27 + CheckFailure UX,
  final `{{CONFIRM}}`/HUMAN-TODO pass. No unbounded caches were found (§6 of
  CLAUDE.md's worry list doesn't apply — there is no in-memory state keyed by
  user/guild).
