"""Route-level test: POST /v1/chat/completions with task_type=vault_query
branches into the agentic tool loop and returns a grounded answer."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from api.chat import router as chat_router
from config import Config, get_config
from memory.entities import EntityIndex
from memory.vault import VaultWriter
from memory.vault_reader import VaultReader
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class ScriptedOllama:
    """Stub for app.state.ollama — only .chat is exercised on the vault path."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"tools": tools})
        return self._responses.pop(0)


def _tool_call(name, args):
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": name, "arguments": json.dumps(args)}}
                    ],
                }
            }
        ]
    }


def _final(content):
    return {"choices": [{"message": {"content": content}},],
            "usage": {"prompt_tokens": 40, "completion_tokens": 12}}


@pytest.fixture
def app(tmp_path: Path) -> tuple[FastAPI, ScriptedOllama]:
    vault_path = tmp_path / "vault"
    (vault_path / "entities").mkdir(parents=True)
    (vault_path / "entities" / "msa.md").write_text(
        "MSA = multi-head sparse attention, the bridge to EverMind.\n", encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()

    ollama = ScriptedOllama(
        [
            _tool_call("search_vault", {"query": "MSA"}),
            _tool_call("read_note", {"path": "entities/msa.md"}),
            _final("From your notes: MSA is multi-head sparse attention."),
        ]
    )

    a = FastAPI()
    a.include_router(chat_router)
    a.state.classifier = Classifier(ollama, "phi3.5:3.8b")  # unused (explicit task)
    a.state.roster = Roster()
    a.state.ollama = ollama
    a.state.vault = VaultWriter(vault_path, timezone="America/Chicago")
    a.state.request_logger = RequestLogger(logs, timezone="America/Chicago")
    a.state.entity_index = EntityIndex(vault_path, threshold=2)
    a.state.metrics = Metrics()
    a.state.vault_reader = VaultReader(str(vault_path))
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault_path),
        log_dir=str(logs),
    )
    return a, ollama


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_vault_query_runs_agent_and_grounds_answer(app) -> None:
    a, ollama = app
    async with _client(a) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "vault_query",
                "stream": False,
                "messages": [{"role": "user", "content": "what do I know about MSA?"}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == (
        "From your notes: MSA is multi-head sparse attention."
    )
    # The agent made two tool rounds (search + read) then answered: 3 calls.
    assert len(ollama.calls) == 3
    # Tool schemas were offered on the tool-using calls.
    assert ollama.calls[0]["tools"] is not None


async def test_vault_query_streams_when_requested(app) -> None:
    a, _ = app
    async with _client(a) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "vault_query",
                "stream": True,
                "messages": [{"role": "user", "content": "what do I know about MSA?"}],
            },
        )
        assert resp.status_code == 200
        text = (await resp.aread()).decode()
    assert "data:" in text and "[DONE]" in text
    assert "multi-head sparse attention" in text
