"""Deterministic reducer from a session's event list to SessionStats.

Raw prompt/tool content never flows out of this module unchanged. Downstream
scorers and LLM prompts see only the structured stats + capped excerpts and
red-flag labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

_FILE_PATH_KEYS = ("file_path", "path", "notebook_path")
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# (flag_label, regex). Regex runs against Bash commands.
_DANGEROUS_BASH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rm_rf", re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-rf|-fr)\b")),
    ("force_push", re.compile(r"\bgit\s+push\b.*(--force|-f\b)")),
    ("no_verify", re.compile(r"--no-verify\b")),
    ("reset_hard", re.compile(r"\bgit\s+reset\s+--hard\b")),
    ("checkout_discard", re.compile(r"\bgit\s+checkout\s+--\s+\.")),
    ("branch_delete_force", re.compile(r"\bgit\s+branch\s+-D\b")),
]

# (flag_label, regex). Regex runs against user prompt text.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key_in_prompt", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("github_pat_in_prompt", re.compile(r"\bghp_[A-Za-z0-9]{20,}")),
    ("aws_key_in_prompt", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token_in_prompt", re.compile(r"\bxox[bpar]-[A-Za-z0-9-]{10,}")),
    ("jwt_in_prompt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("basic_auth_url_in_prompt", re.compile(r"https?://[^/\s:]+:[^/\s@]+@")),
]

_GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b")


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
    permission_mode: str = "unknown"
    edit_paths: list[str] = field(default_factory=list)
    git_commit_count: int = 0
    security_red_flags: list[str] = field(default_factory=list)


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
        edit_paths: list[str] = []
        seen_files: set[str] = set()
        git_commit_count = 0
        red_flags: set[str] = set()

        for use in tool_uses:
            result_ts = tool_results.get(use.get("id"))
            use_ts = _parse_ts(use.get("_ts"))
            if use_ts is not None and result_ts is not None:
                latencies.append(round((result_ts - use_ts).total_seconds() * 1000, 1))

            tool_name = use.get("name")
            tool_input = use.get("input") or {}

            for key in _FILE_PATH_KEYS:
                path = tool_input.get(key)
                if isinstance(path, str):
                    if path not in seen_files:
                        seen_files.add(path)
                        files_touched.append(path)
                    if tool_name in _EDIT_TOOLS:
                        edit_paths.append(path)
                    break

            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                if isinstance(cmd, str):
                    if _GIT_COMMIT_RE.search(cmd):
                        git_commit_count += 1
                    for label, pattern in _DANGEROUS_BASH_PATTERNS:
                        if pattern.search(cmd):
                            red_flags.add(label)

        excerpts: list[str] = []
        for event in events:
            if event.get("type") != "user":
                continue
            content = event.get("message", {}).get("content")
            text = content if isinstance(content, str) else None
            if text is None:
                continue
            for label, pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    red_flags.add(label)
            if len(excerpts) < self._max_excerpts:
                excerpts.append(text[: self._max_chars])

        permission_mode = "unknown"
        for event in events:
            if event.get("type") == "permission-mode" and isinstance(event.get("permissionMode"), str):
                permission_mode = event["permissionMode"]
                break

        session_id = (
            f"{raw_session_id}#{started.isoformat()}" if started else raw_session_id
        )
        return SessionStats(
            session_id=session_id,
            project_root=project_root,
            started_at=started.isoformat() if started else "",
            ended_at=ended.isoformat() if ended else "",
            duration_seconds=(ended - started).total_seconds() if started and ended else 0.0,
            tool_call_count=len(tool_uses),
            approval_latencies_ms=latencies,
            files_touched=files_touched,
            prompt_excerpts=excerpts,
            permission_mode=permission_mode,
            edit_paths=edit_paths,
            git_commit_count=git_commit_count,
            security_red_flags=sorted(red_flags),
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
