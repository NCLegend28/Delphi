"""Smoke tests for the endpoints defined in ``main.py``.

``/v1/chat/completions`` has its own integration suite in ``test_chat.py``.
This file covers ``/healthz``, ``/readyz``, and ``/v1/models``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from config import Config, get_config
from main import app
from routing.roster import Roster

OLLAMA_BASE = "http://localhost:11434"  # default; lifespan reads from env
TOKEN = "test-token-do-not-use-in-prod"  # matches conftest.py default
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _force_known_token() -> None:
    """The auth dependency reads via ``Depends(get_config)``. Override it so
    the bearer token is stable regardless of what conftest.py set."""
    app.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        boot_probe_enabled=False,
    )
    yield
    app.dependency_overrides.pop(get_config, None)


@pytest.fixture
async def booted_app() -> object:
    """Enter the FastAPI lifespan so ``app.state.*`` is populated."""
    async with app.router.lifespan_context(app):
        yield app


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


# --- /healthz -------------------------------------------------------------


async def test_healthz_returns_ok_without_auth() -> None:
    async with _client() as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- /readyz --------------------------------------------------------------


async def test_readyz_requires_auth() -> None:
    async with _client() as client:
        response = await client.get("/readyz")
    assert response.status_code == 401


@respx.mock
async def test_readyz_reports_ok_when_ollama_reachable(booted_app: object) -> None:
    respx.get(f"{OLLAMA_BASE}/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "phi4:14b"}, {"name": "qwen2.5-coder:14b"}]}
        )
    )
    async with _client() as client:
        response = await client.get("/readyz", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["ollama_models"] == 2


@respx.mock
async def test_readyz_503_when_ollama_unreachable(booted_app: object) -> None:
    respx.get(f"{OLLAMA_BASE}/api/tags").mock(side_effect=httpx.ConnectError("nope"))
    async with _client() as client:
        response = await client.get("/readyz", headers=AUTH)
    assert response.status_code == 503


# --- /v1/models -----------------------------------------------------------


async def test_v1_models_requires_auth() -> None:
    async with _client() as client:
        response = await client.get("/v1/models")
    assert response.status_code == 401


async def test_v1_models_lists_roster(booted_app: object) -> None:
    async with _client() as client:
        response = await client.get("/v1/models", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    task_types = {entry["task_type"] for entry in payload["data"]}
    # Should cover every task type in the canonical roster.
    assert task_types == set(Roster().task_types())
    # Every entry has the expected shape.
    for entry in payload["data"]:
        assert set(entry.keys()) >= {"id", "object", "owned_by", "task_type"}
        assert entry["object"] == "model"
        assert entry["owned_by"] == "delphi"


# --- /metrics -------------------------------------------------------------


async def test_metrics_endpoint_is_unauthenticated(booted_app: object) -> None:
    """Prometheus scrapers don't speak bearer auth — the port is the boundary."""
    async with _client() as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    # Prometheus text format starts with comments.
    assert response.text.startswith("# HELP") or "# TYPE" in response.text


async def test_metrics_endpoint_returns_prometheus_content_type(booted_app: object) -> None:
    async with _client() as client:
        response = await client.get("/metrics")
    assert response.headers["content-type"].startswith("text/plain")


async def test_metrics_endpoint_exposes_known_metric_families(booted_app: object) -> None:
    """Every Delphi metric family is announced even before observations land."""
    async with _client() as client:
        response = await client.get("/metrics")
    text = response.text
    for family in (
        "delphi_requests_total",
        "delphi_request_latency_seconds",
        "delphi_ttft_seconds",
        "delphi_classifier_confidence",
        "delphi_input_tokens_total",
        "delphi_output_tokens_total",
        "delphi_vault_writes_total",
        "delphi_entities_promoted_total",
        "delphi_upstream_errors_total",
    ):
        assert family in text, f"missing metric family: {family}"
