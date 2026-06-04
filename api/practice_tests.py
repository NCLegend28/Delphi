"""POST /v1/practice-tests/{test_id}/grade and friends.

A separate router from ``/v1/chat/completions`` because grading isn't a
chat completion — it's a JSON-in JSON-out endpoint that takes a test_id
plus the user's filled answers, runs the parallel two-model grader, and
returns per-question results.

Three routes:

* ``GET  /v1/practice-tests/{test_id}`` — return the test (questions +
  metadata; answer_key is *not* in the default response, only with
  ``?include_key=true``). The UI uses this to re-fetch state if the user
  navigated away mid-test.
* ``POST /v1/practice-tests/{test_id}/grade`` — accept ``{"answers": {...}}``,
  invoke ``cross_grade`` with the configured primary + secondary models,
  append the graded take to the test file, return the per-question result.
* ``GET  /v1/practice-tests`` — list recent tests (lightweight metadata
  only). For an eventual "history" view in the UI.

Auth is the same bearer pattern the chat router uses. Failures return
typed JSON errors with stable codes so the UI can render specific
messages (404 for missing test, 502 when both graders fail).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, status

from api.deps import get_ollama
from auth.bearer import require_bearer
from config import Config, get_config
from memory.cross_grade import CrossGradeError, cross_grade
from memory.practice_test import (
    PracticeTest,
    PracticeTestError,
    PracticeTestStore,
    Take,
)
from proxy.ollama_client import OllamaClient

log = structlog.get_logger("delphi.practice_tests")

router = APIRouter(prefix="/v1/practice-tests")


# Dependency factory mirroring api/deps.py — kept inline because it's
# only used by this router, no need for a sibling import dance.
def get_practice_test_store(
    cfg: Annotated[Config, Depends(get_config)],
) -> PracticeTestStore:
    if not cfg.obsidian_vault_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "VAULT_NOT_CONFIGURED", "message": "no vault path configured"},
        )
    return PracticeTestStore(cfg.obsidian_vault_path)


def _test_to_public_json(test: PracticeTest, *, include_key: bool) -> dict[str, Any]:
    """Render a test for the wire. Answer key withheld unless asked."""
    payload: dict[str, Any] = {
        "test_id": test.test_id,
        "created": test.created.isoformat(),
        "n_questions": test.n_questions,
        "sections": [
            {"kind": s.kind, "n": s.n, **s.extras} for s in test.sections
        ],
        "sources": test.sources,
        "body": test.body,
        "takes": [
            {
                "take_n": t.take_n,
                "submitted_at": t.submitted_at.isoformat(),
                "primary_grader": t.primary_grader,
                "secondary_grader": t.secondary_grader,
                "score": {"correct": t.score_correct, "total": t.score_total},
            }
            for t in test.takes
        ],
    }
    if include_key:
        payload["answer_key"] = {
            qid: {"answer": ak.answer, "rubric": ak.rubric}
            for qid, ak in test.answer_key.items()
        }
    return payload


@router.get("/{test_id}", dependencies=[Depends(require_bearer)])
async def get_test(
    test_id: str,
    store: Annotated[PracticeTestStore, Depends(get_practice_test_store)],
    include_key: bool = False,
) -> dict[str, Any]:
    """Fetch one practice test. Answer key withheld unless ``include_key=true``."""
    try:
        test = store.load(test_id)
    except PracticeTestError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "TEST_MALFORMED", "message": str(exc)},
        ) from exc
    if test is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_NOT_FOUND", "message": f"no test with id {test_id!r}"},
        )
    return _test_to_public_json(test, include_key=include_key)


@router.post("/{test_id}/grade", dependencies=[Depends(require_bearer)])
async def grade_test(
    test_id: str,
    store: Annotated[PracticeTestStore, Depends(get_practice_test_store)],
    cfg: Annotated[Config, Depends(get_config)],
    ollama: Annotated[OllamaClient, Depends(get_ollama)],
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Submit answers; run the two-model cross-check; append the take."""
    answers = body.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "ANSWERS_MISSING", "message": "body.answers must be a non-empty mapping"},
        )

    try:
        test = store.load(test_id)
    except PracticeTestError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "TEST_MALFORMED", "message": str(exc)},
        ) from exc
    if test is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_NOT_FOUND", "message": f"no test with id {test_id!r}"},
        )

    primary_model = cfg.delphi_model_gre_practice_test
    secondary_model = cfg.delphi_model_gre_practice_secondary or None

    try:
        result = await cross_grade(
            ollama=ollama,
            primary_model=primary_model,
            secondary_model=secondary_model,
            test=test,
            answers=answers,
        )
    except CrossGradeError as exc:
        log.warning(
            "cross_grade_failed",
            test_id=test_id,
            primary=primary_model,
            secondary=secondary_model,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "GRADERS_UNAVAILABLE",
                "message": "both graders failed to return a usable verdict",
            },
        ) from exc

    # Append a take to the test file. ``append_take`` overrides ``take_n``
    # to the next monotonic value so a stale caller can't write the wrong number.
    graded_dicts = [
        {
            "id": g.question_id,
            "your_answer": g.your_answer,
            "correct_answer": g.correct_answer,
            "grade": g.grade,
            "primary_reasoning": g.primary_reasoning,
            "secondary_reasoning": g.secondary_reasoning,
            "disagreement": g.disagreement,
            "mechanical_grade": g.mechanical_grade,
        }
        for g in result.graded
    ]
    take = Take(
        take_n=0,  # store overrides
        submitted_at=datetime.now().astimezone(),
        primary_grader=result.primary_grader,
        secondary_grader=result.secondary_grader,
        answers=answers,
        graded=graded_dicts,
        score_correct=result.score_correct,
        score_total=result.score_total,
    )
    try:
        updated = store.append_take(test_id, take)
    except PracticeTestError as exc:
        # The grade itself succeeded; only persistence failed. Surface the
        # grade to the caller anyway so the user sees their result, but log
        # the persistence error so it's debuggable.
        log.error("append_take_failed", test_id=test_id, error=str(exc))
        updated_take_n = (max((t.take_n for t in test.takes), default=0)) + 1
    else:
        updated_take_n = updated.takes[-1].take_n

    return {
        "test_id": test_id,
        "take_n": updated_take_n,
        "score": {
            "correct": result.score_correct,
            "total": result.score_total,
            "percent": (
                result.score_correct * 100 // result.score_total
                if result.score_total
                else 0
            ),
        },
        "graded_by": {
            "primary": result.primary_grader,
            "secondary": result.secondary_grader,
        },
        "questions": graded_dicts,
    }


@router.get("", dependencies=[Depends(require_bearer)])
async def list_tests(
    store: Annotated[PracticeTestStore, Depends(get_practice_test_store)],
    limit: int = 20,
) -> dict[str, Any]:
    """List recent tests as lightweight metadata.

    Sorted newest first. Returns at most ``limit`` entries. Useful for a UI
    "history" view; not optimized for huge libraries (we glob the directory
    and parse each test's frontmatter), but that's fine until there are
    thousands of tests.
    """
    if not store.tests_dir.is_dir():
        return {"tests": []}

    items: list[tuple[float, dict[str, Any]]] = []
    for path in store.tests_dir.glob("*.md"):
        try:
            test = store.load(path.stem)
        except PracticeTestError:
            continue
        if test is None:
            continue
        items.append(
            (
                path.stat().st_mtime,
                {
                    "test_id": test.test_id,
                    "created": test.created.isoformat(),
                    "n_questions": test.n_questions,
                    "take_count": len(test.takes),
                    "latest_score": (
                        test.takes[-1].score_correct if test.takes else None
                    ),
                },
            )
        )
    items.sort(key=lambda t: t[0], reverse=True)
    return {"tests": [meta for _, meta in items[:limit]]}
