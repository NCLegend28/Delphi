"""Entity index — wikilinks, candidate tracking, threshold-based promotion.

CLAUDE.md → "Entity creation":

  When the assistant response mentions a noun-phrase the service hasn't seen
  before *and* it appears in 2+ different conversations, auto-create
  ``entities/<slug>.md`` with a one-line stub. This is what makes the graph
  view light up over time.

Two stores back this module:

- ``<vault>/entities/`` and ``<vault>/projects/`` — read straight from disk.
  Filenames *are* display names; the filename is what shows up in wikilinks.
  ``projects/`` is read-only to Delphi (human-curated). ``entities/`` is
  read+write — that's where promotion writes new stubs.
- ``<vault>/.delphi/entity_candidates.json`` — our private cache of
  noun-phrases that haven't earned a stub yet, plus the cross-conversation
  count and first-seen date.

Concurrency: a single ``asyncio.Lock`` serializes candidate-file writes.
Single-instance service per VM (CLAUDE.md → "Not multi-tenant"), so an
in-process lock is enough; if a second instance ever shares the vault, swap
this for a file lock.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from memory.templates import TemplateRenderer

_CANDIDATE_RELPATH = ".delphi/entity_candidates.json"

# Phrases that look like proper nouns but almost never are — they tend to
# show up because they sit at the start of a sentence. The threshold rule
# would eventually filter them, but the candidate file would balloon.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "this", "that", "these", "those", "a", "an", "and", "or", "but", "so",
        "is", "are", "was", "were", "be", "been", "being", "am",
        "i", "you", "he", "she", "it", "they", "we", "me", "him", "her", "us", "them",
        "yes", "no", "ok", "okay", "yeah", "yep", "nope",
        "of", "in", "on", "at", "to", "for", "with", "by", "from", "into", "onto",
        "if", "then", "else", "when", "where", "why", "how", "what", "who", "which",
        "while", "as", "such", "like", "very", "many", "much", "some", "all", "any",
        "each", "every", "do", "does", "did", "doing", "have", "has", "had", "having",
        "will", "would", "should", "could", "may", "might", "must", "can", "shall",
        "let", "make", "get", "give", "take", "see", "say", "tell", "use", "used",
        "first", "last", "next", "previous", "above", "below", "more", "less", "most",
        "least", "now", "then", "here", "there", "today", "yesterday", "tomorrow",
        "good", "bad", "great", "fine", "well", "new", "old", "same",
        "other", "another", "different", "either", "neither", "both",
        "however", "because", "since", "though", "although", "unless", "until",
        "before", "after", "during", "without", "within",
        "upon", "across", "through", "between", "among",
        "about", "around", "near", "far", "always", "never", "often", "sometimes",
        "really", "just", "only", "even", "still", "ever",
    }
)

# Capitalized phrase: one or more capitalized words. "Pydantic", "Tali Mosley",
# "Federated Learning Project". Word boundary on either side stops mid-word matches.
_CAP_PHRASE = re.compile(
    r"(?<![\w\[])([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z0-9]*)*)(?![\w\]])"
)

# Mixed-case identifier (PascalCase / camelCase with 2+ capital letters).
# Matches "FastAPI", "OpenAI", "AgentRig"; skips plain "Pydantic" (handled above).
_PASCAL = re.compile(r"(?<![\w\[])([A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]+)+)(?![\w\]])")

# Backtick-quoted identifier: ``Pydantic``, ``cosine-similarity-routing``.
_BACKTICK = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_.\-]{2,})`")

# Existing ``[[...]]`` regions — never touched when annotating.
_WIKILINK = re.compile(r"\[\[[^\[\]]+?\]\]")


def _slugify(name: str) -> str:
    """Lowercase, hyphenated slug. Empty input → empty string."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


@dataclass(frozen=True, slots=True)
class ProcessedExchange:
    """Output of ``EntityIndex.process`` — everything the persistence layer needs."""

    annotated_user: str
    annotated_assistant: str
    entities: list[str] = field(default_factory=list)
    project: str | None = None  # Pre-formatted as ``[[Name]]`` or ``None``.
    promoted: list[str] = field(default_factory=list)


