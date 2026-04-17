from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from claude_judge.claude_cli_backend import CallCapExceeded, LLMUnavailable
from claude_judge.llm_scorers import (
    LeverageFitScorer,
    PromptQualityScorer,
    SkillProgressionScorer,
)
from claude_judge.summarizer import SessionStats


def _stats(**overrides) -> SessionStats:
    base = dict(
        session_id="sess#2026-04-17T10:00:00+00:00",
        project_root="/p",
        started_at="2026-04-17T10:00:00+00:00",
        ended_at="2026-04-17T10:30:00+00:00",
        duration_seconds=1800.0,
        tool_call_count=25,
        edit_paths=["/a.py", "/b.py"],
        prompt_excerpts=["Fix the bug in login flow", "Also add tests"],
    )
    base.update(overrides)
    return SessionStats(**base)


def _backend(response: str) -> MagicMock:
    b = MagicMock()
    b.complete.return_value = response
    return b


# --- Base behaviors (shared across all three scorers) ---


def test_trivial_session_returns_none(tmp_path: Path) -> None:
    backend = _backend("SCORE: 9\nRATIONALE: great")
    stats = _stats(tool_call_count=3)
    for scorer in (
        LeverageFitScorer(backend=backend, cache_dir=tmp_path),
        SkillProgressionScorer(backend=backend, cache_dir=tmp_path),
        PromptQualityScorer(backend=backend, cache_dir=tmp_path),
    ):
        assert scorer.score(stats) is None
    backend.complete.assert_not_called()


def test_parses_structured_response(tmp_path: Path) -> None:
    backend = _backend("SCORE: 7\nRATIONALE: Opus was overkill for small edits.")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    result = scorer.score(_stats())
    assert result is not None
    assert result.score == 7.0
    assert "overkill" in result.rationale.lower()


def test_clamps_score_to_valid_range(tmp_path: Path) -> None:
    for raw in ("SCORE: 11", "SCORE: -1", "SCORE: 15\nRATIONALE: x"):
        backend = _backend(raw)
        scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
        result = scorer.score(_stats())
        assert result is not None
        assert 0.0 <= result.score <= 10.0


def test_unparseable_response_returns_none(tmp_path: Path) -> None:
    backend = _backend("I don't know.")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    assert scorer.score(_stats()) is None


def test_llm_unavailable_returns_none(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = LLMUnavailable("down")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    assert scorer.score(_stats()) is None


def test_call_cap_exceeded_returns_none(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = CallCapExceeded("cap")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    assert scorer.score(_stats()) is None


# --- Caching ---


def test_result_cached_by_session_id(tmp_path: Path) -> None:
    backend = _backend("SCORE: 8\nRATIONALE: ok")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    scorer.score(_stats())
    scorer.score(_stats())
    assert backend.complete.call_count == 1


def test_different_scorers_do_not_collide_in_cache(tmp_path: Path) -> None:
    backend_a = _backend("SCORE: 8\nRATIONALE: leverage")
    backend_b = _backend("SCORE: 5\nRATIONALE: prompt")
    leverage = LeverageFitScorer(backend=backend_a, cache_dir=tmp_path)
    prompt = PromptQualityScorer(backend=backend_b, cache_dir=tmp_path)
    a = leverage.score(_stats())
    b = prompt.score(_stats())
    assert a is not None and b is not None
    assert a.score == 8.0
    assert b.score == 5.0


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    backend = _backend("SCORE: 6\nRATIONALE: thing")
    LeverageFitScorer(backend=backend, cache_dir=tmp_path).score(_stats())

    fresh_backend = _backend("SCORE: 0\nRATIONALE: should-not-be-called")
    result = LeverageFitScorer(backend=fresh_backend, cache_dir=tmp_path).score(_stats())
    assert result is not None
    assert result.score == 6.0
    fresh_backend.complete.assert_not_called()


# --- Prompt content sanity ---


def test_leverage_fit_prompt_references_tool_and_edit_counts(tmp_path: Path) -> None:
    backend = _backend("SCORE: 9\nRATIONALE: ok")
    scorer = LeverageFitScorer(backend=backend, cache_dir=tmp_path)
    scorer.score(_stats(tool_call_count=42, edit_paths=["/a.py"]))
    sent = backend.complete.call_args.kwargs["prompt"]
    assert "42" in sent


def test_skill_progression_prompt_mentions_advanced_features(tmp_path: Path) -> None:
    backend = _backend("SCORE: 4\nRATIONALE: meh")
    scorer = SkillProgressionScorer(backend=backend, cache_dir=tmp_path)
    scorer.score(_stats())
    sent = backend.complete.call_args.kwargs["prompt"]
    # Must ask about at least plan mode + subagents + skills
    lowered = sent.lower()
    assert "plan" in lowered and ("subagent" in lowered or "agent" in lowered) and "skill" in lowered


def test_prompt_quality_includes_prompt_excerpts(tmp_path: Path) -> None:
    backend = _backend("SCORE: 7\nRATIONALE: clear")
    scorer = PromptQualityScorer(backend=backend, cache_dir=tmp_path)
    scorer.score(_stats(prompt_excerpts=["the quick brown fox"]))
    sent = backend.complete.call_args.kwargs["prompt"]
    assert "quick brown fox" in sent
