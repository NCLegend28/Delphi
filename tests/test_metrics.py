"""Tests for ``telemetry/metrics.py``.

Each test gets its own ``Metrics`` instance (and therefore its own
``CollectorRegistry``) so observations don't bleed across tests.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST

from telemetry.metrics import Metrics


def _expose_text(m: Metrics) -> str:
    body, _ = m.expose()
    return body.decode("utf-8")


def test_record_request_increments_counter() -> None:
    m = Metrics()
    m.record_request(
        task_type="code",
        model="qwen2.5-coder:14b",
        resolution_source="classified",
        status="ok",
        latency_ms=1840.0,
        ttft_ms=220.0,
        input_tokens=412,
        output_tokens=1103,
        classifier_confidence=0.92,
    )
    text = _expose_text(m)
    assert (
        'delphi_requests_total{model="qwen2.5-coder:14b",resolution_source="classified",'
        'status="ok",task_type="code"} 1.0' in text
    )


def test_record_request_observes_latency_and_ttft() -> None:
    m = Metrics()
    m.record_request(
        task_type="code",
        model="qwen2.5-coder:14b",
        resolution_source="classified",
        status="ok",
        latency_ms=1840.0,
        ttft_ms=220.0,
        input_tokens=412,
        output_tokens=1103,
        classifier_confidence=0.92,
    )
    text = _expose_text(m)
    # Histogram exposes _count, _sum and _bucket samples.
    assert 'delphi_request_latency_seconds_count{model="qwen2.5-coder:14b"' in text
    assert "delphi_request_latency_seconds_sum" in text
    assert "delphi_ttft_seconds_count" in text


def test_classifier_confidence_only_recorded_for_classified_source() -> None:
    m = Metrics()
    m.record_request(
        task_type="code",
        model="qwen2.5-coder:14b",
        resolution_source="explicit_model",  # not classified
        status="ok",
        latency_ms=100.0,
        ttft_ms=20.0,
        input_tokens=10,
        output_tokens=20,
        classifier_confidence=0.92,  # should be ignored
    )
    text = _expose_text(m)
    # No observation of the classifier confidence means no labeled sample appears
    # in the exposition for our task_type — the label only materialises on .observe().
    assert 'delphi_classifier_confidence_count{task_type="code"}' not in text


def test_classifier_confidence_recorded_when_classified() -> None:
    m = Metrics()
    m.record_request(
        task_type="reason",
        model="deepseek-r1:14b",
        resolution_source="classified",
        status="ok",
        latency_ms=100.0,
        ttft_ms=20.0,
        input_tokens=10,
        output_tokens=20,
        classifier_confidence=0.84,
    )
    text = _expose_text(m)
    assert 'delphi_classifier_confidence_count{task_type="reason"} 1.0' in text
    assert 'delphi_classifier_confidence_sum{task_type="reason"} 0.84' in text


def test_token_counters_accumulate() -> None:
    m = Metrics()
    for _ in range(3):
        m.record_request(
            task_type="chat",
            model="phi4:14b",
            resolution_source="explicit_task",
            status="ok",
            latency_ms=100.0,
            ttft_ms=20.0,
            input_tokens=10,
            output_tokens=50,
            classifier_confidence=None,
        )
    text = _expose_text(m)
    assert 'delphi_input_tokens_total{model="phi4:14b"} 30.0' in text
    assert 'delphi_output_tokens_total{model="phi4:14b"} 150.0' in text


def test_record_vault_write_distinguishes_ok_and_failed() -> None:
    m = Metrics()
    m.record_vault_write(ok=True)
    m.record_vault_write(ok=True)
    m.record_vault_write(ok=False)
    text = _expose_text(m)
    assert 'delphi_vault_writes_total{status="ok"} 2.0' in text
    assert 'delphi_vault_writes_total{status="failed"} 1.0' in text


def test_record_entities_promoted_increments_by_count() -> None:
    m = Metrics()
    m.record_entities_promoted(0)  # noop
    m.record_entities_promoted(3)
    text = _expose_text(m)
    assert "delphi_entities_promoted_total 3.0" in text


def test_record_upstream_error_labels_by_kind() -> None:
    m = Metrics()
    m.record_upstream_error(kind="connect")
    m.record_upstream_error(kind="non_200")
    text = _expose_text(m)
    assert 'delphi_upstream_errors_total{kind="connect"} 1.0' in text
    assert 'delphi_upstream_errors_total{kind="non_200"} 1.0' in text


def test_expose_returns_correct_content_type() -> None:
    m = Metrics()
    _, content_type = m.expose()
    assert content_type == CONTENT_TYPE_LATEST


def test_each_instance_has_independent_registry() -> None:
    """Two ``Metrics`` instances must not interfere — registries are separate."""
    a = Metrics()
    b = Metrics()
    a.record_vault_write(ok=True)
    a.record_vault_write(ok=True)
    a_text = _expose_text(a)
    b_text = _expose_text(b)
    assert 'delphi_vault_writes_total{status="ok"} 2.0' in a_text
    # Without any observation, the labeled sample never appears on B's registry.
    assert 'delphi_vault_writes_total{status="ok"}' not in b_text
