"""Prometheus metrics for Delphi.

A single ``Metrics`` instance owns a ``CollectorRegistry`` and the
counters/histograms the rest of the service reaches for. ``main.py``
builds one in the lifespan; ``api/chat.py`` calls ``record_request``
inside ``_persist`` so the JSONL log line and the Prometheus counter
update from the same data.

Labels are deliberately low-cardinality. ``task_type`` and ``model`` come
from the roster (≤10 values). ``resolution_source`` is a four-value enum.
``status`` is ``ok`` / ``error`` / ``upstream_error``. Anything client-supplied
(``client_id``, ``request_id``) is **not** a label — those would explode
the time-series count.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Buckets chosen for an LLM gateway. Smallest model TTFT ≈ 200ms; biggest
# completion latency ≈ 2 min for a 32B CPU+GPU split.
_LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
_TTFT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_CONFIDENCE_BUCKETS = (0.0, 0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0)

RequestStatus = Literal["ok", "error", "upstream_error"]


class Metrics:
    """Prometheus metric set for the service."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()

        self.requests = Counter(
            "delphi_requests_total",
            "Total /v1/chat/completions requests, by routing decision and outcome.",
            labelnames=("task_type", "model", "resolution_source", "status"),
            registry=self.registry,
        )
        self.latency_seconds = Histogram(
            "delphi_request_latency_seconds",
            "End-to-end request latency, seconds.",
            labelnames=("task_type", "model"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.ttft_seconds = Histogram(
            "delphi_ttft_seconds",
            "Time-to-first-token from t0, seconds.",
            labelnames=("task_type", "model"),
            buckets=_TTFT_BUCKETS,
            registry=self.registry,
        )
        self.classifier_confidence = Histogram(
            "delphi_classifier_confidence",
            "Classifier confidence scores for routed-by-classifier requests.",
            labelnames=("task_type",),
            buckets=_CONFIDENCE_BUCKETS,
            registry=self.registry,
        )
        self.input_tokens = Counter(
            "delphi_input_tokens_total",
            "Total input (prompt) tokens served, by model.",
            labelnames=("model",),
            registry=self.registry,
        )
        self.output_tokens = Counter(
            "delphi_output_tokens_total",
            "Total output (completion) tokens served, by model.",
            labelnames=("model",),
            registry=self.registry,
        )
        self.vault_writes = Counter(
            "delphi_vault_writes_total",
            "Vault write outcomes, by ok/failed.",
            labelnames=("status",),
            registry=self.registry,
        )
        self.entities_promoted = Counter(
            "delphi_entities_promoted_total",
            "Candidates promoted to entity stubs.",
            registry=self.registry,
        )
        self.upstream_errors = Counter(
            "delphi_upstream_errors_total",
            "Ollama upstream errors, by kind.",
            labelnames=("kind",),
            registry=self.registry,
        )

    # --- recording helpers ----------------------------------------------

    def record_request(
        self,
        *,
        task_type: str,
        model: str,
        resolution_source: str,
        status: RequestStatus,
        latency_ms: float,
        ttft_ms: float | None,
        input_tokens: int,
        output_tokens: int,
        classifier_confidence: float | None,
    ) -> None:
        """Single entry point for request-level metrics."""
        self.requests.labels(
            task_type=task_type,
            model=model,
            resolution_source=resolution_source,
            status=status,
        ).inc()
        self.latency_seconds.labels(task_type=task_type, model=model).observe(
            latency_ms / 1000.0
        )
        if ttft_ms is not None:
            self.ttft_seconds.labels(task_type=task_type, model=model).observe(
                ttft_ms / 1000.0
            )
        if classifier_confidence is not None and resolution_source == "classified":
            self.classifier_confidence.labels(task_type=task_type).observe(
                classifier_confidence
            )
        if input_tokens:
            self.input_tokens.labels(model=model).inc(input_tokens)
        if output_tokens:
            self.output_tokens.labels(model=model).inc(output_tokens)

    def record_vault_write(self, *, ok: bool) -> None:
        self.vault_writes.labels(status="ok" if ok else "failed").inc()

    def record_entities_promoted(self, count: int) -> None:
        if count > 0:
            self.entities_promoted.inc(count)

    def record_upstream_error(self, *, kind: str) -> None:
        self.upstream_errors.labels(kind=kind).inc()

    # --- exposition -----------------------------------------------------

    def expose(self) -> tuple[bytes, str]:
        """Return ``(body, content_type)`` for the /metrics endpoint."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
