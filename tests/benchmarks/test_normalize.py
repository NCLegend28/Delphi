"""Unit tests for the model-name canonicalizer.

The canonicalizer is the join key generator — silent regressions here
cause silent leaderboard join misses, which is the worst failure mode.
"""

from __future__ import annotations

import pytest

from benchmarks.normalize import canonicalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Case + separators
        ("Qwen2.5-Coder-32B-Instruct", "qwen2.5-coder-32b"),
        ("qwen2.5-coder:32b", "qwen2.5-coder-32b"),
        ("qwen2.5_coder_32b_instruct", "qwen2.5-coder-32b"),
        # Vendor prefix
        ("meta-llama/Llama-3.1-70B-Instruct", "llama-3.1-70b"),
        ("Qwen/Qwen2.5-7B-Instruct", "qwen2.5-7b"),
        # Quant suffixes
        ("phi4-14b-q4_k_m", "phi4-14b"),
        ("phi4-14b.fp16", "phi4-14b"),
        # Dated checkpoints
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("claude-3-5-sonnet-20241022", "claude-3-5-sonnet"),
        # No-op for already-clean
        ("phi3.5", "phi3.5"),
    ],
)
def test_canonicalize_produces_stable_key(raw: str, expected: str) -> None:
    assert canonicalize(raw, aliases={}) == expected


def test_aliases_override_pipeline() -> None:
    aliases = {"some-funky-name": "canonical-form"}
    assert canonicalize("some-funky-name", aliases=aliases) == "canonical-form"


def test_alias_lookup_is_case_insensitive_input() -> None:
    aliases = {"some-funky-name": "canonical-form"}
    assert canonicalize("SOME-FUNKY-NAME", aliases=aliases) == "canonical-form"


def test_deepseek_distill_aliases_collapse_to_base_id() -> None:
    """The shipped aliases.toml should join distill names to the Ollama tag."""
    # aliases.toml lives next to the module and loads automatically.
    assert canonicalize("deepseek-r1-distill-qwen-32b") == "deepseek-r1-32b"
    assert canonicalize("deepseek-r1-distill-qwen-14b") == "deepseek-r1-14b"
