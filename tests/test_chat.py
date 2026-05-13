"""Integration tests for ``POST /v1/chat/completions``.

We build a minimal FastAPI app per test, wire in *real* components (resolver,
classifier, soul, vault, logger), and mock only Ollama's HTTP layer via
``respx``. The classifier and the chat call both hit Ollama; the side-effect
handler dispatches by the request body's ``model`` so we can verify call
counts independently.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml
from fastapi import FastAPI

from api.chat import router as chat_router
from config import Config, get_config
from memory.entities import EntityIndex
from memory.vault import VaultWriter, WriteResult
from proxy.ollama_client import OllamaClient
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics

OLLAMA_BASE = "http://ollama.test:11434"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

SSE_BODY = (
    b'data: {"id":"x","choices":[{"index":0,"delta":{"role":"assistant","content":"hello "}}]}\n\n'
    b'data: {"id":"x","choices":[{"index":0,"delta":{"content":"world"}}]}\n\n'
    b'data: {"id":"x","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
    b'"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
    b"data: [DONE]\n\n"
)


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    p = tmp_path / "vault"
    p.mkdir()
    return p


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    p = tmp_path / "logs"
    p.mkdir()
    return p


@pytest.fixture
def vault(vault_path: Path) -> VaultWriter:
    return VaultWriter(vault_path, timezone="America/Chicago")


@pytest.fixture
def request_logger(log_dir: Path) -> RequestLogger:
    return RequestLogger(log_dir, timezone="America/Chicago")


@pytest.fixture
def entity_index(vault_path: Path) -> EntityIndex:
    return EntityIndex(vault_path, threshold=2)


@pytest.fixture
def metrics() -> Metrics:
    return Metrics()


@pytest.fixture
def ollama() -> OllamaClient:
    return OllamaClient(OLLAMA_BASE)


@pytest.fixture
def classifier(ollama: OllamaClient) -> Classifier:
    return Classifier(ollama, "phi3.5:3.8b")


@pytest.fixture
def app(
    classifier: Classifier,
    ollama: OllamaClient,
    vault: VaultWriter,
    request_logger: RequestLogger,
    entity_index: EntityIndex,
    metrics: Metrics,
) -> FastAPI:
    a = FastAPI()
    a.include_router(chat_router)
    a.state.classifier = classifier
    a.state.roster = Roster()
    a.state.ollama = ollama
    a.state.vault = vault
    a.state.request_logger = request_logger
    a.state.entity_index = entity_index
    a.state.metrics = metrics
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault.vault),
        log_dir=str(request_logger.path.parent),
    )
    return a


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


# --- ollama mocks ---------------------------------------------------------


def _classifier_reply(task_type: str, confidence: float = 0.92) -> httpx.Response:
    content = json.dumps({"task_type": task_type, "confidence": confidence})
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def _streaming_reply(body: bytes = SSE_BODY) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


def install_ollama_dispatcher(
    *,
    classifier_task: str = "code",
    chat_response: httpx.Response | None = None,
    counters: dict[str, int] | None = None,
) -> respx.Route:
    """Route the shared ``/v1/chat/completions`` mock by the request's ``model``."""
    counters = counters if counters is not None else {}
    counters.setdefault("classifier", 0)
    counters.setdefault("chat", 0)

    chat_response = chat_response if chat_response is not None else _streaming_reply()

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("model") == "phi3.5:3.8b":
            counters["classifier"] += 1
            return _classifier_reply(classifier_task)
        counters["chat"] += 1
        return chat_response

    return respx.post(f"{OLLAMA_BASE}/v1/chat/completions").mock(side_effect=handle)


async def _drain_stream(response: httpx.Response) -> list[bytes]:
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        if chunk:
            chunks.append(chunk)
    return chunks


