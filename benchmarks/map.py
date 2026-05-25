"""Task type → weighted blend of leaderboard scores.

This is the opinionated layer of the pipeline. Every entry in
``TASK_BENCHMARKS`` declares: for the Delphi task of *this* type, the
composite quality score is a weighted sum of these (source, category)
pairs. Tune as evidence accumulates from real Delphi traffic.

Conventions:

- Weights within a task should sum to 1.0. ``rank.rank_task`` normalizes
  if they don't, but keeping the sum at 1.0 makes the file easier to
  read.
- A task that requires a category not present for some model causes that
  model to be dropped from the ranking — partial-blind scoring would
  silently mis-rank.
- Only reference (source, category) pairs that actually exist. Run
  ``uv run python -m benchmarks tasks`` after edits as a sanity check.

The task types must match ``routing.roster.TASK_TYPES``.
"""

from __future__ import annotations

from typing import NamedTuple


class BenchmarkRef(NamedTuple):
    """One component of a task's composite score."""

    source: str
    category: str
    weight: float


TASK_BENCHMARKS: dict[str, list[BenchmarkRef]] = {
    "chat": [
        BenchmarkRef("livebench", "instruction_following", 0.5),
        BenchmarkRef("livebench", "language", 0.5),
    ],
    "code": [
        # Aider covers mostly frontier proprietary models. LiveBench covers
        # the open-weight tier that matters for *local* selection. Keep
        # LiveBench's combined weight at 0.6 so LiveBench-only models still
        # clear the default 0.5 coverage threshold.
        BenchmarkRef("aider", "polyglot", 0.4),
        BenchmarkRef("livebench", "coding", 0.3),
        # ``agentic_coding`` is LiveBench's python/js/ts subset — closer
        # to the actual workflow this slot serves.
        BenchmarkRef("livebench", "agentic_coding", 0.3),
    ],
    "deep_code": [
        # ``deep_code`` is the 32B-class slot — Aider's longer-form edits
        # better predict its value than LiveBench's shorter snippets, so
        # weight Aider higher here. LiveBench combined = 0.5, exactly at
        # the default coverage threshold for LiveBench-only models.
        BenchmarkRef("aider", "polyglot", 0.5),
        BenchmarkRef("livebench", "coding", 0.25),
        BenchmarkRef("livebench", "agentic_coding", 0.25),
    ],
    "reason": [
        BenchmarkRef("livebench", "reasoning", 0.6),
        BenchmarkRef("livebench", "mathematics", 0.4),
    ],
    "deep_reason": [
        BenchmarkRef("livebench", "reasoning", 0.7),
        BenchmarkRef("livebench", "mathematics", 0.3),
    ],
    "multilingual": [
        # LiveBench's language category is English-only; this is a stub
        # until a real multilingual source (MGSM, Belebele, Aya) lands.
        BenchmarkRef("livebench", "language", 1.0),
    ],
    "vault_query": [
        # Best proxies until a hallucination/factuality source is wired.
        BenchmarkRef("livebench", "instruction_following", 0.5),
        BenchmarkRef("livebench", "reasoning", 0.5),
    ],
}
