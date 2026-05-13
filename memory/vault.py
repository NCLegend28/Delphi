"""Obsidian vault writer.

Writes a per-conversation note under ``conversations/YYYY-MM-DD/`` and
appends a one-line rollup to ``daily/YYYY-MM-DD.md``. The service is the
*writer*; Obsidian is the *reader*.

Disk I/O is wrapped with ``asyncio.to_thread`` so it doesn't block the event
loop. ``write()`` never raises — if anything goes wrong, the result carries
``ok=False`` and an error string, and the API contract upstream stays sacred.

Out of scope here:
- Entity extraction / ``[[wikilink]]`` rewriting (``memory/entities.py``)
- Jinja templates (``memory/templates.py``)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from memory.templates import TemplateRenderer

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 50


def _slugify(text: str) -> str:
    """ASCII slug from a user message. Empty input → ``untitled``."""
    lowered = text.strip().lower()
    slug = _SLUG_PATTERN.sub("-", lowered).strip("-")
    if not slug:
        return "untitled"
    return slug[:_MAX_SLUG_LEN].rstrip("-") or "untitled"


@dataclass(frozen=True)
class ConversationNote:
    """Everything needed to write one conversation file.

    ``project`` and ``entities`` should already be in their final ``[[name]]``
    form — vault.py does not resolve names against the projects/ folder.
    """

    timestamp: datetime
    task_type: str
    models: list[str]
    classifier_confidence: float | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    user_message: str
    assistant_message: str
    project: str | None = None
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    client_id: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class WriteResult:
    """What ``VaultWriter.write`` returns. Mirrors the JSONL ``vault_write`` shape."""

    ok: bool
    path: str | None = None
    error: str | None = None


class VaultWriter:
    """Writes conversation notes and daily rollups into an Obsidian vault."""

    def __init__(
        self,
        vault_path: str | Path,
        timezone: str = "America/Chicago",
        renderer: TemplateRenderer | None = None,
    ) -> None:
        self._vault = Path(vault_path)
        self._tz = ZoneInfo(timezone)
        self._renderer = renderer or TemplateRenderer()

    @property
    def vault(self) -> Path:
        return self._vault

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    async def write(self, note: ConversationNote) -> WriteResult:
        """Persist a conversation note plus its daily-rollup bullet. Never raises."""
        try:
            return await asyncio.to_thread(self._write_sync, note)
        except Exception as exc:  # noqa: BLE001 — fail-open by contract
            return WriteResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    def _write_sync(self, note: ConversationNote) -> WriteResult:
        local_ts = note.timestamp.astimezone(self._tz)
        date_str = local_ts.strftime("%Y-%m-%d")
        time_str = local_ts.strftime("%H-%M")
        slug = _slugify(note.user_message)

        conv_dir = self._vault / "conversations" / date_str
        conv_dir.mkdir(parents=True, exist_ok=True)
        conv_path = conv_dir / f"{date_str}_{time_str}_{slug}.md"

        conv_path.write_text(self._render_note(note, local_ts), encoding="utf-8")

        daily_dir = self._vault / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_path = daily_dir / f"{date_str}.md"
        rel = conv_path.relative_to(self._vault).as_posix()
        bullet = self._renderer.render_daily_bullet(
            time=time_str,
            rel_path=rel,
            task_type=note.task_type,
            latency_ms=note.latency_ms,
        )
        with daily_path.open("a", encoding="utf-8") as fh:
            fh.write(bullet)

        return WriteResult(ok=True, path=rel)

    def _render_note(self, note: ConversationNote, local_ts: datetime) -> str:
        return self._renderer.render_conversation_note(
            date=local_ts.isoformat(),
            task_type=note.task_type,
            models=note.models,
            classifier_confidence=note.classifier_confidence,
            latency_ms=note.latency_ms,
            input_tokens=note.input_tokens,
            output_tokens=note.output_tokens,
            project=note.project,
            entities=note.entities,
            tags=note.tags,
            client_id=note.client_id,
            truncated=note.truncated,
            user_message=note.user_message.rstrip(),
            assistant_message=note.assistant_message.rstrip(),
        )
