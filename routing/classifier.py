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
        + ". Reply with ONLY a JSON object — no prose, no code fences — with keys: "
        '"task_type" (one of the listed types), "confidence" (0.0-1.0), '
        '"project" (the name of a project the user referenced, or null). '
        "Use 'code' for any programming task, 'deep_code' only when the message asks "
        "for a substantial refactor or architecture. Use 'reason' for math, debugging "
        "logic, or proofs. Use 'multilingual' only when the message mixes languages. "
        "Use 'vault_query' when the user asks what they already know about something."
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
