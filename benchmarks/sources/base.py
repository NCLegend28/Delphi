"""Protocol every source adapter implements."""

from __future__ import annotations

from typing import Protocol

from benchmarks.models import BenchmarkScore


class BenchmarkSource(Protocol):
    """One leaderboard adapter.

    Implementations should:

    - Cache the raw payload via the injected ``Cache``; never re-fetch on
      the same call.
    - Emit one ``BenchmarkScore`` per (model, category) pair. Categories
      use lowercase snake_case so ``map.py`` keys are predictable.
    - Always score as *higher is better* — invert error-rate metrics
      before emitting.
    - Fail loud on parse errors (raise). Network errors should surface to
      the CLI so missing data isn't silently treated as a zero.
    """

    name: str

    def fetch(self) -> list[BenchmarkScore]:
        ...
