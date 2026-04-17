from pathlib import Path

from claude_judge.config import Config, load_config


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.tone == "roast"
    assert cfg.daily_llm_cap == 50
    assert cfg.idle_gap_seconds == 1800
    assert cfg.trivial_tool_threshold == 5


def test_reads_tone_and_thresholds(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'tone = "coach"\n'
        'daily_llm_cap = 100\n'
        'idle_gap_seconds = 3600\n'
        'trivial_tool_threshold = 10\n'
    )
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.tone == "coach"
    assert cfg.daily_llm_cap == 100
    assert cfg.idle_gap_seconds == 3600
    assert cfg.trivial_tool_threshold == 10


def test_invalid_tone_falls_back_to_default(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('tone = "shouty"\n')
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.tone == "roast"


def test_partial_file_uses_defaults_for_missing_fields(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('tone = "coach"\n')
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.tone == "coach"
    assert cfg.daily_llm_cap == 50  # default
