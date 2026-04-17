"""Splits a raw event stream into logical sessions using an idle-gap rule.

A "session" for the judge's purposes is a bounded chunk of attention, not a raw
JSONL file — so a single file can yield many sessions across days. Default gap
is 30 minutes of inactivity.
"""
from __future__ import annotations

from datetime import datetime


class SessionSegmenter:
    def __init__(self, idle_gap_seconds: int = 1800) -> None:
        self._gap = idle_gap_seconds

    def segment(self, events: list[dict]) -> list[list[dict]]:
        timestamped = [e for e in events if _parse_ts(e.get("timestamp")) is not None]
        if not timestamped:
            return []
        timestamped.sort(key=lambda e: _parse_ts(e["timestamp"]))

        groups: list[list[dict]] = [[timestamped[0]]]
        prev_ts = _parse_ts(timestamped[0]["timestamp"])
        for event in timestamped[1:]:
            ts = _parse_ts(event["timestamp"])
            if (ts - prev_ts).total_seconds() > self._gap:
                groups.append([event])
            else:
                groups[-1].append(event)
            prev_ts = ts
        return groups


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
