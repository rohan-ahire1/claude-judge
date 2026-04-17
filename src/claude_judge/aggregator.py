"""Weighted rollup of per-dimension scores into an overall 0-100.

Weights:
  Tier A (2x): review_discipline, security_hygiene, outcome_correlation, rework_rate
  Tier B (1x): leverage_fit, skill_progression, prompt_quality

Unknown scorer names get the Tier B default so future dimensions don't
silently break the rollup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from claude_judge.scorers import ScoreResult

_TIER_A = frozenset(
    {"review_discipline", "security_hygiene", "outcome_correlation", "rework_rate"}
)
_TIER_B = frozenset({"leverage_fit", "skill_progression", "prompt_quality"})

_TIER_A_WEIGHT = 2
_TIER_B_WEIGHT = 1


@dataclass(frozen=True)
class AggregateScore:
    overall: float  # 0-100
    tier_a_average: float | None  # average of Tier A scores present, 0-10
    tier_b_average: float | None  # average of Tier B scores present, 0-10


def _weight_for(name: str) -> int:
    if name in _TIER_A:
        return _TIER_A_WEIGHT
    return _TIER_B_WEIGHT  # Tier B or forward-compat default


def aggregate(results: Iterable[ScoreResult]) -> AggregateScore | None:
    results = list(results)
    if not results:
        return None

    total_weighted = 0.0
    total_weight = 0
    tier_a_sum = 0.0
    tier_a_n = 0
    tier_b_sum = 0.0
    tier_b_n = 0

    for r in results:
        w = _weight_for(r.name)
        total_weighted += w * r.score
        total_weight += w
        if r.name in _TIER_A:
            tier_a_sum += r.score
            tier_a_n += 1
        else:
            tier_b_sum += r.score
            tier_b_n += 1

    if total_weight == 0:
        return None

    overall_raw = total_weighted / total_weight  # 0-10
    return AggregateScore(
        overall=round(overall_raw * 10, 1),
        tier_a_average=round(tier_a_sum / tier_a_n, 1) if tier_a_n else None,
        tier_b_average=round(tier_b_sum / tier_b_n, 1) if tier_b_n else None,
    )


class ScoreAggregator:
    """Object-oriented alias for the aggregate() function — useful when
    callers want to inject a different aggregator (e.g., for tests or future
    custom weighting schemes)."""

    def aggregate(self, results: Iterable[ScoreResult]) -> AggregateScore | None:
        return aggregate(results)
