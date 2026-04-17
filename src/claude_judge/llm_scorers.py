"""Haiku-backed Tier B scorers: Leverage Fit, Skill Progression, Prompt Quality.

All three share a base class that handles:
- Trivial-session skip (<5 tool calls → None)
- Backend failure / cap-exceeded → None
- Structured SCORE/RATIONALE parsing with clamping to [0, 10]
- Session-id keyed result caching (per-scorer, shared file)
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from claude_judge.claude_cli_backend import CallCapExceeded, ClaudeCLIBackend, LLMUnavailable
from claude_judge.git_correlator import GitWindow
from claude_judge.scorers import ScoreResult
from claude_judge.summarizer import SessionStats

_CACHE_FILENAME = "llm_score_cache.json"
_TRIVIAL_THRESHOLD = 5
_SCORE_RE = re.compile(r"SCORE\s*:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_RATIONALE_RE = re.compile(r"RATIONALE\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


class _LLMScorer(ABC):
    name: str

    def __init__(
        self,
        backend: ClaudeCLIBackend,
        cache_dir: Path,
        model: str = "haiku",
    ) -> None:
        self._backend = backend
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path = self._cache_dir / _CACHE_FILENAME
        self._model = model

    def score(
        self,
        stats: SessionStats,
        git: GitWindow | None = None,
        intent: str | None = None,
    ) -> ScoreResult | None:
        if stats.tool_call_count < _TRIVIAL_THRESHOLD:
            return None

        cached = self._lookup(stats.session_id)
        if cached is not None:
            return ScoreResult(name=self.name, score=cached["score"], rationale=cached["rationale"])

        try:
            response = self._backend.complete(
                prompt=self._build_prompt(stats, intent), model=self._model
            )
        except (LLMUnavailable, CallCapExceeded):
            return None

        parsed = _parse(response)
        if parsed is None:
            return None

        score, rationale = parsed
        self._store(stats.session_id, score, rationale)
        return ScoreResult(name=self.name, score=score, rationale=rationale)

    # --- persistence helpers ---

    def _cache_key(self, session_id: str) -> str:
        return f"{self.name}:{session_id}"

    def _load_cache(self) -> dict:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text())
        except json.JSONDecodeError:
            return {}

    def _lookup(self, session_id: str) -> dict | None:
        return self._load_cache().get(self._cache_key(session_id))

    def _store(self, session_id: str, score: float, rationale: str) -> None:
        cache = self._load_cache()
        cache[self._cache_key(session_id)] = {"score": score, "rationale": rationale}
        self._cache_path.write_text(json.dumps(cache))

    # --- subclass hooks ---

    @abstractmethod
    def _build_prompt(self, stats: SessionStats, intent: str | None) -> str:
        ...


def _parse(response: str) -> tuple[float, str] | None:
    score_match = _SCORE_RE.search(response)
    if not score_match:
        return None
    raw = float(score_match.group(1))
    score = max(0.0, min(10.0, raw))
    rationale_match = _RATIONALE_RE.search(response)
    rationale = (rationale_match.group(1).strip() if rationale_match else response.strip())
    # Clip overly long rationales so they don't dominate the terminal.
    rationale = rationale[:300]
    return score, rationale


# --- concrete scorers ---


class LeverageFitScorer(_LLMScorer):
    name = "leverage_fit"

    def _build_prompt(self, stats: SessionStats, intent: str | None) -> str:
        excerpts = "\n".join(f"- {e[:200]}" for e in stats.prompt_excerpts[:3])
        return (
            "Judge whether this Claude Code session used the right level of leverage "
            "(model capability, tool choices, and delegation) for its apparent complexity. "
            "Overkill (e.g., Opus for a one-line typo) scores low; underkill (Haiku for "
            "architectural work) also scores low. Appropriate fit scores high.\n\n"
            f"Intent: {intent or 'unknown'}\n"
            f"Duration: {stats.duration_seconds / 60:.1f} min\n"
            f"Tool calls: {stats.tool_call_count}\n"
            f"Files edited: {len(stats.edit_paths)}\n"
            f"Files read/touched: {len(stats.files_touched)}\n"
            f"Prompt excerpts:\n{excerpts or '(none)'}\n\n"
            "Respond EXACTLY in this format:\n"
            "SCORE: <integer 0-10>\n"
            "RATIONALE: <one sentence, no more than 40 words>\n"
        )


class SkillProgressionScorer(_LLMScorer):
    name = "skill_progression"

    def _build_prompt(self, stats: SessionStats, intent: str | None) -> str:
        excerpts = "\n".join(f"- {e[:200]}" for e in stats.prompt_excerpts[:3])
        return (
            "Judge how effectively this Claude Code session used advanced features — "
            "plan mode, subagents (Task tool), skills, memory, hooks, MCP servers. "
            "A session that relied purely on basic prompt+edit without any delegation "
            "or planning scores low; one that leveraged advanced features appropriately "
            "scores high.\n\n"
            f"Intent: {intent or 'unknown'}\n"
            f"Permission mode: {stats.permission_mode}\n"
            f"Tool calls: {stats.tool_call_count}\n"
            f"Duration: {stats.duration_seconds / 60:.1f} min\n"
            f"Prompt excerpts:\n{excerpts or '(none)'}\n\n"
            "Respond EXACTLY in this format:\n"
            "SCORE: <integer 0-10>\n"
            "RATIONALE: <one sentence naming which advanced features were/weren't used>\n"
        )


class PromptQualityScorer(_LLMScorer):
    name = "prompt_quality"

    def _build_prompt(self, stats: SessionStats, intent: str | None) -> str:
        excerpts = "\n".join(f"- {e[:200]}" for e in stats.prompt_excerpts[:5])
        return (
            "Judge prompt quality based on these user-prompt excerpts. Good prompts have "
            "clear intent, explicit constraints, and enough context for Claude to act "
            "without guessing. Vague 'fix this' prompts score low; well-scoped prompts "
            "with context and constraints score high.\n\n"
            f"Intent: {intent or 'unknown'}\n"
            f"Excerpts:\n{excerpts or '(none)'}\n\n"
            "Respond EXACTLY in this format:\n"
            "SCORE: <integer 0-10>\n"
            "RATIONALE: <one sentence, cite what was missing or done well>\n"
        )
