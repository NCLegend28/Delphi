"""Async HTTP client for the local Ollama server.

Thin wrapper around ``httpx.AsyncClient``. The contract is deliberately
narrow: list available model tags, do a one-shot chat completion, or stream
chat-completion chunks. Nothing in here interprets task types, soul prompts,
or vault memory — those live above. Keep the proxy dumb and stable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)


class OllamaError(RuntimeError):
    """Raised when Ollama returns an unexpected status or cannot be reached."""


class OllamaClient:
    """Async client for Ollama's ``/api/tags`` and OpenAI-compatible chat route."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def list_models(self) -> list[str]:
        """Return the tag names of every model Ollama has pulled locally."""
        try:
            response = await self._client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise OllamaError(f"ollama unreachable: {exc}") from exc

        if response.status_code != 200:
            raise OllamaError(f"ollama /api/tags returned {response.status_code}")

        payload = response.json()
        models = payload.get("models", [])
        return [m["name"] for m in models if "name" in m]

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns the parsed JSON body verbatim."""
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if options:
            body["options"] = options

        try:
            response = await self._client.post("/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise OllamaError(f"ollama chat failed: {exc}") from exc

        if response.status_code != 200:
            raise OllamaError(
                f"ollama /v1/chat/completions returned {response.status_code}: {response.text}"
            )
        return response.json()

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield raw SSE byte chunks from Ollama's streaming endpoint.

        The caller is responsible for parsing SSE frames — we pass them through
        unchanged so FastAPI can re-emit them to the OpenAI-compatible client.
        """
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if options:
            body["options"] = options

        async with self._client.stream("POST", "/v1/chat/completions", json=body) as response:
            if response.status_code != 200:
                # Read body for diagnostics before raising.
                text = (await response.aread()).decode("utf-8", errors="replace")
                raise OllamaError(
                    f"ollama stream returned {response.status_code}: {text}"
                )
            async for chunk in response.aiter_raw():
                if chunk:
                    yield chunk
