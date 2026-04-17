from claude_judge.segmenter import SessionSegmenter


def _event(ts: str) -> dict:
    return {"timestamp": ts, "type": "assistant"}


def test_empty_stream_yields_no_groups() -> None:
    assert SessionSegmenter().segment([]) == []


def test_single_event_yields_one_group() -> None:
    events = [_event("2026-04-17T10:00:00.000Z")]
    assert SessionSegmenter().segment(events) == [events]


def test_consecutive_events_under_gap_stay_one_group() -> None:
    events = [
        _event("2026-04-17T10:00:00.000Z"),
        _event("2026-04-17T10:15:00.000Z"),
        _event("2026-04-17T10:45:00.000Z"),  # 30-min gaps exactly
    ]
    groups = SessionSegmenter(idle_gap_seconds=1800).segment(events)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_gap_exceeding_threshold_splits_into_two_groups() -> None:
    events = [
        _event("2026-04-17T10:00:00.000Z"),
        _event("2026-04-17T10:10:00.000Z"),
        _event("2026-04-17T11:00:00.000Z"),  # 50 min gap -> split
        _event("2026-04-17T11:05:00.000Z"),
    ]
    groups = SessionSegmenter(idle_gap_seconds=1800).segment(events)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 2


def test_multiple_gaps_produce_multiple_groups() -> None:
    events = [
        _event("2026-04-17T10:00:00.000Z"),
        _event("2026-04-17T11:00:00.000Z"),  # 60 min gap
        _event("2026-04-17T13:00:00.000Z"),  # 120 min gap
        _event("2026-04-17T13:05:00.000Z"),
    ]
    groups = SessionSegmenter(idle_gap_seconds=1800).segment(events)
    assert [len(g) for g in groups] == [1, 1, 2]


def test_unordered_events_are_sorted_before_segmenting() -> None:
    events = [
        _event("2026-04-17T10:10:00.000Z"),
        _event("2026-04-17T10:00:00.000Z"),
        _event("2026-04-17T12:00:00.000Z"),  # 110 min gap from the prior
    ]
    groups = SessionSegmenter(idle_gap_seconds=1800).segment(events)
    assert len(groups) == 2
    assert groups[0][0]["timestamp"] == "2026-04-17T10:00:00.000Z"
    assert groups[0][1]["timestamp"] == "2026-04-17T10:10:00.000Z"


def test_events_without_timestamp_are_dropped() -> None:
    events = [
        _event("2026-04-17T10:00:00.000Z"),
        {"type": "permission-mode", "permissionMode": "auto"},  # no timestamp
        _event("2026-04-17T10:05:00.000Z"),
    ]
    groups = SessionSegmenter(idle_gap_seconds=1800).segment(events)
    assert len(groups) == 1
    assert len(groups[0]) == 2
