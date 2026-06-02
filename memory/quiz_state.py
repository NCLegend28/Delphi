"""Active-quiz session state, persisted to the vault.

A quiz is multi-turn but the service is stateless from the request POV, so
"where does the deck-so-far live between requests?" needs an answer. Three
options were on the table — conversation-history-driven, Redis-backed, or
a vault state file. The vault file wins for the same reason the rest of
Delphi's memory lives there: it survives ``docker compose restart``,
it's inspectable with ``cat``, and the substrate the agent already
reads/writes is the obvious home for anything Tali might want to debug.

One file per active session, written under ``<vault>/state/active-quiz.md``.
Concurrency model: single-user, last-writer-wins. When a second concurrent
client ever appears, the filename gains a ``-<client_id>`` suffix and this
module grows a ``client_id`` parameter on each call. Today: one file.

Format is markdown-with-YAML-frontmatter so the file renders as something
human-readable in Obsidian (a running quiz transcript) while keeping the
machine-parseable state in the frontmatter dict.

Atomic writes use ``tempfile`` + ``os.replace`` so a crash mid-write leaves
the previous state intact — same pattern as ``vocab_card.write_review``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Where the state file lives within the vault. Kept relative so callers
# can resolve against any vault root (prod ``/vault``, tests ``tmp_path``).
_STATE_DIR = "state"
_STATE_FILENAME = "active-quiz.md"


class QuizStateError(Exception):
    """Raised when the state file exists but can't be parsed."""


@dataclass(slots=True)
class QuizCard:
    """One card in the active deck. Mutable on purpose — the agent updates it.

    ``asked`` flips to True once the user has been shown the card. ``grade``
    and ``user_answer`` land when the agent records the review. A card with
    ``asked=True`` and ``grade=None`` is the card currently waiting for a
    user answer (the cursor).
    """

    path: str
    word: str
    asked: bool = False
    grade: int | None = None
    user_answer: str | None = None


@dataclass(slots=True)
class QuizSession:
    """The whole active-quiz state, serializable to the state file."""

    session_id: str
    client_id: str | None
    started_at: datetime
    domain: str
    filters: dict[str, Any]
    deck: list[QuizCard]
    current_index: int = 0  # 0-based; points at the next card to ask
    n_target: int = 10
    transcript: list[str] = field(default_factory=list)  # markdown bullets

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.deck) or self.current_index >= self.n_target

    @property
    def graded_count(self) -> int:
        return sum(1 for c in self.deck if c.grade is not None)


def _serialize_card(card: QuizCard) -> dict[str, Any]:
    """Card → dict, dropping ``None`` so the YAML stays tidy."""
    d = asdict(card)
    return {k: v for k, v in d.items() if v is not None or k in ("path", "word", "asked")}


def _deserialize_card(raw: Any) -> QuizCard:
    if not isinstance(raw, dict):
        raise QuizStateError(f"deck entry must be a mapping, got {type(raw).__name__}")
    path = raw.get("path")
    word = raw.get("word")
    if not isinstance(path, str) or not isinstance(word, str):
        raise QuizStateError("deck entry missing required 'path' or 'word'")
    grade_raw = raw.get("grade")
    grade: int | None
    if grade_raw is None:
        grade = None
    else:
        try:
            grade = int(grade_raw)
        except (TypeError, ValueError):
            grade = None
    return QuizCard(
        path=path,
        word=word,
        asked=bool(raw.get("asked", False)),
        grade=grade,
        user_answer=raw.get("user_answer") if isinstance(raw.get("user_answer"), str) else None,
    )


def _render(session: QuizSession) -> str:
    """Serialize a session to markdown-with-YAML-frontmatter."""
    frontmatter = {
        "type": "quiz-session",
        "session_id": session.session_id,
        "client_id": session.client_id,
        "started_at": session.started_at.isoformat(),
        "domain": session.domain,
        "filters": session.filters,
        "deck": [_serialize_card(c) for c in session.deck],
        "current_index": session.current_index,
        "n_target": session.n_target,
    }
    fm_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )

    header = f"# Active quiz — {session.domain}"
    if session.filters:
        # Render a compact filter summary so a human reading the file sees
        # what's being drilled without parsing YAML.
        pairs = ", ".join(f"{k}={v}" for k, v in session.filters.items())
        header += f" ({pairs})"

    intro = (
        f"> Started {session.started_at.isoformat()}. {session.n_target} cards. "
        f"{session.graded_count} graded so far."
    )

    log = "## Log\n" + ("\n".join(session.transcript) if session.transcript else "_(empty)_") + "\n"

    return f"---\n{fm_text}---\n\n{header}\n\n{intro}\n\n{log}"


