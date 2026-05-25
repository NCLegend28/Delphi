"""Tests for the disk cache."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

from benchmarks.cache import Cache


def test_put_then_get_roundtrips(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("source.csv", "payload")
    assert cache.get("source.csv") == "payload"


def test_get_returns_none_when_expired(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(seconds=0))
    cache.put("source.csv", "payload")
    # Backdate the mtime so the TTL check trips.
    path = tmp_path / "source.csv"
    old = time.time() - 60
    os.utime(path, (old, old))
    assert cache.get("source.csv") is None


def test_invalidate_drops_entry(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("source.csv", "payload")
    cache.invalidate("source.csv")
    assert cache.get("source.csv") is None


def test_invalidate_prefix_drops_all_matching(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("livebench_discovery", "x")
    cache.put("livebench_table_2026_01_08.csv", "x")
    cache.put("livebench_categories_2026_01_08.json", "x")
    cache.put("aider.yml", "x")
    removed = cache.invalidate_prefix("livebench")
    assert removed == 3
    assert cache.get("livebench_discovery") is None
    assert cache.get("aider.yml") == "x"  # untouched


def test_key_sanitization_blocks_path_traversal(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("../escape.csv", "payload")
    # Should land inside tmp_path, not above it.
    assert not (tmp_path.parent / "escape.csv").exists()
    assert cache.get("../escape.csv") == "payload"
