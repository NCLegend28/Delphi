"""Route-level test for POST /v1/chat/completions when task_type=gre_quiz.

The whole tutor chain: route branches into the quiz agent, the agent picks
a deck via list_due_cards (which writes the state file), grades the next
answer via record_review (which writes back to the vocab card), and ends
via end_quiz_session (which clears the state file). Each step is verified
on disk so we know the writeback is real, not just JSON-shaped."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import httpx
from fastapi import FastAPI

from api.chat import router as chat_router
from config import Config, get_config
from memory.entities import EntityIndex
from memory.quiz_state import QuizStateStore
from memory.vault import VaultWriter
from memory.vault_reader import VaultReader
from memory.vocab_card import read as read_card
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _card_md(word: str) -> str:
    return dedent(
        f"""\
        ---
        type: gre-vocab
        word: {word}
        pos: verb
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
    """Stub for ``app.state.ollama`` — only ``.chat`` is hit on the quiz path."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"tools": tools, "messages": list(messages)})
        return self._responses.pop(0)


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


def _build_app(tmp_path: Path, ollama: ScriptedOllama) -> FastAPI:
    vault_path = tmp_path / "vault"
    vocab_dir = vault_path / "knowledge" / "gre" / "vocab"
    vocab_dir.mkdir(parents=True)
    for word in ("abjure", "extol", "obviate"):
        (vocab_dir / f"{word}.md").write_text(_card_md(word), encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

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
    a.state.quiz_state_store = QuizStateStore(str(vault_path))
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault_path),
        log_dir=str(logs),
    )
    a.state.vault_path = vault_path
    return a


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def test_gre_quiz_starts_session_and_asks_card(tmp_path):
    """First turn: the agent picks cards, reads one, asks the user."""
    ollama = ScriptedOllama(
        [
            _tool_call("list_due_cards", {"n": 2, "difficulty": "hard"}),
            _tool_call(
                "read_note", {"path": "knowledge/gre/vocab/abjure.md"}, call_id="c2"
            ),
            _final(
                "Quiz on. 2 hard canonical words. Card 1 of 2: **abjure**.",
                usage={"prompt_tokens": 80, "completion_tokens": 16},
            ),
        ]
    )
    app = _build_app(tmp_path, ollama)
    async with _client(app) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_quiz",
                "stream": False,
                "messages": [{"role": "user", "content": "quiz me on 2 hard GRE words"}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "abjure" in body["choices"][0]["message"]["content"]

    # State file exists after the call.
    state_file = app.state.vault_path / "state" / "active-quiz.md"
    assert state_file.is_file()
    store = QuizStateStore(app.state.vault_path)
    session = store.load()
    assert session is not None
    assert len(session.deck) == 2


async def test_gre_quiz_grades_card_and_writes_back(tmp_path):
    """Second turn: model grades the prior answer; vocab card on disk reflects it."""
    # Pre-seed an active session.
    vault_path = tmp_path / "vault"
    vocab_dir = vault_path / "knowledge" / "gre" / "vocab"
    vocab_dir.mkdir(parents=True)
    for word in ("abjure", "extol"):
        (vocab_dir / f"{word}.md").write_text(_card_md(word), encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()

    # Bootstrap state by calling the tool directly (would be a real network call
    # in prod, but here we shortcut to set up the second-turn scenario).
    from random import Random

    from routing.quiz_agent import _execute_tool

    store = QuizStateStore(vault_path)
    reader = VaultReader(str(vault_path))
    _execute_tool(
        "list_due_cards",
        {"n": 2, "difficulty": "hard"},
        reader=reader,
        state_store=store,
        vault_path=vault_path,
        client_id="delphi-ui",
        now=datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc),
        rng=Random(0),
    )
    seeded = store.load()
    current_path = seeded.deck[0].path
    current_word = seeded.deck[0].word

    ollama = ScriptedOllama(
        [
            _tool_call(
                "record_review",
                {"path": current_path, "grade": 4, "user_answer": "to renounce"},
            ),
            _final(
                "Solid — that's the renounce sense. Next card coming.",
                usage={"prompt_tokens": 60, "completion_tokens": 10},
            ),
        ]
    )

    a = FastAPI()
    a.include_router(chat_router)
    a.state.classifier = Classifier(ollama, "phi3.5:3.8b")
    a.state.roster = Roster()
    a.state.ollama = ollama
    a.state.vault = VaultWriter(vault_path, timezone="America/Chicago")
    a.state.request_logger = RequestLogger(logs, timezone="America/Chicago")
    a.state.entity_index = EntityIndex(vault_path, threshold=2)
    a.state.metrics = Metrics()
    a.state.vault_reader = reader
    a.state.quiz_state_store = store
    a.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token=TOKEN,
        obsidian_vault_path=str(vault_path),
        log_dir=str(logs),
    )

    async with _client(a) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_quiz",
                "stream": False,
                "messages": [{"role": "user", "content": "to renounce something formally"}],
            },
        )
    assert resp.status_code == 200

    # Vocab card on disk got the SM-2 update (interval 1, ease unchanged at grade 4).
    card = read_card(vault_path / current_path)
    assert card.review.interval_days == 1
    assert card.review.last_reviewed is not None

    # Session state advanced to the next card.
    after = store.load()
    assert after.current_index == 1
    assert after.deck[0].grade == 4
    assert after.deck[0].user_answer == "to renounce"

    # The first call must carry the [ACTIVE QUIZ SESSION] state summary.
    first_msgs = ollama.calls[0]["messages"]
    assert any(
        m.get("role") == "system"
        and "[ACTIVE QUIZ SESSION]" in m.get("content", "")
        and current_word in m.get("content", "")
        for m in first_msgs
    )


async def test_gre_quiz_streams_when_requested(tmp_path):
    ollama = ScriptedOllama(
        [
            _tool_call("list_due_cards", {"n": 1, "difficulty": "hard"}),
            _final("Card 1 of 1: abjure."),
        ]
    )
    app = _build_app(tmp_path, ollama)
    async with _client(app) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "task_type": "gre_quiz",
                "stream": True,
                "messages": [{"role": "user", "content": "drill me on 1 word"}],
            },
        )
        assert resp.status_code == 200
        text = (await resp.aread()).decode()
    assert "data:" in text and "[DONE]" in text
    assert "abjure" in text


async def test_gre_quiz_strips_ui_directives_for_non_ui_clients(tmp_path):
    """Non-UI clients (curl, AgentRig) must not see [MODE:…] / [PREVIEW:…]."""
    ollama = ScriptedOllama(
        [
            _tool_call("list_due_cards", {"n": 1, "difficulty": "hard"}),
            _final("[MODE:THINKING]\nCard 1 of 1: abjure.\n[MODE:IDLE]"),
        ]
    )
    app = _build_app(tmp_path, ollama)
    async with _client(app) as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={**AUTH, "x-client-id": "agentrig-m4"},
            json={
                "task_type": "gre_quiz",
                "stream": False,
                "messages": [{"role": "user", "content": "drill me"}],
            },
        )
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    assert "[MODE:" not in content
    assert "abjure" in content
