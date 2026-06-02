"""Read and atomically rewrite a single vocab card's ``review:`` block.

Vocab cards under ``knowledge/<domain>/vocab/`` are hand-curated markdown
files with typed YAML frontmatter. The quiz agent needs to update one
specific block — ``review:`` — without disturbing anything else (mnemonics,
confusion sets, hand-edited examples). A full YAML round-trip would
re-serialize the whole frontmatter and risk re-flowing lists, quoting
strings differently, or stripping trailing whitespace; over thousands of
cards those drifts add up to a meaningless churn diff every quiz session.

So this module takes the surgical approach: parse with ``pyyaml`` for
reading (where round-trip fidelity doesn't matter), but rewrite the
``review:`` block in place via line-level surgery on the original bytes —
locate the block, render the new one in a fixed format, splice. Every
other line in the file lands byte-identical. If a card has no
``review:`` block at all, the new one is inserted at the end of the
frontmatter so the schema converges over time.

The write is atomic: ``tempfile`` next to the target, then ``os.replace``.
A crash mid-write leaves the original intact.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from memory.srs import DEFAULT_EASE, ReviewState

# Frontmatter is bounded by two ``---`` lines at column 0. The opening
# fence must be the very first line of the file (line 0), per the spec.
_FENCE = "---"


class VocabCardError(Exception):
    """Raised when a card's frontmatter can't be parsed or located."""


@dataclass(frozen=True, slots=True)
class VocabCard:
    """Lightweight in-memory view of a vocab card.

    Carries only the fields the quiz agent actually queries on:
    ``word``, ``difficulty``, ``tags``, plus the parsed ``review`` block.
    The raw text is kept so callers that need to display the body
    (definition, examples, confusion set) don't have to re-read the file.
    """

    path: Path  # absolute path on disk
    word: str
    difficulty: str | None
    tags: tuple[str, ...]
    review: ReviewState
    raw_text: str
    frontmatter: dict[str, Any]


def _split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    """Return (frontmatter_lines, body_lines), excluding the fences.

    ``frontmatter_lines`` may be empty if the file has no frontmatter; in
    that case the caller treats it as "no review block" and inserts one.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != _FENCE:
        return [], lines
    # Walk forward until the closing fence.
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == _FENCE:
            return lines[1:i], lines[i + 1 :]
    # Opening fence with no closing → treat as malformed; no frontmatter.
    return [], lines


