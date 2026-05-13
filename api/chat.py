"""POST /v1/chat/completions — Delphi's main request path.

Orchestration only; every piece of logic lives in a sibling module:

    auth (require_bearer)
        → resolve_model (routing)
        → soul_for (routing)
        → ollama.stream_chat (proxy)
        → tee into client + buffer
        → ConversationRecord (memory)
        → vault.write + request_logger.log (background)

The route is intentionally thin. If something gets complex here, it probably
belongs in the module that owns the concern.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from ulid import ULID

from api.deps import (
    get_classifier,
    get_entity_index,
    get_metrics,
    get_ollama,
    get_request_logger,
    get_roster,
    get_vault,
)
from auth.bearer import require_bearer
from memory.entities import EntityIndex, ProcessedExchange
from memory.record import ConversationRecord, Message, Timings, TokenCounts
from memory.vault import ConversationNote, VaultWriter, WriteResult
from proxy.ollama_client import OllamaClient, OllamaError
from routing.classifier import Classifier
from routing.resolver import resolve_model
from routing.roster import Roster
from routing.soul import soul_for
from telemetry.logger import RequestLogger, make_record
from telemetry.metrics import Metrics, RequestStatus

router = APIRouter()

_NS_PER_MS = 1_000_000

# Hold strong refs to fire-and-forget tasks so the GC can't drop them
# mid-flight (asyncio docs warn about this exact footgun).
_background_tasks: set[asyncio.Task[Any]] = set()


def _fire(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# --- helpers --------------------------------------------------------------


def _has_system_message(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(m, dict) and m.get("role") == "system" for m in messages)


def _last_user_content(messages: tuple[Message, ...]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _parse_sse_buffer(buffer: list[bytes]) -> tuple[str, str | None, TokenCounts | None]:
    """Pull text, finish reason, and (when reported) token counts out of an SSE buffer.

    Tolerant on purpose — Ollama's exact frame timing and field set varies
    between models. Anything we can't parse, we drop quietly; what survives
    is what shows up in the vault note.
    """
    raw = b"".join(buffer).decode("utf-8", errors="replace")
    text_parts: list[str] = []
    finish_reason: str | None = None
    tokens: TokenCounts | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue

        for choice in obj.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str):
                text_parts.append(content)
            fr = choice.get("finish_reason")
            if isinstance(fr, str):
                finish_reason = fr

        usage = obj.get("usage")
        if isinstance(usage, dict):
            it = usage.get("prompt_tokens", usage.get("input_tokens"))
            ot = usage.get("completion_tokens", usage.get("output_tokens"))
            if isinstance(it, int) and isinstance(ot, int):
                tokens = TokenCounts(input_tokens=it, output_tokens=ot)

    return "".join(text_parts), finish_reason, tokens


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


async def _persist(
    record: ConversationRecord,
    vault: VaultWriter,
    logger: RequestLogger,
    entity_index: EntityIndex,
    metrics: Metrics,
) -> None:
    """Single background task: process entities, write the vault note, log the line."""
    project_hint: str | None = None
    if record.resolved and record.resolved.classifier_result:
        project_hint = record.resolved.classifier_result.project

    processed = await entity_index.process(
        user_text=_last_user_content(record.messages),
        assistant_text=record.assistant_response,
        project_hint=project_hint,
    )
    write_result = await vault.write(_to_conversation_note(record, processed))
    await logger.log(
        _to_request_record(record, write_result, processed), ts=record.timestamp
    )
    _record_metrics(record, processed, write_result, metrics)


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
        status = "upstream_error" if record.ollama_status and record.ollama_status >= 500 else "error"
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


def _openai_response(
    *,
    request_id: str,
    model: str,
    content: str,
    finish_reason: str | None,
    token_counts: TokenCounts | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": request_id,
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason or "stop",
            }
        ],
    }
    if token_counts:
        payload["usage"] = {
            "prompt_tokens": token_counts.input_tokens,
            "completion_tokens": token_counts.output_tokens,
            "total_tokens": token_counts.input_tokens + token_counts.output_tokens,
        }
    return payload


# --- route ---------------------------------------------------------------


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_bearer),
    classifier: Classifier = Depends(get_classifier),
    roster: Roster = Depends(get_roster),
    ollama: OllamaClient = Depends(get_ollama),
    vault: VaultWriter = Depends(get_vault),
    request_logger: RequestLogger = Depends(get_request_logger),
    entity_index: EntityIndex = Depends(get_entity_index),
    metrics: Metrics = Depends(get_metrics),
) -> Any:
    request_id = f"req_{ULID()}"
    t0 = time.monotonic_ns()

    client_id = request.headers.get("x-client-id")
    stream_requested = bool(body.get("stream", True))

    raw_messages = body.get("messages") or []
    if not isinstance(raw_messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

    soul_injected = not _has_system_message(raw_messages)

    resolved = await resolve_model(body, classifier, roster)

    full_messages: list[dict[str, Any]] = list(raw_messages)
    if soul_injected:
        soul_msg = {"role": "system", "content": soul_for(resolved.task_type)}
        full_messages = [soul_msg, *full_messages]

    entry = roster.lookup(resolved.task_type)
    options: dict[str, Any] = dict(entry.options) if entry else {}

    record_messages = tuple(
        Message(role=m.get("role", "user"), content=m.get("content", ""))
        for m in full_messages
        if isinstance(m, dict)
    )

    # Open the upstream stream eagerly so we can detect 502s before committing
    # to a 200 streaming response.
    chunks_gen = ollama.stream_chat(model=resolved.model, messages=full_messages, options=options)

    try:
        first_chunk = await chunks_gen.__anext__()
        ttft_ns: int | None = time.monotonic_ns()
    except StopAsyncIteration:
        first_chunk = b""
        ttft_ns = time.monotonic_ns()
    except OllamaError as exc:
        t2 = time.monotonic_ns()
        error_record = ConversationRecord(
            request_id=request_id,
            messages=record_messages,
            soul_injected=soul_injected,
            client_id=client_id,
            stream_requested=stream_requested,
            resolved=resolved,
            assistant_response="",
            finish_reason="error",
            truncated=False,
            timings=Timings(
                received_ms=0.0,
                ttft_ms=None,
                completed_ms=(t2 - t0) / _NS_PER_MS,
            ),
            token_counts=None,
            error=str(exc),
            ollama_status=502,
        )
        _fire(_persist(error_record, vault, request_logger, entity_index, metrics))
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": "ollama upstream failed",
                    "details": {},
                }
            },
            headers={"X-Request-ID": request_id},
        )

    state: dict[str, Any] = {
        "buffer": [first_chunk],
        "truncated": False,
        "ttft_ns": ttft_ns,
    }

    async def emit() -> AsyncIterator[bytes]:
        completed_naturally = False
        try:
            yield first_chunk
            async for chunk in chunks_gen:
                state["buffer"].append(chunk)
                yield chunk
            completed_naturally = True
        finally:
            # Generator was interrupted (client disconnect, transport close,
            # task cancel — any of them).  The exact exception type varies by
            # ASGI server and transport, so we infer truncation by absence of
            # a clean exit instead of pattern-matching on the exception.
            if not completed_naturally:
                state["truncated"] = True
            t2 = time.monotonic_ns()
            text, finish_reason, token_counts = _parse_sse_buffer(state["buffer"])
            done_record = ConversationRecord(
                request_id=request_id,
                messages=(*record_messages, Message(role="assistant", content=text)),
                soul_injected=soul_injected,
                client_id=client_id,
                stream_requested=stream_requested,
                resolved=resolved,
                assistant_response=text,
                finish_reason=finish_reason,
                truncated=state["truncated"],
                timings=Timings(
                    received_ms=0.0,
                    ttft_ms=(state["ttft_ns"] - t0) / _NS_PER_MS if state["ttft_ns"] else None,
                    completed_ms=(t2 - t0) / _NS_PER_MS,
                ),
                token_counts=token_counts,
                error=None,
                ollama_status=200,
            )
            _fire(_persist(done_record, vault, request_logger, entity_index, metrics))

    if stream_requested:
        return StreamingResponse(
            emit(),
            media_type="text/event-stream",
            headers={"X-Request-ID": request_id, "Cache-Control": "no-cache"},
        )

    # Non-streaming: drain the same generator (so the finally still fires the
    # record-build), then translate the SSE buffer into one OpenAI-shaped JSON.
    async for _chunk in emit():
        pass
    text, finish_reason, token_counts = _parse_sse_buffer(state["buffer"])
    return JSONResponse(
        content=_openai_response(
            request_id=request_id,
            model=resolved.model,
            content=text,
            finish_reason=finish_reason,
            token_counts=token_counts,
        ),
        headers={"X-Request-ID": request_id},
    )
