"""Command-line interface for the benchmarks pipeline.

Usage::

    uv run python -m benchmarks tasks
    uv run python -m benchmarks fetch [--source aider|livebench]
    uv run python -m benchmarks rank --task code [--top 15] [--ollama-only]

This module is the only place that knows the full source registry. New
sources land in ``sources/`` and get one line in ``_SOURCES`` below.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from benchmarks.cache import Cache
from benchmarks.map import TASK_BENCHMARKS
from benchmarks.models import BenchmarkScore, ModelRanking
from benchmarks.rank import rank_task
from benchmarks.sources.aider import AiderSource
from benchmarks.sources.base import BenchmarkSource
from benchmarks.sources.livebench import LiveBenchSource
from benchmarks.sources.ollama_registry import OllamaRegistry, base_model_name


def _build_sources(cache: Cache) -> dict[str, BenchmarkSource]:
    """Construct every source adapter. Add new ones here."""
    return {
        "aider": AiderSource(cache=cache),
        "livebench": LiveBenchSource(cache=cache),
    }


def _gather_scores(
    cache: Cache,
    on_error: callable = lambda name, exc: print(  # type: ignore[assignment]
        f"warn: {name} fetch failed: {exc}", file=sys.stderr
    ),
) -> list[BenchmarkScore]:
    """Fetch from every source, tolerating individual failures."""
    scores: list[BenchmarkScore] = []
    for name, source in _build_sources(cache).items():
        try:
            scores.extend(source.fetch())
        except Exception as exc:  # noqa: BLE001 — CLI prints + continues
            on_error(name, exc)
    return scores


def _annotate_ollama(
    rankings: list[ModelRanking],
    registry: OllamaRegistry,
    drop_unavailable: bool,
) -> list[ModelRanking]:
    """Attach ``ollama_tag`` where the model family exists in the library.

    Leaderboard canonicals carry the size (``qwen2.5-coder-32b``); the
    Ollama library URL uses the family alone (``qwen2.5-coder``). We
    look up by family, then display ``family:size`` as the suggested
    pull tag.
    """
    out: list[ModelRanking] = []
    for ranking in rankings:
        family = base_model_name(ranking.canonical_model)
        if not registry.is_available(family):
            if drop_unavailable:
                continue
            out.append(ranking)
            continue
        # Show the family slug — the user picks the size tag from
        # ollama.com/library/<family>. Reconstructing ``family:size``
        # from a canonical that's been letter-digit-collapsed gets messy
        # and the family alone is enough to act on.
        out.append(ranking.model_copy(update={"ollama_tag": family}))
    return out


# --- subcommands ---------------------------------------------------------


def cmd_rank(args: argparse.Namespace) -> int:
    cache = Cache()
    scores = _gather_scores(cache)
    try:
        rankings = rank_task(args.task, scores)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rankings = [r for r in rankings if r.coverage_ratio >= args.min_coverage]

    if args.ollama_only or args.show_availability:
        rankings = _annotate_ollama(
            rankings,
            OllamaRegistry(cache=cache),
            drop_unavailable=args.ollama_only,
        )

    rankings = rankings[: args.top]
    _print_ranking_table(args.task, rankings, args.min_coverage)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cache = Cache()
    sources = _build_sources(cache)
    targets = [sources[args.source]] if args.source else list(sources.values())
    for source in targets:
        # Prefix bust handles every cache key the source uses, including
        # the dated keys LiveBench cycles each month.
        cache.invalidate_prefix(source.name)
        count = len(source.fetch())
        print(f"{source.name}: fetched {count} scores")
    return 0


def cmd_tasks(_: argparse.Namespace) -> int:
    for task, refs in TASK_BENCHMARKS.items():
        components = ", ".join(f"{r.source}/{r.category}×{r.weight}" for r in refs)
        print(f"{task:<15}{components}")
    return 0


# --- formatting ----------------------------------------------------------


def _print_ranking_table(
    task: str,
    rankings: list[ModelRanking],
    min_coverage: float,
) -> None:
    print(f"# task: {task}   min_coverage: {min_coverage:.2f}")
    print(
        f"{'rank':<5}{'model':<45}{'score':>8}{'cov':>7}  {'ollama':<20}"
    )
    print("-" * 90)
    if not rankings:
        print(
            "(no models met the coverage threshold — try "
            "--min-coverage 0.3 to widen the net)"
        )
        return
    for i, ranking in enumerate(rankings, 1):
        tag = ranking.ollama_tag or "—"
        print(
            f"{i:<5}{ranking.canonical_model:<45}"
            f"{ranking.composite_score:>8.2f}"
            f"{ranking.coverage_ratio:>7.2f}  {tag:<20}"
        )


# --- entry point ---------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmarks",
        description="Rank LLMs per Delphi task type from public leaderboards.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rank = sub.add_parser("rank", help="rank models for a task type")
    p_rank.add_argument("--task", required=True, choices=sorted(TASK_BENCHMARKS))
    p_rank.add_argument("--top", type=int, default=15)
    p_rank.add_argument(
        "--min-coverage",
        type=float,
        default=0.5,
        help=(
            "drop rankings where fewer than this fraction of the task's "
            "weighted components were scored (default 0.5)"
        ),
    )
    p_rank.add_argument(
        "--ollama-only",
        action="store_true",
        help="exclude models not present in the Ollama library",
    )
    p_rank.add_argument(
        "--show-availability",
        action="store_true",
        help="annotate ranked rows with their Ollama tag if available",
    )
    p_rank.set_defaults(func=cmd_rank)

    p_fetch = sub.add_parser("fetch", help="force-refresh leaderboard caches")
    p_fetch.add_argument("--source", choices=("aider", "livebench"))
    p_fetch.set_defaults(func=cmd_fetch)

    p_tasks = sub.add_parser("tasks", help="list configured task→benchmark mappings")
    p_tasks.set_defaults(func=cmd_tasks)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
