"""Tests for ``memory/record.py``.

Pure construction tests. No mocks, no async, no fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.record import ConversationRecord, Message, Timings, TokenCounts
from routing.classifier import ClassifyResult
from routing.resolver import ResolvedModel


def test_minimal_construction() -> None:
    """Only ``request_id`` is required; every other field has a sensible default."""
    record = ConversationRecord(request_id="req_abc")

    assert record.request_id == "req_abc"
    assert record.schema_version == 1
    assert isinstance(record.timestamp, datetime)
    assert record.timestamp.tzinfo is not None, "default timestamp must be timezone-aware"
    assert record.messages == ()
    assert record.soul_injected is False
    assert record.client_id is None
    assert record.stream_requested is True
    assert record.resolved is None
    assert record.assistant_response == ""
    assert record.finish_reason is None
    assert record.truncated is False
    assert record.timings is None
    assert record.token_counts is None
    assert record.error is None
    assert record.ollama_status is None


def test_full_construction() -> None:
    """Every field populated. Mirrors what api/chat.py builds on the happy path."""
    resolved = ResolvedModel(
        model="qwen2.5-coder:14b",
        task_type="code",
        source="classified",
        classifier_result=ClassifyResult(task_type="code", confidence=0.92),
    )
    record = ConversationRecord(
        request_id="req_xyz",
        schema_version=1,
        timestamp=datetime(2026, 5, 10, 14, 32, tzinfo=timezone.utc),
        messages=(
            Message(role="system", content="you are tali's assistant"),
            Message(role="user", content="refactor this"),
            Message(role="assistant", content="here you go"),
        ),
        soul_injected=True,
        client_id="agentrig-m4",
        stream_requested=True,
        resolved=resolved,
        assistant_response="here you go",
        finish_reason="stop",
        truncated=False,
        timings=Timings(received_ms=0.0, ttft_ms=220.0, completed_ms=1840.0),
        token_counts=TokenCounts(input_tokens=412, output_tokens=1103),
        error=None,
        ollama_status=200,
    )

    assert record.resolved is resolved
    assert record.assistant_response == "here you go"
    assert record.timings.ttft_ms == 220.0
    assert record.token_counts.output_tokens == 1103
    assert record.messages[1].role == "user"
    assert record.client_id == "agentrig-m4"


def test_message_immutability() -> None:
    """``messages`` is a tuple — accumulators can't accidentally mutate it."""
    record = ConversationRecord(
        request_id="req_im",
        messages=(Message(role="user", content="hi"),),
    )

    assert isinstance(record.messages, tuple)
    with pytest.raises(AttributeError):
        record.messages.append(Message(role="user", content="hi again"))  # type: ignore[attr-defined]


def test_record_immutability() -> None:
    """``frozen=True`` blocks downstream consumers from mutating the record."""
    record = ConversationRecord(request_id="req_frozen")

    with pytest.raises((AttributeError, Exception)):
        record.request_id = "tampered"  # type: ignore[misc]

    with pytest.raises((AttributeError, Exception)):
        record.assistant_response = "injected text"  # type: ignore[misc]

    # Message itself is also frozen — pin that here, so the docstring's
    # promise stays honest even if someone later splits these tests.
    msg = Message(role="user", content="hi")
    with pytest.raises((AttributeError, Exception)):
        msg.content = "different"  # type: ignore[misc]
