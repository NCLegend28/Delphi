"""Tiny-model classifier: maps a user message to a roster task type.

Calls Ollama (default ``phi3.5:3.8b``) with a short prompt that asks
for a one-shot JSON answer: ``{"task_type": ..., "confidence": ..., "project": ...}``.

The classifier is advisory. If the client sent an explicit ``model`` or
``task_type``, the caller skips us. If we fail or return an unknown task,
the caller falls back to ``DEFAULT_TASK_TYPE``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from proxy.ollama_client import OllamaClient, OllamaError
from routing.roster import DEFAULT_TASK_TYPE, TASK_TYPES

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ClassifyResult:
    """What the classifier returns: a task type, a confidence, and a project hint.

    ``project`` is a name the user referenced (e.g. "AgentRig"); resolving it
    against ``projects/*.md`` happens in the memory layer, not here.
    """

    task_type: str
    confidence: float
    project: str | None = None


def _system_prompt() -> str:
    return (
        "You classify a user's chat message into one of these task types: "
        + ", ".join(TASK_TYPES)
        + '. Reply with ONLY a JSON object — no prose, no code fences — with keys: '
        '"task_type" (one of the listed types), "confidence" (0.0-1.0), '
        '"project" (the name of a project the user referenced, or null).\n'
        "\n"
        "Rubric:\n"
        "- 'code' — any programming task: write, fix, refactor, explain code.\n"
        "- 'deep_code' — substantial refactor, multi-file design, architecture.\n"
        "- 'reason' — math, proofs, debugging logic, step-by-step deduction.\n"
        "- 'deep_reason' — hard reasoning that needs a long, careful chain.\n"
        "- 'multilingual' — the message mixes languages (e.g. English ↔ Spanish).\n"
        "- 'vault_query' — the answer should come from the user's own notes. "
        "This covers (a) lookups about anything the user has likely stored "
        "(GRE vocabulary, study material, personal projects, prior decisions), "
        "(b) meta-prompts like 'help me study X' / 'what do I have on Z' "
        "that imply consulting curated knowledge, and "
        "(c) explicit asks like 'check my vault' or 'look in my notes'.\n"
        "- 'gre_quiz' — an *interactive vocab drill* over the user's GRE "
        "knowledge base. Distinct from vault_query: vault_query answers ONE "
        "question against the notes; gre_quiz runs a multi-turn ask-grade-"
        "advance loop. Triggers: 'quiz me', 'drill me', 'give me a quiz', "
        "'run me through N words', 'start a vocab review', 'test me on hard "
        "words'. Vague phrasings like 'give me a quiz on my GREs' default "
        "to this bucket — the drill is the right answer when intent is "
        "ambiguous between drill and full-test. Mid-session user replies "
        "('next', 'stop', short definitions) also stay here.\n"
        "- 'gre_practice_test' — a *full mock-exam style test*: multi-section, "
        "multi-question, generated as a structured document the user fills "
        "out and submits for two-model grading. Triggers must be explicit: "
        "'practice test', 'mock exam', 'full practice section', 'simulate a "
        "GRE section', 'generate a test', 'grade my answers'. NOT triggered "
        "by 'quiz me' (that's the drill above).\n"
        "- 'chat' — default for general conversation that fits no other type.\n"
        "\n"
        "Examples (message → task_type):\n"
        '  "refactor this Python function" → code\n'
        '  "redesign the auth layer across services" → deep_code\n'
        '  "prove that sqrt(2) is irrational" → reason\n'
        '  "what does perspicacious mean?" → vault_query\n'
        '  "define laconic" → vault_query\n'
        '  "help me with my GRE vocabulary" → vault_query\n'
        '  "do I have notes on permutations vs combinations?" → vault_query\n'
        '  "what was the decision we made about the memory layer?" → vault_query\n'
        '  "check my vault for anything on FinBERT" → vault_query\n'
        '  "quiz me on 10 hard GRE words" → gre_quiz\n'
        '  "drill me on canonical GRE vocab" → gre_quiz\n'
        '  "run me through some vocab cards" → gre_quiz\n'
        '  "start a vocab review session" → gre_quiz\n'
        "  \"test me on hard words I haven't seen\" → gre_quiz\n"
        '  "can you give me a quiz on my GREs" → gre_quiz\n'
        '  "let\'s run some drills" → gre_quiz\n'
        '  "give me a 10-question GRE practice test" → gre_practice_test\n'
        '  "generate a GRE mock exam" → gre_practice_test\n'
        '  "I want a full practice section, verbal heavy" → gre_practice_test\n'
        '  "grade my answers" → gre_practice_test\n'
        '  "simulate a GRE verbal section" → gre_practice_test\n'
        '  "¿cómo se dice perspicacious en español?" → multilingual\n'
        '  "hey, how are you" → chat\n'
    )


def _extract_json(raw: str) -> dict[str, object] | None:
    """Pull the first ``{...}`` block out of the model's reply and parse it."""
    match = _JSON_BLOCK.search(raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _coerce(parsed: dict[str, object]) -> ClassifyResult:
    """Validate the parsed JSON. Unknown task → fallback. Bad confidence → 0.0."""
    raw_task = parsed.get("task_type")
    task_type = raw_task if isinstance(raw_task, str) and raw_task in TASK_TYPES else DEFAULT_TASK_TYPE

    raw_conf = parsed.get("confidence")
    try:
        confidence = float(raw_conf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    raw_project = parsed.get("project")
    project = raw_project if isinstance(raw_project, str) and raw_project.strip() else None

    return ClassifyResult(task_type=task_type, confidence=confidence, project=project)


class Classifier:
    """Wraps an ``OllamaClient`` and a small model tag."""

    def __init__(self, ollama: OllamaClient, model: str) -> None:
        self._ollama = ollama
        self._model = model

    async def classify(self, user_message: str) -> ClassifyResult:
        """Classify a single user message. Never raises — failures degrade gracefully."""
        try:
            response = await self._ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_message},
                ],
                options={"temperature": 0.0},
            )
        except OllamaError:
            return ClassifyResult(task_type=DEFAULT_TASK_TYPE, confidence=0.0)

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ClassifyResult(task_type=DEFAULT_TASK_TYPE, confidence=0.0)

        parsed = _extract_json(content) if isinstance(content, str) else None
        if parsed is None:
            return ClassifyResult(task_type=DEFAULT_TASK_TYPE, confidence=0.0)

        return _coerce(parsed)
