"""Table-driven SM-2 tests. Pin the math so a refactor can't drift it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from memory.srs import DEFAULT_EASE, ReviewState, is_due, next_due, update

_FIXED_NOW = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)


# --- fail path (grade < 3): interval resets to 1, ease drops by 0.2, floored at 1.3 ---


@pytest.mark.parametrize(
    "grade, prev_ease, expected_ease",
    [
        (0, 2.5, 2.3),
        (1, 2.5, 2.3),
        (2, 2.5, 2.3),
        (0, 1.4, 1.3),  # floor kicks in
        (2, 1.3, 1.3),  # already at floor
        (1, 2.5, 2.3),
    ],
)
def test_fail_resets_interval_and_drops_ease(grade, prev_ease, expected_ease):
    prev = ReviewState(ease=prev_ease, interval_days=30, last_reviewed=_FIXED_NOW)
    new = update(prev, grade, now=_FIXED_NOW)
    assert new.interval_days == 1
    assert new.ease == pytest.approx(expected_ease)
    assert new.last_reviewed == _FIXED_NOW


# --- pass path: 0 → 1 → 6 → geometric on ease ---


def test_first_pass_sets_interval_to_one():
    prev = ReviewState(ease=2.5, interval_days=0, last_reviewed=None)
    new = update(prev, 4, now=_FIXED_NOW)
    assert new.interval_days == 1
    assert new.ease == pytest.approx(2.5)


def test_second_pass_sets_interval_to_six():
    prev = ReviewState(ease=2.5, interval_days=1, last_reviewed=_FIXED_NOW)
    new = update(prev, 4, now=_FIXED_NOW)
    assert new.interval_days == 6


def test_third_pass_is_geometric():
    prev = ReviewState(ease=2.5, interval_days=6, last_reviewed=_FIXED_NOW)
    new = update(prev, 4, now=_FIXED_NOW)
    assert new.interval_days == round(6 * 2.5)  # 15


def test_long_card_grows_geometrically():
    prev = ReviewState(ease=2.36, interval_days=30, last_reviewed=_FIXED_NOW)
    new = update(prev, 4, now=_FIXED_NOW)
    assert new.interval_days == round(30 * 2.36)  # 71


# --- ease deltas: SM-2 reference formula ---


@pytest.mark.parametrize(
    "grade, expected_delta",
    [
        (5, 0.10),
        (4, 0.00),
        (3, -0.14),
    ],
)
def test_pass_path_ease_delta_matches_sm2(grade, expected_delta):
    prev = ReviewState(ease=2.5, interval_days=10, last_reviewed=_FIXED_NOW)
    new = update(prev, grade, now=_FIXED_NOW)
    assert new.ease == pytest.approx(round(2.5 + expected_delta, 2))


def test_grade_3_can_floor_ease():
    prev = ReviewState(ease=1.35, interval_days=10, last_reviewed=_FIXED_NOW)
    new = update(prev, 3, now=_FIXED_NOW)
    assert new.ease == pytest.approx(1.3)


# --- grade clamping ---


def test_out_of_band_grade_is_clamped_low():
    prev = ReviewState(ease=2.5, interval_days=10, last_reviewed=_FIXED_NOW)
    # -1 clamps to 0 → fail path
    new = update(prev, -1, now=_FIXED_NOW)
    assert new.interval_days == 1


def test_out_of_band_grade_is_clamped_high():
    prev = ReviewState(ease=2.5, interval_days=10, last_reviewed=_FIXED_NOW)
    new = update(prev, 99, now=_FIXED_NOW)
    # 99 clamps to 5 → pass path, ease nudges up
    assert new.interval_days == round(10 * 2.5)
    assert new.ease == pytest.approx(2.6)


# --- timestamp injection ---


def test_last_reviewed_uses_injected_now():
    prev = ReviewState(ease=2.5, interval_days=1, last_reviewed=None)
    custom_now = datetime(2026, 12, 25, 9, 0, tzinfo=timezone.utc)
    new = update(prev, 4, now=custom_now)
    assert new.last_reviewed == custom_now


# --- next_due / is_due helpers ---


def test_next_due_none_for_unreviewed():
    state = ReviewState()
    assert next_due(state) is None


def test_next_due_adds_interval():
    state = ReviewState(ease=2.5, interval_days=6, last_reviewed=_FIXED_NOW)
    assert next_due(state) == (_FIXED_NOW + timedelta(days=6)).date()


def test_is_due_true_for_unreviewed():
    assert is_due(ReviewState()) is True


def test_is_due_false_when_in_future():
    state = ReviewState(ease=2.5, interval_days=30, last_reviewed=_FIXED_NOW)
    today = _FIXED_NOW.date() + timedelta(days=5)
    assert is_due(state, today=today) is False


def test_is_due_true_when_overdue():
    state = ReviewState(ease=2.5, interval_days=1, last_reviewed=_FIXED_NOW)
    today = _FIXED_NOW.date() + timedelta(days=5)
    assert is_due(state, today=today) is True


def test_is_due_true_exactly_on_due_date():
    state = ReviewState(ease=2.5, interval_days=6, last_reviewed=_FIXED_NOW)
    today = (_FIXED_NOW + timedelta(days=6)).date()
    assert is_due(state, today=today) is True


# --- defaults ---


def test_default_state_matches_brand_new_card():
    state = ReviewState()
    assert state.ease == DEFAULT_EASE
    assert state.interval_days == 0
    assert state.last_reviewed is None
