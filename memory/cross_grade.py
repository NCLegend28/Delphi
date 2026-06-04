"""Parallel two-model grading — the "second opinion" primitive.

When a practice test is submitted, we want graded feedback that isn't
one model's freelance opinion. The pattern here: fire the *same* grading
prompt at two different models concurrently, blind to each other; parse
both responses; reconcile. Matching grades pass through with both
reasonings surfaced. Disagreements surface as a "second opinion" note
per question rather than the service silently picking a winner.

Three reasons the disagreement-surfacing matters:

1. **Inflation hurts learning.** If the service splits the difference or
   defers to the more generous grader, partial-credit drift creeps in
   over time. SM-2 has the same disease in Phase 5; same antidote here.
2. **Transparency over magic.** Tali sees both models' reasoning, picks
   what she trusts, and learns from the disagreement itself
   ("apparently 'monotonous' isn't a full synonym for 'tedious' in
   GRE-land").
3. **Generalizable beyond GRE.** The same primitive applies to
   algotrading signal cross-validation, document review, anywhere
   "two independent opinions" beats "one confident one".

The deterministic mechanical-match (``practice_test.compare_answers``)
runs as a third reference. If it agrees with both models → no note. If
it disagrees with both models → we trust the models (they have rubric
context). If it picks the same answer as one model but not the other →
that's still a disagreement, surfaced as such.

Failure modes are explicit:

- One model errors → use the other; the take records ``secondary_grader=None``
- Both error → ``CrossGradeError``; the route returns 502, no take is appended
- One model returns unparseable JSON → treated as that model erroring
- Both return unparseable → ``CrossGradeError``
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from memory.practice_test import (
    AnswerKey,
    PracticeTest,
    compare_answers,
    normalize_answer,
)
from proxy.ollama_client import OllamaClient, OllamaError

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_VALID_GRADES = {"correct", "partial", "wrong"}


class CrossGradeError(Exception):
    """Raised when both graders fail and no usable verdict can be produced."""


@dataclass(frozen=True, slots=True)
class GradedAnswer:
    """One question's full graded record. Serializable into ``Take.graded``."""

    question_id: str
    your_answer: Any
    correct_answer: Any
    grade: str  # "correct" | "partial" | "wrong"
    primary_reasoning: str
    secondary_reasoning: str
    disagreement: str | None
    mechanical_grade: str  # what compare_answers said, for the record


@dataclass(frozen=True, slots=True)
class CrossGradeResult:
    """The whole batch: per-question grades + which graders ran."""

    graded: list[GradedAnswer]
    primary_grader: str
    secondary_grader: str | None  # None when secondary failed; primary stood alone
    score_correct: int
    score_total: int


# --- prompt building -----------------------------------------------------


def _grader_system_prompt() -> str:
    return (
        "You are a GRE practice-test grader. Given an answer key and a user's "
        "submission, judge each answer on the SM-2 scale used elsewhere in this "
        "service:\n"
        "- ``correct`` — the user's answer matches the canonical answer.\n"
        "- ``partial`` — for sentence-equivalence (two correct answers), the "
        "user picked one of the two valid choices but not both. Otherwise wrong.\n"
        "- ``wrong`` — none of the above.\n"
        "\n"
        "Be calibrated, not generous. A misspelled-but-recognizable single-"
        "select answer ('3' vs 'three') is correct. A near-synonym for the "
        "wrong sense is wrong, not partial. Inflation prevents the user from "
        "learning what they actually missed.\n"
        "\n"
        "Output ONLY a JSON object — no prose, no code fences — keyed by "
        'question id. Each value is ``{"grade": "correct"|"partial"|"wrong", '
        '"reasoning": "<one sentence: WHY this grade, referencing the rubric '
        'note when relevant>"}``.\n'
    )


def _grader_user_prompt(test: PracticeTest, answers: dict[str, Any]) -> str:
    lines = ["Test ID: " + test.test_id, "", "Answer key and submissions:", ""]
    for qid, key in test.answer_key.items():
        user_raw = answers.get(qid, "")
        user = normalize_answer(user_raw)
        canonical = key.answer
        lines.append(f"- {qid}:")
        lines.append(f"    canonical: {json.dumps(canonical)}")
        lines.append(f"    user:      {json.dumps(user)}")
        if key.rubric:
            lines.append(f"    rubric:    {key.rubric}")
    lines.append("")
    lines.append(
        "Return the JSON object now. Every key listed above must appear; do "
        "not invent ids that weren't asked about."
    )
    return "\n".join(lines)


# --- parsing -------------------------------------------------------------


def _extract_json(raw: str) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
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


def _parse_grader_response(raw: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    """Validate and normalize a grader's JSON output.

    Returns ``None`` if the structure is unusable; otherwise a dict of
    ``{question_id: {grade, reasoning}}`` where ``grade`` is one of the
    three valid values. Out-of-band grades fail this validation rather
    than being coerced — silently coercing would hide a misbehaving model.
    """
    out: dict[str, dict[str, str]] = {}
    for qid, entry in raw.items():
        if not isinstance(entry, dict):
            return None
        grade = entry.get("grade")
        if grade not in _VALID_GRADES:
            return None
        reasoning = entry.get("reasoning") if isinstance(entry.get("reasoning"), str) else ""
        out[str(qid)] = {"grade": grade, "reasoning": reasoning}
    return out


async def _call_grader(
    ollama: OllamaClient,
    model: str,
    system: str,
    user: str,
    options: dict[str, Any] | None,
) -> dict[str, dict[str, str]] | None:
    """Run one grader. Returns parsed output or ``None`` on any failure."""
    try:
        resp = await ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            options=options,
        )
    except OllamaError:
        return None
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    extracted = _extract_json(content) if isinstance(content, str) else None
    if extracted is None:
        return None
    return _parse_grader_response(extracted)