class EntityIndex:
    """Per-vault index of known entities + candidate noun-phrases."""

    def __init__(
        self,
        vault: Path | str,
        threshold: int = 2,
        renderer: TemplateRenderer | None = None,
    ) -> None:
        self._vault = Path(vault)
        self._threshold = threshold
        self._lock = asyncio.Lock()
        self._renderer = renderer or TemplateRenderer()

    @property
    def vault(self) -> Path:
        return self._vault

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def _candidate_path(self) -> Path:
        return self._vault / _CANDIDATE_RELPATH

    @property
    def _entities_dir(self) -> Path:
        return self._vault / "entities"

    @property
    def _projects_dir(self) -> Path:
        return self._vault / "projects"

    # --- known-entity / project lookup ----------------------------------

    @staticmethod
    def _read_dir_sync(directory: Path) -> dict[str, str]:
        if not directory.is_dir():
            return {}
        result: dict[str, str] = {}
        for path in directory.glob("*.md"):
            display = path.stem
            slug = _slugify(display)
            if slug:
                result[slug] = display
        return result

    async def known_entities(self) -> dict[str, str]:
        return await asyncio.to_thread(self._read_dir_sync, self._entities_dir)

    async def known_projects(self) -> dict[str, str]:
        return await asyncio.to_thread(self._read_dir_sync, self._projects_dir)

    async def resolve_project(self, hint: str | None) -> str | None:
        """Return ``[[Name]]`` matching a project file, or ``None``."""
        if not hint:
            return None
        slug = _slugify(hint)
        if not slug:
            return None
        projects = await self.known_projects()
        match = projects.get(slug)
        return f"[[{match}]]" if match else None

    # --- candidate extraction -------------------------------------------

    @staticmethod
    def _extract_candidates_sync(text: str) -> list[tuple[str, str]]:
        """Pull (slug, display) candidate pairs from text.

        First match wins on display form — later matches with the same slug
        but different casing don't overwrite. Order is preserved so tests
        can rely on it.
        """
        found: dict[str, str] = {}

        def consider(display: str) -> None:
            slug = _slugify(display)
            if not slug or slug in _STOPWORDS or len(slug) < 3:
                return
            found.setdefault(slug, display)

        for match in _CAP_PHRASE.finditer(text):
            consider(match.group(1))
        for match in _PASCAL.finditer(text):
            consider(match.group(1))
        for match in _BACKTICK.finditer(text):
            consider(match.group(1))

        return list(found.items())

    def extract_candidates(self, text: str) -> list[tuple[str, str]]:
        """Public sync API for candidate extraction (no I/O)."""
        return self._extract_candidates_sync(text)

    # --- wikilink rewriting ---------------------------------------------

    @staticmethod
    def _annotate_sync(text: str, known: dict[str, str]) -> tuple[str, list[str]]:
        if not known or not text:
            return text, []

        # Sort longest first so multi-word names win over single-word substrings.
        names_by_length = sorted(known.values(), key=len, reverse=True)
        pattern = re.compile(
            r"(?<![\w\[])(?:" + "|".join(re.escape(n) for n in names_by_length) + r")(?![\w\]])",
            re.IGNORECASE,
        )

        # Track existing wikilink spans so we don't rewrite inside them.
        protected: list[tuple[int, int]] = [
            (m.start(), m.end()) for m in _WIKILINK.finditer(text)
        ]

        def is_protected(start: int, end: int) -> bool:
            return any(ps <= start and end <= pe for ps, pe in protected)

        canonical_by_lower = {n.lower(): n for n in names_by_length}
        seen: list[str] = []
        seen_set: set[str] = set()
        parts: list[str] = []
        last_end = 0

        for match in pattern.finditer(text):
            if is_protected(match.start(), match.end()):
                continue
            canonical = canonical_by_lower.get(match.group(0).lower())
            if canonical is None:
                continue
            parts.append(text[last_end : match.start()])
            parts.append(f"[[{canonical}]]")
            last_end = match.end()
            if canonical not in seen_set:
                seen_set.add(canonical)
                seen.append(canonical)
        parts.append(text[last_end:])
        return "".join(parts), seen

    async def annotate(self, text: str) -> tuple[str, list[str]]:
        """Rewrite known entity/project mentions as ``[[wikilinks]]``."""
        entities = await self.known_entities()
        projects = await self.known_projects()
        merged = {**entities, **projects}
        return await asyncio.to_thread(self._annotate_sync, text, merged)

    # --- candidate persistence ------------------------------------------

    def _read_candidates_sync(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self._candidate_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_candidates_sync(self, store: dict[str, dict[str, Any]]) -> None:
        self._candidate_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._candidate_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._candidate_path)

    def _create_entity_stub_sync(self, display: str, first_seen: str) -> Path:
        self._entities_dir.mkdir(parents=True, exist_ok=True)
        path = self._entities_dir / f"{display}.md"
        today = date.today().isoformat()
        content = self._renderer.render_entity_stub(
            display=display,
            first_mentioned=first_seen,
            created=today,
        )
        path.write_text(content, encoding="utf-8")
        return path

    async def record_mentions(
        self,
        candidates: Iterable[tuple[str, str]],
        *,
        when: date | None = None,
    ) -> list[str]:
        """Bump cross-conversation counts. Return display names of newly promoted entities."""
        async with self._lock:
            return await asyncio.to_thread(self._record_mentions_sync, list(candidates), when)

    def _record_mentions_sync(
        self,
        candidates: list[tuple[str, str]],
        when: date | None,
    ) -> list[str]:
        known = self._read_dir_sync(self._entities_dir)
        stamp = (when or date.today()).isoformat()
        store = self._read_candidates_sync()
        promoted: list[str] = []

        for slug, display in candidates:
            if slug in known:
                continue
            entry = store.get(slug) or {"display": display, "count": 0, "first_seen": stamp}
            entry["count"] = int(entry.get("count", 0)) + 1
            entry.setdefault("first_seen", stamp)
            # Prefer the display form we already saved (first wins) so promotion
            # uses a stable name even if later mentions vary in casing.
            entry["display"] = entry.get("display") or display
            store[slug] = entry
            if entry["count"] >= self._threshold:
                self._create_entity_stub_sync(entry["display"], entry["first_seen"])
                promoted.append(entry["display"])
                del store[slug]

        self._write_candidates_sync(store)
        return promoted

    # --- one-call API ----------------------------------------------------

    async def process(
        self,
        *,
        user_text: str,
        assistant_text: str,
        project_hint: str | None = None,
        when: date | None = None,
    ) -> ProcessedExchange:
        """Run the full entity pipeline for one exchange.

        Order matters:
        1. Extract candidates from the assistant text (only the model's
           own output earns mention credit).
        2. Bump counts and promote — promotion writes new entity files
           *before* annotation runs, so a newly promoted entity gets a
           wikilink in the same conversation that promoted it.
        3. Annotate user + assistant against the now-current known set.
        4. Resolve the project hint against ``projects/``.
        """
        candidates = self._extract_candidates_sync(assistant_text)
        promoted = await self.record_mentions(candidates, when=when)

        annotated_user, entities_in_user = await self.annotate(user_text)
        annotated_assistant, entities_in_assistant = await self.annotate(assistant_text)

        seen: set[str] = set()
        entities: list[str] = []
        for name in (*entities_in_user, *entities_in_assistant):
            if name not in seen:
                seen.add(name)
                entities.append(name)

        project = await self.resolve_project(project_hint)
        return ProcessedExchange(
            annotated_user=annotated_user,
            annotated_assistant=annotated_assistant,
            entities=entities,
            project=project,
            promoted=promoted,
        )
