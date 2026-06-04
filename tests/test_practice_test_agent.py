"""Tests for the practice-test generation agent."""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from textwrap import dedent

import pytest

from memory.practice_test import PracticeTestStore
from memory.vault_reader import VaultReader
from routing.practice_test_agent import (
    _execute_tool,
    run_practice_test_agent,
)


_FIXED_NOW = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)


def _vocab_card(word: str, *, difficulty: str = "hard", tags=None) -> str:
    tags = tags or ["gre", "vocab", "canonical"]
    return dedent(
        f"""\
        ---
        type: gre-vocab
        word: {word}
        pos: adjective
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


def _quant_topic(slug: str, *, section: str = "counting") -> str:
    return dedent(
        f"""\
        ---
        type: gre-quant
        topic: {slug}
        section: {section}
        difficulty: medium
        ---

        # {slug}

        Worked example for {slug}.
        """
    )


@pytest.fixture
def vault(tmp_path):
    vocab_dir = tmp_path / "knowledge" / "gre" / "vocab"
    vocab_dir.mkdir(parents=True)
    for word in ("perspicacious", "sycophant", "laconic", "rapacious"):
        (vocab_dir / f"{word}.md").write_text(_vocab_card(word), encoding="utf-8")
    quant_dir = tmp_path / "knowledge" / "gre" / "quant"
    quant_dir.mkdir(parents=True)
    for slug, sec in [("permutations", "counting"), ("exponents", "algebra")]:
        (quant_dir / f"{slug}.md").write_text(
            _quant_topic(slug, section=sec), encoding="utf-8"
        )
    return tmp_path


@pytest.fixture
def store(vault):
    return PracticeTestStore(vault)


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


# --- _execute_tool: sample_vocab_cards -----------------------------------


def test_sample_vocab_picks_n(vault, store, reader):
    persisted = []
    out = _execute_tool(
        "sample_vocab_cards",
        {"n": 2},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    assert len(payload["cards"]) == 2
    assert payload["total_matched"] == 4


def test_sample_vocab_filters_by_difficulty(vault, store, reader):
    # Add an easy card; sampling with difficulty="hard" must skip it.
    (vault / "knowledge" / "gre" / "vocab" / "easy_one.md").write_text(
        _vocab_card("easy_one", difficulty="easy"), encoding="utf-8"
    )
    persisted = []
    out = _execute_tool(
        "sample_vocab_cards",
        {"n": 10, "difficulty": "hard"},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    words = [c["word"] for c in payload["cards"]]
    assert "easy_one" not in words


def test_sample_vocab_filters_by_tag(vault, store, reader):
    p = vault / "knowledge" / "gre" / "vocab" / "perspicacious.md"
    p.write_text(_vocab_card("perspicacious", tags=["gre", "vocab"]), encoding="utf-8")
    persisted = []
    out = _execute_tool(
        "sample_vocab_cards",
        {"n": 10, "tags_any": ["canonical"]},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    assert "perspicacious" not in [c["word"] for c in payload["cards"]]


def test_sample_vocab_includes_body(vault, store, reader):
    persisted = []
    out = _execute_tool(
        "sample_vocab_cards",
        {"n": 1},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    assert "Definition for" in payload["cards"][0]["body"]


# --- _execute_tool: sample_quant_topics ----------------------------------


def test_sample_quant_filters_by_section(vault, store, reader):
    persisted = []
    out = _execute_tool(
        "sample_quant_topics",
        {"n": 5, "section": "algebra"},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    assert len(payload["topics"]) == 1
    assert "exponents" in payload["topics"][0]["path"]


# --- _execute_tool: persist_test ----------------------------------------


def test_persist_test_writes_to_disk(vault, store, reader):
    persisted: list[str] = []
    args = {
        "body": "# Practice Test\n\n1. Q?\n",
        "answer_key": {"q1": {"answer": "B", "rubric": "B = conciliatory"}},
        "sections": [{"kind": "text_completion", "n": 1}],
        "sources_vocab": ["knowledge/gre/vocab/perspicacious.md"],
        "sources_quant": [],
    }
    out = _execute_tool(
        "persist_test",
        args,
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=persisted,
    )
    payload = json.loads(out)
    assert payload["test_id"]
    assert payload["preview_directive"].startswith("[PREVIEW:practice-test:")
    assert payload["preview_directive"].endswith("[/PREVIEW]")
    assert persisted == [payload["test_id"]]
    # File on disk.
    loaded = store.load(payload["test_id"])
    assert loaded is not None
    assert loaded.answer_key["q1"].answer == "B"


def test_persist_test_rejects_empty_body(vault, store, reader):
    out = _execute_tool(
        "persist_test",
        {"body": "", "answer_key": {"q1": {"answer": "B"}}, "sections": [{"kind": "x", "n": 1}]},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=[],
    )
    assert out.startswith("error:")


def test_persist_test_rejects_empty_answer_key(vault, store, reader):
    out = _execute_tool(
        "persist_test",
        {"body": "body", "answer_key": {}, "sections": [{"kind": "x", "n": 1}]},
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=[],
    )
    assert out.startswith("error:")


def test_persist_test_rejects_bad_answer_shape(vault, store, reader):
    out = _execute_tool(
        "persist_test",
        {
            "body": "body",
            "answer_key": {"q1": {"answer": 42}},  # int isn't string or list
            "sections": [{"kind": "x", "n": 1}],
        },
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        persisted_ids=[],
    )
    assert out.startswith("error:")


# --- run_practice_test_agent ---------------------------------------------


async def test_agent_samples_then_persists_then_answers(vault, store, reader):
    """Full flow: sample vocab → persist → final answer with directive."""
    ollama = ScriptedOllama(
        [
            _tool_call("sample_vocab_cards", {"n": 2, "difficulty": "hard"}, call_id="c1"),
            _tool_call(
                "persist_test",
                {
                    "body": "# Practice Test\n\n1. Q?\n",
                    "answer_key": {"q1": {"answer": "B", "rubric": "B fits"}},
                    "sections": [{"kind": "text_completion", "n": 1}],
                    "sources_vocab": ["knowledge/gre/vocab/perspicacious.md"],
                },
                call_id="c2",
            ),
            _final(
                "Here's your test. [PREVIEW:practice-test:01H...]\n# Practice Test\n[/PREVIEW]"
            ),
        ]
    )
    result = await run_practice_test_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "give me a 1-question practice test"}],
        options=None,
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        max_steps=5,
    )
    assert "PREVIEW:practice-test" in result.content
    assert result.test_id is not None
    assert store.load(result.test_id) is not None


async def test_agent_bounded_by_max_steps(vault, store, reader):
    responses = [_tool_call("sample_vocab_cards", {"n": 1}) for _ in range(3)]
    responses.append(_final("Forced final."))
    ollama = ScriptedOllama(responses)

    result = await run_practice_test_agent(
        ollama=ollama,
        model="m",
        messages=[{"role": "user", "content": "generate a test"}],
        options=None,
        reader=reader,
        store=store,
        vault_path=vault,
        now=_FIXED_NOW,
        rng=random.Random(0),
        max_steps=3,
    )
    assert result.content == "Forced final."
    assert result.steps == 3
    # Tools withheld on the forced final call.
    assert ollama.calls[-1]["tools"] is None
    # No test persisted because persist_test was never called.
    assert result.test_id is None


async def test_agent_without_tools_still_replies(vault, store, reader):
    ollama = ScriptedOllama([_final("I can't help right now.")])
    result = await run_practice_test_agent(
        ollama=ollama, model="m",
        messages=[{"role": "user", "content": "x"}], options=None,
        reader=reader, store=store, vault_path=vault,
        now=_FIXED_NOW, rng=random.Random(0), max_steps=3,
    )
    assert result.content == "I can't help right now."
    assert result.test_id is None
