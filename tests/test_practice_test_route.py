"""Route-level tests for the gre_practice_test path.

Two flows verified end-to-end through ``httpx.ASGITransport``:

1. Generation via ``POST /v1/chat/completions`` with ``task_type=gre_practice_test``
   — agent samples vocab, persists a test, returns the preview directive.
2. Grading via ``POST /v1/practice-tests/<test_id>/grade`` — accepts answers,
   runs the parallel two-model grader (mocked), appends a take, returns the
   per-question result with second-opinion notes when graders disagree.

Both endpoints share the same FastAPI app fixture; ``ScriptedOllama``
replays either generation tool-calls or grader JSON depending on which
endpoint is being exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import httpx
import pytest
from fastapi import FastAPI

from api.chat import router as chat_router
from api.practice_tests import router as practice_tests_router
from config import Config, get_config
from memory.entities import EntityIndex
from memory.practice_test import PracticeTestStore
from memory.vault import VaultWriter
from memory.vault_reader import VaultReader
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

PRIMARY = "gpt-oss:120b-cloud"
SECONDARY = "deepseek-v3.1:671b-cloud"


def _card(word: str) -> str:
    return dedent(
        f"""\
        ---
        type: gre-vocab
        word: {word}
        pos: adjective
        difficulty: hard
        tags: [gre, vocab, canonical]
        review:
          last_reviewed: null
          ease: 2.5
          interval_days: 0
        ---

        # {word}

        > Definition for {word}.
        """
    )


class ScriptedOllama:
    """Replays a per-model script. For grading the lookup is by model; for
    generation it's a positional queue. Both modes coexist in one class
    because the route hits the same ``chat`` method either way."""

    def __init__(self, queue=None, by_model=None):
        self._queue = list(queue or [])
        self._by_model = dict(by_model or {})
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"model": model, "tools": tools})
        if model in self._by_model:
            return self._by_model[model]
        return self._queue.pop(0)


def _tool_call(name, args, call_id="c1"):
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
            }
        ]
    }


def _final(content, usage=None):
    msg = {"choices": [{"message": {"content": content}}]}
    if usage:
        msg["usage"] = usage
    return msg


def _grader_reply(payload):
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 20},
    }


def _build_app(tmp_path: Path, ollama: ScriptedOllama) -> FastAPI:
    vault_path = tmp_path / "vault"
    vocab_dir = vault_path / "knowledge" / "gre" / "vocab"
    vocab_dir.mkdir(parents=True)
    for word in ("perspicacious", "sycophant", "laconic"):
        (vocab_dir / f"{word}.md").write_text(_card(word), encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    a = FastAPI()
    a.include_router(chat_router)
    a.include_router(practice_tests_router)
    a.state.classifier = Classifier(ollama, "phi3.5:3.8b")
    a.state.roster = Roster()
    a.state.ollama = ollama
    a.state.vault = VaultWriter(vault_path, timezone="America/Chicago")
    a.state.request_logger = RequestLogger(logs, timezone="America/Chicago")
    a.state.entity_index = EntityIndex(vault_path, threshold=2)
    a.state.metrics = Metrics()
    a.state.vault_reader = VaultReader(str(vault_path))
    a.state.practice_test_store = PracticeTestStore(str(vault_path))
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault_path),
        log_dir=str(logs),
        delphi_model_gre_practice_test=PRIMARY,
        delphi_model_gre_practice_secondary=SECONDARY,
    )
    a.state.vault_path = vault_path
    return a


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


# --- generation flow -----------------------------------------------------


async def test_generation_persists_and_returns_preview_directive(tmp_path):
    ollama = ScriptedOllama(
        queue=[
            _tool_call("sample_vocab_cards", {"n": 2, "difficulty": "hard"}, call_id="c1"),
            _tool_call(
                "persist_test",
                {
                    "body": "# GRE Test\n\n1. Q?\n   - (A) (B) (C)\n",
                    "answer_key": {"q1": {"answer": "B", "rubric": "B is correct"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                    "sources_vocab": ["knowledge/gre/vocab/perspicacious.md"],
                },
                call_id="c2",
            ),
            _final(
                "Here's your test. [PREVIEW:practice-test:XYZ]\n# GRE Test\n[/PREVIEW]"
            ),
        ]
    )
    app = _build_app(tmp_path, ollama)
    async with _client(app) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={**AUTH, "x-client-id": "delphi-ui"},
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [
                    {"role": "user", "content": "give me a 1q practice test"}
                ],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    # UI clients see the directive verbatim; non-UI clients get it stripped.
    assert "PREVIEW:practice-test:" in body["choices"][0]["message"]["content"]

    # The agent's persist_test landed a real file. List the dir.
    tests_dir = app.state.vault_path / "knowledge" / "gre" / "practice-tests"
    files = list(tests_dir.glob("*.md"))
    assert len(files) == 1


async def test_generation_strips_directive_for_non_ui_client(tmp_path):
    ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "Q?",
                    "answer_key": {"q1": {"answer": "B"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:abc]\nQ?\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, ollama)
    async with _client(app) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={**AUTH, "x-client-id": "agentrig-m4"},
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "test"}],
            },
        )
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    assert "[PREVIEW:" not in content


# --- grading flow --------------------------------------------------------


async def test_grade_endpoint_runs_cross_check_and_appends_take(tmp_path):
    # Phase 1: seed a test on disk via the agent.
    seed_ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "1. Q?\n",
                    "answer_key": {
                        "q1": {"answer": "B", "rubric": "B fits"},
                        "q2": {"answer": ["B", "D"], "rubric": "B+D"},
                    },
                    "sections": [{"kind": "text_completion", "n": 2}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:ID1]\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, seed_ollama)
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "seed test"}],
            },
        )

    test_id = (
        next((app.state.vault_path / "knowledge" / "gre" / "practice-tests").glob("*.md")).stem
    )

    # Phase 2: replace the Ollama stub with grader replies, hit /grade.
    grader_payload = {
        "q1": {"grade": "correct", "reasoning": "B"},
        "q2": {"grade": "correct", "reasoning": "B and D"},
    }
    app.state.ollama = ScriptedOllama(
        by_model={
            PRIMARY: _grader_reply(grader_payload),
            SECONDARY: _grader_reply(grader_payload),
        }
    )

    async with _client(app) as client:
        resp = await client.post(
            f"/v1/practice-tests/{test_id}/grade",
            headers=AUTH,
            json={"answers": {"q1": "B", "q2": ["B", "D"]}},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"]["correct"] == 2
    assert body["score"]["total"] == 2
    assert body["graded_by"]["primary"] == PRIMARY
    assert body["graded_by"]["secondary"] == SECONDARY
    assert body["take_n"] == 1
    assert all(q["disagreement"] is None for q in body["questions"])


async def test_grade_endpoint_surfaces_disagreement(tmp_path):
    # Seed.
    seed_ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "Q?",
                    "answer_key": {"q1": {"answer": "B"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:ID1]\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, seed_ollama)
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "seed"}],
            },
        )

    test_id = (
        next((app.state.vault_path / "knowledge" / "gre" / "practice-tests").glob("*.md")).stem
    )

    app.state.ollama = ScriptedOllama(
        by_model={
            PRIMARY: _grader_reply({"q1": {"grade": "correct", "reasoning": "B fits"}}),
            SECONDARY: _grader_reply({"q1": {"grade": "wrong", "reasoning": "no"}}),
        }
    )

    async with _client(app) as client:
        resp = await client.post(
            f"/v1/practice-tests/{test_id}/grade",
            headers=AUTH,
            json={"answers": {"q1": "B"}},
        )
    body = resp.json()
    assert body["questions"][0]["disagreement"] is not None
    assert body["questions"][0]["grade"] == "correct"  # primary wins headline


async def test_grade_endpoint_returns_404_for_missing_test(tmp_path):
    app = _build_app(tmp_path, ScriptedOllama())
    async with _client(app) as client:
        resp = await client.post(
            "/v1/practice-tests/no-such-id/grade",
            headers=AUTH,
            json={"answers": {"q1": "B"}},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "TEST_NOT_FOUND"


async def test_grade_endpoint_rejects_missing_answers(tmp_path):
    app = _build_app(tmp_path, ScriptedOllama())
    async with _client(app) as client:
        resp = await client.post(
            "/v1/practice-tests/anything/grade",
            headers=AUTH,
            json={},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "ANSWERS_MISSING"


async def test_get_test_withholds_answer_key_by_default(tmp_path):
    # Seed.
    seed_ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "Q?",
                    "answer_key": {"q1": {"answer": "B"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:Z]\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, seed_ollama)
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "seed"}],
            },
        )

    test_id = (
        next((app.state.vault_path / "knowledge" / "gre" / "practice-tests").glob("*.md")).stem
    )

    async with _client(app) as client:
        resp_blind = await client.get(
            f"/v1/practice-tests/{test_id}", headers=AUTH
        )
        resp_with_key = await client.get(
            f"/v1/practice-tests/{test_id}?include_key=true", headers=AUTH
        )
    assert "answer_key" not in resp_blind.json()
    assert "answer_key" in resp_with_key.json()


async def test_grade_endpoint_502_when_both_graders_fail(tmp_path):
    seed_ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "Q?",
                    "answer_key": {"q1": {"answer": "B"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:Z]\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, seed_ollama)
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "seed"}],
            },
        )
    test_id = (
        next((app.state.vault_path / "knowledge" / "gre" / "practice-tests").glob("*.md")).stem
    )

    # Both graders return unparseable garbage.
    app.state.ollama = ScriptedOllama(
        by_model={
            PRIMARY: {"choices": [{"message": {"content": "garbage"}}]},
            SECONDARY: {"choices": [{"message": {"content": "more garbage"}}]},
        }
    )
    async with _client(app) as client:
        resp = await client.post(
            f"/v1/practice-tests/{test_id}/grade",
            headers=AUTH,
            json={"answers": {"q1": "B"}},
        )
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "GRADERS_UNAVAILABLE"


async def test_list_tests_returns_recent(tmp_path):
    seed_ollama = ScriptedOllama(
        queue=[
            _tool_call(
                "persist_test",
                {
                    "body": "Q?",
                    "answer_key": {"q1": {"answer": "B"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                },
                call_id="c1",
            ),
            _final("[PREVIEW:practice-test:Z]\n[/PREVIEW]"),
        ]
    )
    app = _build_app(tmp_path, seed_ollama)
    async with _client(app) as client:
        await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_practice_test",
                "stream": False,
                "messages": [{"role": "user", "content": "seed"}],
            },
        )
        resp = await client.get("/v1/practice-tests", headers=AUTH)
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["tests"]) == 1
    assert payload["tests"][0]["n_questions"] == 1
