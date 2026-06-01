"""Tests for the UI-directive stripper used by the chat route's
non-streaming response path."""

from __future__ import annotations

from routing.directives import strip_ui_directives


def test_passthrough_when_no_brackets() -> None:
    text = "Just a normal sentence with no directives."
    assert strip_ui_directives(text) == text


def test_strips_mode_directive() -> None:
    assert strip_ui_directives("[MODE:THINKING]thinking...") == "thinking..."
    assert strip_ui_directives("done [MODE:IDLE]") == "done"


def test_strips_task_directive_with_payload() -> None:
    out = strip_ui_directives("[TASK: GRE vocabulary review] Here we go")
    assert out == "Here we go"


def test_strips_preview_document_block() -> None:
    text = (
        "Here is the summary:\n"
        "[PREVIEW:document]\n"
        "# Title\n\nA structured artifact.\n"
        "[/PREVIEW]\n"
        "Open the preview to read it."
    )
    out = strip_ui_directives(text)
    assert "PREVIEW" not in out
    assert "Title" not in out, "preview body must go with the directive"
    assert "Here is the summary:" in out
    assert "Open the preview" in out


def test_strips_preview_code_block_with_language() -> None:
    text = (
        "Sure:\n"
        "[PREVIEW:code:python]\n"
        "def f():\n    return 1\n"
        "[/PREVIEW]"
    )
    out = strip_ui_directives(text)
    assert "[PREVIEW" not in out
    assert "[/PREVIEW]" not in out
    assert "def f" not in out


def test_strips_multiple_inline_directives() -> None:
    text = "[MODE:SEARCHING]Looking up…[MODE:BUILDING]Drafting…[MODE:IDLE]"
    out = strip_ui_directives(text)
    assert "[" not in out and "]" not in out
    assert "Looking up" in out and "Drafting" in out


def test_strips_back_to_back_preview_blocks() -> None:
    text = (
        "[PREVIEW:document]\nfirst\n[/PREVIEW]\n"
        "[PREVIEW:code:json]\n{}\n[/PREVIEW]\n"
        "tail"
    )
    out = strip_ui_directives(text)
    assert out == "tail"


def test_strips_unknown_inline_directive_following_protocol() -> None:
    """Future directives that follow the [WORD:…] shape are also stripped,
    so adding ``[STATUS:…]`` to the soul doesn't require a stripper bump."""
    assert strip_ui_directives("[STATUS:OK]all good") == "all good"


def test_leaves_unrelated_brackets_alone() -> None:
    """Markdown links, math notation, and code that uses brackets must not
    be accidentally clipped."""
    text = "Use [click here](https://example.com) and `arr[0]` for the index."
    assert strip_ui_directives(text) == text


def test_collapses_blank_lines_left_by_directives() -> None:
    """Runs of blank lines (one of which came from a stripped directive on
    its own line) collapse to a single blank, preserving paragraph breaks
    without leaving a ladder of empty rows."""
    text = "Answer.\n[MODE:IDLE]\n\n\nSource: knowledge/x.md"
    out = strip_ui_directives(text)
    assert "\n\n\n" not in out
    assert out == "Answer.\n\nSource: knowledge/x.md"


def test_empty_input_returns_empty() -> None:
    assert strip_ui_directives("") == ""


def test_only_directive_becomes_empty_string() -> None:
    assert strip_ui_directives("[MODE:IDLE]") == ""
    assert strip_ui_directives("[PREVIEW:document]\nbody\n[/PREVIEW]") == ""
