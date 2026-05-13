"""End-to-end smoke test against a real local Ollama.

This file is **skipped by default**. To run it:

    DELPHI_SMOKE_OLLAMA=1 uv run pytest tests/test_smoke_ollama.py -v

Preconditions:
- Ollama running and reachable on ``OLLAMA_BASE_URL`` (default
  ``http://localhost:11434``).
- The classifier model (``phi3.5:3.8b`` by default) is pulled.
- At least one roster model is pulled — typically ``phi4:14b`` or
  ``qwen2.5-coder:14b``. Configure the test to use whichever you have
  with ``DELPHI_SMOKE_MODEL`` (default: ``phi4:14b``).

This exercises the full pipeline against real weights:
auth → resolver → soul injection → ollama stream → vault write → log.
It's the in-process version of the curl in CLAUDE.md → "First milestone".
For the full over-the-wire test, run ``uv run uvicorn main:app`` and
``curl`` from another terminal.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from api.chat import router as chat_router
from config import Config, get_config
from memory.entities import EntityIndex
from memory.vault import VaultWriter
from proxy.ollama_client import OllamaClient
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics

pytestmark = pytest.mark.skipif(
    os.environ.get("DELPHI_SMOKE_OLLAMA") != "1",
    reason="real-Ollama smoke; set DELPHI_SMOKE_OLLAMA=1 to enable",
)


OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
SMOKE_MODEL = os.environ.get("DELPHI_SMOKE_MODEL", "phi4:14b")
TOKEN = "smoke-token"


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    vault = tmp_path / "vault"
    logs = tmp_path / "logs"
    vault.mkdir()
    logs.mkdir()

    ollama = OllamaClient(OLLAMA_BASE)
    a = FastAPI()
    a.include_router(chat_router)
    a.state.ollama = ollama
    a.state.classifier = Classifier(ollama, os.environ.get("CLASSIFIER_MODEL", "phi3.5:3.8b"))
    a.state.roster = Roster()
    a.state.vault = VaultWriter(vault, timezone="America/Chicago")
    a.state.request_logger = RequestLogger(logs, timezone="America/Chicago")
    a.state.entity_index = EntityIndex(vault)
    a.state.metrics = Metrics()
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault),
        log_dir=str(logs),
        boot_probe_enabled=False,
    )
    return a


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        timeout=120.0,
    )


async def _wait_for(predicate, *, timeout: float = 30.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        out = predicate()
        if out:
            return out
        import asyncio
        await asyncio.sleep(interval)
    raise AssertionError("predicate never became truthy")


async def test_curl_milestone_from_claude_md(app: FastAPI, tmp_path: Path) -> None:
    """The success criteria in CLAUDE.md → "First milestone".

    Preflight: confirm the smoke model is actually pulled. If not, fail with
    a clear message rather than letting Ollama return an opaque 502 that the
    streaming client can't surface cleanly.
    """
    ollama: OllamaClient = app.state.ollama
    available = await ollama.list_models()
    if SMOKE_MODEL not in available:
        pytest.skip(
            f"smoke model {SMOKE_MODEL!r} not pulled on this Ollama. "
            f"Available: {sorted(available)}. "
            f"Run `ollama pull {SMOKE_MODEL}` or set DELPHI_SMOKE_MODEL."
        )

    # Use the explicit-model path so we don't also depend on the classifier
    # model being pulled. The auto-classify path is exercised in mocked tests;
    # this smoke is about the full HTTP+streaming+memory pipeline working.
    async with _client(app) as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": SMOKE_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Refactor this Python: "
                            "def f(x):\n    return x*2 if x>0 else 0"
                        ),
                    }
                ],
                "stream": True,
            },
            headers={"Authorization": f"Bearer {TOKEN}", "X-Client-ID": "smoke"},
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", "replace")
                pytest.fail(
                    f"upstream returned {response.status_code}: {body}"
                )
            assert response.headers["content-type"].startswith("text/event-stream")
            collected = b""
            async for chunk in response.aiter_bytes():
                collected += chunk

    # 1. Streamed body terminates cleanly.
    assert b"[DONE]" in collected, "stream never closed with [DONE]"

    # 2. A vault note appeared.
    vault = Path(app.state.vault.vault)
    note_path = await _wait_for(
        lambda: next(iter(vault.glob("conversations/*/*.md")), None),
        timeout=10.0,
    )
    body = note_path.read_text()
    assert body.startswith("---\n")
    _, fm, conversation = body.split("---\n", 2)

    # 3. Classifier picked something code-flavored (best-effort — real models drift).
    assert "task_type:" in fm
    assert "models:" in fm
    assert "## Assistant" in conversation

    # 4. JSONL log line landed with the right request_id.
    log_path = Path(app.state.request_logger.path)
    log_line_json = await _wait_for(
        lambda: log_path.exists() and log_path.read_text().strip(),
        timeout=10.0,
    )
    line = json.loads(log_line_json.splitlines()[-1])
    assert line["request_id"].startswith("req_")
    assert line["client_id"] == "smoke"
    assert line["vault_write"]["ok"] is True

    # 5. Metrics counter incremented at least once.
    metrics_body, _ = app.state.metrics.expose()
    assert b"delphi_requests_total" in metrics_body
    assert b'status="ok"' in metrics_body
