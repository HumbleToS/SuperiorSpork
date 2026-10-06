#!/usr/bin/env bash
# Launch blocker: any {{CONFIRM or {{SAMPLE tag anywhere in the shipped tree fails CI, on every branch.
set -uo pipefail
cd "$(dirname "$0")/.."

matches="$(grep -rn --binary-files=without-match -e '{{CONFIRM' -e '{{SAMPLE' \
  --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git \
  --exclude=HUMAN-TODO.md --exclude=check-tokens.sh . 2>/dev/null || true)"

if [ -z "$matches" ]; then
  echo "check-tokens: clean"
  exit 0
fi
printf '%s\n' "$matches"
echo "check-tokens: unresolved tokens found — fill in the real value first." >&2
exit 1
