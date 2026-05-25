"""Benchmark ingestion and ranking for Delphi's per-task model selection.

The roster (``routing/roster.py``) maps each task type to an Ollama model
tag. Picking which tag should serve a task is an evidence question, not a
vibes question: this package crawls public LLM leaderboards, normalizes
their results, and ranks the available local models per Delphi task type.

Run::

    uv run python -m benchmarks rank --task code --ollama-only

The ranking pipeline is three layers thin:

1. ``sources/`` — one module per leaderboard, each emitting ``BenchmarkScore``.
2. ``map.py`` — opinionated weighted blend mapping each task type to the
   benchmark categories that predict real-world quality for it.
3. ``rank.py`` — joins, weights, and sorts. ``cli.py`` prints the result.

Sources fetch over HTTPS and cache to disk (~/.cache/delphi-benchmarks) so
repeated rankings during tuning don't hammer source sites.
"""
