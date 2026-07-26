"""Tests for the nursery CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nursery import cli
from nursery.records import ChildAttemptRecord


def test_list_candidates_prints_configured_children(capsys: Any) -> None:
    assert cli.main(["list-candidates"]) == 0
    out = capsys.readouterr().out

    assert "phi-3.5-mini-q6" in out
    assert "qwen2.5-coder-7b-q4" in out
    assert "GB" in out


def test_run_seed_refuses_unknown_candidate(tmp_path: Path, capsys: Any) -> None:
    code = cli.main(
        [
            "run-seed",
            "--candidate",
            "not-real",
            "--child-base-url",
            "http://127.0.0.1:18080/v1",
            "--parent-base-url",
            "http://127.0.0.1:8090/v1",
            "--parent-model",
            "delphi-auto",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    err = capsys.readouterr().err
    assert code == 2
    assert "unknown candidate" in err


def test_run_seed_requires_child_runtime_url_without_manifest_runtime(
    tmp_path: Path,
    capsys: Any,
) -> None:
    code = cli.main(
        [
            "run-seed",
            "--candidate",
            "phi-3.5-mini-q6",
            "--parent-base-url",
            "http://127.0.0.1:8090/v1",
            "--parent-model",
            "delphi-auto",
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    err = capsys.readouterr().err
    assert code == 2
    assert "--child-base-url" in err


def test_run_seed_calls_runner_once(monkeypatch: Any, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_run_curriculum_item(**kwargs: Any) -> ChildAttemptRecord:
        calls.append(kwargs)
        return ChildAttemptRecord(
            task_type=kwargs["item"].task_type,
            candidate=kwargs["candidate"].name,
            prompt_id=kwargs["item"].id,
            prompt=kwargs["item"].prompt,
            child_output="fake",
            parent_score=1.0,
            parent_passed=True,
            rubric_notes="ok",
            failure_modes=[],
            repair=None,
        )

    monkeypatch.setattr(cli, "run_curriculum_item", fake_run_curriculum_item)
    output_path = tmp_path / "out.jsonl"

    code = cli.main(
        [
            "run-seed",
            "--candidate",
            "phi-3.5-mini-q6",
            "--child-base-url",
            "http://127.0.0.1:18080/v1",
            "--parent-base-url",
            "http://127.0.0.1:8090/v1",
            "--parent-model",
            "delphi-auto",
            "--limit",
            "1",
            "--child-max-tokens",
            "2048",
            "--parent-max-tokens",
            "4096",
            "--child-temperature",
            "0.4",
            "--parent-temperature",
            "0.1",
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    assert len(calls) == 1
    assert calls[0]["candidate"].name == "phi-3.5-mini-q6"
    assert calls[0]["parent_model"] == "delphi-auto"
    assert calls[0]["output_path"] == output_path
    assert calls[0]["child_max_tokens"] == 2048
    assert calls[0]["parent_max_tokens"] == 4096
    assert calls[0]["child_temperature"] == 0.4
    assert calls[0]["parent_temperature"] == 0.1
