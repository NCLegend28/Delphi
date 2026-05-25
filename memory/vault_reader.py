"""Read-only vault access for the vault-query agent.

The counterpart to ``VaultWriter``. Where the writer appends conversation
notes, this reads them back so the model can ground a ``vault_query`` answer
in what Tali has actually written — the same search→read→reason loop a human
(or Claude) uses against the vault.

Two operations, both safe to expose to a model as tools:

* ``search(query)`` — keyword scan over ``*.md`` content, ranked, with a
  snippet per hit. Cheap and dependency-free; swap for an embedding index
  later behind this same interface without touching the agent.
* ``read(rel_path)`` — return one note's text. **Path-confined**: the
  resolved target must live inside the vault, or it's refused. A model
  emitting ``../../etc/passwd`` gets nothing.

Nothing here mutates the vault. The writer's territory (``conversations/``,
``daily/``, ``entities/``) is included in reads — past exchanges are fair
game for recall — but ``.delphi/`` bookkeeping and hidden dirs are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Word-ish tokens for keyword scoring. Lowercased; punctuation dropped.
_WORD = re.compile(r"[a-z0-9]+")
# How much of a note to hand back on read — enough for context, bounded so a
# runaway note can't blow the model's window or the tool-result payload.
_MAX_NOTE_CHARS = 12_000
_SNIPPET_RADIUS = 160


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One ranked match: where it is, how strong, and a readable excerpt."""

    path: str  # vault-relative, forward-slashed — feed straight back to read()
    score: int
    snippet: str


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class VaultReader:
    """Keyword search + path-safe read over a markdown vault."""

    def __init__(
        self,
        vault_path: str,
        *,
        max_results: int = 8,
        max_note_chars: int = _MAX_NOTE_CHARS,
    ) -> None:
        # resolve() collapses ``..`` and symlinks once, up front, so every
        # later containment check compares against a canonical absolute root.
        self._vault = Path(vault_path).expanduser().resolve() if vault_path else None
        self._max_results = max_results
        self._max_note_chars = max_note_chars

    @property
    def available(self) -> bool:
        """False when no vault is configured or the path doesn't exist yet."""
        return self._vault is not None and self._vault.is_dir()

    def _iter_notes(self) -> list[Path]:
        vault = self._vault
        if vault is None:
            return []
        # Skip hidden dirs (.delphi bookkeeping, .obsidian config, .git).
        return [
            p
            for p in vault.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(vault).parts)
        ]

    def search(self, query: str, limit: int | None = None) -> list[SearchHit]:
        """Rank notes by keyword overlap with ``query``; return the top hits.

        Scoring is deliberately simple: term frequency in the body plus a
        boost for matches in the filename (a note *named* for the topic is a
        strong signal). Notes with zero matched terms are dropped — no
        zero-score filler. Ties break toward the more recently modified note.
        """
        vault = self._vault
        if vault is None or not self.available:
            return []
        terms = set(_tokenize(query))
        if not terms:
            return []

        scored: list[tuple[int, float, SearchHit]] = []
        for path in self._iter_notes():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            body_tokens = _tokenize(text)
            score = sum(1 for tok in body_tokens if tok in terms)
            name_tokens = set(_tokenize(path.stem))
            score += 3 * len(terms & name_tokens)  # filename hit is worth more
            if score == 0:
                continue
            rel = path.relative_to(vault).as_posix()
            hit = SearchHit(rel, score, self._snippet(text, terms))
            scored.append((score, path.stat().st_mtime, hit))

        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        cap = limit if limit is not None else self._max_results
        return [hit for _, _, hit in scored[:cap]]

    def _snippet(self, text: str, terms: set[str]) -> str:
        """A short excerpt centered on the first matched term."""
        lowered = text.lower()
        idx = min(
            (lowered.find(t) for t in terms if t in lowered),
            default=-1,
        )
        if idx < 0:
            return text[: _SNIPPET_RADIUS * 2].strip()
        start = max(0, idx - _SNIPPET_RADIUS)
        end = min(len(text), idx + _SNIPPET_RADIUS)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    def read(self, rel_path: str) -> str:
        """Return one note's text. Refuses anything outside the vault.

        ``rel_path`` is taken relative to the vault root. Absolute inputs,
        ``..`` traversal, and symlink escapes all resolve and then fail the
        containment check, raising ``FileNotFoundError`` rather than leaking
        host files to the model.
        """
        if self._vault is None:
            raise FileNotFoundError("no vault configured")
        # Strip any leading slash so an absolute-looking arg is still treated
        # as vault-relative before resolution.
        candidate = (self._vault / rel_path.lstrip("/")).resolve()
        if self._vault not in candidate.parents and candidate != self._vault:
            raise FileNotFoundError(f"path escapes vault: {rel_path}")
        if not candidate.is_file():
            raise FileNotFoundError(f"no such note: {rel_path}")
        text = candidate.read_text(encoding="utf-8", errors="replace")
        if len(text) > self._max_note_chars:
            return text[: self._max_note_chars] + "\n\n…[truncated]"
        return text
