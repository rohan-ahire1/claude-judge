"""CLI entrypoint — fully deterministic for interactive use, LLM reserved for digests."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from claude_judge.aggregator import aggregate
from claude_judge.git_correlator import GitCorrelator, GitWindow
from claude_judge.output_store import OutputStore
from claude_judge.scorers import (
    OutcomeCorrelationScorer,
    ReviewDisciplineScorer,
    ReworkRateScorer,
    ScoreResult,
    SecurityHygieneScorer,
)
from claude_judge.summarizer import SessionStats
from claude_judge.transcript_source import ClaudeCodeJSONLSource


def _default_projects_root() -> Path:
    return Path(os.path.expanduser("~/.claude/projects"))


def _default_output_dir() -> Path:
    return Path(os.path.expanduser("~/Documents/projects/claude-judge/data"))


def _project_dir_for_cwd(projects_root: Path, cwd: Path) -> Path:
    encoded = str(cwd).replace("/", "-")
    return projects_root / encoded


def _decode_project_dir(encoded: str) -> Path:
    if not encoded.startswith("-"):
        return Path(encoded)
    return Path("/" + encoded.lstrip("-").replace("-", "/"))


def _short_id(session: SessionStats) -> str:
    return (session.session_id.split("#", 1)[0] or "unknown")[:8]


def _correlate_git(session: SessionStats) -> GitWindow:
    if not session.started_at or not session.ended_at:
        return GitWindow()
    try:
        since = datetime.fromisoformat(session.started_at)
        until = datetime.fromisoformat(session.ended_at)
    except ValueError:
        return GitWindow()
    repo = _decode_project_dir(session.project_root)
    if not repo.exists():
        return GitWindow()
    return GitCorrelator(repo).window(since=since, until=until)


def _heuristic_intent(session: SessionStats) -> str:
    """Fast, deterministic intent classification — no LLM needed."""
    if session.tool_call_count == 0:
        return "idle"
    has_edits = len(session.edit_paths) > 0
    has_commits = session.git_commit_count > 0
    if has_edits and has_commits:
        return "coding"
    if has_edits:
        return "coding"
    # All reads/greps, no edits
    if session.tool_call_count > 5:
        return "exploration"
    return "unknown"


def _score_session(
    session: SessionStats,
    git: GitWindow,
    intent: str,
) -> list[ScoreResult]:
    results: list[ScoreResult] = []
    for r in [
        ReviewDisciplineScorer().score(session, git=git),
        SecurityHygieneScorer().score(session, git=git),
        OutcomeCorrelationScorer().score(session, git=git, intent=intent),
        ReworkRateScorer().score(session, git=git),
    ]:
        if r is not None:
            results.append(r)
    return results


def _format_session(
    session: SessionStats,
    git: GitWindow,
    intent: str,
    scores: list[ScoreResult],
    overall_line: str,
) -> str:
    dur_min = session.duration_seconds / 60
    header = (
        f"— {_short_id(session)}  "
        f"intent={intent:<11}  "
        f"dur={dur_min:>5.1f}m  "
        f"tools={session.tool_call_count:>3}  "
        f"edits={len(session.edit_paths):>3}  "
        f"commits={session.git_commit_count}+{len(git.commits)}ext  "
        f"reverts={git.reverts_matched}"
    )
    if not scores:
        return header + "\n    (trivial/ghost session)"
    lines = [header, f"    {overall_line}"]
    for r in scores:
        lines.append(f"    {r.name:<22} {r.score:>4.1f}/10  {r.rationale}")
    return "\n".join(lines)


# --- hook modes ---


def _run_zinger(sessions: list[SessionStats], min_tools: int) -> int:
    candidates = [s for s in sessions if s.tool_call_count >= min_tools]
    if not candidates:
        return 0
    latest = max(candidates, key=lambda s: s.started_at)
    git = _correlate_git(latest)
    intent = _heuristic_intent(latest)
    scores = _score_session(latest, git, intent)
    overall = aggregate(scores)
    if overall is None or not scores:
        return 0
    weakest = min(scores, key=lambda r: r.score)
    short = _short_id(latest)
    print(
        f"judge[{short}] {overall.overall:.0f}/100 — weakest: {weakest.name} "
        f"{weakest.score:.1f} ({weakest.rationale[:80]})",
        file=sys.stderr,
    )
    return 0


def _run_brief(sessions: list[SessionStats], min_tools: int) -> int:
    candidates = [s for s in sessions if s.tool_call_count >= min_tools]
    if not candidates:
        return 0
    latest = max(candidates, key=lambda s: s.started_at)
    git = _correlate_git(latest)
    intent = _heuristic_intent(latest)
    scores = _score_session(latest, git, intent)
    overall = aggregate(scores)
    if overall is None or not scores:
        return 0
    short = _short_id(latest)
    weakest_two = sorted(scores, key=lambda r: r.score)[:2]
    print(f"judge[{short}] overall={overall.overall:.0f}/100  intent={intent}", file=sys.stderr)
    for r in weakest_two:
        print(f"  ↳ {r.name} {r.score:.1f}: {r.rationale[:80]}", file=sys.stderr)
    return 0


# --- main ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge")
    parser.add_argument("--root", type=Path, default=_default_projects_root())
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=_default_output_dir())
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--latest", type=int, default=3, help="Only show the N most recent sessions")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--zinger", action="store_true")
    parser.add_argument("--brief", action="store_true")
    parser.add_argument("--zinger-min-tools", type=int, default=10)
    args = parser.parse_args(argv)

    scan_root = args.root if args.all else _project_dir_for_cwd(args.root, args.cwd)
    # Only read the N most-recently-modified JSONL files — avoids parsing
    # hundreds of old files when we only want the latest few sessions.
    max_files = args.latest * 3 if not args.all else 0
    source = ClaudeCodeJSONLSource(root=scan_root, max_files=max_files)
    store = OutputStore(root=args.output)

    sessions = list(source.list_sessions())
    if args.session_id:
        sessions = [s for s in sessions if s.session_id.startswith(args.session_id)]

    if args.zinger:
        return _run_zinger(sessions, args.zinger_min_tools)
    if args.brief:
        return _run_brief(sessions, args.zinger_min_tools)

    # Sort by start time descending, take latest N
    sessions.sort(key=lambda s: s.started_at, reverse=True)
    sessions = sessions[: args.latest]
    sessions.reverse()  # chronological for display

    any_printed = False
    for session in sessions:
        git = _correlate_git(session)
        intent = _heuristic_intent(session)
        scores = _score_session(session, git, intent)
        overall = aggregate(scores)

        overall_line = "(no applicable scorers)"
        if overall is not None:
            tier_a_str = (
                f"{overall.tier_a_average:>4.1f}/10"
                if overall.tier_a_average is not None
                else " n/a "
            )
            overall_line = f"overall={overall.overall:>5.1f}/100  tierA={tier_a_str}"
            store.write_session(
                stats=session, intent=intent, scores=scores, overall=overall, verdict=""
            )

        print(_format_session(session, git, intent, scores, overall_line))
        any_printed = True

    if not any_printed:
        print("Judge: no sessions found for this project yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
