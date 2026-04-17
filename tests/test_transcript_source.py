import json
from datetime import datetime, timezone
from pathlib import Path

from claude_judge.transcript_source import ClaudeCodeJSONLSource


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_reads_single_session_with_tool_call_count(tmp_path: Path) -> None:
    # Fixture: one JSONL file with 3 tool_use events, interleaved with other noise.
    project_dir = tmp_path / "-Users-rohanahire-Documents-projects-demo"
    project_dir.mkdir()
    jsonl = project_dir / "sess-abc.jsonl"
    ts = "2026-04-17T10:00:00.000Z"
    _write_jsonl(
        jsonl,
        [
            {"type": "permission-mode", "permissionMode": "auto", "sessionId": "sess-abc"},
            {
                "type": "assistant",
                "sessionId": "sess-abc",
                "timestamp": ts,
                "message": {"content": [{"type": "tool_use", "name": "Read"}]},
            },
            {
                "type": "user",
                "sessionId": "sess-abc",
                "timestamp": "2026-04-17T10:00:05.000Z",
                "message": {"content": "hey"},
            },
            {
                "type": "assistant",
                "sessionId": "sess-abc",
                "timestamp": "2026-04-17T10:00:06.000Z",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash"},
                        {"type": "tool_use", "name": "Edit"},
                    ]
                },
            },
        ],
    )

    source = ClaudeCodeJSONLSource(root=tmp_path)
    sessions = list(source.list_sessions())

    assert len(sessions) == 1
    session = sessions[0]
    assert session.session_id == "sess-abc"
    assert session.tool_call_count == 3
    assert session.project_root.endswith("demo")


def test_empty_root_yields_no_sessions(tmp_path: Path) -> None:
    source = ClaudeCodeJSONLSource(root=tmp_path)
    assert list(source.list_sessions()) == []
