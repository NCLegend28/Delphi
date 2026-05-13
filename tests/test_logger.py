"""Tests for ``telemetry/logger.py``.

Asserts the JSONL contract: every required field present, vault_write
serialized as a nested object, timestamps in the configured timezone, and
write failures swallowed instead of raised.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from telemetry.logger import RequestLogger, make_record


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _base_record_kwargs() -> dict[str, object]:
    return {
        "request_id": "req_abc123",
        "client_id": "agentrig-m4",
        "task_type": "code",
        "classifier_confidence": 0.92,
        "model": "qwen2.5-coder:14b",
        "latency_ms": 1840,
        "ttft_ms": 220,
        "input_tokens": 412,
        "output_tokens": 1103,
    }


async def test_log_writes_one_jsonl_line_per_call(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    await logger.log(make_record(**_base_record_kwargs()))  # type: ignore[arg-type]
    await logger.log(make_record(**{**_base_record_kwargs(), "request_id": "req_xyz"}))  # type: ignore[arg-type]

    lines = _read_lines(tmp_path / "requests.jsonl")
    assert len(lines) == 2
    assert lines[0]["request_id"] == "req_abc123"
    assert lines[1]["request_id"] == "req_xyz"


async def test_log_includes_every_schema_field(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    record = make_record(
        **_base_record_kwargs(),  # type: ignore[arg-type]
        vault_write={"ok": True, "path": "conversations/2026-05-10/x.md"},
    )
    await logger.log(record)
    line = _read_lines(tmp_path / "requests.jsonl")[0]

    expected_keys = {
        "ts",
        "request_id",
        "client_id",
        "task_type",
        "classifier_confidence",
        "model",
        "latency_ms",
        "ttft_ms",
        "input_tokens",
        "output_tokens",
        "vault_write",
        "error",
    }
    assert expected_keys.issubset(line.keys()), expected_keys - line.keys()
    assert line["vault_write"] == {
        "ok": True,
        "path": "conversations/2026-05-10/x.md",
        "error": None,
    }


async def test_timestamp_is_rendered_in_configured_timezone(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    ts_utc = datetime(2026, 5, 10, 19, 32, 18, tzinfo=timezone.utc)
    await logger.log(make_record(**_base_record_kwargs()), ts=ts_utc)  # type: ignore[arg-type]

    line = _read_lines(tmp_path / "requests.jsonl")[0]
    ts = str(line["ts"])
    # 19:32 UTC → 14:32 in Chicago (CDT, UTC-5) in May.
    assert ts.startswith("2026-05-10T14:32:18")
    assert ts.endswith("-05:00")


async def test_vault_write_failure_is_serialized(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    record = make_record(
        **_base_record_kwargs(),  # type: ignore[arg-type]
        vault_write={"ok": False, "path": None, "error": "permission denied"},
    )
    await logger.log(record)
    line = _read_lines(tmp_path / "requests.jsonl")[0]
    assert line["vault_write"] == {"ok": False, "path": None, "error": "permission denied"}


async def test_extras_are_added_but_do_not_overwrite_schema(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    record = make_record(
        **_base_record_kwargs(),  # type: ignore[arg-type]
        retry_count=2,
        task_type_override="ignored",  # extras can't clobber a real key
    )
    await logger.log(record)
    line = _read_lines(tmp_path / "requests.jsonl")[0]
    assert line["task_type"] == "code"
    assert line["retry_count"] == 2


async def test_log_does_not_raise_when_directory_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "logs"
    blocker.touch()  # logs path is a file → mkdir would fail
    logger = RequestLogger(blocker, timezone="America/Chicago")
    # Must return cleanly even though the underlying write is impossible.
    await logger.log(make_record(**_base_record_kwargs()))  # type: ignore[arg-type]


async def test_each_line_is_valid_json(tmp_path: Path) -> None:
    logger = RequestLogger(tmp_path, timezone="America/Chicago")
    for i in range(5):
        await logger.log(make_record(**{**_base_record_kwargs(), "request_id": f"r{i}"}))  # type: ignore[arg-type]
    raw = (tmp_path / "requests.jsonl").read_text().splitlines()
    assert len(raw) == 5
    for line in raw:
        json.loads(line)  # raises on malformed JSON


def test_make_record_accepts_missing_vault_write() -> None:
    record = make_record(**_base_record_kwargs())  # type: ignore[arg-type]
    assert record.vault_write is None


def test_make_record_packs_extras_into_dataclass_field() -> None:
    record = make_record(**_base_record_kwargs(), client_label="local")  # type: ignore[arg-type]
    assert record.extra == {"client_label": "local"}
