# VOICE-RECAP-PLAN.md

Implementation plan for the voice recap module. Written before any feature
code, per the kickoff. Lives at repo root because that is where this repo
keeps its documents (AUDIT.md, CONVENTIONS.md, DEPLOY.md) — there is no
`docs/` directory and creating one would violate structure preservation.

Branch: `feat-voice-recap` (repo convention is dashes — `feat-v2-info` — not
slashes; same branch, different spelling than the kickoff's example).

---

## 1. Verified reality checks (probed 2026-07-30, not assumed)

| Check | Result |
|---|---|
| Voice receive in stock discord.py 2.7.1 | **Absent.** No `discord.sinks`, no listen/recv methods on `VoiceClient`. |
| `discord-ext-voice-recv` | Installs alongside discord.py 2.7.1 on Python 3.13, imports, exposes `VoiceRecvClient`. Current version **0.5.2a179 — an alpha**. It is an extension in the `discord.ext` namespace on top of discord.py, not a fork, so the discord.py-only rule holds. `{{CONFIRM: voice receive dependency choice — pin 0.5.2a179 (alpha) or wait for a stable cut}}` |
| `faster-whisper` on py3.13 | 1.2.1 installs and imports (ctranslate2 4.8.1, PyAV 18.0.0). CPU-only works. |
| PyNaCl | Required for any voice connection; currently absent (startup logs say so). 1.5.0 installs. |
| Persistence layer | Postgres via asyncpg already deployed (`spork-db`), schema applied at startup from `database/schema.sql`, accessor-layer precedent in `exts/utils/settings.py`. **No second storage tech needed.** Postgres FTS covers search — no vector/embedding dependency. |
| Intents | `voice_states` was deliberately trimmed in Phase 2 (nothing used voice). This module reverses that: re-add with a why-comment. `members` (role checks) and `message_content` already on. |

**DAVE risk:** Discord is rolling out E2EE voice (DAVE). discord.py 2.7 supports
it via the optional `davey` dependency. If a guild voice channel negotiates
DAVE, receive-side decryption needs it. Mitigation: verify at implementation
in a test channel; add pinned `davey` only if required. Flagged as risk, not
dependency, for now.

## 2. Where the kickoff and this repo disagree — resolved

| Kickoff says | This repo does | Resolution (kickoff's own rule: CLAUDE.md wins on repo conventions) |
|---|---|---|
| Secrets from env vars, placeholders in "the env example file" | Owner directive: `config.py` is the single secrets file, **no .env exists** (see HUMAN-TODO history) | New keys go in gitignored `config.py` with the house `_value`/`_test_value` + `TESTING` pattern; placeholders in committed `config.example.py`. Nothing secret is committed — the compliance goal is met, the mechanism is the repo's. |
| `docs/voice-recap-plan.md` | Docs at root | This file. |
| Slash commands `/record start` etc. | House pattern is `commands.hybrid_*` | Hybrid groups/commands: same slash UX, plus prefix parity for free. Names match spec. |
| Tests per repo conventions | Repo has zero tests | New `tests/` + `requirements-dev.txt` (pytest, pytest-asyncio) — dev-only, not in the runtime image (`.dockerignore` gains `tests/`). CI gains a job with a Postgres service for the store tests. This is the one genuinely new structure; the kickoff mandates the compliance-critical tests, so it earns its place. |

## 3. Architecture

```
/record start ──► Voice cog ──► ConsentGateSink (voice-recv) ──► data/voice/<session>/<user>.wav
                     │                    ▲ packet-level include-set
                     │ usage flush (30s, atomic SQL, quota check → graceful stop)
/record stop ───► session → status 'queued'
                                  │
                Pipeline poller (tasks.loop, serial, durable via sessions table)
                                  │
                 FasterWhisperProvider (asyncio.to_thread, capped cpu_threads)
                                  │  per-user tracks → speaker-attributed transcript
                 raw audio deleted (try/finally on final success or final failure)
                                  │
                 AnthropicProvider (bot.session HTTP, hierarchical chunking)
                                  │
                 Postgres: transcript + recap + tsvector ──► recap card posted
                                                             to configured channel
/recap /journal /minutes /optout /optin /privacy /report read from the store
Retention daily task purges expired sessions; on_guild_remove purges the guild.
```

Processing is **in the bot process** for v1: the poller runs one job at a
time, transcription happens in `asyncio.to_thread` with `cpu_threads` capped
from config so the gateway loop never starves. Recording never waits on
processing (separate code paths, queue is the DB). If VPS CPU contention
shows up in practice, the pipeline module is shaped so a separate worker
container (same image, different CMD) can own the poller later — not built
now. `{{CONFIRM: whisper model size vs. VPS CPU budget — default proposal:
"small", int8, cpu_threads=2}}`

## 4. File map (spec item → file)

| File | Contents |
|---|---|
| `exts/voice.py` (new cog) | `record` hybrid group (`start`/`stop`, role-gated), `optin`, `optout`, `minutes`; active-session registry; disclosure embeds on start/stop; usage flush loop; consent `DynamicItem` button (custom_id `spork:consent:<guild_id>`, restart-proof, no in-memory view state) |
| `exts/recaps.py` (new cog) | `recap` hybrid group (`latest`/`list`/`search`/`delete`), `journal`; pagination via SporkLayout + ActionRow pager; pipeline poller task + retention daily task (both with `before_loop` ready-waits, error handlers, `cog_unload` cancellation per CLAUDE.md §6); `on_guild_remove` purge listener |
| `exts/utils/capture.py` | `ConsentGateSink` (voice-recv AudioSink): per-user WAV writers, **include-set check before any buffer write**, session temp-dir lifecycle |
| `exts/utils/pipeline.py` | job claiming, retry/backoff (attempts + next_attempt_at), orphan sweep at startup, audio deletion in `try/finally`, error-embed surfacing after final failure |
| `exts/utils/transcribe.py` | `TranscriptionProvider` interface; `FasterWhisperProvider` (default); `HostedProvider` stub for later |
| `exts/utils/summarize.py` | `SummaryProvider` interface; `AnthropicProvider` via the existing `bot.session` aiohttp client (Messages API, cheap model from config — **no SDK dependency**); hierarchical chunking; prompt constrained to summary/decisions/actions/quotes — no speaker profiling, no sensitive-category extraction |
| `exts/utils/entitlements.py` | `EntitlementProvider` interface; `DiscordEntitlementProvider` (interaction entitlements + fetch fallback, TTLCache per house pattern); `TIERS` table in this one place (Free 30 min / T1 5 h / T2 20 h) `{{CONFIRM: final tier pricing and Premium Apps SKU setup}}` |
| `exts/utils/sessions.py` | `SessionStore` accessor (CLAUDE.md §14.1 style): session CRUD, atomic usage upsert, consent upsert/lookup, FTS search (`websearch_to_tsquery`, GIN), retention + guild purge SQL — every query for the module lives here |
| `exts/utils/settings.py` (extend) | per-guild recorder role, recap channel, retention days (default 90) |
| `exts/general.py` (extend) | `privacy`, `report` — misc user-facing commands live in General in this repo; report posts to a configured owner channel with owner-DM fallback |
| `bot.py` | re-add `voice_states=True` intent with comment; register consent DynamicItem in `setup_hook` |
| `database/schema.sql` | new tables below (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS` — same idempotent startup-apply as today) |
| `Dockerfile` | `libopus0` + `ffmpeg` in the runtime stage (CLAUDE.md §13.2 already reserves the lines) |
| `compose.yaml` | named volume for the whisper model cache (`spork-models:/app/models`) so deploys don't re-download ~0.5 GB |
| `requirements.txt` | `discord-ext-voice-recv==0.5.2a179`, `PyNaCl>=1.5`, `faster-whisper>=1.2,<2` — **all new runtime deps, listed here for the §2.7 ask; nothing installs until you approve this plan** |
| `config.example.py` | anthropic key pair, whisper model + threads + models dir, SKU ids, privacy/terms URLs, report channel id |
| `tests/` | `test_quota.py`, `test_capture_gate.py`, `test_retention.py` (the three compliance-critical paths) |
| `README.md` + `CLAUDE.md` | module section: env keys, invariants (audio deleted post-transcription, opt-out at capture, quotas server-side). Note: CLAUDE.md is still untracked in git — I'll edit it; committing it stays your call. |

## 5. Schema (added to `database/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS voice_sessions (
    id uuid PRIMARY KEY,
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    started_by bigint NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    status text NOT NULL DEFAULT 'recording',
        -- recording | queued | processing | done | failed | cancelled
    seconds_recorded integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    error text,
    title text,
    transcript text,
    recap text,
    search tsvector GENERATED ALWAYS AS
        (to_tsvector('english', coalesce(title,'') || ' ' ||
         coalesce(transcript,'') || ' ' || coalesce(recap,''))) STORED
);
CREATE INDEX IF NOT EXISTS voice_sessions_search_idx
    ON voice_sessions USING gin (search);
CREATE INDEX IF NOT EXISTS voice_sessions_guild_idx
    ON voice_sessions (guild_id, started_at DESC);

CREATE TABLE IF NOT EXISTS voice_consent (
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    status text NOT NULL,               -- consented | opted_out
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS voice_usage (
    guild_id bigint NOT NULL,
    month date NOT NULL,                -- first day of the calendar month
    seconds_used integer NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, month)
);

ALTER TABLE guilds ADD COLUMN IF NOT EXISTS recorder_role_id bigint;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS recap_channel_id bigint;
ALTER TABLE guilds ADD COLUMN IF NOT EXISTS retention_days integer;
```

Transcripts live in the sessions row (FTS generated column indexes them);
the `/recap` attachment is generated on the fly from the stored text. Temp
audio only ever touches local disk under `data/voice/<session id>/`.

## 6. Compliance constraints → mechanism (by construction)

| # | Constraint | Mechanism |
|---|---|---|
| 1 | No auto-record | The only call site that connects + attaches a sink is the `record start` callback, gated by `guild_only` + configured role. No task, listener, or scheduler touches voice. |
| 2 | Loud disclosure | `record start` posts the disclosure card (what's captured, that raw audio is deleted after transcription) in the channel's text chat before capture begins; matching card on stop. Bot is visibly in the channel. |
| 3 | Consent at capture | `ConsentGateSink.write()` checks the include-set **before any buffer write** — non-consented and opted-out users' packets are dropped at the sink boundary and never reach disk. First-time users acknowledge via the DynamicItem button (works mid-session: clicking live-adds to the include-set). `optout` is permanent per guild until `optin`. Unit-tested (`test_capture_gate.py`). |
| 4 | Minimization & retention | Audio deleted in `try/finally` on final success and final failure; startup orphan sweep removes any session dir without a live claim (crash path); retention task purges sessions past the guild's window (default 90 days); `recap delete` removes one session; `on_guild_remove` purges everything for that guild. Unit-tested (`test_retention.py`). |
| 5 | No secondary use | Content flows capture → local whisper → one Anthropic recap call → Postgres. Nothing else reads content. Logging policy for the module: metadata only (ids, durations, counts) — transcript/recap text never enters logs. No analytics of any kind. |
| 6 | No sensitive-category features | The summary prompt asks for narrative/decisions/actions/quotes only; no per-speaker profiling anywhere; no tagging or extraction features exist to misuse. |
| 7 | Reporting | `report` posts to the configured owner channel (owner DM fallback) and logs the event id. |
| 8 | Privacy surface | `privacy` card: what is collected (audio during announced sessions → transcripts/recaps), when, retention window, how to delete (`optout`, `recap delete`, kick the bot), links to hosted policy + ToS (URLs from config; hosting is a HUMAN-TODO). |
| 9 | Age | No features target minors; module collects no age data; Discord's own gate is the gate. |

## 7. Monetization

- Metering: session wall-clock seconds, flushed every 30 s by the capture
  loop via one atomic `INSERT .. ON CONFLICT .. DO UPDATE .. RETURNING` —
  durable across restarts and race-safe across concurrent sessions by
  construction (single-statement increments).
- Quota check happens on every flush against the entitled tier; on exceed:
  graceful stop, clear card ("out of recorded minutes this month"), session
  still processed. Unit-tested (`test_quota.py`).
- `EntitlementProvider` interface with `DiscordEntitlementProvider` first
  (Premium Apps as primary rail, per Discord's rules); Stripe later behind
  the same interface, not built now. Tier table defined once in
  `entitlements.py`. `minutes` shows used/quota/reset (first of next month).

## 8. Config additions (`config.example.py` placeholders)

```python
_anthropic_key = "key"  # recap generation
ANTHROPIC_KEY = ...
RECAP_MODEL = "claude-haiku-4-5-20251001"
WHISPER_MODEL = "small"  # {{CONFIRM: model size vs CPU budget}}
WHISPER_THREADS = 2
MODELS_DIR = "/app/models"
SKU_TIER_1 = 0  # {{CONFIRM: Premium Apps SKUs}}
SKU_TIER_2 = 0
REPORT_CHANNEL_ID = 0
PRIVACY_URL = "https://..."  # hosted page is a HUMAN-TODO
TERMS_URL = "https://..."
```

## 9. Commit sequence (reviewable, each ruff-clean)

1. `chore:` deps + Dockerfile (opus/ffmpeg) + compose volume + schema + config example
2. `feat:` capture layer — sink, consent gate, temp-dir lifecycle (+ gate tests)
3. `feat:` pipeline — poller, transcribe/summarize providers, deletion + retry (+ retention tests)
4. `feat:` voice cog — record start/stop, disclosure, consent button, optin/optout
5. `feat:` entitlements + quota enforcement + minutes (+ quota tests)
6. `feat:` recaps cog — latest/list/search/delete, journal, retention task, guild purge
7. `feat:` privacy + report + docs (README, CLAUDE.md section, HUMAN-TODO)

## 10. HUMAN-TODO entries (added during step 7)

Host privacy policy + ToS and link in Dev Portal · legal review · Premium
Apps SKU setup · verify libopus/ffmpeg land in the VPS image (Dockerfile
handles it; disk/RAM check for the whisper model is yours) · final tier
pricing at parity · decide the voice-recv alpha pin.

## 11. Risks, stated plainly

- **discord-ext-voice-recv is alpha** and receive is inherently
  undocumented-API territory; Discord gateway changes can break capture.
  Pin exactly, wrap failures loudly.
- **DAVE/E2EE rollout** may require `davey` for receive in guild channels —
  verified during implementation, added only if needed.
- **Whisper on the VPS**: "small" int8 needs roughly ~1 GB RAM while running
  and ~0.5 GB disk (persisted in the models volume). Overnight-speed is
  acceptable per spec; threads capped so the bot stays responsive.
- **V2 cards + file attachments**: recap cards are SporkLayout (house
  identity — airy sections, no unicode emoji, custom emotes only if you
  supply them); if the `ui.File` + attachment path fights us, fallback is
  the card plus a plain follow-up message carrying the transcript file.

## 12. {{CONFIRM}} inventory — status after owner review (2026-07-30)

1. ~~Voice receive dependency~~ — **owner-approved**: pinned
   `discord-ext-voice-recv==0.5.2a179`; revisit when a stable cut ships.
2. ~~Whisper model size~~ — **owner-approved**: small / int8 / 2 threads
   (config-adjustable; RAM check listed in HUMAN-TODO).
3. **OPEN — launch blocker:** `{{CONFIRM: final tier pricing and Premium
   Apps SKU setup}}`. Until the SKU ids land in config.py, every server is
   effectively Free tier. Tracked in HUMAN-TODO.md and the PR description.

The §2.7 dependency gate (voice-recv, PyNaCl, faster-whisper) was approved
with this plan; the pins are live in requirements.txt.
