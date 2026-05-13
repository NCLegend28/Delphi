"""Conversation record — the persistence boundary.

One immutable object built in the ``finally`` block of the streaming
generator after the upstream call completes (cleanly or via client
disconnect). The vault writer and the JSONL request logger both consume
this record; neither sees the raw OpenAI wire format. That decouples the
wire (which OpenAI may evolve) from the persistence layer (which the
user's Obsidian graph depends on).

Every field has a sensible default because the construction site is a
``finally`` block: things can fail before timings are captured, before the
resolver runs, before Ollama returns anything. The record must always be
constructible. ``schema_version`` lets future tooling read old notes when
this shape changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from routing.resolver import ResolvedModel

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    """One turn in the conversation as Delphi observed it.

    No ``tool_calls`` / ``name`` / ``id`` yet — Delphi doesn't proxy tools.
    When function-calling lands, bump ``ConversationRecord.schema_version``
    so old vault notes stay parseable.
    """

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Timings:
    """All three measurements from ``time.monotonic_ns``, normalized to ms.

    ``received_ms`` is t0 (request hit the route). ``ttft_ms`` is t1 - t0
    (first Ollama byte; ``None`` if non-streaming). ``completed_ms`` is
    t2 - t0 (full response in hand).
    """

    received_ms: float
    ttft_ms: float | None
    completed_ms: float


@dataclass(frozen=True, slots=True)
class TokenCounts:
    """Token counts as Ollama reports them, translated from its native names.

    Ollama uses ``prompt_eval_count`` and ``eval_count``; the proxy maps
    those to ``input_tokens`` and ``output_tokens`` so callers don't have
    to think about it.
    """

    input_tokens: int
    output_tokens: int


def _default_timestamp() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """Everything one ``/v1/chat/completions`` exchange produced.

    The only object the vault writer and logger receive. Each consumer picks
    the fields it cares about — one source of truth, two destinations.
    """

    # --- identity ---
    request_id: str
    schema_version: int = 1
    timestamp: datetime = field(default_factory=_default_timestamp)

    # --- request shape (what came in) ---
    messages: tuple[Message, ...] = ()
    soul_injected: bool = False
    client_id: str | None = None
    stream_requested: bool = True

    # --- routing decision (how Delphi chose) ---
    resolved: ResolvedModel | None = None

    # --- response (what came back) ---
    assistant_response: str = ""
    finish_reason: str | None = None
    truncated: bool = False

    # --- measurements ---
    timings: Timings | None = None
    token_counts: TokenCounts | None = None

    # --- error envelope ---
    error: str | None = None
    ollama_status: int | None = None
