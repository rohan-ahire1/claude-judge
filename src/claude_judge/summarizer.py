"""Deterministic reducer from a session's event list to SessionStats.

Raw prompt/tool content never flows out of this module unchanged. Downstream
scorers and LLM prompts see only the structured stats + capped excerpts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

_FILE_PATH_KEYS = ("file_path", "path", "notebook_path")


@dataclass
class SessionStats:
    session_id: str
    project_root: str
    started_at: str
    ended_at: str
    duration_seconds: float
    tool_call_count: int
    approval_latencies_ms: list[float] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    prompt_excerpts: list[str] = field(default_factory=list)


class TranscriptSummarizer:
    def __init__(self, max_excerpt_chars: int = 200, max_excerpts: int = 5) -> None:
        self._max_chars = max_excerpt_chars
        self._max_excerpts = max_excerpts

    def summarize(
        self, events: list[dict], *, project_root: str, raw_session_id: str
    ) -> SessionStats:
        timestamps = [_parse_ts(e.get("timestamp")) for e in events]
        timestamps = [t for t in timestamps if t is not None]
        started = timestamps[0] if timestamps else None
        ended = timestamps[-1] if timestamps else None

        tool_uses = list(_iter_tool_uses(events))
        tool_results = _index_tool_results(events)

        latencies: list[float] = []
        files_touched: list[str] = []
        seen_files: set[str] = set()
        for use in tool_uses:
            result_ts = tool_results.get(use.get("id"))
            use_ts = _parse_ts(use.get("_ts"))
            if use_ts is not None and result_ts is not None:
                latency_ms = (result_ts - use_ts).total_seconds() * 1000
                latencies.append(round(latency_ms, 1))
            for key in _FILE_PATH_KEYS:
                path = (use.get("input") or {}).get(key)
                if isinstance(path, str) and path not in seen_files:
                    seen_files.add(path)
                    files_touched.append(path)

        excerpts: list[str] = []
        for event in events:
            if event.get("type") != "user":
                continue
            content = event.get("message", {}).get("content")
            text = content if isinstance(content, str) else None
            if text is None:
                continue
            excerpts.append(text[: self._max_chars])
            if len(excerpts) >= self._max_excerpts:
                break

        session_id = (
            f"{raw_session_id}#{started.isoformat()}" if started else raw_session_id
        )
        return SessionStats(
            session_id=session_id,
            project_root=project_root,
            started_at=started.isoformat() if started else "",
            ended_at=ended.isoformat() if ended else "",
            duration_seconds=(
                (ended - started).total_seconds() if started and ended else 0.0
            ),
            tool_call_count=len(tool_uses),
            approval_latencies_ms=latencies,
            files_touched=files_touched,
            prompt_excerpts=excerpts,
        )


def _iter_tool_uses(events: Iterable[dict]) -> Iterable[dict]:
    for event in events:
        if event.get("type") != "assistant":
            continue
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                # annotate with the carrier event's timestamp so callers can
                # compute latency without re-walking the event stream
                yield {**block, "_ts": event.get("timestamp")}


def _index_tool_results(events: Iterable[dict]) -> dict[str, datetime]:
    index: dict[str, datetime] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        ts = _parse_ts(event.get("timestamp"))
        if ts is None:
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if isinstance(tool_use_id, str) and tool_use_id not in index:
                index[tool_use_id] = ts
    return index


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
