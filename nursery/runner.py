"""Runner for one Delphi nursery child-answer → parent-critique cycle."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Protocol

from nursery.candidates import ChildCandidate
from nursery.curriculum import CurriculumItem
from nursery.judge import JudgeParseError, build_judge_messages, parse_parent_critique
from nursery.records import ChildAttemptRecord

DEFAULT_CHILD_TEMPERATURE = 0.2
DEFAULT_CHILD_MAX_TOKENS = 2048
DEFAULT_PARENT_TEMPERATURE = 0.0
DEFAULT_PARENT_MAX_TOKENS = 2048


class ChatCompleter(Protocol):
    """Protocol shared by real and fake OpenAI-compatible chat clients."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str: ...


async def run_curriculum_item(
    *,
    item: CurriculumItem,
    child: ChatCompleter,
    parent: ChatCompleter,
    candidate: ChildCandidate,
    output_path: Path,
    parent_model: str,
    child_temperature: float = DEFAULT_CHILD_TEMPERATURE,
    child_max_tokens: int = DEFAULT_CHILD_MAX_TOKENS,
    parent_temperature: float = DEFAULT_PARENT_TEMPERATURE,
    parent_max_tokens: int = DEFAULT_PARENT_MAX_TOKENS,
) -> ChildAttemptRecord:
    """Run one curriculum item and append a durable JSONL attempt record."""
    started = perf_counter()
    child_output = await child.complete(
        model=candidate.name,
        messages=[{"role": "user", "content": item.prompt}],
        temperature=child_temperature,
        max_tokens=child_max_tokens,
    )
    latency_ms = int((perf_counter() - started) * 1000)

    parent_output = await parent.complete(
        model=parent_model,
        messages=build_judge_messages(item=item, child_output=child_output),
        temperature=parent_temperature,
        max_tokens=parent_max_tokens,
    )

    try:
        critique = parse_parent_critique(parent_output)
    except JudgeParseError as exc:
        record = ChildAttemptRecord(
            task_type=item.task_type,
            candidate=candidate.name,
            prompt_id=item.id,
            prompt=item.prompt,
            child_output=child_output,
            parent_score=None,
            parent_passed=None,
            rubric_notes="parent critique parse failed",
            failure_modes=[],
            repair=None,
            parent_parse_error=str(exc),
            latency_ms=latency_ms,
        )
    else:
        record = ChildAttemptRecord(
            task_type=item.task_type,
            candidate=candidate.name,
            prompt_id=item.id,
            prompt=item.prompt,
            child_output=child_output,
            parent_score=critique.score,
            parent_passed=critique.passed,
            rubric_notes=critique.rubric_notes,
            failure_modes=critique.failure_modes,
            repair=critique.repair,
            latency_ms=latency_ms,
        )

    append_jsonl(output_path, record)
    return record


def append_jsonl(path: Path, record: ChildAttemptRecord) -> None:
    """Append one JSONL record, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json_line())
