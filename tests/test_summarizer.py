from claude_judge.summarizer import TranscriptSummarizer


def _assistant(ts: str, blocks: list[dict]) -> dict:
    return {"type": "assistant", "timestamp": ts, "message": {"content": blocks}}


def _user(ts: str, text: str) -> dict:
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}


def _tool_result(ts: str, tool_use_id: str) -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id}],
        },
    }


def test_counts_tool_uses_across_events() -> None:
    events = [
        _assistant(
            "2026-04-17T10:00:00.000Z",
            [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x.py"}},
                {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}},
            ],
        ),
    ]
    stats = TranscriptSummarizer().summarize(events, project_root="/proj", raw_session_id="sess")
    assert stats.tool_call_count == 2


def test_captures_session_bounds_and_duration() -> None:
    events = [
        _user("2026-04-17T10:00:00.000Z", "hi"),
        _assistant("2026-04-17T10:05:30.000Z", [{"type": "tool_use", "id": "t1", "name": "Read"}]),
    ]
    stats = TranscriptSummarizer().summarize(events, project_root="/proj", raw_session_id="sess")
    assert stats.started_at == "2026-04-17T10:00:00+00:00"
    assert stats.ended_at == "2026-04-17T10:05:30+00:00"
    assert stats.duration_seconds == 330


def test_computes_approval_latencies_by_matching_tool_use_to_result() -> None:
    events = [
        _assistant(
            "2026-04-17T10:00:00.000Z",
            [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
        ),
        _tool_result("2026-04-17T10:00:02.500Z", "t1"),  # 2.5s latency
        _assistant(
            "2026-04-17T10:00:10.000Z",
            [{"type": "tool_use", "id": "t2", "name": "Read"}],
        ),
        _tool_result("2026-04-17T10:00:10.100Z", "t2"),  # 100ms latency
    ]
    stats = TranscriptSummarizer().summarize(events, project_root="/proj", raw_session_id="sess")
    assert stats.approval_latencies_ms == [2500.0, 100.0]


def test_extracts_files_touched_from_common_tool_inputs() -> None:
    events = [
        _assistant(
            "2026-04-17T10:00:00.000Z",
            [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}},
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/b.py"}},
                {"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "/a.py"}},
                {"type": "tool_use", "id": "t4", "name": "Bash", "input": {"command": "ls"}},
            ],
        ),
    ]
    stats = TranscriptSummarizer().summarize(events, project_root="/proj", raw_session_id="sess")
    assert stats.files_touched == ["/a.py", "/b.py"]  # deduped, order preserved


def test_prompt_excerpts_capped_and_truncated() -> None:
    long_text = "x" * 500
    events = [_user("2026-04-17T10:00:00.000Z", long_text)]
    stats = TranscriptSummarizer(max_excerpt_chars=200, max_excerpts=5).summarize(
        events, project_root="/proj", raw_session_id="sess"
    )
    assert len(stats.prompt_excerpts) == 1
    assert len(stats.prompt_excerpts[0]) == 200


def test_composite_session_id_includes_start_timestamp() -> None:
    events = [_user("2026-04-17T10:00:00.000Z", "hi")]
    stats = TranscriptSummarizer().summarize(events, project_root="/proj", raw_session_id="sess-abc")
    assert stats.session_id.startswith("sess-abc#")
    assert "2026-04-17T10:00:00" in stats.session_id
