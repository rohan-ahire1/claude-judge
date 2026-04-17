from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from claude_judge.digest import build_daily_digest, build_weekly_digest


def _row(**kwargs) -> dict:
    base = {
        "session_id": "s#2026-04-17T10:00:00+00:00",
        "project_root": "-Users-dev-projects-webapp",
        "started_at": "2026-04-17T10:00:00+00:00",
        "ended_at": "2026-04-17T10:30:00+00:00",
        "intent": "coding",
        "overall": 75.0,
        "tier_a_average": 8.0,
        "tier_b_average": 6.0,
    }
    base.update(kwargs)
    return base


def _write_scores(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows))


def test_daily_digest_returns_none_when_no_sessions_for_date(tmp_path: Path) -> None:
    _write_scores(tmp_path / "scores.json", [_row(started_at="2026-04-10T10:00:00+00:00")])
    assert build_daily_digest(tmp_path, date="2026-04-17", llm=None) is None


def test_daily_digest_aggregates_intents_and_averages(tmp_path: Path) -> None:
    _write_scores(
        tmp_path / "scores.json",
        [
            _row(started_at="2026-04-17T10:00:00+00:00", intent="coding", overall=80.0),
            _row(started_at="2026-04-17T11:00:00+00:00", intent="planning", overall=60.0),
            _row(started_at="2026-04-17T12:00:00+00:00", intent="coding", overall=70.0),
        ],
    )
    digest = build_daily_digest(tmp_path, date="2026-04-17", llm=None)
    assert digest is not None
    assert digest.date == "2026-04-17"
    assert digest.session_count == 3
    assert digest.average_overall == 70.0
    assert digest.intents == {"coding": 2, "planning": 1}


def test_daily_digest_writes_markdown(tmp_path: Path) -> None:
    _write_scores(
        tmp_path / "scores.json",
        [_row(started_at="2026-04-17T10:00:00+00:00", overall=75.0)],
    )
    digest = build_daily_digest(tmp_path, date="2026-04-17", llm=None)
    assert digest is not None
    md = (tmp_path / "daily" / "2026-04-17.md").read_text()
    assert "2026-04-17" in md
    assert "75.0" in md
    assert digest.markdown_path.name == "2026-04-17.md"


def test_daily_digest_uses_llm_for_narrative_when_provided(tmp_path: Path) -> None:
    _write_scores(
        tmp_path / "scores.json",
        [_row(started_at="2026-04-17T10:00:00+00:00", overall=75.0)],
    )
    llm = MagicMock()
    llm.complete.return_value = "You shipped, barely."
    build_daily_digest(tmp_path, date="2026-04-17", llm=llm)
    md = (tmp_path / "daily" / "2026-04-17.md").read_text()
    assert "You shipped, barely." in md


def test_weekly_digest_aggregates_a_full_iso_week(tmp_path: Path) -> None:
    _write_scores(
        tmp_path / "scores.json",
        [
            _row(started_at="2026-04-13T10:00:00+00:00", overall=60.0),  # Mon of week 16
            _row(started_at="2026-04-14T10:00:00+00:00", overall=70.0),  # Tue
            _row(started_at="2026-04-19T10:00:00+00:00", overall=80.0),  # Sun (last day)
            _row(started_at="2026-04-20T10:00:00+00:00", overall=90.0),  # next week
        ],
    )
    digest = build_weekly_digest(tmp_path, iso_week="2026-W16", llm=None)
    assert digest is not None
    assert digest.session_count == 3
    assert digest.average_overall == 70.0


def test_weekly_digest_computes_delta_vs_prior_week(tmp_path: Path) -> None:
    _write_scores(
        tmp_path / "scores.json",
        [
            # Prior week (W15): 2026-04-06 .. 2026-04-12
            _row(started_at="2026-04-07T10:00:00+00:00", overall=50.0),
            _row(started_at="2026-04-08T10:00:00+00:00", overall=60.0),
            # This week (W16)
            _row(started_at="2026-04-13T10:00:00+00:00", overall=80.0),
            _row(started_at="2026-04-14T10:00:00+00:00", overall=80.0),
        ],
    )
    digest = build_weekly_digest(tmp_path, iso_week="2026-W16", llm=None)
    assert digest is not None
    assert digest.prior_average_overall == 55.0
    assert digest.delta_overall == 25.0
