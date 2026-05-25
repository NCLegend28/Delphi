"""Per-leaderboard adapters.

Each source module exports one class implementing the ``BenchmarkSource``
protocol (see ``base.py``). To add a new source: copy ``aider.py``,
swap the URL and parser, register it in ``benchmarks/cli.py``.
"""
