"""Pydantic models for the benchmark pipeline.

``BenchmarkScore`` is the cross-source common form — every leaderboard
adapter emits a list of these. ``ModelRanking`` is the output of
``rank.rank_task`` and what the CLI prints.

Scores are always *higher is better*. Source adapters invert any
error-rate-style metric before emitting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BenchmarkScore(BaseModel):
    """One model's score on one (source, category) pair.

    ``canonical_model`` is the normalized join key (see ``normalize.py``).
    ``raw_model`` is preserved for debugging — when two sources disagree
    on a model's score, the first thing to check is whether they were
    actually scoring the same checkpoint.
    """

    canonical_model: str
    raw_model: str
    source: str
    category: str
    score: float
    fetched_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRanking(BaseModel):
    """Composite ranking for one model on one task type.

    ``components`` carries the constituent scores so the CLI can show
    *why* a model ranked where it did, not just the final number.

    ``coverage_ratio`` is the fraction of the task's total declared
    weight that was present for this model. 1.0 = scored on every
    component the map asks for; 0.3 = scored on only ~30%, so the
    composite is reweighted over what was available and the rank should
    be read with suspicion. Callers filter on this via ``--min-coverage``.
    """

    canonical_model: str
    task_type: str
    composite_score: float
    components: list[BenchmarkScore]
    coverage_ratio: float = 1.0
    ollama_tag: str | None = None
