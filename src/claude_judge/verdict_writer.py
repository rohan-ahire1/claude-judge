"""Composes the natural-language verdict for a session.

Two personas:
  - roast: blunt, pointed, no sugar-coating
  - coach: constructive, improvement-focused

Both use Sonnet for prose quality. Results cached per (session_id, tone).
Backend failure → deterministic fallback template so the CLI always prints
*something*.
"""
from __future__ import annotations

import json
from pathlib import Path

from claude_judge.aggregator import AggregateScore
from claude_judge.claude_cli_backend import CallCapExceeded, ClaudeCLIBackend, LLMUnavailable
from claude_judge.scorers import ScoreResult
from claude_judge.summarizer import SessionStats

_CACHE_FILENAME = "verdict_cache.json"

_ROAST_INSTRUCTION = (
    "Write a blunt, pointed 2-3 sentence roast of this Claude Code session. "
    "No sugar-coating, no exclamation points, no emojis. "
    "Lead with the weakest dimension. If the session is clean, say so tersely "
    "and pick the next most-actionable weakness. Match a no-nonsense Pattern "
    "engineering-manager voice. Under 60 words total."
)

_COACH_INSTRUCTION = (
    "Write a constructive 2-3 sentence coaching note for this Claude Code session. "
    "Acknowledge what went well, then name the single most-actionable thing to "
    "change next time. No platitudes, no exclamation points. Match a senior "
    "engineer mentoring a peer. Under 60 words total."
)

_VALID_TONES = ("roast", "coach")


class VerdictWriter:
    def __init__(
        self,
        backend: ClaudeCLIBackend,
        cache_dir: Path,
        tone: str = "roast",
        model: str = "sonnet",
    ) -> None:
        if tone not in _VALID_TONES:
            raise ValueError(f"tone must be one of {_VALID_TONES}, got {tone!r}")
        self._backend = backend
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path = self._cache_dir / _CACHE_FILENAME
        self._tone = tone
        self._model = model

    def write(
        self,
        stats: SessionStats,
        intent: str,
        scores: list[ScoreResult],
        overall: AggregateScore,
    ) -> str:
        cache_key = f"{self._tone}:{stats.session_id}"
        cached = self._lookup(cache_key)
        if cached:
            return cached

        prompt = self._build_prompt(stats, intent, scores, overall)
        try:
            verdict = self._backend.complete(prompt=prompt, model=self._model).strip()
        except (LLMUnavailable, CallCapExceeded):
            return self._fallback(overall, scores)

        if not verdict:
            return self._fallback(overall, scores)

        self._store(cache_key, verdict)
        return verdict

    # --- internals ---

    def _build_prompt(
        self,
        stats: SessionStats,
        intent: str,
        scores: list[ScoreResult],
        overall: AggregateScore,
    ) -> str:
        instruction = _ROAST_INSTRUCTION if self._tone == "roast" else _COACH_INSTRUCTION
        weakest = min(scores, key=lambda r: r.score) if scores else None
        scorecard = "\n".join(f"- {r.name}: {r.score:.1f}/10 — {r.rationale}" for r in scores)
        return (
            f"{instruction}\n\n"
            f"Tone: {self._tone}\n"
            f"Intent: {intent}\n"
            f"Overall: {overall.overall:.1f} / 100\n"
            f"Weakest dimension: {weakest.name if weakest else 'n/a'}\n"
            f"Duration: {stats.duration_seconds / 60:.1f} min, tools={stats.tool_call_count}\n\n"
            f"Scorecard:\n{scorecard}\n\n"
            "Respond with only the verdict prose. No preamble, no headers."
        )

    @staticmethod
    def _fallback(overall: AggregateScore, scores: list[ScoreResult]) -> str:
        weakest = min(scores, key=lambda r: r.score) if scores else None
        if weakest is None:
            return f"Score: {overall.overall:.1f}/100. No rated dimensions — trivial session."
        return (
            f"Score: {overall.overall:.1f}/100. Weakest: {weakest.name} "
            f"at {weakest.score:.1f}/10 — {weakest.rationale}"
        )

    def _load_cache(self) -> dict:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text())
        except json.JSONDecodeError:
            return {}

    def _lookup(self, key: str) -> str | None:
        return self._load_cache().get(key)

    def _store(self, key: str, verdict: str) -> None:
        cache = self._load_cache()
        cache[key] = verdict
        self._cache_path.write_text(json.dumps(cache))
