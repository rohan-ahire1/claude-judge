from __future__ import annotations

import json
from pathlib import Path

from claude_judge.aggregator import AggregateScore
from claude_judge.output_store import OutputStore
from claude_judge.scorers import ScoreResult
from claude_judge.summarizer import SessionStats


def _stats(session_id: str = "sess#2026-04-17T10:00:00+00:00") -> SessionStats:
    return SessionStats(
        session_id=session_id,
        project_root="-Users-dev-projects-webapp",
        started_at="2026-04-17T10:00:00+00:00",
        ended_at="2026-04-17T10:30:00+00:00",
        duration_seconds=1800.0,
        tool_call_count=25,
        edit_paths=["/a.py"],
    )


def _scores() -> list[ScoreResult]:
    return [
        ScoreResult(name="review_discipline", score=7.0, rationale="ok"),
        ScoreResult(name="security_hygiene", score=10.0, rationale="clean"),
        ScoreResult(name="leverage_fit", score=6.0, rationale="fit"),
    ]


def _aggregate() -> AggregateScore:
    return AggregateScore(overall=78.5, tier_a_average=8.5, tier_b_average=6.0)


def test_writes_per_session_markdown(tmp_path: Path) -> None:
    store = OutputStore(root=tmp_path)
    store.write_session(
        stats=_stats(),
        intent="coding",
        scores=_scores(),
        overall=_aggregate(),
        verdict="You shipped. Stop blind-approving bash.",
    )
    files = list((tmp_path / "sessions").glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "78.5" in content
    assert "coding" in content
    assert "review_discipline" in content
    assert "You shipped" in content


def test_session_filename_is_session_id_safe(tmp_path: Path) -> None:
    # Session IDs contain '#', ':', '+' which are not safe on all filesystems.
    OutputStore(root=tmp_path).write_session(
        stats=_stats(session_id="abc#2026-04-17T10:00:00+00:00"),
        intent="coding",
        scores=_scores(),
        overall=_aggregate(),
        verdict="zinger",
    )
    files = list((tmp_path / "sessions").glob("*.md"))
    assert len(files) == 1
    # No slashes, colons, or '+' characters in filename
    name = files[0].name
    assert "#" not in name and ":" not in name and "+" not in name


def test_scores_json_appended_once_per_session(tmp_path: Path) -> None:
    store = OutputStore(root=tmp_path)
    store.write_session(
        stats=_stats("a"),
        intent="coding",
        scores=_scores(),
        overall=_aggregate(),
        verdict="v",
    )
    store.write_session(
        stats=_stats("b"),
        intent="planning",
        scores=_scores(),
        overall=AggregateScore(overall=60.0, tier_a_average=6.0, tier_b_average=6.0),
        verdict="v",
    )
    rows = json.loads((tmp_path / "scores.json").read_text())
    assert len(rows) == 2
    assert rows[0]["session_id"] == "a"
    assert rows[1]["session_id"] == "b"
    assert rows[0]["overall"] == 78.5
    assert rows[1]["overall"] == 60.0


def test_rewriting_same_session_updates_in_place(tmp_path: Path) -> None:
    store = OutputStore(root=tmp_path)
    store.write_session(
        stats=_stats("a"),
        intent="coding",
        scores=_scores(),
        overall=AggregateScore(overall=50.0, tier_a_average=5.0, tier_b_average=5.0),
        verdict="v1",
    )
    store.write_session(
        stats=_stats("a"),
        intent="coding",
        scores=_scores(),
        overall=AggregateScore(overall=90.0, tier_a_average=9.0, tier_b_average=9.0),
        verdict="v2",
    )
    rows = json.loads((tmp_path / "scores.json").read_text())
    assert len(rows) == 1
    assert rows[0]["overall"] == 90.0
    sess_file = next((tmp_path / "sessions").glob("*.md"))
    assert "v2" in sess_file.read_text()
    assert "v1" not in sess_file.read_text()
