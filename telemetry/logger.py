"""Structured JSONL request logger.

One JSON object per request, appended to ``<log_dir>/requests.jsonl``.
``logrotate`` handles rotation in production — this module just writes.

Disk I/O is wrapped with ``asyncio.to_thread`` so the request path never
blocks on a slow filesystem. Failures inside ``log()`` are swallowed and
re-emitted to stderr via a fallback structlog logger; logging must never
take a request down.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

_REQUESTS_FILENAME = "requests.jsonl"


@dataclass(frozen=True)
class VaultWriteRecord:
    """Mirror of ``memory.vault.WriteResult`` for serialization in the log line."""

    ok: bool
    path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RequestRecord:
    """One log line. Field names match the JSONL schema in CLAUDE.md → Logging."""

    request_id: str
    client_id: str | None
    task_type: str
    classifier_confidence: float | None
    model: str
    latency_ms: int
    ttft_ms: int | None
    input_tokens: int
    output_tokens: int
    vault_write: VaultWriteRecord | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class RequestLogger:
    """Append-only JSONL writer for request telemetry."""

    def __init__(self, log_dir: str | Path, timezone: str = "America/Chicago") -> None:
        self._log_dir = Path(log_dir)
        self._tz = ZoneInfo(timezone)
        self._path = self._log_dir / _REQUESTS_FILENAME
        self._fallback = structlog.get_logger("delphi.telemetry.fallback")

    @property
    def path(self) -> Path:
        return self._path

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _build_line(self, record: RequestRecord, ts: datetime) -> str:
        payload: dict[str, Any] = {
            "ts": ts.isoformat(),
            "request_id": record.request_id,
            "client_id": record.client_id,
            "task_type": record.task_type,
            "classifier_confidence": record.classifier_confidence,
            "model": record.model,
            "latency_ms": record.latency_ms,
            "ttft_ms": record.ttft_ms,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "vault_write": asdict(record.vault_write) if record.vault_write else None,
            "error": record.error,
        }
        if record.extra:
            # Caller-supplied extras don't override schema fields by accident.
            for key, value in record.extra.items():
                payload.setdefault(key, value)
        return json.dumps(payload, separators=(",", ":"), default=str) + "\n"

    async def log(self, record: RequestRecord, *, ts: datetime | None = None) -> None:
        """Append one record. Never raises — errors go to stderr via fallback logger."""
        when = ts.astimezone(self._tz) if ts else self._now()
        line = self._build_line(record, when)
        try:
            await asyncio.to_thread(self._append, line)
        except Exception as exc:  # noqa: BLE001 — telemetry must not break the request
            self._fallback.error(
                "request_log_write_failed",
                error=f"{type(exc).__name__}: {exc}",
                path=str(self._path),
            )

    def _append(self, line: str) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def configure_stdlib_logging() -> None:
    """Configure structlog to emit JSON to stderr for app-level events.

    Called once at boot. Request telemetry goes through ``RequestLogger`` and
    bypasses structlog entirely; this only shapes the boot/error log stream.
    """
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def make_record(
    *,
    request_id: str,
    client_id: str | None,
    task_type: str,
    classifier_confidence: float | None,
    model: str,
    latency_ms: int,
    ttft_ms: int | None,
    input_tokens: int,
    output_tokens: int,
    vault_write: Mapping[str, Any] | None = None,
    error: str | None = None,
    **extra: Any,
) -> RequestRecord:
    """Helper to build a ``RequestRecord`` from loose kwargs (e.g. inside a route)."""
    vault: VaultWriteRecord | None = None
    if vault_write is not None:
        vault = VaultWriteRecord(
            ok=bool(vault_write.get("ok", False)),
            path=vault_write.get("path"),
            error=vault_write.get("error"),
        )
    return RequestRecord(
        request_id=request_id,
        client_id=client_id,
        task_type=task_type,
        classifier_confidence=classifier_confidence,
        model=model,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        vault_write=vault,
        error=error,
        extra=dict(extra),
    )
