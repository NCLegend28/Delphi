"""SM-2 spaced repetition — pure-function update for a single card.

Anki's algorithm in miniature. One vocab card carries a ``review:`` block in
its frontmatter (``ease``, ``interval_days``, ``last_reviewed``); one drill
turn produces one grade on the 0–5 SM-2 scale; this module computes the new
state. No I/O, no time-of-day dependence beyond ``now`` injection — pure
deterministic math so the table-driven tests can pin every cell.

Why this lives alongside ``memory/vocab_card.py`` rather than under
``routing/``: SRS state is *vault* data. The schedule is a property of the
card on disk, not of the agent that asked the question. The agent reads
state, asks a question, posts a grade; ``srs.update()`` translates the
grade into the next state; ``vocab_card.write_review()`` lands it in the
markdown. Three small pieces, each independently testable.

Grade rubric (the soul appendix mirrors this for the model):

* ``0`` — total blackout
* ``1`` — wrong; right answer felt familiar on reveal
* ``2`` — wrong; easy to remember once seen
* ``3`` — correct with serious difficulty                ← passing threshold
* ``4`` — correct after a hesitation
* ``5`` — correct, easy, immediate
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Floor on the ease factor. Anki uses 1.3; below this, intervals would
# collapse and the card would loop forever. Leeches stay scheduled but
# stop accelerating.
_EASE_FLOOR = 1.3

# Default ease for a brand-new card. SM-2 paper says 2.5.
DEFAULT_EASE = 2.5

# Passing grade. < this resets the interval; >= this extends it.
_PASSING_GRADE = 3

# After the first successful review, the next interval is 1 day.
# After the second, 6 days. Then geometric on ease.
_FIRST_PASS_DAYS = 1
_SECOND_PASS_DAYS = 6


@dataclass(frozen=True, slots=True)
class ReviewState:
    """One vocab card's spaced-repetition state.

    ``last_reviewed`` is ``None`` for a card that's never been graded —
    distinct from a card graded today (which carries a concrete datetime).
    Storing the timezone-aware datetime keeps next-due calculations
    unambiguous when the user crosses a DST boundary between sessions.
    """

    ease: float = DEFAULT_EASE
    interval_days: int = 0
    last_reviewed: datetime | None = None


def _clamp_grade(grade: int) -> int:
    """Coerce out-of-band grades to the legal 0–5 range without raising.

    A bad grade from the model is a bug, but not one the user should see —
    treat it as a total blackout (grade 0) so the card schedules for
    tomorrow and the tutor moves on. The grade gets logged separately so
    the regression is debuggable.
    """
    if grade < 0:
        return 0
    if grade > 5:
        return 5
    return grade


def update(prev: ReviewState, grade: int, *, now: datetime | None = None) -> ReviewState:
    """Compute the post-grade review state for one card.

    ``now`` is injected so tests can pin the wall clock; in production
    callers pass an aware datetime (typically ``datetime.now().astimezone()``).
    The returned ``last_reviewed`` is whatever ``now`` was — we don't try to
    normalize to UTC here. The vault stores local timestamps everywhere else
    (see ``CLAUDE.md`` on the timezone field), so we match.

    Algorithm:

    1. **Fail path** (``grade < 3``): reset ``interval_days`` to 1 and
       drop ``ease`` by 0.2, floored at 1.3. The card resurfaces tomorrow.
    2. **Pass path** (``grade >= 3``): extend the interval — 1 day on the
       first pass, 6 days on the second, geometric on ease after that —
       and nudge ``ease`` by the SM-2 delta
       ``0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)``. Grade 5 nudges
       ease up, grade 3 nudges it down, grade 4 holds it flat. Floored at 1.3.
    """
    g = _clamp_grade(grade)
    stamp = now if now is not None else datetime.now().astimezone()

    if g < _PASSING_GRADE:
        new_ease = max(_EASE_FLOOR, prev.ease - 0.2)
        return ReviewState(ease=round(new_ease, 2), interval_days=1, last_reviewed=stamp)

    # Pass path: extend the interval.
    if prev.interval_days <= 0:
        new_interval = _FIRST_PASS_DAYS
    elif prev.interval_days < _SECOND_PASS_DAYS:
        # Anything 1..5 still counts as "second pass" — protects against
        # a previously failed card that's been re-graded on its 1-day reset.
        new_interval = _SECOND_PASS_DAYS
    else:
        new_interval = max(1, round(prev.interval_days * prev.ease))

    # SM-2 ease delta. Grade 5 → +0.1; grade 4 → 0.0; grade 3 → -0.14.
    delta = 0.1 - (5 - g) * (0.08 + (5 - g) * 0.02)
    new_ease = max(_EASE_FLOOR, prev.ease + delta)
    return ReviewState(
        ease=round(new_ease, 2),
        interval_days=new_interval,
        last_reviewed=stamp,
    )


def next_due(state: ReviewState) -> date | None:
    """The calendar date this card is next due on, or ``None`` if never reviewed."""
    if state.last_reviewed is None:
        return None
    return (state.last_reviewed + timedelta(days=state.interval_days)).date()


def is_due(state: ReviewState, *, today: date | None = None) -> bool:
    """Whether the card should appear in a "due cards" pick today.

    A never-reviewed card (``last_reviewed is None``) is always due — that's
    the gate that pulls fresh cards into circulation. A reviewed card is due
    when its computed ``next_due`` is on or before ``today``.
    """
    if state.last_reviewed is None:
        return True
    due_on = next_due(state)
    cutoff = today if today is not None else datetime.now().astimezone().date()
    return due_on is not None and due_on <= cutoff