class QuizStateStore:
    """File-backed CRUD for the active-quiz state.

    All operations are best-effort — ``load`` returns ``None`` if no file
    exists, ``clear`` is idempotent. ``save`` writes atomically and creates
    the ``state/`` directory if needed.
    """

    def __init__(self, vault_path: str | Path) -> None:
        self._vault = Path(vault_path)

    @property
    def vault_path(self) -> Path:
        """The vault root this store is bound to.

        Surfacing this lets callers — the quiz agent in particular — drive
        ``list_due_cards`` off the same root the state file lives under,
        without re-reading ``Config`` (which is ``lru_cache``'d and may not
        match the test's per-case tmp_path).
        """
        return self._vault

    @property
    def state_path(self) -> Path:
        return self._vault / _STATE_DIR / _STATE_FILENAME

    def exists(self) -> bool:
        return self.state_path.is_file()

    def load(self) -> QuizSession | None:
        """Read the state file and parse it. ``None`` if no active session."""
        path = self.state_path
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")

        # Frontmatter parser identical to vocab_card's but scoped here so
        # the two modules can evolve independently.
        if not text.startswith("---\n"):
            raise QuizStateError("state file is missing its frontmatter fence")
        end = text.find("\n---", 4)
        if end == -1:
            raise QuizStateError("state file frontmatter is unterminated")
        try:
            fm = yaml.safe_load(text[4:end])
        except yaml.YAMLError as exc:
            raise QuizStateError(f"state frontmatter is not valid YAML: {exc}") from exc
        if not isinstance(fm, dict):
            raise QuizStateError("state frontmatter must be a mapping")

        # Parse fields with defaults; a partial file shouldn't crash the agent.
        started_raw = fm.get("started_at")
        if isinstance(started_raw, datetime):
            started_at = started_raw
        elif isinstance(started_raw, str) and started_raw.strip():
            try:
                started_at = datetime.fromisoformat(started_raw)
            except ValueError as exc:
                raise QuizStateError(f"bad started_at: {started_raw!r}") from exc
        else:
            raise QuizStateError("started_at missing or invalid")

        deck_raw = fm.get("deck", [])
        if not isinstance(deck_raw, list):
            raise QuizStateError("deck must be a list")
        deck = [_deserialize_card(c) for c in deck_raw]

        # Pull transcript lines out of the body so the next save round-trips them.
        body = text[end + 4 :]
        transcript: list[str] = []
        in_log = False
        for line in body.splitlines():
            if line.strip() == "## Log":
                in_log = True
                continue
            if in_log:
                stripped = line.strip()
                if stripped and stripped.startswith("-"):
                    transcript.append(line)

        return QuizSession(
            session_id=str(fm.get("session_id", "")),
            client_id=fm.get("client_id") if isinstance(fm.get("client_id"), str) else None,
            started_at=started_at,
            domain=str(fm.get("domain", "gre")),
            filters=fm.get("filters") if isinstance(fm.get("filters"), dict) else {},
            deck=deck,
            current_index=int(fm.get("current_index", 0)),
            n_target=int(fm.get("n_target", len(deck))),
            transcript=transcript,
        )

    def save(self, session: QuizSession) -> None:
        """Atomically rewrite the state file."""
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)

        rendered = _render(session)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{_STATE_FILENAME}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(rendered)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        """Delete the state file. Idempotent — a missing file isn't an error."""
        path = self.state_path
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def append_log(session: QuizSession, line: str) -> None:
    """Append one bullet to the session's transcript. Helper for the agent."""
    bullet = line if line.startswith("-") else f"- {line}"
    session.transcript.append(bullet)
