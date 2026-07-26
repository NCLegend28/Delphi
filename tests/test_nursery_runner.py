"""Tests for the nursery child → parent → record runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nursery.candidates import ChildCandidate
from nursery.curriculum import SEED_CURRICULUM
from nursery.records import ChildAttemptRecord
from nursery.runner import run_curriculum_item


class FakeClient:
    def __init__(self, name: str, response: str, events: list[str]) -> None:
        self.name = name
        self.response = response
        self.events = events
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        self.events.append(self.name)
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


def _candidate() -> ChildCandidate:
    return ChildCandidate(
        name="phi-3.5-mini-q6",
        repo="bartowski/Phi-3.5-mini-instruct-GGUF",
        quant="Q6_K",
        gguf_size_gb=3.14,
        task_types=["chat"],
    )


async def test_run_curriculum_item_calls_child_before_parent(tmp_path: Path) -> None:
    events: list[str] = []
    child = FakeClient("child", "child answer", events)
    parent = FakeClient(
        "parent",
        '{"score": 0.9, "passed": true, "rubric_notes": "good", '
        '"failure_modes": [], "repair": null}',
        events,
    )

    record = await run_curriculum_item(
        item=SEED_CURRICULUM["chat"][0],
        child=child,
        parent=parent,
        candidate=_candidate(),
        output_path=tmp_path / "attempts.jsonl",
        parent_model="delphi-auto",
    )

    assert events == ["child", "parent"]
    assert isinstance(record, ChildAttemptRecord)
    assert record.child_output == "child answer"
    assert record.parent_score == 0.9
    assert record.parent_passed is True


async def test_parent_receives_prompt_child_output_rubric_and_failure_modes(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    item = SEED_CURRICULUM["vault_query"][0]
    child = FakeClient("child", "child says it found an uncited note", events)
    parent = FakeClient(
        "parent",
        '{"score": 0.2, "passed": false, "rubric_notes": "not grounded", '
        '"failure_modes": ["missing_grounding"], "repair": "search first"}',
        events,
    )

    await run_curriculum_item(
        item=item,
        child=child,
        parent=parent,
        candidate=_candidate(),
        output_path=tmp_path / "attempts.jsonl",
        parent_model="delphi-auto",
    )

    parent_messages = parent.calls[0]["messages"]
    combined = "\n".join(message["content"] for message in parent_messages)
    assert item.prompt in combined
    assert item.rubric in combined
    assert "missing_grounding" in combined
    assert "child says it found an uncited note" in combined


async def test_runner_writes_one_jsonl_record(tmp_path: Path) -> None:
    events: list[str] = []
    output_path = tmp_path / "attempts.jsonl"
    child = FakeClient("child", "hello", events)
    parent = FakeClient(
        "parent",
        '{"score": 1.0, "passed": true, "rubric_notes": "ok", '
        '"failure_modes": [], "repair": null}',
        events,
    )

    await run_curriculum_item(
        item=SEED_CURRICULUM["chat"][0],
        child=child,
        parent=parent,
        candidate=_candidate(),
        output_path=output_path,
        parent_model="delphi-auto",
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["candidate"] == "phi-3.5-mini-q6"
    assert payload["parent_score"] == 1.0


async def test_failed_parent_parse_records_error_and_preserves_child_output(tmp_path: Path) -> None:
    events: list[str] = []
    child = FakeClient("child", "valuable child output", events)
    parent = FakeClient("parent", "not json", events)

    record = await run_curriculum_item(
        item=SEED_CURRICULUM["chat"][0],
        child=child,
        parent=parent,
        candidate=_candidate(),
        output_path=tmp_path / "attempts.jsonl",
        parent_model="delphi-auto",
    )

    assert record.child_output == "valuable child output"
    assert record.parent_score is None
    assert record.parent_parse_error is not None
    assert "valid JSON" in record.parent_parse_error
