"""Tests for the Ollama library availability helper.

Network is never touched — registry queries are tested by pre-populating
the cache. ``base_model_name`` is pure-function tested via parametrize.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from benchmarks.cache import Cache
from benchmarks.sources.ollama_registry import OllamaRegistry, base_model_name


@pytest.mark.parametrize(
    "canonical,expected_family",
    [
        ("qwen2.5-coder-32b", "qwen2.5-coder"),
        ("qwen3-32b-thinking", "qwen3"),
        ("deepseek-r1-32b", "deepseek-r1"),
        ("gemma-4-31b", "gemma4"),
        ("phi4-14b", "phi4"),
        ("phi3.5", "phi3.5"),  # no size suffix — passthrough
        ("qwen3-235b-a22b-thinking-2507", "qwen3"),
        ("qwen2.5-coder", "qwen2.5-coder"),
        # Parenthesized variants (snapshot date, effort, mode flag).
        ("deepseek-r1-(0528)", "deepseek-r1"),
        ("deepseek-v3.2-exp-(reasoner)", "deepseek-v3.2-exp"),
        ("deepseek-v3-(0324)", "deepseek-v3"),
        # Bare mode suffixes without parens.
        ("deepseek-v3.2-exp-thinking", "deepseek-v3.2-exp"),
        ("qwen3-32b-thinking", "qwen3"),
        # Leading <brand>-<digit> collapse (gemma-3 → gemma3).
        ("gemma-3-27b", "gemma3"),
        ("llama-4-maverick", "llama4-maverick"),
        ("phi-4", "phi4"),
        ("qwen-3", "qwen3"),
    ],
)
def test_base_model_name_strips_size_and_variants(
    canonical: str, expected_family: str
) -> None:
    assert base_model_name(canonical) == expected_family


_LIBRARY_FIXTURE = (
    '[{"name":"qwen2.5-coder","tags":["7b","14b","32b","latest"]},'
    '{"name":"gemma3","tags":["1b","4b","12b","27b"]}]'
)


def test_is_available_reads_cached_library(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("ollama_library", _LIBRARY_FIXTURE)
    registry = OllamaRegistry(cache=cache)
    assert registry.is_available("qwen2.5-coder") is True
    assert registry.tags("qwen2.5-coder") == ["7b", "14b", "32b", "latest"]
    assert registry.is_available("gemma3") is True


def test_is_available_returns_false_for_unknown_family(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("ollama_library", _LIBRARY_FIXTURE)
    registry = OllamaRegistry(cache=cache)
    assert registry.is_available("does-not-exist") is False
    assert registry.tags("does-not-exist") is None


def test_invalid_json_payload_raises(tmp_path: Path) -> None:
    cache = Cache(cache_dir=tmp_path, ttl=timedelta(hours=1))
    cache.put("ollama_library", "not json")
    with pytest.raises(RuntimeError, match="not JSON"):
        OllamaRegistry(cache=cache).is_available("qwen2.5-coder")
