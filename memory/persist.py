"""The persist pipeline — what happens to an exchange after the bytes ship.

One exchange produces one :class:`~memory.record.ConversationRecord`. Turning
that into durable memory means three I/O steps plus telemetry:

    entity extraction → vault note write → JSONL log line → Prometheus metrics

Historically this ran in-process as a fire-and-forget ``asyncio`` task on the
gateway. It now lives here so two callers can share it verbatim:

* the **worker** (``worker/main.py``) — the normal path; the gateway enqueues
  a serialized record and the worker runs ``run_persist`` out of process, so
  disk writes and entity-index scans never touch the request path.
* the **gateway** itself — the *fallback* path. If Redis is unreachable the
  gateway runs ``run_persist`` inline so memory is never silently dropped
  (fail-open: the API contract is sacred, memory is best-effort).

Both build their own ``Metrics`` registry and both call ``run_persist``; each
exposes ``/metrics`` separately, so Prometheus scrapes both targets and sums.
Nothing here is gateway-specific — no FastAPI, no request object.
"""

from __future__ import annotations

from typing import Any

from memory.entities import EntityIndex, ProcessedExchange
from memory.record import ConversationRecord, Message
from memory.vault import ConversationNote, VaultWriter, WriteResult
from telemetry.logger import RequestLogger, make_record
from telemetry.metrics import Metrics, RequestStatus


def _last_user_content(messages: tuple[Message, ...]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _to_conversation_note(
    record: ConversationRecord, processed: ProcessedExchange
) -> ConversationNote:
    classifier_confidence = None
    if record.resolved and record.resolved.classifier_result:
        classifier_confidence = record.resolved.classifier_result.confidence

    return ConversationNote(
        timestamp=record.timestamp,
        task_type=record.resolved.task_type if record.resolved else "unknown",
        models=[record.resolved.model] if record.resolved else [],
        classifier_confidence=classifier_confidence,
        latency_ms=int(record.timings.completed_ms) if record.timings else 0,
        input_tokens=record.token_counts.input_tokens if record.token_counts else 0,
        output_tokens=record.token_counts.output_tokens if record.token_counts else 0,
        user_message=processed.annotated_user,
        assistant_message=processed.annotated_assistant,
        project=processed.project,
        entities=[f"[[{name}]]" for name in processed.entities],
        tags=[],
        client_id=record.client_id,
        truncated=record.truncated,
    )


def _to_request_record(
    record: ConversationRecord,
    write_result: WriteResult,
    processed: ProcessedExchange,
) -> Any:
    classifier_confidence = None
    if record.resolved and record.resolved.classifier_result:
        classifier_confidence = record.resolved.classifier_result.confidence

    ttft_ms: int | None = None
    if record.timings and record.timings.ttft_ms is not None:
        ttft_ms = int(record.timings.ttft_ms)
    latency_ms = int(record.timings.completed_ms) if record.timings else 0

    return make_record(
        request_id=record.request_id,
        client_id=record.client_id,
        task_type=record.resolved.task_type if record.resolved else "unknown",
        classifier_confidence=classifier_confidence,
        model=record.resolved.model if record.resolved else "unknown",
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        input_tokens=record.token_counts.input_tokens if record.token_counts else 0,
        output_tokens=record.token_counts.output_tokens if record.token_counts else 0,
        vault_write={
            "ok": write_result.ok,
            "path": write_result.path,
            "error": write_result.error,
        },
        error=record.error,
        # Carried as extras until/unless the canonical log schema grows.
        ollama_status=record.ollama_status,
        resolution_source=record.resolved.source if record.resolved else None,
        soul_injected=record.soul_injected,
        schema_version=record.schema_version,
        entities_referenced=processed.entities,
        entities_promoted=processed.promoted,
        project=processed.project,
    )


def _record_metrics(
    record: ConversationRecord,
    processed: ProcessedExchange,
    write_result: WriteResult,
    metrics: Metrics,
) -> None:
    """All Prometheus updates for one exchange. Cheap, sync, no exceptions raised."""
    if record.resolved is None:
        return  # auth failed before resolution — no useful labels available

    status: RequestStatus
    if record.error:
        upstream = record.ollama_status is not None and record.ollama_status >= 500
        status = "upstream_error" if upstream else "error"
    else:
        status = "ok"

    classifier_confidence = None
    if record.resolved.classifier_result is not None:
        classifier_confidence = record.resolved.classifier_result.confidence

    metrics.record_request(
        task_type=record.resolved.task_type,
        model=record.resolved.model,
        resolution_source=record.resolved.source,
        status=status,
        latency_ms=record.timings.completed_ms if record.timings else 0.0,
        ttft_ms=record.timings.ttft_ms if record.timings else None,
        input_tokens=record.token_counts.input_tokens if record.token_counts else 0,
        output_tokens=record.token_counts.output_tokens if record.token_counts else 0,
        classifier_confidence=classifier_confidence,
    )
    metrics.record_vault_write(ok=write_result.ok)
    metrics.record_entities_promoted(len(processed.promoted))
    if status == "upstream_error":
        metrics.record_upstream_error(kind="non_200")


async def run_persist(
    record: ConversationRecord,
    *,
    vault: VaultWriter,
    logger: RequestLogger,
    entity_index: EntityIndex,
    metrics: Metrics,
) -> None:
    """Process entities, write the vault note, log the line, record metrics.

    The single durable side effect of an exchange. Safe to run on either the
    worker (normal path) or the gateway (Redis-down fallback) — it owns no
    process-global state beyond the components handed to it.
    """
    project_hint: str | None = None
    if record.resolved and record.resolved.classifier_result:
        project_hint = record.resolved.classifier_result.project

    processed = await entity_index.process(
        user_text=_last_user_content(record.messages),
        assistant_text=record.assistant_response,
        project_hint=project_hint,
    )
    write_result = await vault.write(_to_conversation_note(record, processed))
    await logger.log(_to_request_record(record, write_result, processed), ts=record.timestamp)
    _record_metrics(record, processed, write_result, metrics)
