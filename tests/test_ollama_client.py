"""Tests for the Ollama proxy client.

Network is mocked with ``respx``. These exercise the wire contract — we never
hit a real Ollama in unit tests.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from proxy.ollama_client import OllamaClient, OllamaError

BASE = "http://ollama.test:11434"


@pytest.fixture
async def client() -> OllamaClient:
    return OllamaClient(BASE)


@respx.mock
async def test_list_models_returns_tag_names(client: OllamaClient) -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "phi4:14b", "size": 1},
                    {"name": "qwen2.5-coder:14b", "size": 2},
                ]
            },
        )
    )
    names = await client.list_models()
    assert names == ["phi4:14b", "qwen2.5-coder:14b"]
    await client.aclose()


@respx.mock
async def test_list_models_raises_on_non_200(client: OllamaClient) -> None:
    respx.get(f"{BASE}/api/tags").mock(return_value=httpx.Response(500))
    with pytest.raises(OllamaError):
        await client.list_models()
    await client.aclose()


@respx.mock
async def test_list_models_raises_on_connect_error(client: OllamaClient) -> None:
    respx.get(f"{BASE}/api/tags").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(OllamaError, match="unreachable"):
        await client.list_models()
    await client.aclose()


@respx.mock
async def test_chat_returns_parsed_body(client: OllamaClient) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        )
    )
    out = await client.chat(model="phi4:14b", messages=[{"role": "user", "content": "hi"}])
    assert out["choices"][0]["message"]["content"] == "hi"
    await client.aclose()


@respx.mock
async def test_chat_raises_on_non_200(client: OllamaClient) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(400, text="bad model")
    )
    with pytest.raises(OllamaError, match="400"):
        await client.chat(model="nope", messages=[])
    await client.aclose()


@respx.mock
async def test_stream_chat_yields_raw_chunks(client: OllamaClient) -> None:
    body = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )
    collected = b""
    async for chunk in client.stream_chat(
        model="phi4:14b", messages=[{"role": "user", "content": "hi"}]
    ):
        collected += chunk
    assert b"[DONE]" in collected
    await client.aclose()


async def test_context_manager_closes_owned_client() -> None:
    async with OllamaClient(BASE) as c:
        assert not c._client.is_closed
    assert c._client.is_closed


async def test_external_client_not_closed() -> None:
    external = httpx.AsyncClient(base_url=BASE)
    async with OllamaClient(BASE, client=external):
        pass
    assert not external.is_closed
    await external.aclose()
