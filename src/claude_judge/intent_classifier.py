"""Classifies a session's intent via Haiku.

Labels: coding | planning | learning | exploration | debugging | ops | unknown
(unknown = backend unavailable or unparseable response)

Classifications are cached by session_id forever — session IDs encode the
segment start timestamp, so they are stable. A cached session never re-hits
the LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from claude_judge.claude_cli_backend import ClaudeCLIBackend
from claude_judge.summarizer import SessionStats

VALID_INTENTS = ("coding", "planning", "learning", "exploration", "debugging", "ops")
_UNKNOWN = "unknown"

_CACHE_FILENAME = "intent_cache.json"


class IntentClassifier:
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

    def classify(self, stats: SessionStats) -> str:
        cache = self._load()
        if stats.session_id in cache:
            return cache[stats.session_id]

        prompt = self._build_prompt(stats)
        try:
            response = self._backend.complete(prompt=prompt, model=self._model)
        except Exception:
            return _UNKNOWN

        label = _parse_intent(response)
        if label == _UNKNOWN:
            return _UNKNOWN  # don't cache unparseable — next run may succeed

        cache[stats.session_id] = label
        self._cache_path.write_text(json.dumps(cache))
        return label

    # --- internals ---

    def _load(self) -> dict[str, str]:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text())
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _build_prompt(stats: SessionStats) -> str:
        excerpts = "\n".join(f"- {e[:200]}" for e in stats.prompt_excerpts[:3])
        return (
            "Classify this Claude Code session's primary intent. "
            f"Choose EXACTLY one label from: {', '.join(VALID_INTENTS)}. "
            "Respond with only the label — no explanation.\n\n"
            f"Duration: {stats.duration_seconds / 60:.1f} min\n"
            f"Tool calls: {stats.tool_call_count}\n"
            f"Files edited: {len(stats.edit_paths)}\n"
            f"Files read/touched: {len(stats.files_touched)}\n"
            f"Git commits in-session: {stats.git_commit_count}\n"
            f"First 3 user-prompt excerpts:\n{excerpts or '(none)'}\n"
        )


def _parse_intent(response: str) -> str:
    text = response.lower()
    for label in VALID_INTENTS:
        # word-boundary match so 'coding' doesn't spuriously match 'decoding'
        if re.search(rf"\b{re.escape(label)}\b", text):
            return label
    return _UNKNOWN
