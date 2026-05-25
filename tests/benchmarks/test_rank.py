"""Unit tests for ``benchmarks/rank.py``.

Builds tiny synthetic score lists to exercise: weighting, drop-on-missing,
sort order, and the unknown-task-type error path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from benchmarks.map import TASK_BENCHMARKS, BenchmarkRef
from benchmarks.models import BenchmarkScore
from benchmarks.rank import rank_task


def _score(model: str, source: str, category: str, value: float) -> BenchmarkScore:
    return BenchmarkScore(
        canonical_model=model,
        raw_model=model,
        source=source,
        category=category,
        score=value,
        fetched_at=datetime.now(timezone.utc),
    )


def test_rank_orders_by_weighted_composite() -> None:
    # ``reason`` weights: livebench/reasoning=0.6, livebench/mathematics=0.4
    scores = [
        _score("alpha", "livebench", "reasoning", 80),
        _score("alpha", "livebench", "mathematics", 60),
        _score("beta", "livebench", "reasoning", 70),
        _score("beta", "livebench", "mathematics", 90),
    ]
    rankings = rank_task("reason", scores)
    # alpha: 0.6*80 + 0.4*60 = 72; beta: 0.6*70 + 0.4*90 = 78
    assert [r.canonical_model for r in rankings] == ["beta", "alpha"]
    assert rankings[0].composite_score == pytest.approx(78.0)
    assert rankings[1].composite_score == pytest.approx(72.0)


def test_rank_keeps_models_with_partial_coverage_and_reports_ratio() -> None:
    """Partial coverage no longer drops the model — it reweights against
    present components and flags coverage for the caller to filter on."""
    scores = [
        _score("alpha", "livebench", "reasoning", 80),
        _score("alpha", "livebench", "mathematics", 60),
        _score("beta", "livebench", "reasoning", 99),
        # beta missing mathematics → coverage 0.6 (the reasoning weight).
    ]
    rankings = {r.canonical_model: r for r in rank_task("reason", scores)}
    assert set(rankings) == {"alpha", "beta"}
    assert rankings["alpha"].coverage_ratio == pytest.approx(1.0)
    assert rankings["beta"].coverage_ratio == pytest.approx(0.6)
    # beta's composite is reweighted: 99 * 0.6 / 0.6 = 99
    assert rankings["beta"].composite_score == pytest.approx(99.0)


def test_rank_drops_models_with_zero_components() -> None:
    scores = [_score("alpha", "livebench", "reasoning", 50)]
    # beta has no scores at all — never appears in by_model so isn't ranked.
    rankings = rank_task("reason", scores)
    assert [r.canonical_model for r in rankings] == ["alpha"]
    assert rankings[0].coverage_ratio == pytest.approx(0.6)


def test_rank_unknown_task_type_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        rank_task("not-a-task", [])


def test_rank_normalizes_when_weights_dont_sum_to_one(monkeypatch) -> None:
    """A misconfigured map shouldn't silently scale composite scores."""
    fake = [
        BenchmarkRef("livebench", "reasoning", 2.0),
        BenchmarkRef("livebench", "mathematics", 2.0),
    ]
    monkeypatch.setitem(TASK_BENCHMARKS, "reason", fake)
    scores = [
        _score("alpha", "livebench", "reasoning", 80),
        _score("alpha", "livebench", "mathematics", 60),
    ]
    rankings = rank_task("reason", scores)
    # (2*80 + 2*60) / 4 = 70 — same as if weights were (0.5, 0.5).
    assert rankings[0].composite_score == pytest.approx(70.0)


def test_rank_returns_empty_when_no_scores_at_all() -> None:
    assert rank_task("reason", []) == []


def test_rank_components_list_carries_provenance() -> None:
    """``code`` blends Aider + two LiveBench categories; ranking must
    expose every component."""
    scores = [
        _score("alpha", "aider", "polyglot", 80),
        _score("alpha", "livebench", "coding", 60),
        _score("alpha", "livebench", "agentic_coding", 70),
    ]
    rankings = rank_task("code", scores)
    sources = {c.source for c in rankings[0].components}
    assert sources == {"aider", "livebench"}
    categories = {c.category for c in rankings[0].components}
    assert categories == {"polyglot", "coding", "agentic_coding"}
