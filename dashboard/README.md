# sprok-dashboard

The web dashboard for the [Sprok](https://github.com/HumbleToS/SuperiorSpork) Discord bot, at
[sprok.umbleh.dev](https://sprok.umbleh.dev). Sign in with Discord, pick a server you manage, and
tune the bot without slash commands.

- **Commands** — a searchable reference generated from the bot's own help, public at `/commands`.
- **Anti-brainrot** — channels, terms, exemptions, settings, offenders, and the activity feed.

The bot owns every byte of data: the dashboard has no database and talks to the bot's internal API
over a private Docker network. The architecture rules and the deploy story live in the project notes.

```bash
pnpm install
BOT_API_TOKEN=dev-token-dev-token-dev STUB_PORT=18080 pnpm stub:bot     # a stand-in for the bot
BOT_API_URL=http://127.0.0.1:18080/internal/v1 BOT_API_TOKEN=dev-token-dev-token-dev pnpm dev
```
