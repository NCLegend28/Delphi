"""Tests for the gre_quiz tutor agent."""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from textwrap import dedent

import pytest

from memory.quiz_state import QuizStateStore
from memory.vault_reader import VaultReader
from memory.vocab_card import read as read_card
from routing.quiz_agent import (
    _execute_tool,
    _state_summary,
    run_quiz_agent,
)

_FIXED_NOW = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)


def _card(word: str, *, difficulty: str = "hard", tags: list[str] | None = None) -> str:
    tags = tags or ["gre", "vocab", "canonical"]
    return dedent(
        f"""\
        ---
        type: gre-vocab
        word: {word}
        pos: verb
        difficulty: {difficulty}
        tags: {tags}
        review:
          last_reviewed: null
          ease: 2.5
          interval_days: 0
        ---

        # {word}

        > Definition for {word}.
        """
    )


@pytest.fixture
def vault(tmp_path):
    vocab_dir = tmp_path / "knowledge" / "gre" / "vocab"
    vocab_dir.mkdir(parents=True)
    for word, diff in [
        ("abjure", "hard"),
        ("extol", "hard"),
        ("obviate", "hard"),
        ("rapacious", "medium"),
        ("ennui", "medium"),
    ]:
        (vocab_dir / f"{word}.md").write_text(_card(word, difficulty=diff), encoding="utf-8")
    # An index file the agent should skip.
    (vocab_dir / "_index.md").write_text("# Index\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(vault):
    return QuizStateStore(vault)


@pytest.fixture
def reader(vault):
    return VaultReader(str(vault))


class ScriptedOllama:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
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


def _final(content):
    return {"choices": [{"message": {"content": content}}]}


# --- _execute_tool: list_due_cards ---------------------------------------


def test_list_due_cards_picks_n_and_filters_difficulty(vault, store):
    rng = random.Random(0)
    out = _execute_tool(
        "list_due_cards",
        {"n": 2, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        rng=rng,
    )
    payload = json.loads(out)
    assert payload["n_target"] == 2
    assert payload["total_matched"] == 3  # abjure, extol, obviate
    assert all(c["difficulty"] == "hard" for c in payload["cards"])
    # State file was written.
    session = store.load()
    assert session is not None
    assert len(session.deck) == 2


def test_list_due_cards_creates_fresh_session_overwriting_prior(vault, store):
    rng = random.Random(0)
    _execute_tool(
        "list_due_cards",
        {"n": 3, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        rng=rng,
    )
    first_session_id = store.load().session_id

    _execute_tool(
        "list_due_cards",
        {"n": 2, "difficulty": "medium"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        rng=rng,
    )
    second = store.load()
    assert second.session_id != first_session_id
    assert second.n_target == 2


def test_list_due_cards_respects_tags_any(vault, store):
    # Drop the canonical tag from one card; tags_any=["canonical"] should exclude it.
    p = vault / "knowledge" / "gre" / "vocab" / "abjure.md"
    p.write_text(_card("abjure", difficulty="hard", tags=["gre", "vocab"]), encoding="utf-8")

    out = _execute_tool(
        "list_due_cards",
        {"n": 10, "difficulty": "hard", "tags_any": ["canonical"]},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    words = {c["word"] for c in payload["cards"]}
    assert "abjure" not in words
    assert {"extol", "obviate"}.issubset(words)


def test_list_due_cards_skips_index_files(vault, store):
    out = _execute_tool(
        "list_due_cards",
        {"n": 10},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    paths = [c["path"] for c in payload["cards"]]
    assert all("_index" not in p for p in paths)


def test_list_due_cards_reports_no_match(vault, store):
    out = _execute_tool(
        "list_due_cards",
        {"n": 5, "difficulty": "obscure"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    assert payload["cards"] == []
    assert payload["total_matched"] == 0


# --- _execute_tool: record_review ----------------------------------------


def test_record_review_updates_card_and_state(vault, store):
    # Bootstrap a session.
    _execute_tool(
        "list_due_cards",
        {"n": 3, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    target = session.deck[0]

    out = _execute_tool(
        "record_review",
        {
            "path": target.path,
            "grade": 4,
            "user_answer": "to renounce",
            "notes": "hit the renounce sense",
        },
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    assert payload["ok"] is True
    # SM-2: first pass + grade 4 → interval 1, ease unchanged.
    assert payload["new_interval_days"] == 1

    # Card on disk reflects the update.
    card = read_card(vault / target.path)
    assert card.review.interval_days == 1
    assert card.review.last_reviewed is not None

    # State advanced.
    after = store.load()
    assert after.deck[0].grade == 4
    assert after.deck[0].asked is True
    assert after.deck[0].user_answer == "to renounce"
    assert after.current_index == 1


def test_record_review_without_session_returns_error(vault, store):
    out = _execute_tool(
        "record_review",
        {"path": "knowledge/gre/vocab/abjure.md", "grade": 4},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    assert out.startswith("error: no active quiz session")


def test_record_review_rejects_unknown_card(vault, store):
    _execute_tool(
        "list_due_cards",
        {"n": 2, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    out = _execute_tool(
        "record_review",
        {"path": "knowledge/gre/vocab/nope.md", "grade": 4},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    assert "not in the active deck" in out


def test_record_review_handles_bad_grade(vault, store):
    _execute_tool(
        "list_due_cards",
        {"n": 1, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    out = _execute_tool(
        "record_review",
        {"path": session.deck[0].path, "grade": "lol"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    assert out.startswith("error: grade must be an integer")


# --- _execute_tool: end_quiz_session -------------------------------------


def test_end_quiz_session_returns_stats_and_clears_state(vault, store):
    _execute_tool(
        "list_due_cards",
        {"n": 3, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    # Grade two cards.
    for card, grade in [(session.deck[0], 4), (session.deck[1], 2)]:
        _execute_tool(
            "record_review",
            {"path": card.path, "grade": grade, "user_answer": "x"},
            reader=VaultReader(str(vault)),
            state_store=store,
            vault_path=vault,
            client_id=None,
            now=_FIXED_NOW,
            rng=random.Random(0),
        )

    out = _execute_tool(
        "end_quiz_session",
        {"reason": "user_stopped"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    assert payload["cards_graded"] == 2
    assert payload["cards_correct"] == 1
    assert payload["accuracy_overall"] == 0.5
    assert not store.exists()


def test_end_quiz_session_without_active_session(vault, store):
    out = _execute_tool(
        "end_quiz_session",
        {"reason": "completed"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    payload = json.loads(out)
    assert "no active session" in payload["note"]


# --- _state_summary ------------------------------------------------------


def test_state_summary_marks_current_card(vault, store):
    _execute_tool(
        "list_due_cards",
        {"n": 3, "difficulty": "hard"},
        reader=VaultReader(str(vault)),
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    # Pretend we just asked card 0 — but don't grade it yet.
    summary = _state_summary(session)
    assert "[ACTIVE QUIZ SESSION]" in summary
    assert "CURRENT" in summary
    # All three deck words appear.
    for c in session.deck:
        assert c.word in summary


# --- run_quiz_agent ------------------------------------------------------


async def test_agent_starts_quiz_picks_and_asks(vault, store, reader):
    """First turn: model calls list_due_cards then asks the user."""
    ollama = ScriptedOllama(
        [
            _tool_call("list_due_cards", {"n": 2, "difficulty": "hard"}),
            _tool_call("read_note", {"path": None}, call_id="c2"),  # placeholder; path filled below
            _final("Quiz on. Card 1 of 2: abjure. Take your shot."),
        ]
    )
    # Need to patch the second call's path to match a real card. Easier:
    # let the model read whatever — VaultReader handles bad paths gracefully.
    ollama._responses[1] = _tool_call(
        "read_note", {"path": "knowledge/gre/vocab/abjure.md"}, call_id="c2"
    )

    result = await run_quiz_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "quiz me on 2 hard GRE words"}],
        options=None,
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        max_steps=5,
        rng=random.Random(0),
    )
    assert "abjure" in result.content
    assert result.tool_calls_made == 2
    # State file exists — session still active.
    assert result.session_active is True


async def test_agent_resumes_session_injects_state(vault, store, reader):
    """Subsequent turn: state file already exists; agent injects summary."""
    # Bootstrap a session.
    _execute_tool(
        "list_due_cards",
        {"n": 2, "difficulty": "hard"},
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    current_path = session.deck[0].path

    ollama = ScriptedOllama(
        [
            _tool_call(
                "record_review",
                {"path": current_path, "grade": 4, "user_answer": "to renounce"},
            ),
            _final("Solid. Card 2 of 2: extol. Take your shot."),
        ]
    )
    result = await run_quiz_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "to renounce something formally"}],
        options=None,
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id="delphi-ui",
        now=_FIXED_NOW,
        max_steps=5,
        rng=random.Random(0),
    )
    assert "Card 2" in result.content
    # First call had a system message with the active-session summary.
    first_call_messages = ollama.calls[0]["messages"]
    assert any(
        m.get("role") == "system" and "[ACTIVE QUIZ SESSION]" in m.get("content", "")
        for m in first_call_messages
    )
    # Card was graded on disk.
    card = read_card(vault / current_path)
    assert card.review.interval_days == 1


async def test_agent_completes_session_clears_state(vault, store, reader):
    _execute_tool(
        "list_due_cards",
        {"n": 1, "difficulty": "hard"},
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        rng=random.Random(0),
    )
    session = store.load()
    card_path = session.deck[0].path

    ollama = ScriptedOllama(
        [
            _tool_call(
                "record_review", {"path": card_path, "grade": 5, "user_answer": "yes"}
            ),
            _tool_call(
                "end_quiz_session", {"reason": "completed"}, call_id="c2"
            ),
            _final("Done! 1/1 correct."),
        ]
    )
    result = await run_quiz_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "answer"}],
        options=None,
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        max_steps=5,
        rng=random.Random(0),
    )
    assert "1/1" in result.content
    assert result.session_active is False
    assert not store.exists()


async def test_agent_bounded_by_max_steps(vault, store, reader):
    responses = [_tool_call("search_vault", {"query": "x"}) for _ in range(3)]
    responses.append(_final("Forced final answer."))
    ollama = ScriptedOllama(responses)

    result = await run_quiz_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "quiz me"}],
        options=None,
        reader=reader,
        state_store=store,
        vault_path=vault,
        client_id=None,
        now=_FIXED_NOW,
        max_steps=3,
        rng=random.Random(0),
    )
    assert result.content == "Forced final answer."
    assert result.steps == 3
    # Final forced call withholds tools.
    assert ollama.calls[-1]["tools"] is None
