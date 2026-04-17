"""Pluggable transcript sources.

Abstract interface so future adapters (Cursor, Aider, Codex) can be added
without rewriting the scoring engine. V1 ships only ClaudeCodeJSONLSource.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Iterator

from claude_judge.segmenter import SessionSegmenter
from claude_judge.summarizer import SessionStats, TranscriptSummarizer


class TranscriptSource(ABC):
    @abstractmethod
    def list_sessions(self) -> Iterable[SessionStats]:
        ...


class ClaudeCodeJSONLSource(TranscriptSource):
    """Reads Claude Code's per-project JSONL transcripts and yields segmented sessions."""

    def __init__(
        self,
        root: Path,
        segmenter: SessionSegmenter | None = None,
        summarizer: TranscriptSummarizer | None = None,
    ) -> None:
        self._root = Path(root)
        self._segmenter = segmenter or SessionSegmenter()
        self._summarizer = summarizer or TranscriptSummarizer()

    def list_sessions(self) -> Iterator[SessionStats]:
        if not self._root.exists():
            return
        # Root may point at the projects dir (contains per-project subdirs)
        # or at a single project dir (contains jsonl files directly).
        for jsonl in sorted(self._root.glob("*/*.jsonl")):
            yield from self._read_jsonl(jsonl)
        for jsonl in sorted(self._root.glob("*.jsonl")):
            yield from self._read_jsonl(jsonl)

    def _read_jsonl(self, path: Path) -> Iterator[SessionStats]:
        events: list[dict] = []
        raw_session_id = ""
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
                raw_session_id = raw_session_id or event.get("sessionId", "")

        project_root = path.parent.name
        raw_session_id = raw_session_id or path.stem
        for group in self._segmenter.segment(events):
            yield self._summarizer.summarize(
                group, project_root=project_root, raw_session_id=raw_session_id
            )
