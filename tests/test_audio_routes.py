"""Contract tests for ``POST /v1/audio/transcriptions``.

The route delegates the actual model call to ``proxy.stt.transcribe`` so the
heavyweight faster-whisper import never has to happen during tests — we
monkeypatch the dispatcher and assert on the HTTP contract only.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from api.audio import router as audio_router
from config import Config, get_config
from proxy import stt

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _build_app(**overrides: object) -> FastAPI:
    app = FastAPI()
    app.include_router(audio_router)

    defaults: dict[str, object] = {
        "delphi_bearer_token": TOKEN,
        "obsidian_vault_path": "/tmp/delphi-vault",  # noqa: S108 (test-only)
        "log_dir": "/tmp/delphi-logs",  # noqa: S108
        "boot_probe_enabled": False,
    }
    defaults.update(overrides)
    app.dependency_overrides[get_config] = lambda: Config(**defaults)  # type: ignore[arg-type]
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


# --- tests ----------------------------------------------------------------


async def test_transcription_requires_auth() -> None:
    app = _build_app()
    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            files={"file": ("clip.wav", b"RIFF....", "audio/wav")},
        )
    assert resp.status_code in (401, 403)


async def test_transcription_rejects_missing_file() -> None:
    app = _build_app()
    async with _client(app) as c:
        resp = await c.post("/v1/audio/transcriptions", headers=AUTH, data={"model": "base"})
    assert resp.status_code in (400, 422)


async def test_transcription_rejects_oversize_file(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(speech_to_text_max_upload_bytes=16)
    big = b"x" * 1024  # well over 16 bytes

    async def _should_not_be_called(*a: object, **kw: object) -> str:
        raise AssertionError("provider must not be invoked for oversize uploads")

    monkeypatch.setattr(stt, "transcribe", _should_not_be_called)

    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("clip.wav", big, "audio/wav")},
        )
    assert resp.status_code == 413


async def test_transcription_rejects_unsupported_mime() -> None:
    app = _build_app()
    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("clip.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 415


async def test_transcription_returns_text_when_provider_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()

    captured: dict[str, object] = {}

    async def fake_transcribe(
        audio_bytes: bytes,
        mime_type: str,
        model: str | None = None,
        language: str | None = None,
    ) -> str:
        captured["len"] = len(audio_bytes)
        captured["mime"] = mime_type
        captured["model"] = model
        captured["language"] = language
        return "hello world"

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)

    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("clip.webm", b"OggS....", "audio/webm")},
            data={"model": "tiny", "language": "en"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"text": "hello world"}
    assert captured["mime"] == "audio/webm"
    assert captured["model"] == "tiny"
    assert captured["language"] == "en"
    assert captured["len"] == len(b"OggS....")


async def test_transcription_returns_502_when_provider_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()

    async def boom(*a: object, **kw: object) -> str:
        raise RuntimeError("model exploded")

    monkeypatch.setattr(stt, "transcribe", boom)

    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("clip.wav", b"RIFF....", "audio/wav")},
        )
    assert resp.status_code == 502


async def test_transcription_returns_503_when_disabled() -> None:
    app = _build_app(speech_to_text_enabled=False)
    async with _client(app) as c:
        resp = await c.post(
            "/v1/audio/transcriptions",
            headers=AUTH,
            files={"file": ("clip.wav", b"RIFF....", "audio/wav")},
        )
    assert resp.status_code == 503


def test_provider_dispatch_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown.*provider"):
        stt._select_provider("does-not-exist")  # noqa: SLF001
