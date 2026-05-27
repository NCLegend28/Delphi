"""Speech-to-text provider abstraction.

The FastAPI route in ``api/audio.py`` calls :func:`transcribe` and doesn't
care which backend serves the request — that selection happens here,
driven by ``Config.speech_to_text_provider``. This keeps the route free
of provider-specific imports (so tests can monkeypatch :func:`transcribe`
without ever importing ``faster-whisper``) and leaves a clean seam for a
future hosted-OpenAI implementation.

The faster-whisper model is heavy (hundreds of MB on disk, multi-second
warm-up). We load it lazily on first request and cache the instance as a
module-level singleton keyed by model size.
"""

from __future__ import annotations

import asyncio
import io
from typing import Protocol

from config import get_config


class _Provider(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        model: str | None,
        language: str | None,
    ) -> str: ...


# --- faster-whisper -------------------------------------------------------


class _FasterWhisperProvider:
    """Local CPU/GPU inference via the ``faster-whisper`` package.

    The model object is cached per size string because instantiation is
    expensive (downloads weights on first use, allocates CTranslate2 state).
    """

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def _get_model(self, size: str) -> object:
        cached = self._models.get(size)
        if cached is not None:
            return cached
        # Import inside the method so tests that monkeypatch ``transcribe``
        # never need faster-whisper installed.
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        model = WhisperModel(size)
        self._models[size] = model
        return model

    def _sync_transcribe(
        self,
        audio_bytes: bytes,
        size: str,
        language: str | None,
    ) -> str:
        model = self._get_model(size)
        # faster-whisper accepts a file-like object positionally.
        segments, _info = model.transcribe(  # type: ignore[attr-defined]
            io.BytesIO(audio_bytes),
            language=language,
        )
        return "".join(segment.text for segment in segments).strip()

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,  # noqa: ARG002 — faster-whisper sniffs the container
        model: str | None,
        language: str | None,
    ) -> str:
        cfg = get_config()
        size = model or cfg.speech_to_text_model
        return await asyncio.to_thread(self._sync_transcribe, audio_bytes, size, language)


class _OpenAIProvider:
    """Placeholder for the hosted OpenAI Whisper endpoint.

    Intentionally not implemented — leaving the dispatcher seam wired so
    flipping ``SPEECH_TO_TEXT_PROVIDER=openai`` becomes a one-PR change
    rather than a refactor.
    """

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        model: str | None,
        language: str | None,
    ) -> str:
        raise NotImplementedError("openai STT provider not implemented yet")


# --- dispatcher -----------------------------------------------------------

_PROVIDER_CACHE: dict[str, _Provider] = {}


def _select_provider(name: str) -> _Provider:
    """Return a cached provider instance for ``name`` or raise ``ValueError``."""
    cached = _PROVIDER_CACHE.get(name)
    if cached is not None:
        return cached

    if name == "faster-whisper":
        provider: _Provider = _FasterWhisperProvider()
    elif name == "openai":
        provider = _OpenAIProvider()
    else:
        raise ValueError(f"unknown speech-to-text provider: {name!r}")

    _PROVIDER_CACHE[name] = provider
    return provider


async def transcribe(
    audio_bytes: bytes,
    mime_type: str,
    model: str | None = None,
    language: str | None = None,
) -> str:
    """Public entry point used by the FastAPI route.

    Picks the configured provider and delegates. Errors bubble up so the
    route can convert them to a 502.
    """
    cfg = get_config()
    provider = _select_provider(cfg.speech_to_text_provider)
    return await provider.transcribe(audio_bytes, mime_type, model, language)
