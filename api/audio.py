"""``POST /v1/audio/transcriptions`` — OpenAI-compatible speech-to-text.

Thin route: validate the upload, hand the bytes to ``proxy.stt.transcribe``,
return ``{"text": "..."}``. All provider knowledge lives in ``proxy/stt.py``
so this file never imports faster-whisper / OpenAI / etc.

Errors map to status codes per the task contract:
- 400  missing file or empty filename
- 413  upload exceeds ``speech_to_text_max_upload_bytes``
- 415  content-type not in the audio allowlist
- 502  provider raised
- 503  ``speech_to_text_enabled=False``
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from auth.bearer import require_bearer
from config import Config, get_config
from proxy import stt

router = APIRouter()

# Browsers and ffmpeg between them produce a long tail of audio MIME types;
# this list covers the container formats faster-whisper handles directly.
_ALLOWED_MIME_TYPES = frozenset(
    {
        "audio/webm",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/ogg",
        "audio/flac",
        "audio/x-flac",
    }
)


def _content_type_allowed(content_type: str | None) -> bool:
    if not content_type:
        return False
    base = content_type.split(";", 1)[0].strip().lower()
    return base in _ALLOWED_MIME_TYPES


async def _read_with_limit(upload: UploadFile, limit: int) -> bytes | None:
    """Read up to ``limit`` bytes; return ``None`` if the stream exceeds it.

    We read ``limit + 1`` so a one-byte overrun is detectable without
    pulling a hostile multi-gigabyte upload into memory.
    """
    data = await upload.read(limit + 1)
    if len(data) > limit:
        return None
    return data


@router.post(
    "/v1/audio/transcriptions",
    dependencies=[Depends(require_bearer)],
)
async def transcribe_audio(
    config: Annotated[Config, Depends(get_config)],
    file: Annotated[UploadFile | None, File()] = None,
    model: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
) -> dict[str, str]:
    if not config.speech_to_text_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech-to-text disabled",
        )

    if file is None or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing file",
        )

    if not _content_type_allowed(file.content_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported media type: {file.content_type!r}",
        )

    payload = await _read_with_limit(file, config.speech_to_text_max_upload_bytes)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"file exceeds maximum upload size of "
                f"{config.speech_to_text_max_upload_bytes} bytes"
            ),
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty file",
        )

    try:
        text = await stt.transcribe(
            payload,
            mime_type=(file.content_type or "").split(";", 1)[0].strip().lower(),
            model=model,
            language=language,
        )
    except NotImplementedError:
        # Provider is configured but not implemented (e.g. ``openai`` stub).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="configured speech-to-text provider is not implemented",
        ) from None
    except Exception as exc:  # noqa: BLE001 — any provider failure is a 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"speech-to-text provider failed: {exc}",
        ) from exc

    return {"text": text}
