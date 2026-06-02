"""The gre_quiz tutor agent — bounded tool loop with vault writeback.

A close cousin of ``routing.vault_agent``. The vault agent is read-only:
search the vault, read promising notes, answer. The quiz agent extends
that pattern with three more tools — pick a deck, grade a card, end the
session — and with side effects on disk (vocab cards' ``review:`` blocks
and the active-quiz state file).

Mental model — three stages cycle until the deck is exhausted:

    LOAD STATE  ──►  GRADE prev card  ──►  ASK next card

``LOAD STATE`` runs once per request: the agent loop opens the
``active-quiz.md`` file (if any) and injects a state summary into the
conversation so the model sees what was asked, what's been graded, and
what's pending. ``GRADE`` happens when the user has just answered a
card — the model calls ``record_review`` with a 0–5 grade and the
review block on disk updates atomically. ``ASK`` is the model picking
the next pending card (via ``read_note``) and composing the prompt for
the user.

The loop is bounded by ``max_steps``. If the model burns its budget
without producing a final answer, the loop forces one with tools
withheld — same shape as the vault agent.

Tool execution is best-effort: errors come back to the model as text
("error: …") rather than raising, so the model can recover by trying a
different card or by calling ``end_quiz_session`` to bail cleanly.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ulid import ULID

from memory.quiz_state import QuizCard, QuizSession, QuizStateStore, append_log
from memory.record import TokenCounts
from memory.srs import ReviewState, is_due, update
from memory.vault_reader import VaultReader
from memory.vocab_card import VocabCardError, write_review
from memory.vocab_card import read as read_card
from proxy.ollama_client import OllamaClient

# Tool schemas the agent presents to the model. Descriptions are written
# *for the model* — they teach the workflow (pick → ask → grade → next)
# alongside the parameter shapes.
QUIZ_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_due_cards",
            "description": (
                "Start a new quiz session by sampling N cards from the user's vocab "
                "knowledge base. Creates the active-quiz state file (overwriting any "
                "existing session). Returns the chosen deck as JSON with each card's "
                "path, word, difficulty, tags, and current SRS state. Call this ONCE "
                "at the start of a quiz; afterwards rely on read_note + record_review."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Deck size (default 10)."},
                    "difficulty": {
                        "type": "string",
                        "description": (
                            "Filter to one difficulty bucket "
                            "(easy|medium|hard|brutal|obscure). Omit for any."
                        ),
                    },
                    "tags_any": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Card must carry at least one of these tags "
                            "(e.g. ['canonical'] for words in all three source lists)."
                        ),
                    },
                    "only_due": {
                        "type": "boolean",
                        "description": (
                            "When true (default), include only cards whose SM-2 due "
                            "date is today or earlier. Set false for free practice."
                        ),
                    },
                    "domain": {
                        "type": "string",
                        "description": "Knowledge domain. Defaults to 'gre'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_review",
            "description": (
                "Grade one card after the user has answered. Applies SM-2: updates the "
                "card's review: frontmatter on disk and advances the active-quiz state. "
                "Idempotent within a session — calling twice for the same card overwrites "
                "the grade. Grade scale: 0=blackout, 1=wrong-but-familiar, 2=wrong-near, "
                "3=correct-with-effort, 4=correct-hesitation, 5=correct-instant. "
                "Anything < 3 is a fail (interval resets to 1 day, ease drops)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path of the card being graded.",
                    },
                    "grade": {
                        "type": "integer",
                        "description": "0–5 SM-2 grade.",
                    },
                    "user_answer": {
                        "type": "string",
                        "description": "What the user said. Recorded for the session log.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Tutor's reasoning for the grade (optional).",
                    },
                },
                "required": ["path", "grade"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_quiz_session",
            "description": (
                "Close the active quiz: delete the state file, return summary stats so "
                "you can compose a sign-off. Call this when the deck is exhausted or "
                "the user says stop / quit / I'm done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "'completed', 'user_stopped', or 'error'.",
                    },
                },
            },
        },
    },
    # The read-only vault tools come along too, so the model can answer
    # ad-hoc follow-ups ("wait, how's this different from perspicuous?")
    # mid-quiz without having to end the session.
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Keyword search across the user's vault. Returns ranked paths + snippets."
            ),
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
            "description": "Read the full text of one vault note by vault-relative path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


@dataclass(frozen=True, slots=True)
class QuizAgentResult:
    """Outcome of the loop — same shape as vault agent's ``AgentResult``."""

    content: str
    steps: int
    tool_calls_made: int
    token_counts: TokenCounts | None
    session_active: bool  # is there still a state file after the agent returns?


