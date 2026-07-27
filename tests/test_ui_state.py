from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from api.ui_state import router as ui_state_router
from config import Config, get_config
from routing.roster import Roster
from telemetry.logger import RequestLogger

TOKEN = "test-token"


class ScriptedRuntime:
    async def list_models(self) -> list[str]:
        return ["phi-local"]


@pytest.fixture
def ui_app(tmp_path: Path) -> FastAPI:
    today = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    vault = tmp_path / "vault"
    (vault / "entities").mkdir(parents=True)
    (vault / "projects").mkdir()
    (vault / "knowledge" / "gre" / "vocab").mkdir(parents=True)
    (vault / "entities" / "Delphi.md").write_text("entity", encoding="utf-8")
    (vault / "projects" / "Nursery.md").write_text("project", encoding="utf-8")
    (vault / "knowledge" / "gre" / "vocab" / "obviate.md").write_text(
        "# obviate\n", encoding="utf-8"
    )
    (vault / "notes.md").write_text("hello vault", encoding="utf-8")

    logs = tmp_path / "logs"
    logs.mkdir()
    records = [
        {
            "ts": f"{today}T09:00:00-05:00",
            "request_id": "r1",
            "client_id": "delphi-ui",
            "task_type": "chat",
            "classifier_confidence": None,
            "model": "phi-local",
            "latency_ms": 1000,
            "ttft_ms": 200,
            "input_tokens": 10,
            "output_tokens": 20,
            "vault_write": {"ok": True, "path": str(vault / "notes.md"), "error": None},
            "error": None,
        },
        {
            "ts": f"{today}T10:00:00-05:00",
            "request_id": "r2",
            "client_id": "delphi-ui",
            "task_type": "chat",
            "classifier_confidence": None,
            "model": "phi-local",
            "latency_ms": 3000,
            "ttft_ms": 600,
            "input_tokens": 30,
            "output_tokens": 50,
            "vault_write": {"ok": False, "path": None, "error": "disk full"},
            "error": "upstream_error",
        },
        {
            "ts": f"{today}T11:00:00-05:00",
            "request_id": "r3",
            "client_id": "delphi-ui",
            "task_type": "code",
            "classifier_confidence": None,
            "model": "phi-local",
            "latency_ms": 5000,
            "ttft_ms": 1000,
            "input_tokens": 40,
            "output_tokens": 80,
            "vault_write": None,
            "error": None,
        },
    ]
    with (logs / "requests.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")

    cfg = Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault),
        log_dir=str(logs),
        delphi_model_chat="phi-local",
        delphi_model_code="phi-local",
        delphi_vault_bitspace_bytes=1024,
        delphi_context_window_tokens=1000,
        timezone="America/Chicago",
        worker_enabled=True,
    )

    app = FastAPI()
    app.include_router(ui_state_router)
    app.dependency_overrides[get_config] = lambda: cfg
    app.state.roster = Roster.from_config(cfg)
    app.state.ollama = ScriptedRuntime()
    app.state.request_logger = RequestLogger(logs, timezone="America/Chicago")
    app.state.arq_pool = object()
    return app


@pytest.mark.anyio
async def test_ui_state_uses_real_request_log_and_vault_metrics(ui_app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ui_app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ui/state", headers={"Authorization": f"Bearer {TOKEN}"})

    assert resp.status_code == 200
    data = resp.json()

    assert data["system"]["requests_today"] == 3
    assert data["system"]["failures_today"] == 1
    assert data["system"]["last_request"]["request_id"] == "r3"
    assert data["system"]["uplink"]["last_ttft_ms"] == 1000
    assert data["system"]["uplink"]["last_tokens_per_second"] == 16.0
    assert data["system"]["context"] == {
        "last_request_tokens": 120,
        "window_tokens": 1000,
        "fill": 0.12,
        "source": "last completed request input_tokens + output_tokens",
    }

    chat_route = next(route for route in data["roster"] if route["task_type"] == "chat")
    assert chat_route["model"] == "phi-local"
    assert chat_route["request_count"] == 2
    assert chat_route["p50_latency_ms"] == 2000
    assert chat_route["error_count"] == 1

    assert data["memory"]["note_count"] == 4
    assert data["memory"]["entity_count"] == 1
    assert data["memory"]["project_count"] == 1
    assert data["memory"]["vault_bytes"] > 0
    assert data["memory"]["vault_allotted_bytes"] == 1024
    assert 0 < data["memory"]["fill"] <= 1
    assert data["memory"]["last_vault_write"]["ok"] is False
    assert data["memory"]["active_zone_index"] == 4
    assert data["memory"]["active_zone_source"] == "largest vault note-count zone"
    assert data["practice"]["vocab_card_count"] == 1
    assert data["practice"]["due_cards"] is None

    service_ids = {service["id"]: service for service in data["services"]}
    assert service_ids["gateway"]["status"] == "ok"
    assert service_ids["worker"]["status"] == "ok"
    assert service_ids["inference"]["detail"] == "1 model available"


@pytest.mark.anyio
async def test_ui_state_requires_bearer(ui_app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ui_app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ui/state")

    assert resp.status_code == 401
