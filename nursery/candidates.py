"""Typed manifests for Delphi model nursery runtimes and model roles."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SIX_GB_BUDGET = 6.0


class RuntimeEndpoint(BaseModel):
    """OpenAI-compatible runtime endpoint for a standalone model process."""

    base_url: str
    api_key_env: str | None = None
    timeout_s: int = Field(default=120, gt=0)

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        stripped = value.rstrip("/")
        if not stripped:
            raise ValueError("base_url must be non-empty")
        return stripped

    @property
    def api_base_url(self) -> str:
        """Base URL normalized to include the OpenAI-compatible /v1 prefix."""
        return self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

    @property
    def chat_completions_url(self) -> str:
        """Full chat completions URL."""
        return f"{self.api_base_url}/chat/completions"


class ChildCandidate(BaseModel):
    """A quantized child model candidate constrained by the 6 GB target."""

    role: Literal["child"] = "child"
    name: str
    repo: str
    quant: str
    gguf_size_gb: float = Field(gt=0)
    task_types: list[str]
    max_context: int = Field(default=4096, gt=0)
    runtime: RuntimeEndpoint | None = None

    @field_validator("gguf_size_gb")
    @classmethod
    def _fits_six_gb_budget(cls, value: float) -> float:
        if value > SIX_GB_BUDGET:
            raise ValueError(f"child candidate exceeds 6 GB budget: {value:.2f} GB")
        return value

    @field_validator("task_types")
    @classmethod
    def _has_task_type(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("child candidate must target at least one task type")
        if any(not item for item in value):
            raise ValueError("task types must be non-empty")
        return value


class ParentModel(BaseModel):
    """A stronger model used to critique, repair, and expand child outputs."""

    role: Literal["parent"] = "parent"
    name: str
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_s: int = Field(default=120, gt=0)

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        stripped = value.rstrip("/")
        if not stripped:
            raise ValueError("base_url must be non-empty")
        return stripped


DEFAULT_CHILD_CANDIDATES: dict[str, ChildCandidate] = {
    "phi-3.5-mini-q6": ChildCandidate(
        name="phi-3.5-mini-q6",
        repo="bartowski/Phi-3.5-mini-instruct-GGUF",
        quant="Q6_K",
        gguf_size_gb=3.14,
        task_types=["chat", "reason", "vault_query", "gre_quiz"],
    ),
    "llama-3.2-3b-q6": ChildCandidate(
        name="llama-3.2-3b-q6",
        repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
        quant="Q6_K",
        gguf_size_gb=2.64,
        task_types=["chat", "tool_step", "vault_query"],
    ),
    "qwen2.5-coder-7b-q3": ChildCandidate(
        name="qwen2.5-coder-7b-q3",
        repo="bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        quant="Q3_K_M",
        gguf_size_gb=3.81,
        task_types=["code", "reason"],
    ),
    "qwen2.5-coder-7b-q4": ChildCandidate(
        name="qwen2.5-coder-7b-q4",
        repo="bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        quant="Q4_K_M",
        gguf_size_gb=4.68,
        task_types=["code", "reason"],
    ),
    "gemma-2-9b-q3": ChildCandidate(
        name="gemma-2-9b-q3",
        repo="bartowski/gemma-2-9b-it-GGUF",
        quant="Q3_K_M",
        gguf_size_gb=4.76,
        task_types=["chat", "reason", "multilingual"],
    ),
}
