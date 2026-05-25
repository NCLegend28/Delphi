"""Task-type → model roster.

Per-task sampling options and notes live here in code (``TASK_METADATA``);
the model tag for each task is read from ``Config`` at boot via
``Roster.from_config``. This lets ``.env`` evolve the active model per task
without code changes — see ``config.delphi_model_*``.

``resolve()`` is the only function callers should use — it returns the model
name and any per-task default sampling options. The classifier and the
request handler both depend on this module being the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from config import Config

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


# Fixed per-task metadata (sampling options + human notes). The *model* for
# each task is env-driven — see ``_FALLBACK_MODELS`` and ``Roster.from_config``.
TASK_METADATA: dict[str, tuple[dict[str, Any], str]] = {
    "chat": ({"temperature": 0.7}, "default; general conversation"),
    "code": ({"temperature": 0.2}, "every coding task"),
    "reason": ({"temperature": 0.3}, "math, debugging logic, proofs"),
    "multilingual": ({"temperature": 0.6}, "EN<->ES code-switching, prose"),
    "deep_code": ({"temperature": 0.2}, "slow but capable; CPU+GPU split"),
    "deep_reason": ({"temperature": 0.3}, "hard reasoning; CPU+GPU split"),
    "vault_query": (
        {"temperature": 0.4},
        "answering 'do I have notes on X' style questions",
    ),
}


# Fallback model tags used when no ``Config`` is supplied (tests, ad-hoc
# scripts). Production builds the roster from env via ``Roster.from_config``.
_FALLBACK_MODELS: dict[str, str] = {
    "chat": "phi4:14b",
    "code": "qwen2.5-coder:14b",
    "reason": "deepseek-r1:14b",
    "multilingual": "gemma3:12b",
    "deep_code": "qwen2.5-coder:32b",
    "deep_reason": "deepseek-r1:32b",
    "vault_query": "phi4:14b",
}


def _build_entries(models: Mapping[str, str]) -> dict[str, RosterEntry]:
    """Combine env-driven model tags with the fixed per-task metadata."""
    missing = set(TASK_TYPES) - set(models)
    if missing:
        raise ValueError(f"roster build missing models for: {sorted(missing)}")
    return {
        task: RosterEntry(model=models[task], options=opts, notes=notes)
        for task, (opts, notes) in TASK_METADATA.items()
    }


ROSTER: dict[str, RosterEntry] = _build_entries(_FALLBACK_MODELS)


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
    arguments to use the canonical ``ROSTER`` (env-independent fallback
    tags); ``Roster.from_config(cfg)`` builds one from ``Config``.
    """

    def __init__(self, entries: dict[str, RosterEntry] | None = None) -> None:
        self._entries: dict[str, RosterEntry] = entries if entries is not None else ROSTER
        self._reverse: dict[str, str] = {
            entry.model: task for task, entry in self._entries.items()
        }

    @classmethod
    def from_config(cls, cfg: "Config") -> "Roster":
        """Build a roster whose model tags are pulled from ``cfg``.

        Per-task sampling options and notes come from ``TASK_METADATA``;
        only the model tag is env-driven. This is the production path —
        ``main.py`` calls it at boot so swapping a model is one ``.env``
        line + an ``ollama pull`` + a restart.
        """
        models = {
            "chat": cfg.delphi_model_chat,
            "code": cfg.delphi_model_code,
            "reason": cfg.delphi_model_reason,
            "multilingual": cfg.delphi_model_multilingual,
            "deep_code": cfg.delphi_model_deep_code,
            "deep_reason": cfg.delphi_model_deep_reason,
            "vault_query": cfg.delphi_model_vault_query,
        }
        return cls(_build_entries(models))

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
