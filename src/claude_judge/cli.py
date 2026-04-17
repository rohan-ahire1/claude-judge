"""CLI entrypoint. Invoked by the /judge-me slash command and the bin wrapper."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from claude_judge.transcript_source import ClaudeCodeJSONLSource, Session


def _default_projects_root() -> Path:
    return Path(os.path.expanduser("~/.claude/projects"))


def _project_dir_for_cwd(projects_root: Path, cwd: Path) -> Path:
    # Claude Code encodes the absolute cwd as a directory name by replacing
    # path separators with dashes. /Users/rohan/foo -> -Users-rohan-foo
    encoded = str(cwd).replace("/", "-")
    return projects_root / encoded


def _format_verdict(session: Session) -> str:
    n = session.tool_call_count
    short_id = session.session_id[:8] if session.session_id else "unknown"
    if n == 0:
        return f"Judge: ghost session ({short_id}) — 0 tool calls. Burn."
    if n < 5:
        return f"Judge: trivial session ({short_id}) — {n} tool calls. Skipping."
    return f"Judge: session {short_id} — {n} tool calls. Real scoring coming soon."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge")
    parser.add_argument("--root", type=Path, default=_default_projects_root())
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument(
        "--all",
        action="store_true",
        help="Judge every session under --root (default: only current cwd)",
    )
    args = parser.parse_args(argv)

    scan_root = args.root if args.all else _project_dir_for_cwd(args.root, args.cwd)
    source = ClaudeCodeJSONLSource(root=scan_root)

    any_printed = False
    for session in source.list_sessions():
        print(_format_verdict(session))
        any_printed = True

    if not any_printed:
        print("Judge: no sessions found for this project yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
