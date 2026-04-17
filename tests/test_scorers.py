from claude_judge.scorers import (
    OutcomeCorrelationScorer,
    ReviewDisciplineScorer,
    ReworkRateScorer,
    SecurityHygieneScorer,
)
from claude_judge.summarizer import SessionStats


def _stats(**overrides) -> SessionStats:
    base: dict = dict(
        session_id="s#t",
        project_root="/p",
        started_at="2026-04-17T10:00:00+00:00",
        ended_at="2026-04-17T10:10:00+00:00",
        duration_seconds=600.0,
        tool_call_count=10,
    )
    base.update(overrides)
    return SessionStats(**base)


# --- Review Discipline ---


def test_review_discipline_penalizes_all_fast_approvals_in_prompt_mode() -> None:
    stats = _stats(
        approval_latencies_ms=[100.0] * 10,
        tool_call_count=10,
        permission_mode="prompt",
    )
    result = ReviewDisciplineScorer().score(stats)
    assert result is not None
    assert result.score <= 3
    assert "fast" in result.rationale.lower() or "blind" in result.rationale.lower()


def test_review_discipline_rewards_deliberate_approvals_in_prompt_mode() -> None:
    stats = _stats(
        approval_latencies_ms=[5000.0] * 10,
        tool_call_count=10,
        permission_mode="prompt",
    )
    result = ReviewDisciplineScorer().score(stats)
    assert result is not None
    assert result.score >= 8


def test_review_discipline_skips_trivial_sessions() -> None:
    stats = _stats(tool_call_count=2, approval_latencies_ms=[])
    assert ReviewDisciplineScorer().score(stats) is None


# --- Security Hygiene ---


def test_security_hygiene_perfect_on_clean_session() -> None:
    stats = _stats(security_red_flags=[])
    result = SecurityHygieneScorer().score(stats)
    assert result is not None
    assert result.score == 10.0


def test_security_hygiene_deducts_per_flag() -> None:
    stats = _stats(security_red_flags=["rm_rf", "force_push"])
    result = SecurityHygieneScorer().score(stats)
    assert result is not None
    assert result.score < 10.0
    assert "rm_rf" in result.rationale


def test_security_hygiene_floors_at_zero() -> None:
    stats = _stats(security_red_flags=["rm_rf", "force_push", "no_verify", "reset_hard", "openai_key_in_prompt", "aws_key_in_prompt"])
    result = SecurityHygieneScorer().score(stats)
    assert result is not None
    assert result.score == 0.0


# --- Outcome Correlation ---


def test_outcome_correlation_low_when_edits_but_no_commits() -> None:
    stats = _stats(edit_paths=["/a.py", "/b.py", "/c.py"], git_commit_count=0)
    result = OutcomeCorrelationScorer().score(stats)
    assert result is not None
    assert result.score <= 4


def test_outcome_correlation_high_when_edits_and_commits() -> None:
    stats = _stats(edit_paths=["/a.py", "/b.py"], git_commit_count=2)
    result = OutcomeCorrelationScorer().score(stats)
    assert result is not None
    assert result.score >= 8


def test_outcome_correlation_neutral_for_no_edits() -> None:
    stats = _stats(edit_paths=[], git_commit_count=0)
    result = OutcomeCorrelationScorer().score(stats)
    assert result is not None
    assert 5 <= result.score <= 8  # neutral — could be reading/exploring


# --- Rework Rate ---


def test_rework_rate_perfect_when_each_file_edited_once() -> None:
    stats = _stats(edit_paths=["/a.py", "/b.py", "/c.py"])
    result = ReworkRateScorer().score(stats)
    assert result is not None
    assert result.score >= 9


def test_rework_rate_low_when_files_repeatedly_edited() -> None:
    stats = _stats(edit_paths=["/a.py"] * 6 + ["/b.py"] * 4)  # 10 edits, 2 files -> heavy rework
    result = ReworkRateScorer().score(stats)
    assert result is not None
    assert result.score <= 4


def test_rework_rate_skips_when_no_edits() -> None:
    stats = _stats(edit_paths=[])
    assert ReworkRateScorer().score(stats) is None
