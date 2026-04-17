"""Subprocess wrapper around `claude -p`.

Gives us access to Haiku/Sonnet for intent classification and semantic scoring
without requiring a separate ANTHROPIC_API_KEY — the user's existing Claude
Code auth is reused via the CLI.

Global per-day call cap (default 50) prevents runaway token spend; exceeding
it raises CallCapExceeded and the caller is expected to fall back to
deterministic-only scoring.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class LLMUnavailable(RuntimeError):
    """`claude -p` couldn't be run or returned non-zero."""


class CallCapExceeded(RuntimeError):
    """Daily call cap hit; caller should degrade to deterministic-only scoring."""


class ClaudeCLIBackend:
    def __init__(
        self,
        cache_dir: Path,
        daily_cap: int = 50,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._counter_path = self._cache_dir / "llm_calls.json"
        self._cap = daily_cap
        self._timeout = timeout_seconds

    def complete(self, prompt: str, *, model: str) -> str:
        if self._today_count() >= self._cap:
            raise CallCapExceeded(
                f"Daily LLM call cap ({self._cap}) hit — falling back to deterministic scoring."
            )
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model, prompt],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LLMUnavailable("claude CLI not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMUnavailable(f"claude -p timed out after {self._timeout}s") from exc

        if result.returncode != 0:
            raise LLMUnavailable(
                f"claude -p exited {result.returncode}: {(result.stderr or '').strip()[:200]}"
            )

        self._increment_today()
        return (result.stdout or "").strip()

    def today_calls(self) -> int:
        return self._today_count()

    # --- persistence helpers ---

    def _today_count(self) -> int:
        data = self._load()
        return data.get(self._today_key(), 0)

    def _increment_today(self) -> None:
        data = self._load()
        key = self._today_key()
        data[key] = data.get(key, 0) + 1
        self._counter_path.write_text(json.dumps(data))

    def _load(self) -> dict[str, int]:
        if not self._counter_path.exists():
            return {}
        try:
            return json.loads(self._counter_path.read_text())
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).date().isoformat()
