"""Tests for the parallel two-model grading primitive."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from memory.cross_grade import (
    CrossGradeError,
    _parse_grader_response,
    _reconcile_one,
    cross_grade,
)
from memory.practice_test import AnswerKey, PracticeTest, Section


def _make_test(answers_key: dict[str, AnswerKey]) -> PracticeTest:
    return PracticeTest(
        test_id="01HXTEST",
        created=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
        sections=[Section(kind="text_completion", n=len(answers_key))],
        n_questions=len(answers_key),
        sources={},
        answer_key=answers_key,
        body="",
    )


# --- _parse_grader_response ----------------------------------------------


def test_parse_valid_response():
    out = _parse_grader_response(
        {"q1": {"grade": "correct", "reasoning": "B fits"}, "q2": {"grade": "wrong", "reasoning": "no"}}
    )
    assert out == {"q1": {"grade": "correct", "reasoning": "B fits"}, "q2": {"grade": "wrong", "reasoning": "no"}}


def test_parse_rejects_invalid_grade():
    out = _parse_grader_response({"q1": {"grade": "amazing", "reasoning": "..."}})
    assert out is None


def test_parse_rejects_missing_grade():
    out = _parse_grader_response({"q1": {"reasoning": "..."}})
    assert out is None


def test_parse_rejects_non_dict_entry():
    out = _parse_grader_response({"q1": "correct"})
    assert out is None


def test_parse_defaults_missing_reasoning():
    out = _parse_grader_response({"q1": {"grade": "correct"}})
    assert out == {"q1": {"grade": "correct", "reasoning": ""}}


# --- _reconcile_one ------------------------------------------------------


def test_reconcile_both_agree():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="B", rubric="..."),
        "B",
        {"grade": "correct", "reasoning": "B matches"},
        {"grade": "correct", "reasoning": "agreed"},
    )
    assert g.grade == "correct"
    assert g.disagreement is None
    assert g.primary_reasoning == "B matches"
    assert g.secondary_reasoning == "agreed"


def test_reconcile_disagreement_keeps_primary_grade_with_note():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="B", rubric="..."),
        "B",
        {"grade": "correct", "reasoning": "B matches"},
        {"grade": "partial", "reasoning": "not full"},
    )
    assert g.grade == "correct"
    assert g.disagreement is not None
    assert "primary" in g.disagreement.lower()
    assert "secondary" in g.disagreement.lower()


def test_reconcile_only_primary():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="B"),
        "B",
        {"grade": "correct", "reasoning": "B"},
        None,
    )
    assert g.grade == "correct"
    assert g.secondary_reasoning == ""
    assert g.disagreement is None


def test_reconcile_only_secondary():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="B"),
        "B",
        None,
        {"grade": "correct", "reasoning": "B"},
    )
    assert g.grade == "correct"
    assert g.primary_reasoning == ""
    assert g.disagreement is None


def test_reconcile_neither_falls_back_to_mechanical():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="B"),
        "B",  # mechanical = correct
        None,
        None,
    )
    assert g.grade == "correct"  # mechanical agreed
    assert g.disagreement is not None
    assert "fall" in g.disagreement.lower()


def test_reconcile_records_mechanical_grade():
    g = _reconcile_one(
        "q1",
        AnswerKey(answer="A"),
        "B",  # mechanical = wrong
        {"grade": "correct", "reasoning": "..."},
        {"grade": "correct", "reasoning": "..."},
    )
    # Models agreed it's correct; mechanical disagrees but we surface both.
    assert g.grade == "correct"
    assert g.mechanical_grade == "wrong"


# --- cross_grade (integration with mocked OllamaClient) ------------------


class ScriptedOllama:
    """Per-model scripted responses for cross-grade."""

    def __init__(self, responses_by_model):
        self._responses = dict(responses_by_model)
        self.calls = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"model": model, "messages": messages})
        return self._responses[model]


def _ollama_reply(payload: dict):
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30},
    }


async def test_cross_grade_both_agree():
    test = _make_test(
        {"q1": AnswerKey(answer="B"), "q2": AnswerKey(answer=["B", "D"])}
    )
    ollama = ScriptedOllama(
        {
            "primary:1": _ollama_reply(
                {
                    "q1": {"grade": "correct", "reasoning": "B"},
                    "q2": {"grade": "correct", "reasoning": "B+D"},
                }
            ),
            "secondary:1": _ollama_reply(
                {
                    "q1": {"grade": "correct", "reasoning": "agree"},
                    "q2": {"grade": "correct", "reasoning": "agree"},
                }
            ),
        }
    )
    result = await cross_grade(
        ollama=ollama,
        primary_model="primary:1",
        secondary_model="secondary:1",
        test=test,
        answers={"q1": "B", "q2": ["B", "D"]},
    )
    assert result.score_correct == 2
    assert result.score_total == 2
    assert result.primary_grader == "primary:1"
    assert result.secondary_grader == "secondary:1"
    assert all(g.disagreement is None for g in result.graded)
    # Both calls made in parallel.
    assert len(ollama.calls) == 2


async def test_cross_grade_disagreement_is_surfaced():
    test = _make_test({"q1": AnswerKey(answer="B")})
    ollama = ScriptedOllama(
        {
            "p:1": _ollama_reply({"q1": {"grade": "correct", "reasoning": "B fits"}}),
            "s:1": _ollama_reply({"q1": {"grade": "wrong", "reasoning": "no"}}),
        }
    )
    result = await cross_grade(
        ollama=ollama, primary_model="p:1", secondary_model="s:1",
        test=test, answers={"q1": "B"},
    )
    assert result.graded[0].disagreement is not None
    assert result.graded[0].grade == "correct"  # primary wins headline


async def test_cross_grade_secondary_failure_degrades_gracefully():
    test = _make_test({"q1": AnswerKey(answer="B")})
    ollama = ScriptedOllama(
        {
            "p:1": _ollama_reply({"q1": {"grade": "correct", "reasoning": "B"}}),
            "s:1": {"choices": [{"message": {"content": "no json here"}}]},
        }
    )
    result = await cross_grade(
        ollama=ollama, primary_model="p:1", secondary_model="s:1",
        test=test, answers={"q1": "B"},
    )
    assert result.secondary_grader is None
    assert result.primary_grader == "p:1"
    assert result.graded[0].grade == "correct"


async def test_cross_grade_primary_failure_promotes_secondary():
    test = _make_test({"q1": AnswerKey(answer="B")})
    ollama = ScriptedOllama(
        {
            "p:1": {"choices": [{"message": {"content": "garbage"}}]},
            "s:1": _ollama_reply({"q1": {"grade": "correct", "reasoning": "B"}}),
        }
    )
    result = await cross_grade(
        ollama=ollama, primary_model="p:1", secondary_model="s:1",
        test=test, answers={"q1": "B"},
    )
    # Secondary stood in for primary; recorded as the primary grader so the
    # take doesn't lie about which model produced the headline grade.
    assert result.primary_grader == "s:1"
    assert result.secondary_grader is None


async def test_cross_grade_both_fail_raises():
    test = _make_test({"q1": AnswerKey(answer="B")})
    ollama = ScriptedOllama(
        {
            "p:1": {"choices": [{"message": {"content": "garbage"}}]},
            "s:1": {"choices": [{"message": {"content": "more garbage"}}]},
        }
    )
    with pytest.raises(CrossGradeError):
        await cross_grade(
            ollama=ollama, primary_model="p:1", secondary_model="s:1",
            test=test, answers={"q1": "B"},
        )


async def test_cross_grade_single_grader_mode():
    test = _make_test({"q1": AnswerKey(answer="B")})
    ollama = ScriptedOllama(
        {"p:1": _ollama_reply({"q1": {"grade": "correct", "reasoning": "B"}})}
    )
    result = await cross_grade(
        ollama=ollama, primary_model="p:1", secondary_model=None,
        test=test, answers={"q1": "B"},
    )
    assert result.primary_grader == "p:1"
    assert result.secondary_grader is None
    assert len(ollama.calls) == 1


async def test_cross_grade_missing_user_answer_marks_wrong():
    test = _make_test({"q1": AnswerKey(answer="B"), "q2": AnswerKey(answer="A")})
    ollama = ScriptedOllama(
        {
            "p:1": _ollama_reply(
                {
                    "q1": {"grade": "correct", "reasoning": "B"},
                    "q2": {"grade": "wrong", "reasoning": "no answer"},
                }
            ),
            "s:1": _ollama_reply(
                {
                    "q1": {"grade": "correct", "reasoning": "agree"},
                    "q2": {"grade": "wrong", "reasoning": "agree"},
                }
            ),
        }
    )
    # User only answered q1.
    result = await cross_grade(
        ollama=ollama, primary_model="p:1", secondary_model="s:1",
        test=test, answers={"q1": "B"},
    )
    assert result.score_correct == 1
    assert result.score_total == 2
