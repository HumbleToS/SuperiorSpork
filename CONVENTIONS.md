# CONVENTIONS.md

The style fingerprint of this repo, extracted in Phase 0. These are rules I
follow from here on. Where the tree is inconsistent, the dominant pattern is
named, I picked it, and the exception is logged in HUMAN-TODO.md.

## Quotes

**Double quotes.** 13 of 15 files are already exactly what `ruff format`'s
double-quote style produces. The exception is `exts/utils/embeds.py` (all
single quotes) — logged in HUMAN-TODO.md; the `flake8-quotes single`
setting in pyproject.toml contradicts the actual tree and isn't enforced
(Q rules were never selected). Pending confirm, Phase 1 sets
`quote-style = "double"` and lets the sweep commit normalize embeds.py.

## Line length

Configured 125, real. Code stays under it; long user-facing f-strings are
allowed to run past (max observed 257) because E501 is off and the formatter
doesn't split strings. Keep `line-length = 125`. Do not re-wrap prose strings
to satisfy a limit the repo never enforced.

## Imports

- Order: `__future__` → stdlib → third-party (`discord`, `asyncpg`, `aiohttp`,
  `psutil`) → first-party absolute (`config`, `bot`) → relative (`.utils.x`).
  Ruff-isort with `combine-as-imports` and `split-on-trailing-comma` already
  matches how it's written.
- `from __future__ import annotations` appears in files that need
  `TYPE_CHECKING`-only imports (cogs, `checks.py`, `guilds.py`), not
  everywhere. New files follow that rule, not a blanket policy.
- The bot class is always imported guarded: `if TYPE_CHECKING: from bot import
  Spork` (avoids the circular import). Same for `GuildContext` / `Context`.
- Mixed `import discord` + `from discord import X` in the same file is normal
  here (`bot.py` does both). Don't "clean it up."

## Type hints

Full signatures everywhere, including `-> None`; `ANN` is enforced by ruff
with `ANN401`/star-args relaxed. Modern syntax: `X | None`, lowercase
generics, `Literal`, format-helper classes annotate attributes explicitly.
`None` goes at the end of unions (two existing violations are ruff-flagged,
fixed in Phase 1). No `Optional[...]` in new code.

## Docstrings

- **Command callbacks:** always. One-line summary (it becomes the slash
  description), then a NumPy-style `Parameters` section with type and
  ", optional" / "by default X" phrasing, matching `whois`/`cleanup`.
- **Helpers:** one-liner or nothing (`is_guild_owner` has one; `plural`, `ts`,
  `SporkEmbed` have none). Match the neighbor, don't backfill.
- **Cog classes and `setup()`:** no docstrings. Keep it that way.

## Naming

- Cogs: PascalCase nouns (`Developer`, `General`).
- Format-spec helper classes: deliberately lowercase (`ts`, `plural`) — this
  is an idiom here, not an error; pep8-naming exceptions get configured
  rather than the classes renamed.
- Dataclasses/enums: PascalCase (`GuildGraphics`, `Status`).
- Module-private state: leading underscore (`_logger`, `_ext`,
  `_current_process`, `_original_handler`).
- Module-level constants: UPPER (`EXTENSIONS`, `PREFIX`, `TOKEN`, `TESTING`).
- Command callback name == command name; aliases as tuples `("cu", "pb")`.
- Loggers: `_logger = logging.getLogger(__name__)` at module top, after
  imports.

## Structure

- Cogs live flat in `exts/`, shared code in `exts/utils/`, private cogs in
  gitignored `exts/private/`. Every cog file ends with
  `async def setup(bot: Spork) -> None: await bot.add_cog(...)`.
- **`exts/utils/` must never get an `__init__.py`.** Extension discovery
  (`pkgutil.iter_modules` in `exts/__init__.py`) skips it only because it
  isn't a regular package; adding one turns it into a failing extension.
- Modules prefixed `_` are skipped by discovery — that's the mechanism for
  non-extension files inside `exts/`.

## Embeds

- Always `SporkEmbed`, never raw `discord.Embed`; colour is never passed
  (the random pastel is the brand).
- Built inline in the command body: `title`/`description` in the constructor,
  then `add_field` calls. No builder helpers, no factory functions beyond the
  subclass itself.
- Field values are multi-line f-strings with `**Bold:**` labels, backticked
  numbers, and `:,` thousands separators. Footers carry IDs and dates
  (`"User ID: … | Date: …"`, `"… • Guild ID: …"`). Thumbnails from
  avatars/icons. Custom emoji come from the `Status` enum.

## Errors to the user

- Centralized in the errorhandler cog; commands themselves only catch what
  they can answer for (`cleanup` catching `Forbidden`).
- Plain text, never embeds. Short, casual, second person, backticked command
  and argument names: "You're missing the required argument \`x\`".
  Unexpected errors are logged with traceback and the user gets nothing.

## Logging

- Stdlib `logging`, configured once in `bot.py` (`setup_logging()`), stream
  handler in TESTING else rotating file.
- Cog code logs with f-strings (`G004` is deliberately ignored), debug lines
  use `{value=}` specs. `bot.py` itself uses lazy `%s` args — both exist;
  f-strings are dominant in cogs and that's what new cog code uses.
- Levels as used: `debug` for command-flow tracing, `info` for lifecycle,
  `exception` for unhandled errors.

## Config

- `config.py` module constants; secrets never in git (file is gitignored).
  Cogs import what they need directly (`from config import PREFIX`).
- The `_value` / `_test_value` pair switched by `TESTING` is the house
  pattern; anything new that differs between dev and prod follows it.
- jishaku env flags are set as `config.py` side effects — leave them there.

## Comments

Sparse. Two kinds only: credit comments for borrowed ideas
(`# Roles and format_date credit: https://github.com/Rapptz/RoboDanny`) and
short clarifiers on non-obvious values (`# 1 per 5 seconds per user`,
`# 4 MB`). No section banners, no narration of what the next line does. New
borrowed code gets a credit comment — that's clearly a value the author holds.

## User-facing voice

Friendly and casual, sentence case, exclamation points where there's good
news ("are in this server!", "Hello! My prefix is …"), first-person bot
("I couldn't process this request."), a little playful ("my bad code",
"The Invites Demise", a `:(` when a count is zero). Statistics wrapped in
backticks. New strings match this register — no corporate tone, no ALL-CAPS
field names, no emoji spam.
