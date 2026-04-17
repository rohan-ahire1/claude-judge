from claude_judge.aggregator import ScoreAggregator, aggregate
from claude_judge.scorers import ScoreResult


def _r(name: str, score: float) -> ScoreResult:
    return ScoreResult(name=name, score=score, rationale="")


# Tier A: review_discipline, security_hygiene, outcome_correlation, rework_rate (weight 2)
# Tier B: leverage_fit, skill_progression, prompt_quality (weight 1)


def test_weighted_average_all_tier_a_tens() -> None:
    scores = [
        _r("review_discipline", 10),
        _r("security_hygiene", 10),
        _r("outcome_correlation", 10),
        _r("rework_rate", 10),
    ]
    result = aggregate(scores)
    assert result.overall == 100.0
    assert result.tier_a_average == 10.0
    assert result.tier_b_average is None


def test_weighted_average_mixed_tiers() -> None:
    scores = [
        _r("review_discipline", 10),
        _r("security_hygiene", 10),
        _r("outcome_correlation", 10),
        _r("rework_rate", 10),
        _r("leverage_fit", 5),
        _r("skill_progression", 5),
        _r("prompt_quality", 5),
    ]
    # Weighted: (2*10 + 2*10 + 2*10 + 2*10 + 1*5 + 1*5 + 1*5) / (8+3) = 95/11
    # Normalized to 0-100 = 95/11 * 10 = 86.36
    result = aggregate(scores)
    assert 86.0 <= result.overall <= 87.0
    assert result.tier_a_average == 10.0
    assert result.tier_b_average == 5.0


def test_missing_scorers_reduce_denominator_not_score() -> None:
    # Only security_hygiene applied and got 10. Overall should still be 100.
    scores = [_r("security_hygiene", 10)]
    result = aggregate(scores)
    assert result.overall == 100.0
    assert result.tier_a_average == 10.0


def test_empty_scorers_returns_none() -> None:
    assert aggregate([]) is None


def test_unknown_scorer_names_get_default_tier_b_weight() -> None:
    # Forward-compatibility: future scorer names shouldn't silently break aggregation
    scores = [_r("future_unknown_scorer", 8)]
    result = aggregate(scores)
    assert result is not None
    assert result.overall == 80.0


def test_class_interface_matches_function() -> None:
    scores = [_r("security_hygiene", 8), _r("leverage_fit", 6)]
    via_class = ScoreAggregator().aggregate(scores)
    via_func = aggregate(scores)
    assert via_class == via_func
