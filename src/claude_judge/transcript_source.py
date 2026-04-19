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


import heapq
import os


def _find_jsonls(root: Path, max_files: int) -> list[Path]:
    """Find JSONL files, optionally limited to the most-recently-modified."""
    candidates: list[Path] = []
    for entry in os.scandir(root):
        if entry.is_file() and entry.name.endswith(".jsonl"):
            candidates.append(Path(entry.path))
        elif entry.is_dir():
            try:
                for sub in os.scandir(entry.path):
                    if sub.is_file() and sub.name.endswith(".jsonl"):
                        candidates.append(Path(sub.path))
            except PermissionError:
                continue
    if max_files > 0 and len(candidates) > max_files:
        # Use a heap to find top-N by mtime without sorting everything.
        return heapq.nlargest(max_files, candidates, key=lambda p: p.stat().st_mtime)
    return candidates


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
        max_files: int = 0,
    ) -> None:
        self._root = Path(root)
        self._segmenter = segmenter or SessionSegmenter()
        self._summarizer = summarizer or TranscriptSummarizer()
        self._max_files = max_files  # 0 = no limit

    def list_sessions(self) -> Iterator[SessionStats]:
        if not self._root.exists():
            return
        jsonls = _find_jsonls(self._root, self._max_files)
        for jsonl in jsonls:
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