# --- reconciliation ------------------------------------------------------


def _reconcile_one(
    qid: str,
    key: AnswerKey,
    user_raw: Any,
    primary: dict[str, str] | None,
    secondary: dict[str, str] | None,
) -> GradedAnswer:
    """Build one ``GradedAnswer`` from up to two grader verdicts.

    Resolution order:
    1. If both graders ran AND agreed → use their grade; reasoning from both.
    2. If both ran AND disagreed → emit a disagreement note; keep both
       reasonings; the surfaced ``grade`` is the primary's (it's the
       *primary* by configuration, not by majority), so the user sees
       what the headline grader said but with the secondary's objection
       attached.
    3. If only one ran → use it, blank the other reasoning, no disagreement.
    4. If neither ran → fall back to the mechanical grade with an empty
       reasoning. (The CALLER decides whether to raise; reconciliation
       itself never raises so the route can still emit a record.)
    """
    user = normalize_answer(user_raw)
    canonical = key.answer
    mechanical = compare_answers(user, canonical)

    primary_grade = primary["grade"] if primary else None
    primary_reasoning = primary["reasoning"] if primary else ""
    secondary_grade = secondary["grade"] if secondary else None
    secondary_reasoning = secondary["reasoning"] if secondary else ""

    if primary_grade and secondary_grade:
        if primary_grade == secondary_grade:
            return GradedAnswer(
                question_id=qid,
                your_answer=user,
                correct_answer=canonical,
                grade=primary_grade,
                primary_reasoning=primary_reasoning,
                secondary_reasoning=secondary_reasoning,
                disagreement=None,
                mechanical_grade=mechanical,
            )
        return GradedAnswer(
            question_id=qid,
            your_answer=user,
            correct_answer=canonical,
            grade=primary_grade,
            primary_reasoning=primary_reasoning,
            secondary_reasoning=secondary_reasoning,
            disagreement=(
                f"Primary marked {primary_grade}; secondary marked "
                f"{secondary_grade}. Surfacing both for your judgment."
            ),
            mechanical_grade=mechanical,
        )

    if primary_grade:
        return GradedAnswer(
            question_id=qid,
            your_answer=user,
            correct_answer=canonical,
            grade=primary_grade,
            primary_reasoning=primary_reasoning,
            secondary_reasoning="",
            disagreement=None,
            mechanical_grade=mechanical,
        )

    if secondary_grade:
        return GradedAnswer(
            question_id=qid,
            your_answer=user,
            correct_answer=canonical,
            grade=secondary_grade,
            primary_reasoning="",
            secondary_reasoning=secondary_reasoning,
            disagreement=None,
            mechanical_grade=mechanical,
        )

    # No grader spoke for this question — fall back to the deterministic match.
    return GradedAnswer(
        question_id=qid,
        your_answer=user,
        correct_answer=canonical,
        grade=mechanical,
        primary_reasoning="",
        secondary_reasoning="",
        disagreement=(
            "Both graders failed to grade this question; falling back to "
            "mechanical answer-key match."
        ),
        mechanical_grade=mechanical,
    )


# --- public entrypoint ---------------------------------------------------


async def cross_grade(
    *,
    ollama: OllamaClient,
    primary_model: str,
    secondary_model: str | None,
    test: PracticeTest,
    answers: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> CrossGradeResult:
    """Run parallel two-model grading and reconcile.

    ``secondary_model`` is optional — when None, only the primary runs and
    the result carries ``secondary_grader=None`` so the take record shows
    "single-grader run". Pass None deliberately when you want a fast path
    (e.g. ad-hoc dev), but production grading should always pair them.

    Raises ``CrossGradeError`` only when BOTH graders fail to return any
    usable verdict. If one fails and the other succeeds, the result stands
    with the surviving grader; the caller's UI surfaces the degradation.
    """
    system = _grader_system_prompt()
    user_prompt = _grader_user_prompt(test, answers)

    tasks = [_call_grader(ollama, primary_model, system, user_prompt, options)]
    if secondary_model:
        tasks.append(_call_grader(ollama, secondary_model, system, user_prompt, options))

    results = await asyncio.gather(*tasks)
    primary_out = results[0]
    secondary_out = results[1] if len(results) > 1 else None

    if primary_out is None and secondary_out is None:
        raise CrossGradeError(
            "both graders failed to return a usable verdict (network error or "
            "malformed output from both)"
        )

    # Whichever grader survived determines which slot is recorded.
    survived_primary = primary_model if primary_out is not None else None
    survived_secondary = secondary_model if secondary_out is not None else None

    # When the primary fails but the secondary stands, promote the
    # secondary to the recorded "primary" so the take doesn't lie about
    # which grader produced the headline grade.
    if primary_out is None and secondary_out is not None:
        survived_primary = secondary_model
        survived_secondary = None
        primary_out, secondary_out = secondary_out, None

    graded: list[GradedAnswer] = []
    for qid, key in test.answer_key.items():
        primary_entry = primary_out.get(qid) if primary_out else None
        secondary_entry = secondary_out.get(qid) if secondary_out else None
        graded.append(
            _reconcile_one(
                qid=qid,
                key=key,
                user_raw=answers.get(qid),
                primary=primary_entry,
                secondary=secondary_entry,
            )
        )

    correct = sum(1 for g in graded if g.grade == "correct")
    total = len(graded)

    return CrossGradeResult(
        graded=graded,
        primary_grader=survived_primary or primary_model,
        secondary_grader=survived_secondary,
        score_correct=correct,
        score_total=total,
    )
