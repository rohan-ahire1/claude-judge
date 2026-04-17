"""CLI entrypoint. Invoked by the /judge-me slash command and the bin wrapper."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from claude_judge.scorers import TIER_A_SCORERS, ScoreResult
from claude_judge.summarizer import SessionStats
from claude_judge.transcript_source import ClaudeCodeJSONLSource


def _default_projects_root() -> Path:
    return Path(os.path.expanduser("~/.claude/projects"))


def _project_dir_for_cwd(projects_root: Path, cwd: Path) -> Path:
    encoded = str(cwd).replace("/", "-")
    return projects_root / encoded


def _short_id(session: SessionStats) -> str:
    return (session.session_id.split("#", 1)[0] or "unknown")[:8]


def _format_session(session: SessionStats) -> str:
    dur_min = session.duration_seconds / 60
    header = (
        f"— {_short_id(session)}  "
        f"dur={dur_min:>5.1f}m  "
        f"tools={session.tool_call_count:>3}  "
        f"files={len(session.files_touched):>3}  "
        f"edits={len(session.edit_paths):>3}  "
        f"commits={session.git_commit_count}  "
        f"mode={session.permission_mode}"
    )
    scores: list[ScoreResult] = [
        r for scorer in TIER_A_SCORERS for r in [scorer.score(session)] if r is not None
    ]
    if not scores:
        return header + "\n    (no applicable scorers — trivial/ghost session)"
    lines = [header]
    for r in scores:
        lines.append(f"    {r.name:<22} {r.score:>4.1f}/10  {r.rationale}")
    return "\n".join(lines)


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
        print(_format_session(session))
        any_printed = True

    if not any_printed:
        print("Judge: no sessions found for this project yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
