"""Tests for Delphi model nursery candidate manifests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nursery.candidates import ChildCandidate, ParentModel, RuntimeEndpoint


def test_child_candidate_enforces_six_gb_budget() -> None:
    with pytest.raises(ValidationError, match="6 GB"):
        ChildCandidate(
            name="too-big",
            repo="example/model-GGUF",
            quant="Q8_0",
            gguf_size_gb=8.1,
            task_types=["chat"],
        )


def test_runtime_endpoint_chat_url_normalizes_v1() -> None:
    endpoint = RuntimeEndpoint(base_url="http://127.0.0.1:18080/v1")
    assert endpoint.chat_completions_url == "http://127.0.0.1:18080/v1/chat/completions"


def test_runtime_endpoint_chat_url_appends_v1_when_missing() -> None:
    endpoint = RuntimeEndpoint(base_url="http://127.0.0.1:18080")
    assert endpoint.chat_completions_url == "http://127.0.0.1:18080/v1/chat/completions"


def test_parent_and_child_roles_are_distinct() -> None:
    child = ChildCandidate(
        name="phi-3.5-mini-q6",
        repo="bartowski/Phi-3.5-mini-instruct-GGUF",
        quant="Q6_K",
        gguf_size_gb=3.14,
        task_types=["chat", "reason"],
    )
    parent = ParentModel(
        name="delphi-parent",
        base_url="http://127.0.0.1:8090/v1",
        model="delphi-auto",
        api_key_env=None,
    )

    assert child.role == "child"
    assert parent.role == "parent"
    assert child.name != parent.name


def test_candidate_requires_at_least_one_task_type() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        ChildCandidate(
            name="empty",
            repo="example/model-GGUF",
            quant="Q4_K_M",
            gguf_size_gb=2.0,
            task_types=[],
        )
