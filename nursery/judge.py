"""Parent-model judge prompting and strict critique parsing."""

from __future__ import annotations

from pydantic import ValidationError

from nursery.curriculum import CurriculumItem
from nursery.records import ParentCritiqueRecord


class JudgeParseError(ValueError):
    """Raised when the parent judge does not return strict critique JSON."""


def parse_parent_critique(raw: str) -> ParentCritiqueRecord:
    """Parse parent output as strict JSON into a critique record."""
    stripped = raw.strip()
    if stripped.startswith("```") or stripped.endswith("```"):
        raise JudgeParseError("parent judge must return JSON only, not Markdown fences")

    try:
        return ParentCritiqueRecord.model_validate_json(stripped)
    except ValueError as exc:
        message = str(exc)
        if isinstance(exc, ValidationError):
            raise JudgeParseError(
                f"parent judge critique failed schema validation: {message}"
            ) from exc
        raise JudgeParseError(f"parent judge must return valid JSON: {message}") from exc


def build_judge_messages(*, item: CurriculumItem, child_output: str) -> list[dict[str, str]]:
    """Build messages asking the parent model to judge one child answer."""
    system = """You are Delphi's parent judge for the model nursery.
Return JSON only. Do not wrap it in Markdown.

Judge the child model across these dimensions:
- task correctness
- Delphi style / soul fit
- tool discipline / groundedness
- formatting and schema compliance
- whether this answer should escalate to a stronger model

Return exactly these fields:
{
  "score": 0.0,
  "passed": false,
  "rubric_notes": "specific reason for the score",
  "failure_modes": ["matching_failure_mode"],
  "repair": "better answer, or null",
  "escalation_needed": false
}
Scores must be numbers from 0 to 1.
""".strip()

    user = f"""Task type: {item.task_type}
Prompt id: {item.id}

User prompt:
{item.prompt}

Rubric:
{item.rubric}

Expected failure modes:
{', '.join(item.failure_modes)}

Child output to judge:
{child_output}
""".strip()

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
