from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from claude_judge.aggregator import AggregateScore
from claude_judge.claude_cli_backend import CallCapExceeded, LLMUnavailable
from claude_judge.scorers import ScoreResult
from claude_judge.summarizer import SessionStats
from claude_judge.verdict_writer import VerdictWriter


def _stats(session_id: str = "s#2026-04-17T10:00:00+00:00") -> SessionStats:
    return SessionStats(
        session_id=session_id,
        project_root="/p",
        started_at="2026-04-17T10:00:00+00:00",
        ended_at="2026-04-17T10:30:00+00:00",
        duration_seconds=1800.0,
        tool_call_count=25,
    )


def _backend(response: str) -> MagicMock:
    b = MagicMock()
    b.complete.return_value = response
    return b


def _scores() -> list[ScoreResult]:
    return [
        ScoreResult(name="review_discipline", score=3.0, rationale="lots of fast approvals"),
        ScoreResult(name="security_hygiene", score=10.0, rationale="clean"),
    ]


def _agg() -> AggregateScore:
    return AggregateScore(overall=65.0, tier_a_average=6.5, tier_b_average=5.0)


def test_writes_roast_via_backend(tmp_path: Path) -> None:
    backend = _backend("You blind-approved half your bash calls. Quit it.")
    writer = VerdictWriter(backend=backend, cache_dir=tmp_path, tone="roast")
    verdict = writer.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    assert verdict.startswith("You blind-approved")
    # Sonnet model should be requested for prose verdicts
    assert backend.complete.call_args.kwargs["model"] == "sonnet"


def test_caches_verdict_by_session_id(tmp_path: Path) -> None:
    backend = _backend("ouch")
    writer = VerdictWriter(backend=backend, cache_dir=tmp_path, tone="roast")
    writer.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    writer.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    assert backend.complete.call_count == 1


def test_cache_namespaced_by_tone(tmp_path: Path) -> None:
    # Same session, different tones must not collide in cache
    backend_roast = _backend("brutal")
    backend_coach = _backend("encouraging")
    roast = VerdictWriter(backend=backend_roast, cache_dir=tmp_path, tone="roast")
    coach = VerdictWriter(backend=backend_coach, cache_dir=tmp_path, tone="coach")
    r = roast.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    c = coach.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    assert r == "brutal"
    assert c == "encouraging"


def test_backend_failure_returns_fallback_template(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = LLMUnavailable("down")
    writer = VerdictWriter(backend=backend, cache_dir=tmp_path, tone="roast")
    verdict = writer.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    assert verdict  # non-empty
    assert "65" in verdict or "65.0" in verdict  # mentions overall


def test_call_cap_exceeded_returns_fallback(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = CallCapExceeded("cap")
    writer = VerdictWriter(backend=backend, cache_dir=tmp_path, tone="coach")
    verdict = writer.write(_stats(), intent="coding", scores=_scores(), overall=_agg())
    assert verdict


def test_prompt_mentions_score_and_weakest_dimension(tmp_path: Path) -> None:
    backend = _backend("x")
    VerdictWriter(backend=backend, cache_dir=tmp_path, tone="roast").write(
        _stats(), intent="coding", scores=_scores(), overall=_agg()
    )
    prompt = backend.complete.call_args.kwargs["prompt"]
    assert "65" in prompt
    assert "review_discipline" in prompt  # weakest Tier A
    # Tone instruction is present
    assert "roast" in prompt.lower()


def test_tone_coach_uses_different_prompt(tmp_path: Path) -> None:
    backend = _backend("x")
    VerdictWriter(backend=backend, cache_dir=tmp_path, tone="coach").write(
        _stats(), intent="coding", scores=_scores(), overall=_agg()
    )
    prompt = backend.complete.call_args.kwargs["prompt"]
    assert "coach" in prompt.lower()
