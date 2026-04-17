"""User-editable config. Reads TOML from data/config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_VALID_TONES = ("roast", "coach")


@dataclass(frozen=True)
class Config:
    tone: str = "roast"
    daily_llm_cap: int = 50
    idle_gap_seconds: int = 1800
    trivial_tool_threshold: int = 5


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return Config()
    tone = raw.get("tone")
    if tone not in _VALID_TONES:
        tone = Config.tone
    return Config(
        tone=tone,
        daily_llm_cap=int(raw.get("daily_llm_cap", Config.daily_llm_cap)),
        idle_gap_seconds=int(raw.get("idle_gap_seconds", Config.idle_gap_seconds)),
        trivial_tool_threshold=int(raw.get("trivial_tool_threshold", Config.trivial_tool_threshold)),
    )
