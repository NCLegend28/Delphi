"""Serialize a ``ConversationRecord`` across the gateway→worker queue boundary.

arq stores job arguments as msgpack, so everything must reduce to JSON-native
types. The record graph is small and closed (five frozen dataclasses), so we
hand-roll the round-trip rather than pull in a serialization framework — it
keeps the wire shape explicit and versionable. ``schema_version`` rides along
so a worker can reject a record it doesn't understand instead of mis-parsing.

The round-trip is lossless for every field the persist pipeline reads. Keep
``to_payload`` and ``from_payload`` mirror images: add a field to one, add it
to the other, or the worker silently drops it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory.record import ConversationRecord, Message, Timings, TokenCounts
from routing.classifier import ClassifyResult
from routing.resolver import ResolvedModel


def to_payload(record: ConversationRecord) -> dict[str, Any]:
    """Reduce a record to JSON-native types for the queue."""
    resolved: dict[str, Any] | None = None
    if record.resolved is not None:
        cr = record.resolved.classifier_result
        resolved = {
            "model": record.resolved.model,
            "task_type": record.resolved.task_type,
            "source": record.resolved.source,
            "classifier_result": (
                None
                if cr is None
                else {
                    "task_type": cr.task_type,
                    "confidence": cr.confidence,
                    "project": cr.project,
                }
            ),
        }

    timings: dict[str, Any] | None = None
    if record.timings is not None:
        timings = {
            "received_ms": record.timings.received_ms,
            "ttft_ms": record.timings.ttft_ms,
            "completed_ms": record.timings.completed_ms,
        }

    token_counts: dict[str, Any] | None = None
    if record.token_counts is not None:
        token_counts = {
            "input_tokens": record.token_counts.input_tokens,
            "output_tokens": record.token_counts.output_tokens,
        }

    return {
        "request_id": record.request_id,
        "schema_version": record.schema_version,
        "timestamp": record.timestamp.isoformat(),
        "messages": [{"role": m.role, "content": m.content} for m in record.messages],
        "soul_injected": record.soul_injected,
        "client_id": record.client_id,
        "stream_requested": record.stream_requested,
        "resolved": resolved,
        "assistant_response": record.assistant_response,
        "finish_reason": record.finish_reason,
        "truncated": record.truncated,
        "timings": timings,
        "token_counts": token_counts,
        "error": record.error,
        "ollama_status": record.ollama_status,
    }


def from_payload(data: dict[str, Any]) -> ConversationRecord:
    """Rebuild a record from its queue payload. Inverse of ``to_payload``."""
    resolved = None
    rd = data.get("resolved")
    if rd is not None:
        cr_d = rd.get("classifier_result")
        classifier_result = (
            None
            if cr_d is None
            else ClassifyResult(
                task_type=cr_d["task_type"],
                confidence=cr_d["confidence"],
                project=cr_d.get("project"),
            )
        )
        resolved = ResolvedModel(
            model=rd["model"],
            task_type=rd["task_type"],
            source=rd["source"],
            classifier_result=classifier_result,
        )

    td = data.get("timings")
    timings = (
        None
        if td is None
        else Timings(
            received_ms=td["received_ms"],
            ttft_ms=td["ttft_ms"],
            completed_ms=td["completed_ms"],
        )
    )

    tc = data.get("token_counts")
    token_counts = (
        None
        if tc is None
        else TokenCounts(input_tokens=tc["input_tokens"], output_tokens=tc["output_tokens"])
    )

    return ConversationRecord(
        request_id=data["request_id"],
        schema_version=data.get("schema_version", 1),
        timestamp=datetime.fromisoformat(data["timestamp"]),
        messages=tuple(
            Message(role=m["role"], content=m["content"]) for m in data.get("messages", [])
        ),
        soul_injected=data.get("soul_injected", False),
        client_id=data.get("client_id"),
        stream_requested=data.get("stream_requested", True),
        resolved=resolved,
        assistant_response=data.get("assistant_response", ""),
        finish_reason=data.get("finish_reason"),
        truncated=data.get("truncated", False),
        timings=timings,
        token_counts=token_counts,
        error=data.get("error"),
        ollama_status=data.get("ollama_status"),
    )
