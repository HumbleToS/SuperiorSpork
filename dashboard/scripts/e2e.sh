#!/usr/bin/env bash
# Builds the standalone app, starts it with the stub bot api, runs the Playwright suite, tears down.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${E2E_PORT:-3123}
STUB_PORT=${E2E_STUB_PORT:-18080}
TOKEN=dev-token-dev-token-dev
SECRET=c2Vzc2lvbi1zZWNyZXQtZm9yLXRlc3RzLTMyLWJ5dGVzISE

if [ "${E2E_SKIP_BUILD:-}" != "1" ]; then pnpm build >/dev/null; fi
rm -rf .next/standalone/.next/static && cp -r .next/static .next/standalone/.next/static && cp -r public .next/standalone/

STUB_PORT=$STUB_PORT BOT_API_TOKEN=$TOKEN node scripts/stub-bot-api.mjs >/tmp/sprok-e2e-stub.log 2>&1 &
STUB=$!
# exec, so the pid we hold is node's and the trap really stops it
( cd .next/standalone && exec env PORT=$PORT HOSTNAME=127.0.0.1 APP_URL=http://127.0.0.1:$PORT DISCORD_CLIENT_ID=100000000000000001 \
  DISCORD_CLIENT_SECRET=secret-secret-secret SESSION_SECRET=$SECRET BOT_API_URL=http://127.0.0.1:$STUB_PORT/internal/v1 \
  BOT_API_TOKEN=$TOKEN node server.js >/tmp/sprok-e2e-app.log 2>&1 ) &
APP=$!
trap 'kill $STUB $APP 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.5; done
if ! curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; then echo "app did not start; see /tmp/sprok-e2e-app.log" >&2; exit 1; fi

E2E_BASE_URL=http://127.0.0.1:$PORT pnpm exec playwright test -c e2e/playwright.config.ts "$@"
