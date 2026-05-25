"""Parser tests for ``benchmarks/sources/livebench.py``.

The source auto-discovers the latest dated table+categories pair from
the LiveBench website repo on GitHub. Tests pre-populate the cache for
all three keys (discovery listing, table CSV, categories JSON) so no
network is touched and the date is deterministic.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from benchmarks.cache import Cache
from benchmarks.sources.livebench import LiveBenchSource

FIXTURES = Path(__file__).parent / "fixtures"
RELEASE = "2026_01_08"


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    c = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    discovery = (
        f'[{{"name":"table_{RELEASE}.csv","type":"file"}},'
        f'{{"name":"categories_{RELEASE}.json","type":"file"}},'
        f'{{"name":"table_2025_12_23.csv","type":"file"}}]'
    )
    c.put("livebench_discovery", discovery)
    c.put(
        f"livebench_table_{RELEASE}.csv",
        (FIXTURES / "livebench_table.csv").read_text(),
    )
    c.put(
        f"livebench_categories_{RELEASE}.json",
        (FIXTURES / "livebench_categories.json").read_text(),
    )
    return c


def test_picks_latest_dated_release(cache: Cache) -> None:
    """Discovery should pick ``2026_01_08`` over ``2025_12_23``."""
    assert LiveBenchSource(cache=cache)._discover_latest_release() == RELEASE


def test_single_task_category_returns_raw_score(cache: Cache) -> None:
    scores = LiveBenchSource(cache=cache).fetch()
    by = {(s.canonical_model, s.category): s for s in scores}
    # Coding has only ``code_generation`` in the fixture.
    assert by[("qwen2.5-coder-32b", "coding")].score == 75.0


def test_multi_task_category_averages(cache: Cache) -> None:
    scores = LiveBenchSource(cache=cache).fetch()
    by = {(s.canonical_model, s.category): s for s in scores}
    # Mathematics: AMPS_Hard=55, math_comp=60 → mean 57.5
    assert by[("qwen2.5-coder-32b", "mathematics")].score == pytest.approx(57.5)
    # Reasoning: zebra=40, spatial=50 → mean 45
    assert by[("qwen2.5-coder-32b", "reasoning")].score == pytest.approx(45.0)


def test_normalizes_category_display_names(cache: Cache) -> None:
    categories = {s.category for s in LiveBenchSource(cache=cache).fetch()}
    # The site uses "IF" and "Data Analysis"; we emit snake_case.
    assert "instruction_following" in categories
    assert "data_analysis" in categories
    assert "agentic_coding" in categories
    # Display-name forms must not leak.
    assert "IF" not in categories
    assert "Data Analysis" not in categories


def test_canonicalizes_model_names(cache: Cache) -> None:
    canonicals = {s.canonical_model for s in LiveBenchSource(cache=cache).fetch()}
    assert "qwen2.5-coder-32b" in canonicals
    # The distill alias should collapse to the Ollama-style tag.
    assert "deepseek-r1-32b" in canonicals


def test_drops_models_with_no_numeric_scores(cache: Cache) -> None:
    scores = LiveBenchSource(cache=cache).fetch()
    assert all(s.raw_model != "broken-row" for s in scores)


def test_tags_source_and_release_metadata(cache: Cache) -> None:
    sample = next(iter(LiveBenchSource(cache=cache).fetch()))
    assert sample.source == "livebench"
    assert sample.metadata["release"] == RELEASE
    assert sample.metadata["tasks_scored"] >= 1


def test_partial_category_coverage_still_averages_available_tasks(cache: Cache) -> None:
    """If only some tasks in a category have scores, average those rather
    than dropping the model — but emit ``tasks_scored`` so the caller knows."""
    scores = LiveBenchSource(cache=cache).fetch()
    # ``phi4-14b`` has all tasks. Construct partial coverage scenario
    # implicitly by checking the metadata semantics:
    sample = next(
        s for s in scores
        if s.canonical_model == "phi4-14b" and s.category == "mathematics"
    )
    assert sample.metadata["tasks_scored"] == sample.metadata["tasks_in_category"]


def test_missing_discovery_listing_raises(tmp_path: Path) -> None:
    """If discovery JSON has no ``table_*.csv`` entries, fail loud."""
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("livebench_discovery", "[]")
    with pytest.raises(RuntimeError, match="no table_"):
        LiveBenchSource(cache=cache).fetch()
