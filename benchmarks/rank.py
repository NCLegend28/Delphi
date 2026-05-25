"""Per-task ranking — joins scores by canonical model and applies weights.

The only public function is ``rank_task``. It takes a flat list of
``BenchmarkScore`` from any/all sources and returns a sorted list of
``ModelRanking`` for the requested task type.

Coverage policy
---------------
Aider and LiveBench cover very different model populations — frontier
proprietary models on Aider, open-weight + frontier on LiveBench — so
requiring *every* component to be present (the original design) yielded
near-empty rankings. We instead:

- Score over whatever components are present.
- Reweight against the sum of *present* weights so the composite is
  comparable to a fully-covered model on the same scale.
- Emit ``coverage_ratio`` = present-weight / total-weight so the caller
  can filter low-coverage rankings out (``--min-coverage`` at the CLI).
- Drop only models with zero present components — there's nothing to
  rank from.

This trades silent dropout for a coverage signal the user can act on.
"""

from __future__ import annotations

from collections import defaultdict

from benchmarks.map import TASK_BENCHMARKS, BenchmarkRef
from benchmarks.models import BenchmarkScore, ModelRanking


def rank_task(
    task_type: str,
    scores: list[BenchmarkScore],
) -> list[ModelRanking]:
    """Return models ranked by composite score for ``task_type``, best first.

    Raises ``KeyError`` if ``task_type`` isn't in ``TASK_BENCHMARKS``.
    Returns an empty list if no model scored on any required component.
    """
    refs = TASK_BENCHMARKS.get(task_type)
    if not refs:
        raise KeyError(f"unknown task_type: {task_type!r}")

    total_weight = sum(r.weight for r in refs)
    if total_weight <= 0:
        raise ValueError(f"task {task_type!r} has non-positive total weight")

    by_model: dict[str, dict[tuple[str, str], BenchmarkScore]] = defaultdict(dict)
    for s in scores:
        by_model[s.canonical_model][(s.source, s.category)] = s

    rankings: list[ModelRanking] = []
    for canonical, model_scores in by_model.items():
        composite, components, present_weight = _composite(refs, model_scores)
        if not components:
            continue
        rankings.append(
            ModelRanking(
                canonical_model=canonical,
                task_type=task_type,
                composite_score=composite,
                components=components,
                coverage_ratio=present_weight / total_weight,
            )
        )

    rankings.sort(key=lambda r: r.composite_score, reverse=True)
    return rankings


def _composite(
    refs: list[BenchmarkRef],
    model_scores: dict[tuple[str, str], BenchmarkScore],
) -> tuple[float, list[BenchmarkScore], float]:
    """Return ``(composite_score, present_components, present_weight)``.

    Composite is the weighted mean over *present* components — i.e.
    ``sum(score * weight) / sum(present_weights)`` — so partially-covered
    rankings sit on the same 0-100 scale as fully-covered ones.
    """
    components: list[BenchmarkScore] = []
    weighted_sum = 0.0
    present_weight = 0.0
    for ref in refs:
        entry = model_scores.get((ref.source, ref.category))
        if entry is None:
            continue
        components.append(entry)
        weighted_sum += entry.score * ref.weight
        present_weight += ref.weight
    composite = weighted_sum / present_weight if present_weight > 0 else 0.0
    return composite, components, present_weight
