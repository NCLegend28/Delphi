"""Command-line interface for Delphi model nursery evaluations."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from nursery.candidates import DEFAULT_CHILD_CANDIDATES, ChildCandidate, RuntimeEndpoint
from nursery.client import NurseryChatClient
from nursery.curriculum import CurriculumItem, iter_seed_items
from nursery.runner import (
    DEFAULT_CHILD_MAX_TOKENS,
    DEFAULT_CHILD_TEMPERATURE,
    DEFAULT_PARENT_MAX_TOKENS,
    DEFAULT_PARENT_TEMPERATURE,
    run_curriculum_item,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the nursery CLI parser."""
    parser = argparse.ArgumentParser(prog="python -m nursery.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-candidates", help="List configured child candidates")

    run_seed = subparsers.add_parser("run-seed", help="Run seed curriculum against a child")
    run_seed.add_argument("--candidate", required=True)
    run_seed.add_argument("--child-base-url", default=os.getenv("DELPHI_NURSERY_CHILD_BASE_URL"))
    run_seed.add_argument(
        "--child-api-key-env",
        default=_default_api_key_env("DELPHI_NURSERY_CHILD_API_KEY"),
    )
    run_seed.add_argument("--parent-base-url", default=os.getenv("DELPHI_NURSERY_PARENT_BASE_URL"))
    run_seed.add_argument(
        "--parent-api-key-env",
        default=_default_api_key_env("DELPHI_NURSERY_PARENT_API_KEY"),
    )
    run_seed.add_argument("--parent-model", default=os.getenv("DELPHI_NURSERY_PARENT_MODEL"))
    run_seed.add_argument("--child-temperature", type=float, default=DEFAULT_CHILD_TEMPERATURE)
    run_seed.add_argument("--child-max-tokens", type=int, default=DEFAULT_CHILD_MAX_TOKENS)
    run_seed.add_argument("--parent-temperature", type=float, default=DEFAULT_PARENT_TEMPERATURE)
    run_seed.add_argument("--parent-max-tokens", type=int, default=DEFAULT_PARENT_MAX_TOKENS)
    run_seed.add_argument("--limit", type=int, default=None)
    run_seed.add_argument("--output", type=Path, required=True)

    return parser


def _default_api_key_env(env_name: str) -> str | None:
    """Use a Doppler-provided API key env var by default only when it exists."""
    return env_name if os.getenv(env_name) else None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the nursery CLI and return a process-style exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command == "list-candidates":
        _print_candidates()
        return 0

    if args.command == "run-seed":
        return _run_seed(args)

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_candidates() -> None:
    for candidate in DEFAULT_CHILD_CANDIDATES.values():
        tasks = ",".join(candidate.task_types)
        print(
            f"{candidate.name}\t{candidate.repo}:{candidate.quant}\t"
            f"{candidate.gguf_size_gb:.2f} GB\t{tasks}"
        )


def _run_seed(args: argparse.Namespace) -> int:
    candidate = DEFAULT_CHILD_CANDIDATES.get(args.candidate)
    if candidate is None:
        print(f"unknown candidate: {args.candidate}", file=sys.stderr)
        return 2

    child_endpoint = _child_endpoint_from_args(candidate, args)
    if child_endpoint is None:
        print(
            "--child-base-url is required because the candidate manifest has no runtime",
            file=sys.stderr,
        )
        return 2

    try:
        parent_base_url = _required_arg_or_env(
            value=args.parent_base_url,
            cli_name="--parent-base-url",
            env_name="DELPHI_NURSERY_PARENT_BASE_URL",
        )
        parent_model = _required_arg_or_env(
            value=args.parent_model,
            cli_name="--parent-model",
            env_name="DELPHI_NURSERY_PARENT_MODEL",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    parent_endpoint = RuntimeEndpoint(
        base_url=parent_base_url,
        api_key_env=args.parent_api_key_env,
    )
    child_client = NurseryChatClient(child_endpoint)
    parent_client = NurseryChatClient(parent_endpoint)
    items = _items_for_candidate(candidate, args.limit)

    asyncio.run(
        _run_items(
            items=items,
            child_client=child_client,
            parent_client=parent_client,
            candidate=candidate,
            output_path=args.output,
            parent_model=parent_model,
            child_temperature=args.child_temperature,
            child_max_tokens=args.child_max_tokens,
            parent_temperature=args.parent_temperature,
            parent_max_tokens=args.parent_max_tokens,
        )
    )
    return 0


def _required_arg_or_env(*, value: str | None, cli_name: str, env_name: str) -> str:
    if value:
        return value
    raise ValueError(f"{cli_name} is required unless {env_name} is set")


def _child_endpoint_from_args(
    candidate: ChildCandidate,
    args: argparse.Namespace,
) -> RuntimeEndpoint | None:
    if args.child_base_url:
        return RuntimeEndpoint(base_url=args.child_base_url, api_key_env=args.child_api_key_env)
    return candidate.runtime


def _items_for_candidate(candidate: ChildCandidate, limit: int | None) -> list[CurriculumItem]:
    items: list[CurriculumItem] = []
    for task_type in candidate.task_types:
        items.extend(iter_seed_items(task_type))
    return items[:limit] if limit is not None else items


async def _run_items(
    *,
    items: list[CurriculumItem],
    child_client: NurseryChatClient,
    parent_client: NurseryChatClient,
    candidate: ChildCandidate,
    output_path: Path,
    parent_model: str,
    child_temperature: float,
    child_max_tokens: int,
    parent_temperature: float,
    parent_max_tokens: int,
) -> None:
    for item in items:
        await run_curriculum_item(
            item=item,
            child=child_client,
            parent=parent_client,
            candidate=candidate,
            output_path=output_path,
            parent_model=parent_model,
            child_temperature=child_temperature,
            child_max_tokens=child_max_tokens,
            parent_temperature=parent_temperature,
            parent_max_tokens=parent_max_tokens,
        )


if __name__ == "__main__":
    raise SystemExit(main())