def _parse_frontmatter(frontmatter_lines: list[str]) -> dict[str, Any]:
    if not frontmatter_lines:
        return {}
    try:
        loaded = yaml.safe_load("".join(frontmatter_lines))
    except yaml.YAMLError as exc:
        raise VocabCardError(f"frontmatter is not valid YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise VocabCardError("frontmatter must be a mapping at the top level")
    return loaded


def _coerce_review(raw: Any) -> ReviewState:
    """Build a ``ReviewState`` from the parsed frontmatter's ``review`` value.

    Missing or malformed entries fall back to defaults rather than raising —
    the schema has been hand-edited across ingestion runs and we don't want
    one weird card to break the whole drill.
    """
    if not isinstance(raw, dict):
        return ReviewState()

    ease = raw.get("ease", DEFAULT_EASE)
    try:
        ease_f = float(ease) if ease is not None else DEFAULT_EASE
    except (TypeError, ValueError):
        ease_f = DEFAULT_EASE

    interval = raw.get("interval_days", 0)
    try:
        interval_i = int(interval) if interval is not None else 0
    except (TypeError, ValueError):
        interval_i = 0

    last = raw.get("last_reviewed")
    last_dt: datetime | None
    if isinstance(last, datetime):
        last_dt = last
    elif isinstance(last, str) and last.strip():
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            last_dt = None
    else:
        last_dt = None

    return ReviewState(ease=ease_f, interval_days=interval_i, last_reviewed=last_dt)


def _coerce_tags(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(t) for t in raw)
    return ()


def read(path: str | Path) -> VocabCard:
    """Load and parse a vocab card. Raises ``VocabCardError`` on schema problems."""
    p = Path(path)
    if not p.is_file():
        raise VocabCardError(f"no such card: {p}")
    text = p.read_text(encoding="utf-8")
    fm_lines, _body = _split_frontmatter(text)
    fm = _parse_frontmatter(fm_lines)

    word = fm.get("word")
    if not isinstance(word, str) or not word.strip():
        # Fall back to the filename stem so a malformed card is still graded.
        word = p.stem

    difficulty = fm.get("difficulty") if isinstance(fm.get("difficulty"), str) else None
    tags = _coerce_tags(fm.get("tags"))
    review = _coerce_review(fm.get("review"))

    return VocabCard(
        path=p,
        word=word.strip(),
        difficulty=difficulty,
        tags=tags,
        review=review,
        raw_text=text,
        frontmatter=fm,
    )


def _render_review_block(state: ReviewState) -> str:
    """Render the canonical ``review:`` block. Two-space indent, block style.

    Format is deterministic so re-renders of an unchanged state produce
    byte-identical output (idempotent writes).
    """
    if state.last_reviewed is None:
        last_line = "  last_reviewed: null\n"
    else:
        # isoformat() yields the local-timezone-aware ISO string the rest
        # of the codebase uses (e.g. ``2026-06-02T14:32:18-05:00``).
        last_line = f"  last_reviewed: {state.last_reviewed.isoformat()}\n"
    return (
        "review:\n"
        + last_line
        + f"  ease: {state.ease}\n"
        + f"  interval_days: {state.interval_days}\n"
    )


def _locate_review_block(frontmatter_lines: list[str]) -> tuple[int, int] | None:
    """Find the ``review:`` block within frontmatter lines.

    Returns ``(start, end)`` half-open indices into ``frontmatter_lines``
    such that ``frontmatter_lines[start:end]`` is the block (the ``review:``
    line plus all indented continuation lines). ``None`` if no block exists.
    """
    start: int | None = None
    for i, line in enumerate(frontmatter_lines):
        stripped = line.rstrip("\r\n")
        # Top-level key starts at column 0 and looks like ``key:`` (no leading
        # whitespace, contains a colon, not a fence).
        if start is None:
            if stripped.startswith("review:") and not stripped.startswith(" "):
                start = i
            continue
        # We're inside the block — continuation lines are blank or indented.
        if stripped == "" or line.startswith((" ", "\t")):
            continue
        return (start, i)
    if start is not None:
        return (start, len(frontmatter_lines))
    return None


def _splice(text: str, new_review: str) -> str:
    """Return ``text`` with the ``review:`` block replaced (or inserted)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != _FENCE:
        # No frontmatter at all — synthesize a minimal one rather than
        # corrupting the body. Cards without frontmatter shouldn't happen
        # in practice; this is the defensive branch.
        return f"{_FENCE}\n{new_review}{_FENCE}\n{text}"

    # Find the closing fence.
    closing_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == _FENCE:
            closing_idx = i
            break
    if closing_idx is None:
        # Malformed (no closing fence) — leave as-is rather than guessing.
        return text

    fm_lines = lines[1:closing_idx]
    located = _locate_review_block(fm_lines)
    if located is None:
        # Insert a new block at the end of the frontmatter so future reads
        # see it. Keep one trailing newline before the closing fence.
        if fm_lines and not fm_lines[-1].endswith("\n"):
            fm_lines[-1] = fm_lines[-1] + "\n"
        fm_lines.append(new_review)
    else:
        start, end = located
        fm_lines[start:end] = [new_review]

    return "".join(lines[:1] + fm_lines + lines[closing_idx:])


def write_review(path: str | Path, state: ReviewState) -> None:
    """Atomically rewrite a card's ``review:`` block to ``state``.

    The rest of the file is preserved byte-for-byte. Writes via a tempfile
    in the same directory + ``os.replace`` so a crash mid-write leaves the
    original intact (and so ``os.replace`` can be atomic on Linux).
    """
    p = Path(path)
    if not p.is_file():
        raise VocabCardError(f"no such card: {p}")

    original = p.read_text(encoding="utf-8")
    new_block = _render_review_block(state)
    updated = _splice(original, new_block)

    # Same directory so ``os.replace`` is atomic (cross-device rename would not be).
    dir_path = str(p.parent)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=dir_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(updated)
        os.replace(tmp_path, p)
    except Exception:
        # Best-effort cleanup; if replace already happened, unlink is a no-op.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
