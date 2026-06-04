"""Tests for the practice-test storage module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.practice_test import (
    AnswerKey,
    PracticeTest,
    PracticeTestError,
    PracticeTestStore,
    Section,
    Take,
    compare_answers,
    normalize_answer,
)


def _fresh_test(**overrides) -> PracticeTest:
    defaults = dict(
        test_id="01HXPQ9TEST",
        created=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
        sections=[
            Section(kind="text_completion", n=2),
            Section(kind="problem_solving", n=1),
        ],
        n_questions=3,
        sources={"vocab": ["knowledge/gre/vocab/abjure.md"], "quant": []},
        answer_key={
            "q1": AnswerKey(answer="B", rubric="B = conciliatory"),
            "q2": AnswerKey(answer=["B", "D"], rubric="monotonous + tedious"),
            "q3": AnswerKey(answer="3", rubric="3x - 7 = 2 → x = 3"),
        },
        body=(
            "# GRE Practice Test\n\n"
            "## Text Completion\n\n"
            "1. The committee's decision was **___**.\n"
            "   - (A) ambiguous (B) conciliatory (C) obstinate\n\n"
            "2. The lecture was so **___** ...\n"
            "   - (A) stimulating (B) monotonous (C) invigorating (D) tedious\n\n"
            "## Problem Solving\n\n"
            "3. If 3x - 7 = 2, what is x?\n"
        ),
        takes=[],
    )
    defaults.update(overrides)
    return PracticeTest(**defaults)


# --- save / load round-trip ---------------------------------------------


def test_save_creates_tests_dir_and_writes(tmp_path):
    store = PracticeTestStore(tmp_path)
    test = _fresh_test()
    path = store.save(test)
    assert path.exists()
    assert path == tmp_path / "knowledge" / "gre" / "practice-tests" / "01HXPQ9TEST.md"


def test_round_trip_preserves_fields(tmp_path):
    store = PracticeTestStore(tmp_path)
    test = _fresh_test()
    store.save(test)
    loaded = store.load("01HXPQ9TEST")
    assert loaded is not None
    assert loaded.test_id == test.test_id
    assert loaded.n_questions == 3
    assert loaded.answer_key["q1"].answer == "B"
    assert loaded.answer_key["q2"].answer == ["B", "D"]
    assert loaded.answer_key["q2"].rubric == "monotonous + tedious"
    assert loaded.sections[0].kind == "text_completion"
    assert loaded.sections[0].n == 2
    assert "committee's decision" in loaded.body


def test_load_returns_none_when_missing(tmp_path):
    store = PracticeTestStore(tmp_path)
    assert store.load("does-not-exist") is None


def test_load_raises_on_malformed_yaml(tmp_path):
    store = PracticeTestStore(tmp_path)
    bad = store.path_for("bad")
    bad.parent.mkdir(parents=True)
    bad.write_text("---\nnot: valid: yaml: [\n---\n", encoding="utf-8")
    with pytest.raises(PracticeTestError):
        store.load("bad")


def test_load_raises_on_missing_test_id(tmp_path):
    store = PracticeTestStore(tmp_path)
    bad = store.path_for("nope")
    bad.parent.mkdir(parents=True)
    bad.write_text("---\ncreated: 2026-06-03T10:00:00+00:00\n---\nbody\n", encoding="utf-8")
    with pytest.raises(PracticeTestError):
        store.load("nope")


# --- takes append --------------------------------------------------------


def _take(n: int = 1, correct: int = 3) -> Take:
    return Take(
        take_n=n,
        submitted_at=datetime(2026, 6, 3, 10, 30, tzinfo=timezone.utc),
        primary_grader="gpt-oss:120b-cloud",
        secondary_grader="deepseek-v3.1:671b-cloud",
        answers={"q1": "B", "q2": ["B", "D"], "q3": "3"},
        graded=[
            {"id": "q1", "your_answer": "B", "correct_answer": "B",
             "grade": "correct", "disagreement": None},
            {"id": "q2", "your_answer": ["B", "D"], "correct_answer": ["B", "D"],
             "grade": "correct", "disagreement": None},
            {"id": "q3", "your_answer": "3", "correct_answer": "3",
             "grade": "correct", "disagreement": None},
        ],
        score_correct=correct,
        score_total=3,
    )


def test_append_take_persists_to_disk(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    store.append_take("01HXPQ9TEST", _take())
    text = store.path_for("01HXPQ9TEST").read_text(encoding="utf-8")
    assert "## Take 1" in text
    assert "3 / 3" in text


def test_append_take_assigns_next_number(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    store.append_take("01HXPQ9TEST", _take(n=99))  # caller passes nonsense
    after = store.load("01HXPQ9TEST")
    assert after.takes[-1].take_n == 1  # store overrides with next monotonic


def test_multiple_takes_monotonic(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    store.append_take("01HXPQ9TEST", _take())
    store.append_take("01HXPQ9TEST", _take())
    store.append_take("01HXPQ9TEST", _take())
    after = store.load("01HXPQ9TEST")
    assert [t.take_n for t in after.takes] == [1, 2, 3]


def test_append_take_missing_test_raises(tmp_path):
    store = PracticeTestStore(tmp_path)
    with pytest.raises(PracticeTestError):
        store.append_take("ghost", _take())


def test_take_with_disagreement_renders_warning(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    take = _take()
    take.graded[0]["disagreement"] = "Secondary said partial"
    store.append_take("01HXPQ9TEST", take)
    text = store.path_for("01HXPQ9TEST").read_text(encoding="utf-8")
    assert "graders disagreed" in text


def test_single_grader_run_renders_note(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    take = _take()
    take.secondary_grader = None
    store.append_take("01HXPQ9TEST", take)
    text = store.path_for("01HXPQ9TEST").read_text(encoding="utf-8")
    assert "single-grader" in text


# --- normalize_answer ----------------------------------------------------


def test_normalize_strips_and_passes_through():
    assert normalize_answer(" B ") == "B"


def test_normalize_splits_comma_string():
    assert normalize_answer("B, D") == ["B", "D"]


def test_normalize_list_passes_through():
    assert normalize_answer(["B", " D "]) == ["B", "D"]


def test_normalize_none_returns_empty_string():
    assert normalize_answer(None) == ""


def test_normalize_coerces_non_strings():
    assert normalize_answer(3) == "3"


# --- compare_answers -----------------------------------------------------


def test_compare_exact_single_select():
    assert compare_answers("B", "B") == "correct"


def test_compare_case_insensitive():
    assert compare_answers("b", "B") == "correct"


def test_compare_wrong_single_select():
    assert compare_answers("A", "B") == "wrong"


def test_compare_multi_select_full_match():
    assert compare_answers(["B", "D"], ["B", "D"]) == "correct"


def test_compare_multi_select_order_agnostic():
    assert compare_answers(["D", "B"], ["B", "D"]) == "correct"


def test_compare_multi_select_partial():
    assert compare_answers(["B"], ["B", "D"]) == "partial"


def test_compare_multi_select_wrong_member():
    assert compare_answers(["B", "C"], ["B", "D"]) == "wrong"


def test_compare_empty_user_answer_is_wrong():
    assert compare_answers("", "B") == "wrong"


def test_compare_partial_only_when_canonical_is_multi():
    # If canonical is single-select, "partial" doesn't apply.
    assert compare_answers("A", "B") == "wrong"


# --- atomicity ----------------------------------------------------------


def test_save_no_tempfile_leftover(tmp_path):
    store = PracticeTestStore(tmp_path)
    store.save(_fresh_test())
    leftovers = [p for p in store.tests_dir.iterdir() if not p.name.endswith(".md")]
    assert leftovers == []
