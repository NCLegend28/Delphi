"""Tests for parent judge prompt building and strict parsing."""

from __future__ import annotations

import pytest

from nursery.curriculum import SEED_CURRICULUM
from nursery.judge import JudgeParseError, build_judge_messages, parse_parent_critique


def test_parse_parent_critique_accepts_strict_json() -> None:
    critique = parse_parent_critique(
        """
        {
          "score": 0.82,
          "passed": true,
          "rubric_notes": "Grounded answer; minor verbosity.",
          "failure_modes": [],
          "repair": null
        }
        """
    )

    assert critique.score == 0.82
    assert critique.passed is True
    assert critique.rubric_notes == "Grounded answer; minor verbosity."
    assert critique.failure_modes == []
    assert critique.repair is None


def test_parse_parent_critique_rejects_malformed_json() -> None:
    with pytest.raises(JudgeParseError, match="valid JSON"):
        parse_parent_critique("score: 0.8")


def test_parse_parent_critique_rejects_markdown_wrapped_json() -> None:
    with pytest.raises(JudgeParseError, match="JSON only"):
        parse_parent_critique('```json\n{"score": 1}\n```')


def test_parse_parent_critique_rejects_out_of_range_score() -> None:
    with pytest.raises(JudgeParseError, match="score"):
        parse_parent_critique(
            '{"score": 1.2, "passed": false, "rubric_notes": "bad", '
            '"failure_modes": [], "repair": null}'
        )


def test_build_judge_messages_include_rubric_dimensions_and_child_output() -> None:
    item = SEED_CURRICULUM["vault_query"][0]
    messages = build_judge_messages(item=item, child_output="I found a note called X.")

    assert [message["role"] for message in messages] == ["system", "user"]
    combined = "\n".join(message["content"] for message in messages)
    assert "task correctness" in combined.lower()
    assert "delphi style" in combined.lower()
    assert "tool discipline" in combined.lower()
    assert "schema compliance" in combined.lower()
    assert "escalate" in combined.lower()
    assert "I found a note called X." in combined
    assert item.rubric in combined
