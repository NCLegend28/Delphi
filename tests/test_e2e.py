"""End-to-end smoke test for the skeleton.

Only checks that the app boots and /healthz responds. Classifier, routing,
memory, and telemetry tests live in their own files once those modules exist.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_requires_no_auth() -> None:
    """Liveness must work without a bearer token — k8s/Caddy probes can't auth."""
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
