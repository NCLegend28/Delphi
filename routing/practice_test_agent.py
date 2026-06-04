"""Practice-test generation agent — bounded tool loop with vault sampling.

The third agent loop in the project after ``vault_agent`` (read-only) and
``quiz_agent`` (read + writeback to vocab cards). This one composes a full
mock GRE-style test by:

1. Sampling vocab and quant cards from ``knowledge/gre/`` via two new tools
   (``sample_vocab_cards`` / ``sample_quant_topics``). Vault-grounded so the
   test reinforces Tali's actual library.
2. Composing reading-comprehension passages + sentence-equivalence prompts
   from the model's training (no curated RC in the vault yet).
3. Assembling the whole test and calling ``persist_test`` to write it to
   ``knowledge/gre/practice-tests/<test_id>.md`` with the answer key in
   YAML frontmatter.

The final assistant reply wraps the test markdown in
``[PREVIEW:practice-test:<test_id>] … [/PREVIEW]`` — a new UI directive
the editable preview block hooks into.

Bounded by ``max_steps`` like every other agent loop here. If the model
burns its budget without persisting, the loop forces a final answer with
tools withheld; the user sees a partial preview but no test file landed
on disk (consistent failure-open semantics).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.practice_test import (
    AnswerKey,
    PracticeTest,
    PracticeTestStore,
    Section,
)
from memory.record import TokenCounts
from memory.vault_reader import VaultReader
from memory.vocab_card import VocabCardError
from memory.vocab_card import read as read_card
from proxy.ollama_client import OllamaClient
from ulid import ULID

# Where domain cards live. Mirrors the layout the quiz_agent reads from.
_VOCAB_SUBDIR = ("knowledge", "gre", "vocab")
_QUANT_SUBDIR = ("knowledge", "gre", "quant")


PRACTICE_TEST_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "sample_vocab_cards",
            "description": (
                "Sample N vocab cards from the user's GRE vocab library. Returns "
                "each card's word, definition, examples, and confusion set so you "
                "can compose text-completion or sentence-equivalence stems grounded "
                "in real cards. Use this BEFORE writing any vocab questions — the "
                "test must reinforce the user's actual library, not your training."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of cards to sample."},
                    "difficulty": {
                        "type": "string",
                        "description": "easy|medium|hard|brutal|obscure (optional).",
                    },
                    "tags_any": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict to cards carrying at least one of these tags.",
                    },
                },
                "required": ["n"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sample_quant_topics",
            "description": (
                "Sample N quant topic notes (problems / formula playbooks) from "
                "knowledge/gre/quant/. Use this to ground problem-solving and "
                "data-interpretation questions in topics the user has studied."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "section": {
                        "type": "string",
                        "description": (
                            "Optional filter on the card's ``section`` frontmatter "
                            "(e.g. 'counting', 'geometry', 'algebra')."
                        ),
                    },
                },
                "required": ["n"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_test",
            "description": (
                "Save the assembled test to the vault and return the preview "
                "directive to include in your final answer. CALL THIS LAST, after "
                "you've composed body + answer_key + sections. Returns a JSON "
                "object with `test_id` and `preview_directive`; emit the "
                "preview_directive VERBATIM inside your final assistant message so "
                "the UI renders the editable form."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "body": {
                        "type": "string",
                        "description": (
                            "The full markdown of the test as the user will see "
                            "it (questions, options, passages). DO NOT include "
                            "an answer key in the body — that goes in answer_key."
                        ),
                    },
                    "answer_key": {
                        "type": "object",
                        "description": (
                            "Map of question_id ('q1', 'q2', ...) to "
                            "{answer: <string or list>, rubric: <one-line note>}. "
                            "Single-select answers are strings; sentence-"
                            "equivalence is a 2-element list."
                        ),
                    },
                    "sections": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "List of {kind, n} per section. kind is one of "
                            "text_completion, sentence_equivalence, "
                            "reading_comprehension, problem_solving, "
                            "data_interpretation."
                        ),
                    },
                    "sources_vocab": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Vault-relative paths of vocab cards used.",
                    },
                    "sources_quant": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Vault-relative paths of quant topics used.",
                    },
                },
                "required": ["body", "answer_key", "sections"],
            },
        },
    },
    # Read-only tools from the vault-query agent, so the model can look up
    # extra context mid-generation if it wants ("how does this card define
    # the confusion set?") without burning the sample budget.
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": "Keyword search across the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Read one vault note by vault-relative path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


@dataclass(frozen=True, slots=True)
class PracticeTestAgentResult:
    """Outcome of the loop — final answer + persistence flag."""

    content: str
    steps: int
    tool_calls_made: int
    token_counts: TokenCounts | None
    test_id: str | None  # the test the agent persisted, if any


def _usage_from(resp: dict[str, Any]) -> TokenCounts | None:
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        return None
    it = usage.get("prompt_tokens", usage.get("input_tokens"))
    ot = usage.get("completion_tokens", usage.get("output_tokens"))
    if isinstance(it, int) and isinstance(ot, int):
        return TokenCounts(input_tokens=it, output_tokens=ot)
    return None


def _passes_vocab_filters(
    difficulty: str | None,
    tags_any: list[str] | None,
    card_difficulty: str | None,
    card_tags: tuple[str, ...],
) -> bool:
    if difficulty and (card_difficulty or "").lower() != difficulty.lower():
        return False
    if tags_any and not any(t in card_tags for t in tags_any):
        return False
    return True


def _exec_sample_vocab_cards(
    args: dict[str, Any],
    *,
    vault_path: Path,
    rng: random.Random,
) -> str:
    n = int(args.get("n", 5) or 5)
    if n <= 0:
        return "error: n must be positive"
    difficulty = args.get("difficulty")
    tags_any = args.get("tags_any") if isinstance(args.get("tags_any"), list) else None

    vocab_dir = vault_path.joinpath(*_VOCAB_SUBDIR)
    if not vocab_dir.is_dir():
        return json.dumps({"cards": [], "note": f"no vocab dir at {'/'.join(_VOCAB_SUBDIR)}"})

    candidates: list[tuple[str, Any]] = []
    for path in sorted(vocab_dir.glob("*.md")):
        if path.stem.startswith("_"):
            continue
        try:
            card = read_card(path)
        except VocabCardError:
            continue
        if not _passes_vocab_filters(difficulty, tags_any, card.difficulty, card.tags):
            continue
        rel = path.relative_to(vault_path).as_posix()
        # Carry the body so the model has examples + confusion set on hand
        # without a follow-up read_note round trip.
        candidates.append(
            (
                rel,
                {
                    "path": rel,
                    "word": card.word,
                    "difficulty": card.difficulty,
                    "tags": list(card.tags),
                    "body": card.raw_text,
                },
            )
        )

    total = len(candidates)
    if total == 0:
        return json.dumps(
            {"cards": [], "total_matched": 0, "note": "no cards matched; loosen filters"}
        )
    take = min(n, total)
    chosen = rng.sample(candidates, take)  # noqa: S311 — non-crypto sampling is fine here
    return json.dumps({"cards": [c for _, c in chosen], "total_matched": total})


def _exec_sample_quant_topics(
    args: dict[str, Any],
    *,
    vault_path: Path,
    rng: random.Random,
) -> str:
    n = int(args.get("n", 3) or 3)
    if n <= 0:
        return "error: n must be positive"
    section_filter = args.get("section")

    quant_dir = vault_path.joinpath(*_QUANT_SUBDIR)
    if not quant_dir.is_dir():
        return json.dumps({"topics": [], "note": "no quant dir"})

    candidates: list[dict[str, Any]] = []
    for path in sorted(quant_dir.glob("*.md")):
        if path.stem.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(vault_path).as_posix()
        # Light filtering on a ``section: <name>`` frontmatter line — we don't
        # need a full parser here. If the requested section isn't found in
        # the text at all, skip; otherwise include.
        if section_filter and f"section: {section_filter}" not in text:
            continue
        candidates.append({"path": rel, "body": text})

    total = len(candidates)
    if total == 0:
        return json.dumps({"topics": [], "total_matched": 0})
    take = min(n, total)
    chosen = rng.sample(candidates, take)  # noqa: S311
    return json.dumps({"topics": chosen, "total_matched": total})


def _exec_persist_test(
    args: dict[str, Any],
    *,
    store: PracticeTestStore,
    now: datetime,
) -> str:
    body = args.get("body")
    if not isinstance(body, str) or not body.strip():
        return "error: persist_test requires a non-empty 'body'"
    key_raw = args.get("answer_key")
    if not isinstance(key_raw, dict) or not key_raw:
        return "error: persist_test requires a non-empty 'answer_key' mapping"
    sections_raw = args.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        return "error: persist_test requires a non-empty 'sections' list"

    # Coerce answer_key.
    answer_key: dict[str, AnswerKey] = {}
    for qid, entry in key_raw.items():
        if not isinstance(entry, dict):
            return f"error: answer_key[{qid}] must be a mapping"
        answer = entry.get("answer")
        if not isinstance(answer, (str, list)):
            return f"error: answer_key[{qid}].answer must be string or list"
        rubric = entry.get("rubric") if isinstance(entry.get("rubric"), str) else ""
        answer_key[str(qid)] = AnswerKey(answer=answer, rubric=rubric)

    # Coerce sections.
    sections: list[Section] = []
    for s_raw in sections_raw:
        if not isinstance(s_raw, dict):
            return "error: each section must be a mapping"
        kind = s_raw.get("kind")
        n = s_raw.get("n")
        if not isinstance(kind, str) or not isinstance(n, int):
            return "error: each section needs 'kind' (string) and 'n' (int)"
        extras = {k: v for k, v in s_raw.items() if k not in ("kind", "n")}
        sections.append(Section(kind=kind, n=n, extras=extras))

    sources = {
        "vocab": [
            str(p) for p in args.get("sources_vocab") or [] if isinstance(p, str)
        ],
        "quant": [
            str(p) for p in args.get("sources_quant") or [] if isinstance(p, str)
        ],
    }

    test = PracticeTest(
        test_id=str(ULID()),
        created=now,
        sections=sections,
        n_questions=len(answer_key),
        sources=sources,
        answer_key=answer_key,
        body=body,
    )
    store.save(test)
    directive = f"[PREVIEW:practice-test:{test.test_id}]\n{body.rstrip()}\n[/PREVIEW]"
    return json.dumps({"test_id": test.test_id, "preview_directive": directive})


def _exec_search_vault(args: dict[str, Any], *, reader: VaultReader) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "error: search_vault requires a non-empty 'query'"
    limit = args.get("limit")
    hits = reader.search(query, limit=limit if isinstance(limit, int) else None)
    if not hits:
        return json.dumps({"results": [], "note": "no matching notes found"})
    return json.dumps(
        {"results": [{"path": h.path, "score": h.score, "snippet": h.snippet} for h in hits]}
    )


def _exec_read_note(args: dict[str, Any], *, reader: VaultReader) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "error: read_note requires a 'path'"
    try:
        return reader.read(path)
    except FileNotFoundError as exc:
        return f"error: {exc}"


def _execute_tool(
    name: str,
    raw_args: Any,
    *,
    reader: VaultReader,
    store: PracticeTestStore,
    vault_path: Path,
    now: datetime,
    rng: random.Random,
    persisted_ids: list[str],
) -> str:
    """Dispatch one tool call. Records persisted ``test_id`` in ``persisted_ids``."""
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
    except (json.JSONDecodeError, TypeError):
        return "error: could not parse tool arguments as JSON"

    if name == "sample_vocab_cards":
        return _exec_sample_vocab_cards(args, vault_path=vault_path, rng=rng)
    if name == "sample_quant_topics":
        return _exec_sample_quant_topics(args, vault_path=vault_path, rng=rng)
    if name == "persist_test":
        result = _exec_persist_test(args, store=store, now=now)
        # Pull out the test_id for the caller's bookkeeping.
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and isinstance(parsed.get("test_id"), str):
                persisted_ids.append(parsed["test_id"])
        except json.JSONDecodeError:
            pass
        return result
    if name == "search_vault":
        return _exec_search_vault(args, reader=reader)
    if name == "read_note":
        return _exec_read_note(args, reader=reader)
    return f"error: unknown tool '{name}'"


async def run_practice_test_agent(
    *,
    ollama: OllamaClient,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any] | None,
    reader: VaultReader,
    store: PracticeTestStore,
    vault_path: Path,
    now: datetime | None = None,
    rng: random.Random | None = None,
    max_steps: int = 8,
) -> PracticeTestAgentResult:
    """Drive the sample → compose → persist loop and return the final answer."""
    actual_now = now or datetime.now().astimezone()
    actual_rng = rng or random.Random()  # noqa: S311 — non-crypto sampling

    convo: list[dict[str, Any]] = list(messages)
    token_counts: TokenCounts | None = None
    tool_calls_made = 0
    persisted_ids: list[str] = []

    for step in range(1, max_steps + 1):
        resp = await ollama.chat(
            model=model, messages=convo, options=options, tools=PRACTICE_TEST_TOOLS
        )
        token_counts = _usage_from(resp) or token_counts
        message = resp["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return PracticeTestAgentResult(
                content=message.get("content") or "",
                steps=step,
                tool_calls_made=tool_calls_made,
                token_counts=token_counts,
                test_id=persisted_ids[-1] if persisted_ids else None,
            )

        convo.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            tool_calls_made += 1
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            result = _execute_tool(
                fn.get("name", ""),
                fn.get("arguments"),
                reader=reader,
                store=store,
                vault_path=vault_path,
                now=actual_now,
                rng=actual_rng,
                persisted_ids=persisted_ids,
            )
            convo.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
            )

    # Budget exhausted — force a final answer with tools withheld.
    convo.append(
        {
            "role": "user",
            "content": (
                "Compose your final answer now. Do not call any more tools. If you "
                "haven't called persist_test, the test won't be saved; warn the "
                "user and offer to retry."
            ),
        }
    )
    final = await ollama.chat(model=model, messages=convo, options=options)
    token_counts = _usage_from(final) or token_counts
    return PracticeTestAgentResult(
        content=final["choices"][0]["message"].get("content") or "",
        steps=max_steps,
        tool_calls_made=tool_calls_made,
        token_counts=token_counts,
        test_id=persisted_ids[-1] if persisted_ids else None,
    )
