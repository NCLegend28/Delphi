"""Tests for ``memory/record.py``.

Pure construction tests. No mocks, no async, no fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.record import (
    AudioPart,
    ConversationRecord,
    ImageUrlPart,
    Message,
    TextPart,
    Timings,
    TokenCounts,
    content_text,
)
from memory.persist import _last_user_content
from routing.classifier import ClassifyResult
from routing.resolver import ResolvedModel
from worker.serde import from_payload, to_payload


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


def test_content_text_flattens_structured_multimodal_content() -> None:
    content = (
        TextPart(text="describe this"),
        ImageUrlPart(url="data:image/png;base64,AAAA"),
        AudioPart(transcript="spoken follow-up", mime_type="audio/webm"),
    )

    assert content_text(content) == "describe this\n[image attachment]\nspoken follow-up"


def test_structured_message_content_round_trips_through_queue_payload() -> None:
    record = ConversationRecord(
        request_id="req_mm",
        messages=(
            Message(
                role="user",
                content=(
                    TextPart(text="What is in this image?"),
                    ImageUrlPart(url="data:image/png;base64,AAAA"),
                    AudioPart(transcript="I also said this aloud", mime_type="audio/webm"),
                ),
            ),
        ),
    )

    payload = to_payload(record)
    restored = from_payload(payload)

    assert restored == record
    assert isinstance(restored.messages[0].content, tuple)
    assert restored.messages[0].content[0] == TextPart(text="What is in this image?")
    assert restored.messages[0].content[1] == ImageUrlPart(url="data:image/png;base64,AAAA")
    assert restored.messages[0].content[2] == AudioPart(
        transcript="I also said this aloud", mime_type="audio/webm"
    )


def test_last_user_content_derives_text_from_structured_message_content() -> None:
    messages = (
        Message(role="assistant", content="earlier reply"),
        Message(
            role="user",
            content=(
                TextPart(text="Read this chart"),
                ImageUrlPart(url="data:image/png;base64,BBBB"),
            ),
        ),
    )

    assert _last_user_content(messages) == "Read this chart\n[image attachment]"