def _usage_from(resp: dict[str, Any]) -> TokenCounts | None:
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        return None
    it = usage.get("prompt_tokens", usage.get("input_tokens"))
    ot = usage.get("completion_tokens", usage.get("output_tokens"))
    if isinstance(it, int) and isinstance(ot, int):
        return TokenCounts(input_tokens=it, output_tokens=ot)
    return None


def _state_summary(session: QuizSession) -> str:
    """Render an in-conversation status block so the model knows where it is.

    The model gets this as a system message at the start of each request.
    It lists every card in the deck with its status (graded / current /
    pending) plus the session's filters and progress counters. That's what
    a player would see at the top of an Anki review screen — and it's the
    minimum information the model needs to grade-then-ask correctly.
    """
    lines = [
        "[ACTIVE QUIZ SESSION]",
        f"Domain: {session.domain}",
        f"Filters: {session.filters or '(none)'}",
        f"Progress: {session.graded_count}/{session.n_target} graded.",
        "Deck:",
    ]
    for i, card in enumerate(session.deck):
        if card.grade is not None:
            status = f"graded {card.grade}"
        elif i == session.current_index:
            status = "CURRENT (last asked; user's most recent message is the answer)"
        elif card.asked:
            status = "asked but ungraded — grade it now"
        else:
            status = "pending"
        lines.append(f"  {i + 1}. {card.word} — {status}")
    lines.append(
        "After grading the CURRENT card with record_review, read_note the next "
        "pending card and ask the user. When the deck is done, call "
        "end_quiz_session(reason='completed')."
    )
    return "\n".join(lines)


# --- Tool executors ------------------------------------------------------


def _domain_dir(vault: Path, domain: str) -> Path:
    """Where a domain's vocab cards live. Future-proofs for non-GRE domains."""
    return vault / "knowledge" / domain / "vocab"


def _passes_filters(
    card_review: ReviewState,
    difficulty: str | None,
    tags_any: list[str] | None,
    only_due: bool,
    card_difficulty: str | None,
    card_tags: tuple[str, ...],
    today: datetime | None,
) -> bool:
    if difficulty and (card_difficulty or "").lower() != difficulty.lower():
        return False
    if tags_any:
        if not any(t in card_tags for t in tags_any):
            return False
    if only_due:
        cutoff = today.date() if today else None
        if not is_due(card_review, today=cutoff):
            return False
    return True


