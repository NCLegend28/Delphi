"""Tests for ``memory/vault.py``.

Uses ``tmp_path`` so every test writes into a fresh, throwaway vault. Asserts:
- the frontmatter parses as YAML and contains the expected fields,
- the conversation file lives at ``conversations/YYYY-MM-DD/...`` with a slugged name,
- the daily rollup is appended (not overwritten) across multiple writes,
- failures (e.g. unwritable vault) return ``ok=False`` rather than raising.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from memory.vault import ConversationNote, VaultWriter, _slugify


def _note(**overrides: object) -> ConversationNote:
    defaults: dict[str, object] = {
        "timestamp": datetime(2026, 5, 10, 19, 32, 18, tzinfo=timezone.utc),
        "task_type": "code",
        "models": ["qwen2.5-coder:14b"],
        "classifier_confidence": 0.92,
        "latency_ms": 1840,
        "input_tokens": 412,
        "output_tokens": 1103,
        "user_message": "refactor this Python function please",
        "assistant_message": "Sure — here is the refactored version.",
        "project": "[[AgentRig]]",
        "entities": ["[[cosine-similarity-routing]]", "[[Pydantic]]"],
        "tags": ["routing", "debugging"],
        "client_id": "agentrig-m4",
    }
    defaults.update(overrides)
    return ConversationNote(**defaults)  # type: ignore[arg-type]


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    assert text.startswith("---\n"), "note must begin with YAML frontmatter"
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


# --- pure helpers ---------------------------------------------------------


def test_slugify_handles_empty_input() -> None:
    assert _slugify("   ") == "untitled"


def test_slugify_strips_punctuation_and_caps() -> None:
    assert _slugify("Refactor THIS, please!!!") == "refactor-this-please"


def test_slugify_truncates_long_text() -> None:
    out = _slugify("a" * 200)
    assert len(out) <= 50


# --- write() --------------------------------------------------------------


async def test_write_returns_ok_and_relative_path(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    result = await writer.write(_note())
    assert result.ok is True
    assert result.error is None
    assert result.path is not None
    assert result.path.startswith("conversations/2026-05-10/")


async def test_write_creates_conversation_file_with_expected_name(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note())
    # 19:32 UTC → 14:32 Chicago (May, CDT is UTC-5)
    conv_dir = tmp_path / "conversations" / "2026-05-10"
    files = list(conv_dir.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("2026-05-10_14-32_refactor-this-python-function")


async def test_frontmatter_parses_and_carries_every_field(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note())
    conv_file = next((tmp_path / "conversations" / "2026-05-10").iterdir())
    fm, body = _split_frontmatter(conv_file.read_text())
    assert fm["task_type"] == "code"
    assert fm["models"] == ["qwen2.5-coder:14b"]
    assert fm["classifier_confidence"] == 0.92
    assert fm["latency_ms"] == 1840
    assert fm["project"] == "[[AgentRig]]"
    assert fm["entities"] == ["[[cosine-similarity-routing]]", "[[Pydantic]]"]
    assert fm["tags"] == ["routing", "debugging"]
    assert fm["client_id"] == "agentrig-m4"
    assert fm["truncated"] is False
    assert "## User" in body
    assert "## Assistant" in body
    assert "refactor this Python function please" in body


async def test_daily_rollup_appends_one_bullet_per_write(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note(user_message="first thing"))
    await writer.write(
        _note(
            timestamp=datetime(2026, 5, 10, 21, 0, 0, tzinfo=timezone.utc),
            user_message="second thing",
        )
    )
    rollup = (tmp_path / "daily" / "2026-05-10.md").read_text()
    bullets = [line for line in rollup.splitlines() if line.startswith("- ")]
    assert len(bullets) == 2
    assert "first" not in rollup.lower() or "second" not in rollup.lower() or "14-32" in rollup
    assert "16-00" in rollup  # 21:00 UTC → 16:00 Chicago


async def test_truncated_flag_propagates_to_frontmatter(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note(truncated=True))
    conv_file = next((tmp_path / "conversations" / "2026-05-10").iterdir())
    fm, _ = _split_frontmatter(conv_file.read_text())
    assert fm["truncated"] is True


async def test_write_does_not_raise_on_unwritable_vault(tmp_path: Path) -> None:
    bad_vault = tmp_path / "does-not-exist"
    bad_vault.touch()  # vault path is a *file*, so mkdir will fail
    writer = VaultWriter(bad_vault, timezone="America/Chicago")
    result = await writer.write(_note())
    assert result.ok is False
    assert result.error
    assert result.path is None


async def test_project_notes_folder_is_never_touched(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note())
    assert not (tmp_path / "projects").exists(), "service must not auto-create project notes"


@pytest.mark.parametrize("project_value", [None, "[[AgentRig]]"])
async def test_null_project_renders_as_yaml_null(tmp_path: Path, project_value: str | None) -> None:
    writer = VaultWriter(tmp_path, timezone="America/Chicago")
    await writer.write(_note(project=project_value))
    conv_file = next((tmp_path / "conversations" / "2026-05-10").iterdir())
    fm, _ = _split_frontmatter(conv_file.read_text())
    if project_value is None:
        assert fm["project"] is None
    else:
        assert fm["project"] == project_value
