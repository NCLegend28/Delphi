"""Ollama library availability check.

Used to filter the leaderboard ranking down to models that Tali can
actually pull onto the Proxmox VM. A 30-point leaderboard winner that
nobody has packaged for Ollama is useless to us — better to know that
upfront than to chase the name into a dead end.

Data source
-----------
We fetch the full Ollama library listing once and cache it for 24h, then
match locally. The official ``registry.ollama.ai`` Docker v2 endpoint
blocks anonymous tags lookups (returns 404), so we use a community-
maintained JSON mirror at ``ollama-models.zwz.workers.dev``. Format::

    [
      {"name": "qwen2.5-coder", "description": "...", "tags": ["7b","14b","32b",...]},
      ...
    ]

If the mirror goes away the failure is loud — empty rankings for any
``--ollama-only`` query — and the URL constant is the one knob to turn.

Name matching
-------------
Leaderboard canonicals carry the size and variant tag (``qwen2.5-coder-32b``,
``deepseek-r1-(0528)``, ``gemma-3-27b``). Ollama library slugs do not
(``qwen2.5-coder``, ``deepseek-r1``, ``gemma3``). ``base_model_name``
strips size, paren-variants, and mode suffixes, then collapses the
leading ``<brand>-<digit>`` dash (gemma-3 → gemma3) which is the most
common leaderboard-vs-Ollama separator mismatch.
"""

from __future__ import annotations

import json
import re

import httpx

from benchmarks.cache import Cache

_LIBRARY_URL = "https://ollama-models.zwz.workers.dev/"
_LIBRARY_CACHE_KEY = "ollama_library"

# Suffix-stripping patterns. Applied repeatedly so a name like
# ``deepseek-r1-32b-thinking-(0528)`` collapses to ``deepseek-r1`` in
# one pass through the loop.
_SIZE_SUFFIX = re.compile(r"-\d+(?:\.\d+)?[bm](?:-.*)?$", re.IGNORECASE)
_PAREN_SUFFIX = re.compile(r"-?\([^)]*\)$")
_MODE_SUFFIX = re.compile(
    r"-(thinking|think|no-?think|reasoner|reason|chat|instruct)(?:-.*)?$",
    re.IGNORECASE,
)
# Leading ``<brand>-<digit>`` dash that distinguishes leaderboard naming
# (``gemma-3``, ``llama-4``, ``phi-4``, ``qwen-3``) from Ollama's
# (``gemma3``, ``llama4``, ``phi4``, ``qwen3``). Applied only at the
# string start so we don't damage embedded version numbers like
# ``deepseek-r1`` (where the second segment isn't a leading digit anyway).
_LEADING_LETTER_DIGIT = re.compile(r"^([a-z]+)-(\d)")


def base_model_name(canonical: str) -> str:
    """Strip size, paren-variants, and mode suffixes to match an Ollama URL slug.

    Examples:
        ``qwen2.5-coder-32b``           → ``qwen2.5-coder``
        ``qwen3-32b-thinking``          → ``qwen3``
        ``deepseek-r1-(0528)``          → ``deepseek-r1``
        ``deepseek-v3.2-exp-thinking``  → ``deepseek-v3.2-exp``
        ``gemma-3-27b``                 → ``gemma3``
        ``llama-4-maverick``            → ``llama4-maverick``
        ``phi3.5``                      → ``phi3.5``

    Best-effort — leaderboard naming is inconsistent and combinations
    (``model-a-+-model-b``) aren't mapped. Confirm the suggestion against
    ``ollama.com/library/<family>`` before pulling.
    """
    n = canonical
    for _ in range(4):
        prev = n
        n = _PAREN_SUFFIX.sub("", n)
        n = _SIZE_SUFFIX.sub("", n)
        n = _MODE_SUFFIX.sub("", n)
        if n == prev:
            break
    n = n.rstrip("-")
    n = _LEADING_LETTER_DIGIT.sub(r"\1\2", n)
    return n


class OllamaRegistry:
    """Cached lookup against the full Ollama library listing."""

    def __init__(
        self,
        cache: Cache | None = None,
        client: httpx.Client | None = None,
        url: str = _LIBRARY_URL,
    ) -> None:
        self._cache = cache or Cache()
        self._client = client or httpx.Client(timeout=30.0)
        self._url = url
        self._families: dict[str, list[str]] | None = None

    def is_available(self, family: str) -> bool:
        """True if ``family`` is a known Ollama library slug."""
        return self.tags(family) is not None

    def tags(self, family: str) -> list[str] | None:
        """Return the pullable tag list for ``family``, or ``None``."""
        return self._library().get(family)

    # --- internals -------------------------------------------------------

    def _library(self) -> dict[str, list[str]]:
        if self._families is not None:
            return self._families
        raw = self._cache.get(_LIBRARY_CACHE_KEY)
        if raw is None:
            response = self._client.get(self._url)
            response.raise_for_status()
            raw = response.text
            self._cache.put(_LIBRARY_CACHE_KEY, raw)
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Ollama library payload from {self._url} is not JSON"
            ) from exc
        self._families = {
            str(entry["name"]): list(entry.get("tags", []))
            for entry in data
            if isinstance(entry, dict) and "name" in entry
        }
        return self._families
