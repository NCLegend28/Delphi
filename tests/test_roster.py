"""Pure unit tests for ``routing/roster.py`` and ``routing/soul.py``.

No network. These guard the invariants that the rest of the system depends on:
every task type maps to a model, the soul is non-empty, and the coding
appendix is appended (never replacing) the base soul.
"""

from __future__ import annotations

import pytest

from routing import roster
from routing.soul import BASE_SOUL, CODING_APPENDIX, CODING_TASK_TYPES, soul_for


# --- roster ---------------------------------------------------------------


def test_every_task_type_has_a_roster_entry() -> None:
    for task_type in roster.TASK_TYPES:
        entry = roster.resolve(task_type)
        assert entry.model, f"{task_type} has no model"


def test_resolve_unknown_task_type_raises_typed_error() -> None:
    with pytest.raises(roster.UnknownTaskType):
        roster.resolve("not-a-real-task")


def test_default_task_type_is_resolvable() -> None:
    roster.resolve(roster.DEFAULT_TASK_TYPE)


def test_all_models_includes_every_distinct_roster_model() -> None:
    expected = {entry.model for entry in roster.ROSTER.values()}
    assert set(roster.all_models()) == expected


def test_classifier_model_default_is_a_nonempty_tag() -> None:
    assert ":" in roster.CLASSIFIER_MODEL_DEFAULT


# --- soul -----------------------------------------------------------------


def test_base_soul_is_nonempty() -> None:
    assert BASE_SOUL.strip()


def test_coding_appendix_is_nonempty() -> None:
    assert CODING_APPENDIX.strip()


def test_soul_for_chat_returns_base_only() -> None:
    assert soul_for("chat") == BASE_SOUL


def test_soul_for_code_appends_coding_block() -> None:
    out = soul_for("code")
    assert out.startswith(BASE_SOUL), "coding tasks must keep the base soul intact"
    assert out.endswith(CODING_APPENDIX), "coding appendix must be appended last"


def test_soul_for_deep_code_appends_coding_block() -> None:
    assert soul_for("deep_code").endswith(CODING_APPENDIX)


def test_soul_for_unknown_task_type_falls_back_to_base() -> None:
    assert soul_for("never-heard-of-it") == BASE_SOUL


def test_coding_task_types_are_a_subset_of_known_task_types() -> None:
    assert CODING_TASK_TYPES.issubset(set(roster.TASK_TYPES))
