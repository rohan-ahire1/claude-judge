"""CLI entrypoint. Invoked by the /judge-me slash command and the bin wrapper."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from claude_judge.aggregator import aggregate
from claude_judge.claude_cli_backend import CallCapExceeded, ClaudeCLIBackend
from claude_judge.git_correlator import GitCorrelator, GitWindow
from claude_judge.intent_classifier import IntentClassifier
from claude_judge.llm_scorers import (
    LeverageFitScorer,
    PromptQualityScorer,
    SkillProgressionScorer,
)
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
from claude_judge.verdict_writer import VerdictWriter


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


def _score_session(
    session: SessionStats,
    git: GitWindow,
    intent: str,
    tier_b: list,
) -> list[ScoreResult]:
    results: list[ScoreResult] = []
    tier_a = [
        ReviewDisciplineScorer().score(session, git=git),
        SecurityHygieneScorer().score(session, git=git),
        OutcomeCorrelationScorer().score(session, git=git, intent=intent),
        ReworkRateScorer().score(session, git=git),
    ]
    for r in tier_a:
        if r is not None:
            results.append(r)
    for scorer in tier_b:
        r = scorer.score(session, git=git, intent=intent)
        if r is not None:
            results.append(r)
    return results


def _format_session(
    session: SessionStats,
    git: GitWindow,
    intent: str,
    scores: list[ScoreResult],
    overall_line: str,
    verdict: str | None,
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
    lines = [header, f"    {overall_line}"]
    for r in scores:
        lines.append(f"    {r.name:<22} {r.score:>4.1f}/10  {r.rationale}")
    if verdict:
        lines.append(f"    ▸ {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge")
    parser.add_argument("--root", type=Path, default=_default_projects_root())
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=_default_output_dir())
    parser.add_argument("--tone", choices=("roast", "coach"), default="roast")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--no-verdict", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    cache_dir = args.output / "cache"
    scan_root = args.root if args.all else _project_dir_for_cwd(args.root, args.cwd)
    source = ClaudeCodeJSONLSource(root=scan_root)

    classifier: IntentClassifier | None = None
    tier_b: list = []
    writer: VerdictWriter | None = None
    if not args.no_llm:
        backend = ClaudeCLIBackend(cache_dir=cache_dir)
        classifier = IntentClassifier(backend=backend, cache_dir=cache_dir)
        tier_b = [
            LeverageFitScorer(backend=backend, cache_dir=cache_dir),
            SkillProgressionScorer(backend=backend, cache_dir=cache_dir),
            PromptQualityScorer(backend=backend, cache_dir=cache_dir),
        ]
        if not args.no_verdict:
            writer = VerdictWriter(backend=backend, cache_dir=cache_dir, tone=args.tone)

    store = OutputStore(root=args.output)

    any_printed = False
    llm_disabled_reason: str | None = None
    for session in source.list_sessions():
        git = _correlate_git(session)
        if classifier is None or session.tool_call_count < 5 or llm_disabled_reason is not None:
            intent = "unknown"
        else:
            try:
                intent = classifier.classify(session)
            except CallCapExceeded as exc:
                llm_disabled_reason = str(exc)
                intent = "unknown"

        scores = _score_session(session, git, intent, tier_b)
        overall = aggregate(scores)

        verdict: str | None = None
        overall_line = "(no applicable scorers)"
        if overall is not None:
            tier_a_str = (
                f"{overall.tier_a_average:>4.1f}/10" if overall.tier_a_average is not None else " n/a "
            )
            tier_b_str = (
                f"{overall.tier_b_average:>4.1f}/10" if overall.tier_b_average is not None else " n/a "
            )
            overall_line = (
                f"overall={overall.overall:>5.1f}/100  "
                f"tierA={tier_a_str}  "
                f"tierB={tier_b_str}"
            )
            if writer is not None and llm_disabled_reason is None:
                try:
                    verdict = writer.write(session, intent, scores, overall)
                except CallCapExceeded as exc:
                    llm_disabled_reason = str(exc)
            store.write_session(
                stats=session,
                intent=intent,
                scores=scores,
                overall=overall,
                verdict=verdict or "",
            )

        print(_format_session(session, git, intent, scores, overall_line, verdict))
        any_printed = True

    if llm_disabled_reason:
        print(f"\n(LLM note: {llm_disabled_reason})")
    if not any_printed:
        print("Judge: no sessions found for this project yet.")
    else:
        print(f"\nPersisted to: {args.output}/sessions/  (+ scores.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
