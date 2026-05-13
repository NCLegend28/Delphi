"""Tests for ``memory/templates.py``.

We assert the rendered shape (YAML frontmatter parses, body has the right
headers) and that user-supplied override files take precedence over the
in-module defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from memory.templates import (
    CONVERSATION_NOTE_TEMPLATE,
    DAILY_BULLET_TEMPLATE,
    ENTITY_STUB_TEMPLATE,
    TemplateRenderer,
    yaml_list,
    yaml_scalar,
)


# --- filters --------------------------------------------------------------


def test_yaml_scalar_quotes_strings() -> None:
    assert yaml_scalar("hello") == '"hello"'
    assert yaml_scalar("with \"quotes\"") == '"with \\"quotes\\""'


def test_yaml_scalar_passes_numbers_and_bools_unquoted() -> None:
    assert yaml_scalar(42) == "42"
    assert yaml_scalar(3.14) == "3.14"
    assert yaml_scalar(True) == "true"
    assert yaml_scalar(False) == "false"


def test_yaml_scalar_none_becomes_null() -> None:
    assert yaml_scalar(None) == "null"


def test_yaml_list_empty_is_brackets() -> None:
    assert yaml_list([]) == "[]"


def test_yaml_list_quotes_each_item() -> None:
    assert yaml_list(["a", "b"]) == '["a", "b"]'


# --- conversation note ----------------------------------------------------


def _conv_context(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "date": "2026-05-10T14:32:18-05:00",
        "task_type": "code",
        "models": ["qwen2.5-coder:14b"],
        "classifier_confidence": 0.92,
        "latency_ms": 1840,
        "input_tokens": 412,
        "output_tokens": 1103,
        "project": "[[AgentRig]]",
        "entities": ["[[Pydantic]]"],
        "tags": ["routing"],
        "client_id": "agentrig-m4",
        "truncated": False,
        "user_message": "refactor this",
        "assistant_message": "here you go",
    }
    base.update(overrides)
    return base


def test_conversation_note_frontmatter_parses_as_yaml() -> None:
    rendered = TemplateRenderer().render_conversation_note(**_conv_context())
    assert rendered.startswith("---\n")
    _, fm, _ = rendered.split("---\n", 2)
    parsed = yaml.safe_load(fm)
    assert parsed["task_type"] == "code"
    assert parsed["models"] == ["qwen2.5-coder:14b"]
    assert parsed["classifier_confidence"] == 0.92
    assert parsed["project"] == "[[AgentRig]]"
    assert parsed["truncated"] is False


def test_conversation_note_body_has_user_and_assistant_headers() -> None:
    rendered = TemplateRenderer().render_conversation_note(**_conv_context())
    assert "\n## User\n\nrefactor this\n" in rendered
    assert "\n## Assistant\n\nhere you go\n" in rendered


def test_conversation_note_handles_null_classifier_confidence() -> None:
    rendered = TemplateRenderer().render_conversation_note(
        **_conv_context(classifier_confidence=None, project=None, client_id=None)
    )
    _, fm, _ = rendered.split("---\n", 2)
    parsed = yaml.safe_load(fm)
    assert parsed["classifier_confidence"] is None
    assert parsed["project"] is None
    assert parsed["client_id"] is None


# --- entity stub ----------------------------------------------------------


def test_entity_stub_renders() -> None:
    rendered = TemplateRenderer().render_entity_stub(
        display="Pydantic v2",
        first_mentioned="2026-05-04",
        created="2026-05-11",
    )
    assert "type: entity" in rendered
    assert "status: stub" in rendered
    assert "first_mentioned: 2026-05-04" in rendered
    assert "# Pydantic v2" in rendered
    assert "First mentioned in a conversation on 2026-05-04." in rendered


# --- daily bullet ---------------------------------------------------------


def test_daily_bullet_renders_one_line() -> None:
    rendered = TemplateRenderer().render_daily_bullet(
        time="14-32",
        rel_path="conversations/2026-05-10/2026-05-10_14-32_refactor.md",
        task_type="code",
        latency_ms=1840,
    )
    assert rendered == (
        "- 14-32 [[conversations/2026-05-10/2026-05-10_14-32_refactor.md]] — code (1840ms)\n"
    )


# --- overrides ------------------------------------------------------------


def test_override_directory_shadows_default(tmp_path: Path) -> None:
    """A user-supplied template file with the same name wins over the default."""
    (tmp_path / ENTITY_STUB_TEMPLATE).write_text(
        "# {{ display }}\nfirst: {{ first_mentioned }}\ncustom!\n"
    )
    renderer = TemplateRenderer(override_dir=tmp_path)
    rendered = renderer.render_entity_stub(
        display="Custom", first_mentioned="2026-05-11", created="2026-05-11"
    )
    assert rendered == "# Custom\nfirst: 2026-05-11\ncustom!\n"


def test_override_directory_falls_back_for_missing_files(tmp_path: Path) -> None:
    """Override one template, keep defaults for the others."""
    (tmp_path / DAILY_BULLET_TEMPLATE).write_text("custom bullet\n")
    renderer = TemplateRenderer(override_dir=tmp_path)
    # The overridden one wins:
    assert (
        renderer.render_daily_bullet(time="x", rel_path="x", task_type="x", latency_ms=0)
        == "custom bullet\n"
    )
    # The non-overridden one still works:
    rendered = renderer.render_conversation_note(**_conv_context())
    assert rendered.startswith("---\n")


def test_strict_undefined_raises_on_missing_context() -> None:
    """Missing template variables fail loud — caught in tests, not in production."""
    from jinja2 import UndefinedError

    renderer = TemplateRenderer()
    with pytest.raises(UndefinedError):
        renderer.render_conversation_note(date="now")  # everything else missing


# --- ensure template names stay in sync ---


def test_template_name_constants_are_consistent() -> None:
    """The constants the rest of the codebase imports must match the loader keys."""
    renderer = TemplateRenderer()
    for name in (CONVERSATION_NOTE_TEMPLATE, ENTITY_STUB_TEMPLATE, DAILY_BULLET_TEMPLATE):
        assert renderer._env.get_template(name) is not None
