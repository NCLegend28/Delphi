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

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from ulid import ULID

from api.deps import (
    get_arq_pool,
    get_classifier,
    get_entity_index,
    get_metrics,
    get_ollama,
    get_request_logger,
    get_roster,
    get_vault,
    get_vault_reader,
)
from auth.bearer import require_bearer
from config import get_config
from memory.entities import EntityIndex
from memory.persist import run_persist
from memory.record import ConversationRecord, Message, Timings, TokenCounts
from memory.vault import VaultWriter
from memory.vault_reader import VaultReader
from proxy.ollama_client import OllamaClient, OllamaError
from routing.classifier import Classifier
from routing.resolver import resolve_model
from routing.roster import Roster
from routing.soul import soul_for
from routing.vault_agent import run_vault_agent
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics
from worker.queue import PERSIST_JOB
from worker.serde import to_payload

log = structlog.get_logger("delphi.chat")

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


async def _enqueue_or_persist(
    record: ConversationRecord,
    *,
    arq_pool: Any,
    vault: VaultWriter,
    logger: RequestLogger,
    entity_index: EntityIndex,
    metrics: Metrics,
) -> None:
    """Hand the finished exchange to the worker, or persist it inline if we can't.

    Normal path: enqueue a serialized record to Redis and return — the worker
    does the disk I/O. Fallback path: if the queue is disabled (``arq_pool is
    None``) or the enqueue fails (Redis hiccup), run the same pipeline inline so
    the exchange is never silently lost. Memory is best-effort but not careless.
    """
    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job(PERSIST_JOB, to_payload(record))
            return
        except Exception as exc:  # degrade to inline persist on any Redis hiccup
            log.warning(
                "enqueue_failed_persisting_inline",
                request_id=record.request_id,
                error=str(exc),
            )

    await run_persist(
        record, vault=vault, logger=logger, entity_index=entity_index, metrics=metrics
    )


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


async def _sse_from_text(text: str, finish_reason: str = "stop") -> AsyncIterator[bytes]:
    """Frame a complete answer as OpenAI SSE chunks.

    The vault agent runs non-streaming (it has to see tool results before it
    can answer), so by the time we have text the whole answer exists. We still
    emit it as SSE so streaming clients get the shape they expect — one content
    chunk, a finish chunk, then ``[DONE]``.
    """
    content_chunk = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
    yield f"data: {json.dumps(content_chunk)}\n\n".encode()
    done_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
    yield f"data: {json.dumps(done_chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


async def _handle_vault_query(
    *,
    request_id: str,
    t0: int,
    ollama: OllamaClient,
    model: str,
    full_messages: list[dict[str, Any]],
    options: dict[str, Any],
    reader: VaultReader,
    max_steps: int,
    resolved: Any,
    record_messages: tuple[Message, ...],
    soul_injected: bool,
    client_id: str | None,
    stream_requested: bool,
    arq_pool: Any,
    vault: VaultWriter,
    request_logger: RequestLogger,
    entity_index: EntityIndex,
    metrics: Metrics,
) -> Any:
    """Run the vault agent, then feed its answer through the same record →
    persist → response machinery the streaming path uses. Non-streaming during
    the tool loop; the final answer is framed as SSE for streaming clients."""
    try:
        agent = await run_vault_agent(
            ollama=ollama,
            model=model,
            messages=full_messages,
            options=options,
            reader=reader,
            max_steps=max_steps,
        )
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
            timings=Timings(received_ms=0.0, ttft_ms=None, completed_ms=(t2 - t0) / _NS_PER_MS),
            token_counts=None,
            error=str(exc),
            ollama_status=502,
        )
        _fire(
            _enqueue_or_persist(
                error_record,
                arq_pool=arq_pool,
                vault=vault,
                logger=request_logger,
                entity_index=entity_index,
                metrics=metrics,
            )
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": {"code": "UPSTREAM_ERROR", "message": "ollama upstream failed", "details": {}}
            },
            headers={"X-Request-ID": request_id},
        )

    t2 = time.monotonic_ns()
    done_record = ConversationRecord(
        request_id=request_id,
        messages=(*record_messages, Message(role="assistant", content=agent.content)),
        soul_injected=soul_injected,
        client_id=client_id,
        stream_requested=stream_requested,
        resolved=resolved,
        assistant_response=agent.content,
        finish_reason="stop",
        truncated=False,
        timings=Timings(received_ms=0.0, ttft_ms=None, completed_ms=(t2 - t0) / _NS_PER_MS),
        token_counts=agent.token_counts,
        error=None,
        ollama_status=200,
    )
    _fire(
        _enqueue_or_persist(
            done_record,
            arq_pool=arq_pool,
            vault=vault,
            logger=request_logger,
            entity_index=entity_index,
            metrics=metrics,
        )
    )

    if stream_requested:
        return StreamingResponse(
            _sse_from_text(agent.content),
            media_type="text/event-stream",
            headers={"X-Request-ID": request_id, "Cache-Control": "no-cache"},
        )
    return JSONResponse(
        content=_openai_response(
            request_id=request_id,
            model=model,
            content=agent.content,
            finish_reason="stop",
            token_counts=agent.token_counts,
        ),
        headers={"X-Request-ID": request_id},
    )


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
    arq_pool: Any = Depends(get_arq_pool),
    reader: VaultReader | None = Depends(get_vault_reader),
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
        soul_msg = {
            "role": "system",
            "content": soul_for(resolved.task_type, client_id=client_id),
        }
        full_messages = [soul_msg, *full_messages]

    entry = roster.lookup(resolved.task_type)
    options: dict[str, Any] = dict(entry.options) if entry else {}

    record_messages = tuple(
        Message(role=m.get("role", "user"), content=m.get("content", ""))
        for m in full_messages
        if isinstance(m, dict)
    )

    # vault_query → run the agentic tool loop over the vault so the answer is
    # grounded in Tali's notes. Falls through to the plain proxy below when the
    # agent is disabled, no reader is mounted, or the vault dir isn't there yet.
    cfg = get_config()
    if (
        cfg.vault_agent_enabled
        and resolved.task_type == "vault_query"
        and reader is not None
        and reader.available
    ):
        return await _handle_vault_query(
            request_id=request_id,
            t0=t0,
            ollama=ollama,
            model=resolved.model,
            full_messages=full_messages,
            options=options,
            reader=reader,
            max_steps=cfg.vault_agent_max_steps,
            resolved=resolved,
            record_messages=record_messages,
            soul_injected=soul_injected,
            client_id=client_id,
            stream_requested=stream_requested,
            arq_pool=arq_pool,
            vault=vault,
            request_logger=request_logger,
            entity_index=entity_index,
            metrics=metrics,
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
        _fire(
            _enqueue_or_persist(
                error_record,
                arq_pool=arq_pool,
                vault=vault,
                logger=request_logger,
                entity_index=entity_index,
                metrics=metrics,
            )
        )
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
            _fire(
                _enqueue_or_persist(
                    done_record,
                    arq_pool=arq_pool,
                    vault=vault,
                    logger=request_logger,
                    entity_index=entity_index,
                    metrics=metrics,
                )
            )

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
