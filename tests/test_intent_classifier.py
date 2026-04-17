from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from claude_judge.intent_classifier import IntentClassifier, VALID_INTENTS
from claude_judge.summarizer import SessionStats


def _stats(**overrides) -> SessionStats:
    base = dict(
        session_id="sess#2026-04-17T10:00:00+00:00",
        project_root="/p",
        started_at="2026-04-17T10:00:00+00:00",
        ended_at="2026-04-17T10:10:00+00:00",
        duration_seconds=600.0,
        tool_call_count=10,
    )
    base.update(overrides)
    return SessionStats(**base)


def _backend(return_value: str) -> MagicMock:
    b = MagicMock()
    b.complete.return_value = return_value
    return b


def test_returns_valid_intent_from_llm_response(tmp_path: Path) -> None:
    backend = _backend("coding")
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    intent = classifier.classify(_stats())
    assert intent == "coding"
    backend.complete.assert_called_once()


def test_parses_intent_even_when_wrapped_in_prose(tmp_path: Path) -> None:
    backend = _backend('The session looks like "planning" to me.')
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    assert classifier.classify(_stats()) == "planning"


def test_falls_back_to_unknown_on_unparseable_response(tmp_path: Path) -> None:
    backend = _backend("complete gibberish xyz")
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    assert classifier.classify(_stats()) == "unknown"


def test_caches_classification_by_session_id(tmp_path: Path) -> None:
    backend = _backend("coding")
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    classifier.classify(_stats())
    classifier.classify(_stats())  # same session_id — should NOT call backend again
    assert backend.complete.call_count == 1


def test_different_sessions_get_different_classifications(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = ["coding", "learning"]
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    a = classifier.classify(_stats(session_id="a"))
    b = classifier.classify(_stats(session_id="b"))
    assert a == "coding"
    assert b == "learning"
    assert backend.complete.call_count == 2


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    backend = _backend("debugging")
    IntentClassifier(backend=backend, cache_dir=tmp_path).classify(_stats())
    assert backend.complete.call_count == 1

    fresh_backend = _backend("should-never-be-called")
    intent = IntentClassifier(backend=fresh_backend, cache_dir=tmp_path).classify(_stats())
    assert intent == "debugging"
    fresh_backend.complete.assert_not_called()


def test_backend_failure_yields_unknown_without_caching(tmp_path: Path) -> None:
    backend = MagicMock()
    backend.complete.side_effect = RuntimeError("boom")
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    assert classifier.classify(_stats()) == "unknown"
    # Failure is NOT cached — next call should retry.
    backend2 = _backend("coding")
    classifier2 = IntentClassifier(backend=backend2, cache_dir=tmp_path)
    assert classifier2.classify(_stats()) == "coding"


def test_prompt_does_not_include_raw_prompt_excerpts_content_untouched(tmp_path: Path) -> None:
    backend = _backend("coding")
    classifier = IntentClassifier(backend=backend, cache_dir=tmp_path)
    stats = _stats(prompt_excerpts=["Fix the bug in webapp"])
    classifier.classify(stats)
    sent_prompt = backend.complete.call_args.kwargs["prompt"]
    # Excerpts ARE allowed in the classifier prompt (capped upstream) — this test just verifies
    # the six valid intent labels are listed so the LLM has constrained choices.
    for intent in VALID_INTENTS:
        assert intent in sent_prompt
