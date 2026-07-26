"""Tests for durable nursery JSONL records."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nursery.records import (
    ChildAttemptRecord,
    EvaluationSummary,
    NurseryPromptRecord,
    ParentCritiqueRecord,
    assert_no_secret_fields,
)


def test_child_attempt_round_trips_as_deterministic_json() -> None:
    record = ChildAttemptRecord(
        task_type="code",
        candidate="qwen2.5-coder-7b-q4",
        prompt_id="code-debug-1",
        prompt="Fix this failing pytest test.",
        child_output="The issue is an off-by-one assertion.",
        parent_score=0.82,
        parent_passed=True,
        rubric_notes="Correct and concise.",
        failure_modes=[],
        repair=None,
    )

    dumped = record.to_json_line()
    loaded = ChildAttemptRecord.model_validate_json(dumped)

    assert loaded == record
    assert dumped == record.to_json_line()
    assert dumped.endswith("\n")


def test_scores_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        ParentCritiqueRecord(
            score=1.2,
            passed=False,
            rubric_notes="out of range",
            failure_modes=[],
            repair=None,
        )

    with pytest.raises(ValidationError):
        EvaluationSummary(
            candidate="phi-3.5-mini-q6",
            task_type="chat",
            mean_score=-0.1,
            pass_rate=0.9,
            total=10,
        )


def test_child_attempt_contains_required_evaluation_fields() -> None:
    record = ChildAttemptRecord(
        task_type="vault_query",
        candidate="phi-3.5-mini-q6",
        prompt_id="vault-ground-1",
        prompt="Do I have notes on symbolic regression?",
        child_output="I should search first.",
        parent_score=0.5,
        parent_passed=False,
        rubric_notes="Did not cite note titles.",
        failure_modes=["missing_grounding"],
        repair="Search the vault before answering.",
    )
    payload = json.loads(record.to_json_line())

    required_fields = (
        "task_type",
        "candidate",
        "prompt",
        "child_output",
        "parent_score",
        "rubric_notes",
    )
    for field in required_fields:
        assert field in payload


def test_serialized_records_do_not_expose_secret_named_fields() -> None:
    records = [
        NurseryPromptRecord(
            id="chat-1",
            task_type="chat",
            prompt="Say hello.",
            rubric="Be brief.",
            failure_modes=["verbose"],
        ),
        ChildAttemptRecord(
            task_type="chat",
            candidate="llama-3.2-3b-q6",
            prompt_id="chat-1",
            prompt="Say hello.",
            child_output="Hello.",
            parent_score=1.0,
            parent_passed=True,
            rubric_notes="ok",
            failure_modes=[],
            repair=None,
        ),
        ParentCritiqueRecord(
            score=1.0,
            passed=True,
            rubric_notes="ok",
            failure_modes=[],
            repair=None,
        ),
        EvaluationSummary(
            candidate="llama-3.2-3b-q6",
            task_type="chat",
            mean_score=1.0,
            pass_rate=1.0,
            total=1,
        ),
    ]

    for record in records:
        payload = json.loads(record.to_json_line())
        assert_no_secret_fields(payload)


def test_prompt_record_requires_failure_modes() -> None:
    with pytest.raises(ValidationError, match="failure mode"):
        NurseryPromptRecord(
            id="bad",
            task_type="chat",
            prompt="Hi",
            rubric="Answer",
            failure_modes=[],
        )
