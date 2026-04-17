"""CLI entrypoint. Invoked by the /judge-me slash command and the bin wrapper."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from claude_judge.summarizer import SessionStats
from claude_judge.transcript_source import ClaudeCodeJSONLSource


def _default_projects_root() -> Path:
    return Path(os.path.expanduser("~/.claude/projects"))


def _project_dir_for_cwd(projects_root: Path, cwd: Path) -> Path:
    # Claude Code encodes the absolute cwd as a directory name by replacing
    # path separators with dashes. /Users/rohan/foo -> -Users-rohan-foo
    encoded = str(cwd).replace("/", "-")
    return projects_root / encoded


def _format_verdict(session: SessionStats) -> str:
    n = session.tool_call_count
    short_id = session.session_id.split("#", 1)[0][:8] if session.session_id else "unknown"
    dur_min = session.duration_seconds / 60
    latencies = session.approval_latencies_ms
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    fast_approvals = sum(1 for ms in latencies if ms < 500)
    header = (
        f"Judge: {short_id}  "
        f"dur={dur_min:>5.1f}m  "
        f"tools={n:>3}  "
        f"files={len(session.files_touched):>3}  "
        f"avg_latency={avg_latency:>6.0f}ms  "
        f"fast_approvals={fast_approvals}/{len(latencies)}"
    )
    if n == 0:
        return header + "  — ghost session. Burn."
    if n < 5:
        return header + "  — trivial, skipping."
    return header + "  — real scoring coming soon."


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
