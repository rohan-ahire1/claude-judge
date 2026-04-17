#!/usr/bin/env bash
# Install daily + weekly claude-judge cron entries into the user's crontab.
# Safe to re-run: removes any existing claude-judge entries and re-adds them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
DAILY_BIN="$ROOT/bin/judge-daily"
WEEKLY_BIN="$ROOT/bin/judge-weekly"
MARKER="# claude-judge"

if [[ ! -x "$DAILY_BIN" || ! -x "$WEEKLY_BIN" ]]; then
  echo "claude-judge: missing or non-executable daily/weekly scripts" >&2
  exit 1
fi

# Strip any prior claude-judge entries, then append current ones.
CURRENT=$(crontab -l 2>/dev/null | grep -v "$MARKER" || true)
NEW_ENTRIES="$(
cat <<EOF
$MARKER
0 23 * * *   $DAILY_BIN   # daily at 23:00
30 23 * * 0  $WEEKLY_BIN  # weekly Sunday at 23:30
EOF
)"

# Install
if [[ -z "$CURRENT" ]]; then
  printf '%s\n' "$NEW_ENTRIES" | crontab -
else
  printf '%s\n%s\n' "$CURRENT" "$NEW_ENTRIES" | crontab -
fi

echo "Installed claude-judge cron entries:"
crontab -l | grep -A1 "$MARKER"
