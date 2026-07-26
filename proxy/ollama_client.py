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
        api_key: str | None = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout or DEFAULT_TIMEOUT
        # Ollama Cloud authenticates with a bearer token; a local Ollama needs
        # none. Attach the header at the client level so every request (tags,
        # chat, stream) carries it without per-call plumbing. A caller-supplied
        # client is used verbatim — the caller owns its auth.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, headers=headers
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def list_models(self) -> list[str]:
        """Return available model names.

        Ollama exposes ``/api/tags`` while standalone OpenAI-compatible
        runtimes such as ``llama-server`` expose ``/v1/models``. Delphi's chat
        path already uses the OpenAI-compatible completion endpoint, so the
        boot probe accepts either model-list shape.
        """
        try:
            response = await self._client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise OllamaError(f"ollama unreachable: {exc}") from exc

        if response.status_code == 200:
            payload = response.json()
            models = payload.get("models", [])
            return [m["name"] for m in models if "name" in m]

        if response.status_code != 404:
            raise OllamaError(f"ollama /api/tags returned {response.status_code}")

        try:
            response = await self._client.get("/v1/models")
        except httpx.HTTPError as exc:
            raise OllamaError(f"openai-compatible runtime unreachable: {exc}") from exc

        if response.status_code != 200:
            raise OllamaError(f"runtime /v1/models returned {response.status_code}")

        payload = response.json()
        raw_models = payload.get("data", payload.get("models", []))
        names: list[str] = []
        for model in raw_models:
            if not isinstance(model, dict):
                continue
            name = model.get("id") or model.get("name") or model.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns the parsed JSON body verbatim.

        ``tools`` carries OpenAI-style function schemas; when supplied, a
        tool-capable model may answer with ``choices[0].message.tool_calls``
        instead of content. The proxy stays dumb — it forwards the schemas and
        returns whatever the model decides; the caller runs the tool loop.
        """
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if options:
            body["options"] = options
        if tools:
            body["tools"] = tools

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
        messages: list[dict[str, Any]],
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