async def _wait_for_vault_write(vault_path: Path, *, timeout: float = 2.0) -> Path:
    """Spin until a conversation note shows up. Vault writes are fire-and-forget."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        notes = list(vault_path.glob("conversations/*/*.md"))
        if notes:
            return notes[0]
        await asyncio.sleep(0.01)
    raise AssertionError("vault note never appeared")


async def _wait_for_log_line(log_path: Path, *, timeout: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_path.exists() and log_path.read_text().strip():
            line = log_path.read_text().splitlines()[-1]
            return json.loads(line)
        await asyncio.sleep(0.01)
    raise AssertionError("log line never appeared")


def _split_frontmatter(text: str) -> dict[str, Any]:
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)


# --- tests ----------------------------------------------------------------


@respx.mock
async def test_auto_classify_path_uses_classified_model(
    app: FastAPI, vault_path: Path, request_logger: RequestLogger
) -> None:
    counters: dict[str, int] = {}
    install_ollama_dispatcher(classifier_task="code", counters=counters)

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "refactor this Python"}]},
            headers=AUTH,
        )

    assert response.status_code == 200
    assert counters["classifier"] == 1
    assert counters["chat"] == 1

    note = await _wait_for_vault_write(vault_path)
    fm = _split_frontmatter(note.read_text())
    assert fm["task_type"] == "code"
    assert fm["models"] == ["qwen2.5-coder:14b"]
    assert fm["classifier_confidence"] == 0.92

    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["model"] == "qwen2.5-coder:14b"
    assert log_line["task_type"] == "code"
    assert log_line["resolution_source"] == "classified"


@respx.mock
async def test_explicit_model_skips_classifier(
    app: FastAPI, vault_path: Path
) -> None:
    counters: dict[str, int] = {}
    install_ollama_dispatcher(counters=counters)

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:14b",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=AUTH,
        )

    assert response.status_code == 200
    assert counters["classifier"] == 0
    assert counters["chat"] == 1

    note = await _wait_for_vault_write(vault_path)
    fm = _split_frontmatter(note.read_text())
    assert fm["models"] == ["qwen2.5-coder:14b"]


@respx.mock
async def test_explicit_task_type_skips_classifier(
    app: FastAPI, request_logger: RequestLogger, vault_path: Path
) -> None:
    counters: dict[str, int] = {}
    install_ollama_dispatcher(counters=counters)

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "reason",
                "messages": [{"role": "user", "content": "prove it"}],
            },
            headers=AUTH,
        )

    assert response.status_code == 200
    assert counters["classifier"] == 0
    assert counters["chat"] == 1

    await _wait_for_vault_write(vault_path)
    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["task_type"] == "reason"
    assert log_line["model"] == "deepseek-r1:14b"
    assert log_line["resolution_source"] == "explicit_task"


@respx.mock
async def test_client_system_message_disables_soul_injection(
    app: FastAPI, vault_path: Path, request_logger: RequestLogger
) -> None:
    install_ollama_dispatcher()

    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "messages": [
                    {"role": "system", "content": "you are a pirate."},
                    {"role": "user", "content": "ahoy"},
                ],
            },
            headers=AUTH,
        )

    await _wait_for_vault_write(vault_path)
    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["soul_injected"] is False


@respx.mock
async def test_streaming_returns_sse_chunks(app: FastAPI) -> None:
    install_ollama_dispatcher()

    async with _client(app) as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=AUTH,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            collected = b""
            async for chunk in response.aiter_bytes():
                collected += chunk

    assert b"[DONE]" in collected
    assert b'"content":"hello "' in collected
    assert b'"content":"world"' in collected


@respx.mock
async def test_non_streaming_returns_single_json(app: FastAPI) -> None:
    install_ollama_dispatcher()

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=AUTH,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "hello world"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"]["prompt_tokens"] == 3
    assert payload["usage"]["completion_tokens"] == 2


@respx.mock
async def test_ollama_error_returns_clean_502(
    app: FastAPI, request_logger: RequestLogger
) -> None:
    respx.post(f"{OLLAMA_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="ollama backend error: internal details")
    )

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:14b",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
            headers=AUTH,
        )

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_ERROR"
    # Upstream stderr / details must not leak.
    assert "internal details" not in json.dumps(body)

    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["error"]
    assert log_line["ollama_status"] == 502


@respx.mock
async def test_missing_bearer_short_circuits(
    app: FastAPI, vault_path: Path
) -> None:
    counters: dict[str, int] = {}
    install_ollama_dispatcher(counters=counters)

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert counters["classifier"] == 0
    assert counters["chat"] == 0
    assert not list(vault_path.glob("conversations/**/*.md"))


@respx.mock
async def test_request_id_propagates_to_headers_log_and_vault(
    app: FastAPI, vault_path: Path, request_logger: RequestLogger
) -> None:
    install_ollama_dispatcher()

    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=AUTH,
        )

    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    assert response.json()["id"] == request_id

    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["request_id"] == request_id


@respx.mock
async def test_metrics_are_recorded_through_the_full_route(
    app: FastAPI, metrics: Metrics, request_logger: RequestLogger
) -> None:
    install_ollama_dispatcher()
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "stream": False,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers=AUTH,
        )
    # Wait for the fire-and-forget _persist task to land.
    await _wait_for_log_line(request_logger.path)
    body, _ = metrics.expose()
    text = body.decode("utf-8")
    assert (
        'delphi_requests_total{model="phi4:14b",resolution_source="explicit_task",'
        'status="ok",task_type="chat"} 1.0' in text
    )
    assert 'delphi_vault_writes_total{status="ok"} 1.0' in text


@respx.mock
async def test_known_entity_in_response_becomes_wikilink_in_vault_note(
    app: FastAPI, vault_path: Path
) -> None:
    """The entity index should rewrite mentions of pre-existing entities/ files."""
    (vault_path / "entities").mkdir(exist_ok=True)
    (vault_path / "entities" / "Pydantic.md").write_text("# Pydantic\n")

    sse = (
        b'data: {"id":"x","choices":[{"index":0,"delta":{"content":"Use Pydantic"}}]}\n\n'
        b'data: {"id":"x","choices":[{"index":0,"delta":{"content":" for that"}}]}\n\n'
        b'data: {"id":"x","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    install_ollama_dispatcher(chat_response=_streaming_reply(sse))

    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "stream": False,
                "messages": [{"role": "user", "content": "ideas?"}],
            },
            headers=AUTH,
        )

    note = await _wait_for_vault_write(vault_path)
    body = note.read_text()
    assert "[[Pydantic]]" in body
    fm = _split_frontmatter(body)
    assert fm["entities"] == ["[[Pydantic]]"]


@respx.mock
async def test_x_client_id_propagates_into_record(
    app: FastAPI, request_logger: RequestLogger
) -> None:
    install_ollama_dispatcher()

    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            json={
                "task_type": "chat",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={**AUTH, "X-Client-ID": "agentrig-m4"},
        )

    log_line = await _wait_for_log_line(request_logger.path)
    assert log_line["client_id"] == "agentrig-m4"


async def test_vault_write_failure_still_returns_200(
    classifier: Classifier,
    ollama: OllamaClient,
    request_logger: RequestLogger,
    log_dir: Path,
) -> None:
    """If the vault is broken, the API contract still has to hold."""

    class _BrokenVault:
        @property
        def vault(self) -> Path:
            return log_dir  # any path; only its presence matters

        async def write(self, _note: Any) -> WriteResult:
            return WriteResult(ok=False, error="disk full")

    app = FastAPI()
    app.include_router(chat_router)
    app.state.classifier = classifier
    app.state.roster = Roster()
    app.state.ollama = ollama
    app.state.vault = _BrokenVault()
    app.state.request_logger = request_logger
    app.state.entity_index = EntityIndex(log_dir)
    app.state.metrics = Metrics()
    app.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(log_dir),
        log_dir=str(log_dir),
    )

    with respx.mock:
        install_ollama_dispatcher()

        async with _client(app) as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "task_type": "chat",
                    "stream": False,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers=AUTH,
            )

        assert response.status_code == 200

        log_line = await _wait_for_log_line(request_logger.path)
        assert log_line["vault_write"]["ok"] is False
        assert log_line["vault_write"]["error"] == "disk full"


async def test_record_marks_truncated_when_stream_does_not_complete(
    classifier: Classifier,
    vault: VaultWriter,
    vault_path: Path,
    request_logger: RequestLogger,
) -> None:
    """When the upstream stream is interrupted, the vault note records ``truncated: true``.

    This is the same code path a real client disconnect exercises: the
    streaming generator's body raises before reaching ``[DONE]``, so the
    route's emit generator exits via its ``finally`` block with
    ``completed_naturally=False``. We trigger it here by having the proxy
    raise mid-stream because ASGITransport buffers the server output before
    yielding to httpx, which prevents a real HTTP disconnect from arriving
    in time to test the path otherwise.
    """

    class _InterruptedOllama:
        async def stream_chat(
            self,
            *,
            model: str,
            messages: list[dict[str, Any]],
            options: dict[str, Any] | None = None,
        ) -> AsyncIterator[bytes]:
            yield b'data: {"choices":[{"delta":{"content":"partial "}}]}\n\n'
            # No [DONE] — simulate the stream being cut short.
            raise RuntimeError("simulated mid-stream interruption")

        async def aclose(self) -> None:
            pass

    app = FastAPI()
    app.include_router(chat_router)
    app.state.classifier = classifier
    app.state.roster = Roster()
    app.state.ollama = _InterruptedOllama()
    app.state.vault = vault
    app.state.request_logger = request_logger
    app.state.entity_index = EntityIndex(vault_path)
    app.state.metrics = Metrics()
    app.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault_path),
        log_dir=str(request_logger.path.parent),
    )

    async with _client(app) as client:
        try:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "phi4:14b",
                    "stream": True,
                    "messages": [{"role": "user", "content": "tell me a long story"}],
                },
                headers=AUTH,
            ) as response:
                async for _chunk in response.aiter_bytes():
                    pass
        except (httpx.HTTPError, RuntimeError):
            # Either is acceptable — the body iterator died, the connection
            # closed, the test just needs the vault write to have fired.
            pass

    note = await _wait_for_vault_write(vault_path)
    fm = _split_frontmatter(note.read_text())
    assert fm["truncated"] is True
