"""Writes per-session verdict markdown + scores.json history under a local root.

All persistence is local. Nothing ever leaves the machine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from claude_judge.aggregator import AggregateScore
from claude_judge.scorers import ScoreResult
from claude_judge.summarizer import SessionStats


class OutputStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        (self._root / "sessions").mkdir(parents=True, exist_ok=True)
        self._scores_path = self._root / "scores.json"

    def write_session(
        self,
        stats: SessionStats,
        intent: str,
        scores: list[ScoreResult],
        overall: AggregateScore,
        verdict: str,
    ) -> Path:
        session_path = self._root / "sessions" / f"{_safe_filename(stats.session_id)}.md"
        session_path.write_text(_render_markdown(stats, intent, scores, overall, verdict))
        self._append_or_replace_score(stats, intent, overall)
        return session_path

    def _append_or_replace_score(
        self, stats: SessionStats, intent: str, overall: AggregateScore
    ) -> None:
        rows = self._load_scores()
        row = {
            "session_id": stats.session_id,
            "project_root": stats.project_root,
            "started_at": stats.started_at,
            "ended_at": stats.ended_at,
            "intent": intent,
            "overall": overall.overall,
            "tier_a_average": overall.tier_a_average,
            "tier_b_average": overall.tier_b_average,
        }
        existing_index = next(
            (i for i, r in enumerate(rows) if r.get("session_id") == stats.session_id), None
        )
        if existing_index is not None:
            rows[existing_index] = row
        else:
            rows.append(row)
        self._scores_path.write_text(json.dumps(rows, indent=2))

    def _load_scores(self) -> list[dict]:
        if not self._scores_path.exists():
            return []
        try:
            data = json.loads(self._scores_path.read_text())
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(session_id: str) -> str:
    return _SAFE_FILENAME_RE.sub("_", session_id)


def _render_markdown(
    stats: SessionStats,
    intent: str,
    scores: list[ScoreResult],
    overall: AggregateScore,
    verdict: str,
) -> str:
    dur_min = stats.duration_seconds / 60
    lines = [
        f"# Session `{stats.session_id}`",
        "",
        f"- **Project:** `{stats.project_root}`",
        f"- **Started:** {stats.started_at}",
        f"- **Ended:** {stats.ended_at}",
        f"- **Duration:** {dur_min:.1f} min",
        f"- **Intent:** `{intent}`",
        f"- **Tool calls:** {stats.tool_call_count}",
        f"- **Files touched / edited:** {len(stats.files_touched)} / {len(stats.edit_paths)}",
        "",
        f"## Overall: **{overall.overall:.1f} / 100**",
        "",
    ]
    if overall.tier_a_average is not None:
        lines.append(f"- Tier A average: {overall.tier_a_average:.1f} / 10")
    if overall.tier_b_average is not None:
        lines.append(f"- Tier B average: {overall.tier_b_average:.1f} / 10")
    lines.extend(
        [
            "",
            "## Scorecard",
            "",
            "| Dimension | Score | Rationale |",
            "| --- | ---: | --- |",
        ]
    )
    for r in scores:
        rationale = r.rationale.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r.name} | {r.score:.1f} / 10 | {rationale} |")
    lines.extend(["", "## Verdict", "", verdict.strip(), ""])
    return "\n".join(lines)
