"""OpenAI-compatible async chat client for standalone nursery runtimes."""

from __future__ import annotations

import os
from typing import Any

import httpx

from nursery.candidates import RuntimeEndpoint


class NurseryClientError(RuntimeError):
    """Raised when a nursery runtime call fails or returns malformed data."""


class NurseryChatClient:
    """Small async client for OpenAI-compatible chat completions endpoints."""

    def __init__(self, endpoint: RuntimeEndpoint) -> None:
        self.endpoint = endpoint

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Return assistant text from a chat completion."""
        headers = {"Content-Type": "application/json"}
        if self.endpoint.api_key_env:
            api_key = os.environ.get(self.endpoint.api_key_env)
            if not api_key:
                raise NurseryClientError(
                    f"API key environment variable is not set: {self.endpoint.api_key_env}"
                )
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.endpoint.timeout_s) as client:
                response = await client.post(
                    self.endpoint.chat_completions_url,
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise NurseryClientError(f"nursery runtime request failed: {exc}") from exc

        if response.status_code >= 400:
            raise NurseryClientError(
                f"nursery runtime returned {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise NurseryClientError("nursery runtime returned non-JSON response") from exc

        return _extract_assistant_content(data)


def _extract_assistant_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise NurseryClientError("nursery runtime response missing assistant content") from exc

    if not isinstance(content, str):
        raise NurseryClientError("nursery runtime assistant content is not a string")
    return content
