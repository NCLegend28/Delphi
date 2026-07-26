"""Tests for the nursery OpenAI-compatible chat client."""

from __future__ import annotations

import os

import httpx
import pytest
import respx

from nursery.candidates import RuntimeEndpoint
from nursery.client import NurseryChatClient, NurseryClientError


@respx.mock
async def test_complete_sends_openai_compatible_chat_request() -> None:
    route = respx.post("http://127.0.0.1:18080/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "nursery-ok"}}]},
        )
    )
    client = NurseryChatClient(RuntimeEndpoint(base_url="http://127.0.0.1:18080"))

    output = await client.complete(
        model="child-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
        max_tokens=32,
    )

    assert output == "nursery-ok"
    request = route.calls.last.request
    assert request.headers["content-type"] == "application/json"
    assert "authorization" not in request.headers
    assert route.calls.last.request.content
    payload = httpx.Request("POST", "http://x", content=request.content).read()
    assert b'"model":"child-model"' in payload
    assert b'"temperature":0.1' in payload
    assert b'"max_tokens":32' in payload


@respx.mock
async def test_complete_sets_bearer_header_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NURSERY_TEST_KEY", "test-token")
    route = respx.post("http://127.0.0.1:18080/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )
    )
    client = NurseryChatClient(
        RuntimeEndpoint(base_url="http://127.0.0.1:18080/v1", api_key_env="NURSERY_TEST_KEY")
    )

    await client.complete(
        model="child-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=16,
    )

    assert route.calls.last.request.headers["authorization"] == "Bearer test-token"


@respx.mock
async def test_complete_raises_typed_error_for_server_errors() -> None:
    respx.post("http://127.0.0.1:18080/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    client = NurseryChatClient(RuntimeEndpoint(base_url="http://127.0.0.1:18080"))

    with pytest.raises(NurseryClientError, match="500"):
        await client.complete(
            model="child-model",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_tokens=16,
        )


@respx.mock
async def test_complete_raises_typed_error_for_missing_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.environ.pop("MISSING_NURSERY_KEY", None)
    client = NurseryChatClient(
        RuntimeEndpoint(base_url="http://127.0.0.1:18080", api_key_env="MISSING_NURSERY_KEY")
    )

    with pytest.raises(NurseryClientError, match="MISSING_NURSERY_KEY"):
        await client.complete(
            model="child-model",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_tokens=16,
        )


@respx.mock
async def test_complete_raises_typed_error_for_malformed_response() -> None:
    respx.post("http://127.0.0.1:18080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []})
    )
    client = NurseryChatClient(RuntimeEndpoint(base_url="http://127.0.0.1:18080"))

    with pytest.raises(NurseryClientError, match="assistant content"):
        await client.complete(
            model="child-model",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_tokens=16,
        )
