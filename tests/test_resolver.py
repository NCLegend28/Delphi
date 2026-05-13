"""Tests for ``routing/resolver.py``.

Pure async — no network, no respx. Classifier and roster are stubbed so we
can assert exactly when classifier is and isn't called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from routing.classifier import ClassifyResult
from routing.resolver import ResolvedModel, resolve_model
from routing.roster import DEFAULT_TASK_TYPE, Roster, RosterEntry


# --- stand-ins ------------------------------------------------------------


@dataclass
class StubClassifier:
    """Test double: records every call and returns a canned ``ClassifyResult``."""

    result: ClassifyResult
    calls: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    async def classify(self, user_message: str) -> ClassifyResult:
        self.calls.append(user_message)
        return self.result


def _roster() -> Roster:
    """Small deterministic roster for resolver tests."""
    return Roster(
        {
            "chat": RosterEntry(model="phi4:14b"),
            "code": RosterEntry(model="qwen2.5-coder:14b"),
            "reason": RosterEntry(model="deepseek-r1:14b"),
        }
    )


def _classifier(task_type: str = "chat", confidence: float = 0.8) -> StubClassifier:
    return StubClassifier(result=ClassifyResult(task_type=task_type, confidence=confidence))


def _msgs(user: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": user}]


# --- tests ----------------------------------------------------------------


async def test_explicit_model_skips_classifier() -> None:
    clf = _classifier()
    resolved = await resolve_model({"model": "qwen2.5-coder:14b"}, clf, _roster())
    assert resolved == ResolvedModel(
        model="qwen2.5-coder:14b",
        task_type="code",  # via reverse lookup
        source="explicit_model",
    )
    assert clf.calls == [], "classifier must not be called when model is explicit"


async def test_explicit_model_unknown_to_roster() -> None:
    """An experimental tag the roster has never seen: task defaults, source unchanged."""
    clf = _classifier()
    resolved = await resolve_model({"model": "experimental:7b"}, clf, _roster())
    assert resolved.model == "experimental:7b"
    assert resolved.task_type == DEFAULT_TASK_TYPE
    assert resolved.source == "explicit_model"
    assert clf.calls == []


async def test_explicit_task_type() -> None:
    clf = _classifier()
    resolved = await resolve_model({"task_type": "code"}, clf, _roster())
    assert resolved == ResolvedModel(
        model="qwen2.5-coder:14b",
        task_type="code",
        source="explicit_task",
    )
    assert clf.calls == []


async def test_explicit_task_type_unknown() -> None:
    """Bogus explicit task → treated as if absent → classifier path."""
    clf = _classifier(task_type="reason", confidence=0.9)
    resolved = await resolve_model(
        {"task_type": "haiku", "messages": _msgs("prove a thing")}, clf, _roster()
    )
    assert resolved.source == "classified"
    assert resolved.model == "deepseek-r1:14b"
    assert resolved.task_type == "reason"
    assert clf.calls == ["prove a thing"]


async def test_auto_calls_classifier() -> None:
    clf = _classifier(task_type="code", confidence=0.92)
    resolved = await resolve_model(
        {"task_type": "auto", "messages": _msgs("refactor this loop")}, clf, _roster()
    )
    assert resolved.source == "classified"
    assert resolved.model == "qwen2.5-coder:14b"
    assert resolved.classifier_result == ClassifyResult(task_type="code", confidence=0.92)
    assert clf.calls == ["refactor this loop"]


async def test_no_fields_calls_classifier() -> None:
    clf = _classifier(task_type="chat", confidence=0.7)
    resolved = await resolve_model({"messages": _msgs("hello")}, clf, _roster())
    assert resolved.source == "classified"
    assert resolved.task_type == "chat"
    assert clf.calls == ["hello"]


async def test_no_user_message() -> None:
    """No user message → classifier still called, with empty string."""
    clf = _classifier(task_type="chat", confidence=0.0)
    resolved = await resolve_model(
        {"messages": [{"role": "system", "content": "you are nice"}]}, clf, _roster()
    )
    assert resolved.source == "classified"
    assert clf.calls == [""]


async def test_classifier_low_confidence() -> None:
    """Classifier returns default at 0.0 confidence → still source='classified'."""
    clf = _classifier(task_type=DEFAULT_TASK_TYPE, confidence=0.0)
    resolved = await resolve_model({"messages": _msgs("???")}, clf, _roster())
    assert resolved.source == "classified"
    assert resolved.task_type == DEFAULT_TASK_TYPE
    assert resolved.classifier_result is not None
    assert resolved.classifier_result.confidence == 0.0


# --- bonus: edge cases worth pinning -------------------------------------


async def test_empty_string_model_is_treated_as_absent() -> None:
    clf = _classifier(task_type="chat")
    resolved = await resolve_model(
        {"model": "   ", "messages": _msgs("hi")}, clf, _roster()
    )
    assert resolved.source == "classified"
    assert clf.calls == ["hi"]


async def test_resolved_model_is_immutable() -> None:
    """``frozen=True, slots=True`` is part of the contract — pin it."""
    clf = _classifier()
    resolved = await resolve_model({"model": "phi4:14b"}, clf, _roster())
    with pytest.raises((AttributeError, Exception)):
        resolved.model = "other"  # type: ignore[misc]
