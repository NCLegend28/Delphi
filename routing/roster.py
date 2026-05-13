"""Task-type → model roster.

Edit the ``ROSTER`` constant to add or swap models. ``resolve()`` is the only
function callers should use — it returns the model name and any per-task
default sampling options. The classifier and the request handler both depend
on this module being the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Canonical set of task types. The classifier must produce one of these.
TASK_TYPES: tuple[str, ...] = (
    "chat",
    "code",
    "reason",
    "multilingual",
    "deep_code",
    "deep_reason",
    "vault_query",
)


@dataclass(frozen=True)
class RosterEntry:
    """One row in the roster: which model handles a task, and how to sample it."""

    model: str
    options: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


ROSTER: dict[str, RosterEntry] = {
    "chat": RosterEntry(
        model="phi4:14b",
        options={"temperature": 0.7},
        notes="default; general conversation",
    ),
    "code": RosterEntry(
        model="qwen2.5-coder:14b",
        options={"temperature": 0.2},
        notes="every coding task",
    ),
    "reason": RosterEntry(
        model="deepseek-r1:14b",
        options={"temperature": 0.3},
        notes="math, debugging logic, proofs",
    ),
    "multilingual": RosterEntry(
        model="gemma3:12b",
        options={"temperature": 0.6},
        notes="EN<->ES code-switching, prose",
    ),
    "deep_code": RosterEntry(
        model="qwen2.5-coder:32b",
        options={"temperature": 0.2},
        notes="slow but capable; CPU+GPU split",
    ),
    "deep_reason": RosterEntry(
        model="deepseek-r1:32b",
        options={"temperature": 0.3},
        notes="hard reasoning; CPU+GPU split",
    ),
    "vault_query": RosterEntry(
        model="phi4:14b",
        options={"temperature": 0.4},
        notes="answering 'do I have notes on X' style questions",
    ),
}


# The classifier itself runs through Ollama too. Pinned, not part of ROSTER.
CLASSIFIER_MODEL_DEFAULT = "phi3.5:3.8b"

# Fallback when classification fails or is disabled and the client sent no model.
DEFAULT_TASK_TYPE = "chat"


class UnknownTaskType(KeyError):
    """Raised when a task type isn't in the roster."""


def resolve(task_type: str) -> RosterEntry:
    """Look up the roster entry for ``task_type``.

    Raises ``UnknownTaskType`` rather than ``KeyError`` so callers can catch
    a domain-specific exception and decide whether to fall back to the default.
    """
    try:
        return ROSTER[task_type]
    except KeyError as exc:
        raise UnknownTaskType(task_type) from exc


def all_models() -> list[str]:
    """Every distinct model name in the roster. Used at boot to verify Ollama tags."""
    return sorted({entry.model for entry in ROSTER.values()})


class Roster:
    """Thin object wrapper around the roster dict.

    Exists so callers (notably the resolver) can be unit-tested with a
    custom roster instead of the module-level singleton. Construct with no
    arguments to use the canonical ``ROSTER``.
    """

    def __init__(self, entries: dict[str, RosterEntry] | None = None) -> None:
        self._entries: dict[str, RosterEntry] = entries if entries is not None else ROSTER
        self._reverse: dict[str, str] = {
            entry.model: task for task, entry in self._entries.items()
        }

    def lookup(self, task_type: str) -> RosterEntry | None:
        """Forward lookup: task type → roster entry. ``None`` if unknown."""
        return self._entries.get(task_type)

    def reverse_lookup(self, model: str) -> str | None:
        """Reverse lookup: model tag → task type. ``None`` if not in roster."""
        return self._reverse.get(model)

    def all_models(self) -> list[str]:
        return sorted({entry.model for entry in self._entries.values()})

    def task_types(self) -> list[str]:
        return list(self._entries.keys())

    def items(self) -> list[tuple[str, RosterEntry]]:
        """``(task_type, entry)`` pairs in roster declaration order."""
        return list(self._entries.items())