def _exec_list_due_cards(
    args: dict[str, Any],
    *,
    vault_path: Path,
    state_store: QuizStateStore,
    client_id: str | None,
    now: datetime,
    rng: random.Random,
) -> str:
    n = int(args.get("n", 10) or 10)
    if n <= 0:
        return "error: n must be positive"
    difficulty = args.get("difficulty")
    tags_any = args.get("tags_any") if isinstance(args.get("tags_any"), list) else None
    only_due = bool(args.get("only_due", True))
    domain = str(args.get("domain", "gre"))

    vocab_dir = _domain_dir(vault_path, domain)
    if not vocab_dir.is_dir():
        return json.dumps({"error": f"no vocab dir at {vocab_dir.relative_to(vault_path)}"})

    candidates: list[tuple[str, str, str | None, tuple[str, ...], ReviewState]] = []
    for path in sorted(vocab_dir.glob("*.md")):
        # _index.md and similar bookkeeping aren't quiz cards.
        if path.stem.startswith("_"):
            continue
        try:
            card = read_card(path)
        except VocabCardError:
            continue
        if not _passes_filters(
            card.review, difficulty, tags_any, only_due, card.difficulty, card.tags, now
        ):
            continue
        rel = path.relative_to(vault_path).as_posix()
        candidates.append((rel, card.word, card.difficulty, card.tags, card.review))

    total_matched = len(candidates)
    if total_matched == 0:
        return json.dumps(
            {
                "cards": [],
                "total_matched": 0,
                "filters_applied": {
                    "difficulty": difficulty,
                    "tags_any": tags_any,
                    "only_due": only_due,
                    "domain": domain,
                },
                "note": "no cards matched; loosen filters",
            }
        )

    # Sample without replacement; deterministic-ish via injected RNG.
    # ``random.sample`` is the right tool here — quiz card selection is not
    # security-sensitive, so the S311 cryptographic-RNG nudge doesn't apply.
    take = min(n, total_matched)
    chosen = rng.sample(candidates, take)  # noqa: S311

    deck = [QuizCard(path=rel, word=word) for rel, word, _, _, _ in chosen]
    session = QuizSession(
        session_id=str(ULID()),
        client_id=client_id,
        started_at=now,
        domain=domain,
        filters={
            "difficulty": difficulty,
            "tags_any": tags_any,
            "only_due": only_due,
        },
        deck=deck,
        current_index=0,
        n_target=take,
    )
    state_store.save(session)

    return json.dumps(
        {
            "session_id": session.session_id,
            "n_target": session.n_target,
            "total_matched": total_matched,
            "filters_applied": {
                "difficulty": difficulty,
                "tags_any": tags_any,
                "only_due": only_due,
                "domain": domain,
            },
            "cards": [
                {
                    "path": rel,
                    "word": word,
                    "difficulty": diff,
                    "tags": list(tags),
                    "ease": review.ease,
                    "interval_days": review.interval_days,
                    "last_reviewed": (
                        review.last_reviewed.isoformat() if review.last_reviewed else None
                    ),
                }
                for rel, word, diff, tags, review in chosen
            ],
        }
    )


def _exec_record_review(
    args: dict[str, Any],
    *,
    vault_path: Path,
    state_store: QuizStateStore,
    now: datetime,
) -> str:
    path = args.get("path")
    grade = args.get("grade")
    if not isinstance(path, str) or not path.strip():
        return "error: record_review requires a 'path'"
    try:
        grade_i = int(grade)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"error: grade must be an integer 0-5, got {grade!r}"

    session = state_store.load()
    if session is None:
        return "error: no active quiz session; call list_due_cards first"

    # Find the card in the deck. Match by suffix so the model can send a
    # path that's slightly normalized (leading slash, etc.).
    rel = path.lstrip("/")
    idx: int | None = None
    for i, c in enumerate(session.deck):
        if c.path == rel or c.path.endswith(rel):
            idx = i
            break
    if idx is None:
        return f"error: '{path}' is not in the active deck"

    # Read the card from disk, compute the SM-2 update, write it back.
    abs_path = vault_path / session.deck[idx].path
    try:
        card = read_card(abs_path)
    except VocabCardError as exc:
        return f"error: cannot read card: {exc}"

    new_state = update(card.review, grade_i, now=now)
    try:
        write_review(abs_path, new_state)
    except VocabCardError as exc:
        return f"error: cannot write card: {exc}"

    # Update the session.
    user_answer = args.get("user_answer") if isinstance(args.get("user_answer"), str) else None
    notes = args.get("notes") if isinstance(args.get("notes"), str) else None
    session.deck[idx].asked = True
    session.deck[idx].grade = grade_i
    session.deck[idx].user_answer = user_answer

    # Advance the cursor past this card if it was current or earlier.
    if idx >= session.current_index:
        session.current_index = idx + 1

    # Transcript bullet — keeps a human-readable log in the state file.
    label = "✓" if grade_i >= 3 else "✗"
    bullet = (
        f"**{session.deck[idx].word}** — "
        f"user: {(user_answer or '(no answer)')!r} — grade {grade_i}. {label}"
    )
    if notes:
        bullet += f" — {notes}"
    append_log(session, bullet)
    state_store.save(session)

    return json.dumps(
        {
            "ok": True,
            "path": session.deck[idx].path,
            "new_ease": new_state.ease,
            "new_interval_days": new_state.interval_days,
            "next_due": (
                (new_state.last_reviewed.date().isoformat()
                 if new_state.last_reviewed and new_state.interval_days == 0
                 else None)
                if new_state.last_reviewed is None
                else None
            ),
            "session_progress": f"{session.graded_count}/{session.n_target}",
            "is_complete": session.is_complete,
        }
    )


