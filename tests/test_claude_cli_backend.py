from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_judge.claude_cli_backend import (
    CallCapExceeded,
    ClaudeCLIBackend,
    LLMUnavailable,
)


def _fake_run(stdout: str = "ok", returncode: int = 0, side_effect=None):
    mock = MagicMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = MagicMock(stdout=stdout, stderr="", returncode=returncode)
    return mock


def test_calls_claude_p_with_model_and_prompt(tmp_path: Path) -> None:
    backend = ClaudeCLIBackend(cache_dir=tmp_path)
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="hello")) as run:
        out = backend.complete(prompt="what is 2+2?", model="haiku")
    assert out == "hello"
    args = run.call_args.args[0]
    assert args[:2] == ["claude", "-p"]
    assert "--model" in args and "haiku" in args
    assert "what is 2+2?" in args


def test_call_counter_persists_across_instances(tmp_path: Path) -> None:
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="a")):
        ClaudeCLIBackend(cache_dir=tmp_path).complete("p1", model="haiku")
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="b")):
        ClaudeCLIBackend(cache_dir=tmp_path).complete("p2", model="haiku")
    data = json.loads((tmp_path / "llm_calls.json").read_text())
    today = datetime.now(timezone.utc).date().isoformat()
    assert data[today] == 2


def test_hard_cap_raises_call_cap_exceeded(tmp_path: Path) -> None:
    backend = ClaudeCLIBackend(cache_dir=tmp_path, daily_cap=2)
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="x")):
        backend.complete("p1", model="haiku")
        backend.complete("p2", model="haiku")
    with pytest.raises(CallCapExceeded):
        backend.complete("p3", model="haiku")


def test_counter_resets_after_day_rolls_over(tmp_path: Path) -> None:
    # Pre-seed yesterday's count; today should start fresh.
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    (tmp_path / "llm_calls.json").write_text(json.dumps({yesterday: 99}))

    backend = ClaudeCLIBackend(cache_dir=tmp_path, daily_cap=5)
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="ok")):
        backend.complete("p1", model="haiku")

    data = json.loads((tmp_path / "llm_calls.json").read_text())
    today = datetime.now(timezone.utc).date().isoformat()
    assert data[today] == 1


def test_non_zero_exit_raises_llm_unavailable(tmp_path: Path) -> None:
    backend = ClaudeCLIBackend(cache_dir=tmp_path)
    with patch(
        "claude_judge.claude_cli_backend.subprocess.run",
        _fake_run(stdout="", returncode=2),
    ):
        with pytest.raises(LLMUnavailable):
            backend.complete("p", model="haiku")


def test_missing_claude_binary_raises_llm_unavailable(tmp_path: Path) -> None:
    backend = ClaudeCLIBackend(cache_dir=tmp_path)
    with patch(
        "claude_judge.claude_cli_backend.subprocess.run",
        _fake_run(side_effect=FileNotFoundError()),
    ):
        with pytest.raises(LLMUnavailable):
            backend.complete("p", model="haiku")


def test_model_alias_accepts_haiku_sonnet_opus(tmp_path: Path) -> None:
    backend = ClaudeCLIBackend(cache_dir=tmp_path)
    with patch("claude_judge.claude_cli_backend.subprocess.run", _fake_run(stdout="ok")) as run:
        backend.complete("p", model="sonnet")
        backend.complete("p", model="opus")
    models_seen = [call.args[0][call.args[0].index("--model") + 1] for call in run.call_args_list]
    assert set(models_seen) == {"sonnet", "opus"}
