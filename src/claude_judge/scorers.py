"""Deterministic Tier A scorers.

Each scorer is a pure function of SessionStats → ScoreResult | None.
Return None when the scorer is not applicable (e.g., trivial session for
review discipline, or no edits for rework rate).

These scorers are intentionally simple. Intent-awareness is layered on top
via the LLM IntentClassifier (slice 5) — these just need to return a raw
signal the aggregator can weight later.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from claude_judge.git_correlator import GitWindow
from claude_judge.summarizer import SessionStats

# Weight of each red flag label in the Security Hygiene score (out of 10).
_SECURITY_FLAG_WEIGHTS = {
    "openai_key_in_prompt": 6.0,
    "github_pat_in_prompt": 6.0,
    "aws_key_in_prompt": 6.0,
    "slack_token_in_prompt": 6.0,
    "jwt_in_prompt": 4.0,
    "basic_auth_url_in_prompt": 5.0,
    "rm_rf": 4.0,
    "force_push": 4.0,
    "no_verify": 3.0,
    "reset_hard": 3.0,
    "checkout_discard": 3.0,
    "branch_delete_force": 2.0,
}


@dataclass
class ScoreResult:
    name: str
    score: float
    rationale: str


class ReviewDisciplineScorer:
    """Measures deliberation before approving tool calls.

    Only meaningful in 'prompt'/'ask' permission mode, where the user is
    actively approving each tool call. In 'auto' / 'bypass' modes the user
    has opted into blind approval, so latency isn't a discipline signal —
    we return a neutral 7 and let Security Hygiene catch actual bad outcomes.
    """

    name = "review_discipline"
    _TRIVIAL_THRESHOLD = 5

    def score(self, stats: SessionStats, git: GitWindow | None = None) -> ScoreResult | None:
        if stats.tool_call_count < self._TRIVIAL_THRESHOLD:
            return None
        latencies = stats.approval_latencies_ms
        if not latencies:
            return None

        fast = sum(1 for ms in latencies if ms < 500)
        total = len(latencies)
        fast_ratio = fast / total

        if stats.permission_mode in {"auto", "bypass", "bypassPermissions"}:
            return ScoreResult(
                name=self.name,
                score=7.0,
                rationale=(
                    f"Auto/bypass mode ({stats.permission_mode}); "
                    f"{fast}/{total} fast approvals — review discipline measured downstream via Security Hygiene."
                ),
            )

        # prompt / ask / unknown: latency is the discipline signal
        raw = 10.0 * (1.0 - fast_ratio)
        return ScoreResult(
            name=self.name,
            score=round(raw, 1),
            rationale=(
                f"{fast}/{total} approvals under 500ms ({int(fast_ratio * 100)}% fast)."
                + (" Pattern looks like blind approval." if fast_ratio > 0.5 else "")
            ),
        )


class SecurityHygieneScorer:
    """Deducts per red-flag label. Starts at 10, floors at 0."""

    name = "security_hygiene"

    def score(self, stats: SessionStats, git: GitWindow | None = None) -> ScoreResult | None:
        flags = stats.security_red_flags
        if not flags:
            return ScoreResult(name=self.name, score=10.0, rationale="Clean.")

        total_deduction = sum(_SECURITY_FLAG_WEIGHTS.get(f, 2.0) for f in flags)
        score = max(0.0, 10.0 - total_deduction)
        rationale = "Red flags: " + ", ".join(flags)
        return ScoreResult(name=self.name, score=round(score, 1), rationale=rationale)


class OutcomeCorrelationScorer:
    """How well did edits correlate with shipped commits?

    V1 uses in-session git-commit count from Bash commands as a proxy —
    slice 4 upgrades this to real git log correlation.
    Intent-awareness (planning sessions shouldn't be penalized for no
    commits) is added in slice 6 via the LLM intent classifier.
    """

    name = "outcome_correlation"

    def score(self, stats: SessionStats, git: GitWindow | None = None) -> ScoreResult | None:
        edits = len(stats.edit_paths)
        in_session_commits = stats.git_commit_count
        external_commits = len(git.commits) if git else 0
        # Use the max so the user gets credit whether they committed via Bash
        # tool call or via terminal/UI outside the Claude Code session.
        commits = max(in_session_commits, external_commits)

        if edits == 0:
            return ScoreResult(
                name=self.name,
                score=7.0,
                rationale="No edits this session — neutral (intent unknown without classifier).",
            )

        if commits == 0:
            return ScoreResult(
                name=self.name,
                score=3.0,
                rationale=f"{edits} edits but zero commits in window. Orphan work risk.",
            )

        ratio = min(commits / max(1, edits / 3), 1.0)
        score = 6.0 + 4.0 * ratio
        source = "in-session" if in_session_commits >= external_commits else "window"
        return ScoreResult(
            name=self.name,
            score=round(score, 1),
            rationale=f"{edits} edits ↔ {commits} commits ({source}).",
        )


class ReworkRateScorer:
    """Files edited more than once in the session = rework.

    Only runs when the session actually contains edits.
    """

    name = "rework_rate"

    def score(self, stats: SessionStats, git: GitWindow | None = None) -> ScoreResult | None:
        if not stats.edit_paths:
            return None

        counts = Counter(stats.edit_paths)
        unique_files = len(counts)
        multi_edited = sum(1 for _, c in counts.items() if c > 1)
        rework_ratio = multi_edited / unique_files if unique_files else 0.0
        base = 10.0 * (1.0 - rework_ratio)

        reverts = git.reverts_matched if git else 0
        revert_penalty = min(reverts * 2.0, base)  # up to -2 per revert, can't go below 0
        score = max(0.0, round(base - revert_penalty, 1))

        parts = [
            f"{multi_edited}/{unique_files} files edited >1x ({int(rework_ratio * 100)}% rework)"
        ]
        if reverts:
            parts.append(f"{reverts} revert commit(s) in window")
        return ScoreResult(name=self.name, score=score, rationale="; ".join(parts) + ".")


TIER_A_SCORERS = (
    ReviewDisciplineScorer(),
    SecurityHygieneScorer(),
    OutcomeCorrelationScorer(),
    ReworkRateScorer(),
)