def _exec_end_quiz_session(
    args: dict[str, Any], *, state_store: QuizStateStore
) -> str:
    reason = args.get("reason") if isinstance(args.get("reason"), str) else "completed"
    session = state_store.load()
    if session is None:
        return json.dumps({"reason": reason, "note": "no active session to close"})

    graded = [c for c in session.deck if c.grade is not None]
    n_graded = len(graded)
    n_correct = sum(1 for c in graded if (c.grade or 0) >= 3)
    accuracy = round(n_correct / n_graded, 3) if n_graded else 0.0

    # Surface weakest cards (lowest grades). Useful for "drill these next time".
    worst = sorted(graded, key=lambda c: c.grade or 0)[:3]

    state_store.clear()

    return json.dumps(
        {
            "reason": reason,
            "cards_total": len(session.deck),
            "cards_graded": n_graded,
            "cards_correct": n_correct,
            "accuracy_overall": accuracy,
            "drill_suggestion": [c.word for c in worst],
            "session_id": session.session_id,
        }
    )


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
    state_store: QuizStateStore,
    vault_path: Path,
    client_id: str | None,
    now: datetime,
    rng: random.Random,
) -> str:
    """Dispatch one tool call. Never raises — errors come back as strings."""
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
    except (json.JSONDecodeError, TypeError):
        return "error: could not parse tool arguments as JSON"

    if name == "list_due_cards":
        return _exec_list_due_cards(
            args,
            vault_path=vault_path,
            state_store=state_store,
            client_id=client_id,
            now=now,
            rng=rng,
        )
    if name == "record_review":
        return _exec_record_review(
            args, vault_path=vault_path, state_store=state_store, now=now
        )
    if name == "end_quiz_session":
        return _exec_end_quiz_session(args, state_store=state_store)
    if name == "search_vault":
        return _exec_search_vault(args, reader=reader)
    if name == "read_note":
        return _exec_read_note(args, reader=reader)
    return f"error: unknown tool '{name}'"


# --- Agent loop ----------------------------------------------------------


async def run_quiz_agent(
    *,
    ollama: OllamaClient,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any] | None,
    reader: VaultReader,
    state_store: QuizStateStore,
    vault_path: Path,
    client_id: str | None = None,
    now: datetime | None = None,
    max_steps: int = 8,
    rng: random.Random | None = None,
) -> QuizAgentResult:
    """Drive the pick→ask→grade→next loop.

    If an active session exists when the agent starts, a system message is
    prepended summarizing it — the model needs that visibility to know
    which card the user just answered. After the loop returns, the
    state-file presence flag travels back in the result so the route can
    log whether a quiz is still in progress.
    """
    actual_now = now or datetime.now().astimezone()
    # Non-crypto sampling for quiz card selection — S311 doesn't apply.
    actual_rng = rng or random.Random()  # noqa: S311

    convo: list[dict[str, Any]] = list(messages)

    # Inject the active-session summary so the model sees the live state.
    existing = state_store.load()
    if existing is not None and not existing.is_complete:
        convo.append({"role": "system", "content": _state_summary(existing)})

    token_counts: TokenCounts | None = None
    tool_calls_made = 0

    for step in range(1, max_steps + 1):
        resp = await ollama.chat(
            model=model, messages=convo, options=options, tools=QUIZ_TOOLS
        )
        token_counts = _usage_from(resp) or token_counts
        message = resp["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return QuizAgentResult(
                content=message.get("content") or "",
                steps=step,
                tool_calls_made=tool_calls_made,
                token_counts=token_counts,
                session_active=state_store.exists(),
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
                state_store=state_store,
                vault_path=vault_path,
                client_id=client_id,
                now=actual_now,
                rng=actual_rng,
            )
            convo.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
            )

    # Budget exhausted — force a final answer with tools withheld so the
    # model concludes from what it has. Matches the vault-agent fallback.
    convo.append(
        {
            "role": "user",
            "content": "Answer now using the cards you've handled. Do not call any more tools.",
        }
    )
    final = await ollama.chat(model=model, messages=convo, options=options)
    token_counts = _usage_from(final) or token_counts
    return QuizAgentResult(
        content=final["choices"][0]["message"].get("content") or "",
        steps=max_steps,
        tool_calls_made=tool_calls_made,
        token_counts=token_counts,
        session_active=state_store.exists(),
    )
