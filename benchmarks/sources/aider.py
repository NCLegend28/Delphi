"""Aider polyglot coding leaderboard.

Source: ``polyglot_leaderboard.yml`` in the Aider repo on GitHub.

The polyglot test asks each model to make real edits to real files in
six languages (C++, Go, Java, JavaScript, Python, Rust). It's the
single best signal for "is this model useful as a coding assistant"
because it measures the *full loop* (read code, propose a diff, apply
correctly), not synthesis from a clean prompt. ``code`` and
``deep_code`` task rankings should weight this heavily.

Verify the URL on update — Aider has moved the file before. Search
their repo for ``polyglot_leaderboard.yml`` if the fetch starts failing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import yaml

from benchmarks.cache import Cache
from benchmarks.models import BenchmarkScore
from benchmarks.normalize import canonicalize

_AIDER_YAML_URL = (
    "https://raw.githubusercontent.com/Aider-AI/aider/main/"
    "aider/website/_data/polyglot_leaderboard.yml"
)


class AiderSource:
    """Adapter for the Aider polyglot leaderboard."""

    name = "aider"

    def __init__(
        self,
        cache: Cache | None = None,
        client: httpx.Client | None = None,
        url: str = _AIDER_YAML_URL,
    ) -> None:
        self._cache = cache or Cache()
        self._client = client or httpx.Client(timeout=30.0)
        self._url = url

    def fetch(self) -> list[BenchmarkScore]:
        cached = self._cache.get(f"{self.name}.yml")
        if cached is None:
            response = self._client.get(self._url)
            response.raise_for_status()
            cached = response.text
            self._cache.put(f"{self.name}.yml", cached)
        return list(self._parse(cached))

    @staticmethod
    def _parse(raw: str) -> list[BenchmarkScore]:
        """Parse the YAML payload into ``BenchmarkScore`` rows.

        Aider's schema: a list of dicts with ``model`` plus per-attempt
        pass rates (``pass_rate_1``, ``pass_rate_2``). We prefer the
        second-attempt rate because it reflects iterative debugging,
        which is closer to how the model is actually used in a chat
        loop. Fall back to first-attempt if only that's present.
        """
        data = yaml.safe_load(raw)
        if not isinstance(data, list):
            return []

        now = datetime.now(timezone.utc)
        out: list[BenchmarkScore] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            model = row.get("model")
            score = row.get("pass_rate_2", row.get("pass_rate_1"))
            if model is None or score is None:
                continue
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            out.append(
                BenchmarkScore(
                    canonical_model=canonicalize(str(model)),
                    raw_model=str(model),
                    source="aider",
                    category="polyglot",
                    score=value,
                    fetched_at=now,
                    metadata={k: v for k, v in row.items() if k != "model"},
                )
            )
        return out
