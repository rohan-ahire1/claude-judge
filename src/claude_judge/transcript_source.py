"""Pluggable transcript sources.

Abstract interface so future adapters (Cursor, Aider, Codex) can be added
without rewriting the scoring engine. V1 ships only ClaudeCodeJSONLSource.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


@dataclass
class Session:
    session_id: str
    project_root: str
    tool_call_count: int
    events: list[dict] = field(default_factory=list)


class TranscriptSource(ABC):
    @abstractmethod
    def list_sessions(self) -> Iterable[Session]:
        ...


class ClaudeCodeJSONLSource(TranscriptSource):
    """Reads Claude Code's per-project JSONL transcripts.

    The root directory is typically ~/.claude/projects/. Each subdirectory
    corresponds to one Claude-Code-tracked working directory; each JSONL file
    inside is one session's raw event stream.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def list_sessions(self) -> Iterator[Session]:
        if not self._root.exists():
            return
        # Root can point at the projects dir (contains per-project subdirs)
        # or at a single project dir (contains jsonl files directly).
        for jsonl in sorted(self._root.glob("*/*.jsonl")):
            yield self._read_jsonl(jsonl)
        for jsonl in sorted(self._root.glob("*.jsonl")):
            yield self._read_jsonl(jsonl)

    @staticmethod
    def _read_jsonl(path: Path) -> Session:
        tool_call_count = 0
        session_id = ""
        events: list[dict] = []
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(event)
                session_id = session_id or event.get("sessionId", "")
                tool_call_count += _count_tool_uses(event)
        return Session(
            session_id=session_id or path.stem,
            project_root=path.parent.name,
            tool_call_count=tool_call_count,
            events=events,
        )


def _count_tool_uses(event: dict) -> int:
    if event.get("type") != "assistant":
        return 0
    content = event.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return 0
    return sum(1 for block in content if isinstance(block, dict) and block.get("type") == "tool_use")
