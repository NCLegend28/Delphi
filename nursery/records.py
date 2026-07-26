"""Durable JSONL schemas for Delphi model nursery runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

FORBIDDEN_SERIALIZED_NAME_FRAGMENTS = ("api_key", "token", "secret")


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp suitable for durable records."""
    return datetime.now(UTC).isoformat()


class NurseryRecord(BaseModel):
    """Base record with deterministic JSONL dumping."""

    created_at: str = Field(default_factory=utc_now_iso)

    def to_json_line(self) -> str:
        """Serialize as one deterministic JSONL line."""
        return f"{self.model_dump_json(exclude_none=False, by_alias=False)}\n"


class NurseryPromptRecord(NurseryRecord):
    """A task prompt and rubric used to evaluate or train a child model."""

    id: str
    task_type: str
    prompt: str
    rubric: str
    failure_modes: list[str]
    synthetic: bool = False
    private: bool = False
    source_id: str | None = None
    parent_model: str | None = None

    @field_validator("failure_modes")
    @classmethod
    def _requires_failure_modes(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("prompt record must include at least one failure mode")
        return value


class ParentCritiqueRecord(NurseryRecord):
    """Strict parent-model critique parsed from JSON output."""

    score: float = Field(ge=0, le=1)
    passed: bool
    rubric_notes: str
    failure_modes: list[str]
    repair: str | None = None
    escalation_needed: bool = False


class ChildAttemptRecord(NurseryRecord):
    """One child answer, its parent critique, and enough context to replay it."""

    task_type: str
    candidate: str
    prompt_id: str
    prompt: str
    child_output: str
    parent_score: float | None = Field(default=None, ge=0, le=1)
    parent_passed: bool | None = None
    rubric_notes: str
    failure_modes: list[str]
    repair: str | None = None
    parent_parse_error: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class EvaluationSummary(NurseryRecord):
    """Aggregate scorecard for a candidate on one task type."""

    candidate: str
    task_type: str
    mean_score: float = Field(ge=0, le=1)
    pass_rate: float = Field(ge=0, le=1)
    total: int = Field(ge=0)
    invalid_rate: float = Field(default=0, ge=0, le=1)
    escalation_rate: float = Field(default=0, ge=0, le=1)


def assert_no_secret_fields(payload: dict[str, Any]) -> None:
    """Reject serialized keys that look like credential-bearing fields."""
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_SERIALIZED_NAME_FRAGMENTS):
            raise AssertionError(f"serialized nursery record contains secret-like field: {key}")
        if isinstance(value, dict):
            assert_no_secret_fields(value)
