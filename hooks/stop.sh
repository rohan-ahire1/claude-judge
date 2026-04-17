#!/usr/bin/env bash
# Stop hook — reads Claude Code session_id from stdin JSON and emits a
# 1-line zinger about the latest non-trivial session segment to stderr.
# Non-blocking: always exits 0 so an error never interferes with Claude Code.
set +e

INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" | /usr/bin/env jq -r '.session_id // empty' 2>/dev/null)
[ -n "$SESSION_ID" ] || exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
"$ROOT/bin/judge" \
    --zinger \
    --session-id "$SESSION_ID" \
    --no-llm \
    --all \
    2>&1 1>/dev/null

exit 0
