"""Model name normalization for cross-source joins.

Leaderboards use different naming for the same checkpoint:

- HuggingFace:  ``Qwen2.5-Coder-32B-Instruct``
- Ollama:       ``qwen2.5-coder:32b``
- LiveBench:    ``qwen-2.5-coder-32b-instruct``

This module collapses all of these to a canonical lowercase form so
``BenchmarkScore`` records from different sources can be joined on
``canonical_model``. Automatic collapsing handles the common cases; for
edge cases, ``aliases.toml`` provides explicit overrides.

Keep the canonicalization deterministic and reversible-ish — surprises
here produce silent join misses, not loud errors.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ALIASES_PATH = Path(__file__).parent / "aliases.toml"

# Conversational/instruction suffixes that don't carry signal.
_SUFFIX_NOISE: tuple[str, ...] = (
    "-instruct",
    "-chat",
    "-it",
    "-base",
    "-hf",
)

# Quantization markers — never part of the model identity. Matches whatever
# separator survives normalization (``-`` or ``.``); ``_`` is normalized to
# ``-`` upstream so ``q4_k_m`` becomes ``q4-k-m`` before this pattern fires.
_QUANT_PATTERN = re.compile(
    r"[-.](fp16|bf16|q[0-9]+(-[0-9a-z]+)*|int[48])$",
    re.IGNORECASE,
)

# Vendor prefixes a leaderboard might attach (rare but possible).
_VENDOR_PREFIXES: tuple[str, ...] = (
    "anthropic/",
    "openai/",
    "meta-llama/",
    "qwen/",
    "deepseek-ai/",
)


def canonicalize(name: str, aliases: dict[str, str] | None = None) -> str:
    """Return the canonical join key for a model name.

    Steps: lowercase, strip vendor prefix, normalize separators to ``-``,
    strip quant markers, strip well-known suffixes, collapse runs of ``-``.
    Aliases from ``aliases.toml`` short-circuit the pipeline for entries
    that can't be reached algorithmically.
    """
    n = name.strip().lower()
    aliases = aliases if aliases is not None else load_aliases()
    if n in aliases:
        return aliases[n]

    for prefix in _VENDOR_PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break

    n = n.replace("/", "-").replace(":", "-").replace("_", "-").replace(" ", "-")
    n = _QUANT_PATTERN.sub("", n)

    # Repeated suffix strip handles e.g. "...-instruct-hf"
    stripped = True
    while stripped:
        stripped = False
        for suffix in _SUFFIX_NOISE:
            if n.endswith(suffix):
                n = n[: -len(suffix)]
                stripped = True

    while "--" in n:
        n = n.replace("--", "-")

    # Common version-style noise: trailing ``-v0.1`` and dated checkpoint
    # tags in either ``-2024-08-06`` or compact ``-20240806`` form.
    n = re.sub(r"-v\d+(\.\d+)*$", "", n)
    n = re.sub(r"-20\d{2}-?\d{2}-?\d{2}$", "", n)

    return n.strip("-")


def load_aliases() -> dict[str, str]:
    """Load the ``aliases.toml`` overrides. Empty dict if the file is missing."""
    if not ALIASES_PATH.exists():
        return {}
    with ALIASES_PATH.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("aliases", {})
    return {str(k).lower(): str(v).lower() for k, v in raw.items()}
