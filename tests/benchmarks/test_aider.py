"""Parser tests for ``benchmarks/sources/aider.py``.

Network is never touched — the test pre-populates the cache with a saved
fixture and asserts the parser produces the expected ``BenchmarkScore``
shape. The fetcher's HTTP path is exercised by the smoke test in
``test_cli.py`` (skipped by default).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from benchmarks.cache import Cache
from benchmarks.sources.aider import AiderSource

FIXTURE = Path(__file__).parent / "fixtures" / "aider_polyglot.yml"


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    c = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    c.put("aider.yml", FIXTURE.read_text())
    return c


def test_aider_parser_emits_one_score_per_valid_row(cache: Cache) -> None:
    scores = AiderSource(cache=cache).fetch()
    # Five rows in the fixture, last one has no pass_rate fields.
    assert len(scores) == 4


def test_aider_parser_uses_pass_rate_2_when_present(cache: Cache) -> None:
    scores = AiderSource(cache=cache).fetch()
    by_canonical = {s.canonical_model: s for s in scores}
    # Fixture value for Qwen pass_rate_2 is 73.7
    assert by_canonical["qwen2.5-coder-32b"].score == 73.7


def test_aider_parser_canonicalizes_model_names(cache: Cache) -> None:
    scores = AiderSource(cache=cache).fetch()
    canonicals = {s.canonical_model for s in scores}
    assert "qwen2.5-coder-32b" in canonicals  # was Qwen2.5-Coder-32B-Instruct
    assert "claude-3-5-sonnet" in canonicals  # date stripped


def test_aider_parser_tags_source_and_category(cache: Cache) -> None:
    for score in AiderSource(cache=cache).fetch():
        assert score.source == "aider"
        assert score.category == "polyglot"


def test_aider_parser_preserves_raw_metadata(cache: Cache) -> None:
    scores = AiderSource(cache=cache).fetch()
    sample = next(s for s in scores if s.canonical_model == "qwen2.5-coder-32b")
    assert "percent_cases_well_formed" in sample.metadata
