#!/usr/bin/env bash
# Pre-commit git hook — emits a 3-line focused call-out about the in-flight
# session to stderr. Non-blocking: always exits 0.
#
# Install per-repo:  ln -s /path/to/claude-judge/hooks/pre-commit.sh .git/hooks/pre-commit
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

"$ROOT/bin/judge" \
    --brief \
    --no-llm \
    --cwd "$(pwd)" \
    2>&1 1>/dev/null

exit 0
