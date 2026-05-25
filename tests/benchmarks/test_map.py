"""Sanity tests for ``benchmarks/map.py``.

These exist to catch typos and stale entries — a task pointing at a
benchmark category no source emits silently returns an empty ranking,
which is a confusing failure mode for the user.
"""

from __future__ import annotations

from benchmarks.map import TASK_BENCHMARKS
from routing import roster

# Categories every source promises to emit. Update when adding sources.
_KNOWN_CATEGORIES: dict[str, set[str]] = {
    "aider": {"polyglot"},
    "livebench": {
        "reasoning",
        "coding",
        "agentic_coding",
        "mathematics",
        "language",
        "instruction_following",
        "data_analysis",
    },
}


def test_every_delphi_task_type_has_a_mapping() -> None:
    """``TASK_BENCHMARKS`` must cover every roster task type — otherwise
    the user can't rank for that slot."""
    assert set(TASK_BENCHMARKS) == set(roster.TASK_TYPES)


def test_every_mapping_references_a_known_source_and_category() -> None:
    for task, refs in TASK_BENCHMARKS.items():
        for ref in refs:
            assert ref.source in _KNOWN_CATEGORIES, (
                f"task {task!r} references unknown source {ref.source!r}"
            )
            assert ref.category in _KNOWN_CATEGORIES[ref.source], (
                f"task {task!r} references unknown {ref.source}/{ref.category}"
            )


def test_task_weights_are_positive() -> None:
    for task, refs in TASK_BENCHMARKS.items():
        for ref in refs:
            assert ref.weight > 0, f"non-positive weight in {task}"


def test_task_weights_sum_to_one_within_tolerance() -> None:
    """Drift here just means hand-tuned weights got out of sync. ``rank``
    still normalizes, but a non-1 sum is a smell worth flagging."""
    for task, refs in TASK_BENCHMARKS.items():
        total = sum(r.weight for r in refs)
        assert abs(total - 1.0) < 1e-6, f"{task} weights sum to {total}, not 1.0"
