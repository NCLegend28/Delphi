"""Bulk-ingest GRE vocabulary CSVs into ``knowledge/gre/vocab/`` notes.

The Phase 2 ingest path for the GRE knowledge vault. Reads one or more
source CSVs, normalizes each row into a ``MergedWord``, deduplicates on the
canonical word slug, and writes one Obsidian note per word using the
``vocab.md.j2`` template.

Three source formats are supported out of the box:

* **Magoosh** — columns: ``,word,definition,part of speech,example``. Has
  POS and (usually) an example sentence; richer entries.
* **Manhattan Prep** — first row is a title cell, second row is the column
  header (``Word,Definition,…`` plus empty trailing columns). Just word and
  a terse definition.
* **GregMat** — sectioned by group. Marker rows look like ``GroupN,`` and
  introduce ~30 word/definition pairs (multi-sense definitions use
  numbered ``1. … \n2. …`` syntax). The group number is captured as
  ``gregmat_group`` in the merged record — a useful difficulty proxy.

The merge rule is *Magoosh-primary*: if a word appears in multiple
sources, Magoosh's POS + example win, and the other sources' definitions
are appended as additional ``> ...`` lines when they add substance. The
``sources`` frontmatter field records what contributed; the ``n_sources``
integer makes "show me canonical words that appear in all three lists"
trivially queryable.

Idempotency:

- The script never deletes notes. By default it **skips** any existing
  file (hand-curated cards like ``perspicacious.md`` are preserved as-is).
- ``--force`` overwrites all notes, but the ingest will splice the
  existing ``review:`` block back in so SRS state survives a re-ingest.
- ``--dry-run`` lists what would change without touching disk.

Usage::

    uv run python -m scripts.ingest.gre_vocab \\
        --vault $OBSIDIAN_VAULT_PATH \\
        --domain gre \\
        --magoosh scripts/data/gre/magoosh-1000.csv \\
        --manhattan scripts/data/gre/manhattan-1000.csv \\
        --gregmat scripts/data/gre/gregmat.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from memory.templates import yaml_list, yaml_scalar

# --- domain model ---------------------------------------------------------


@dataclass(slots=True)
class RawRow:
    """One parsed CSV row, source-labelled and minimally normalized."""

    word: str
    source: str
    pos: str | None = None
    definition: str | None = None
    example: str | None = None
    gregmat_group: int | None = None  # only set when source == "GregMat"


@dataclass(slots=True)
class MergedWord:
    """A word after merging across sources. Renders 1:1 to a vault note."""

    word: str  # canonical slug — lowercase, hyphen-friendly
    pos: str | None
    definition: str
    secondary_definitions: list[str] = field(default_factory=list)
    example: str | None = None
    sources: list[str] = field(default_factory=list)
    gregmat_group: int | None = None  # group number from the GregMat list


# --- parsing --------------------------------------------------------------

# Horizontal whitespace only (no newlines) — newlines carry semantics in
# the GregMat data where they separate numbered senses inside one cell.
_HORIZONTAL_WS = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE = re.compile(r"\n{2,}")


def _clean(value: str | None) -> str | None:
    """Strip + collapse whitespace; turn empties into ``None``.

    Horizontal whitespace collapses to single spaces. Newlines are
    preserved (GregMat uses them between numbered senses), but runs of
    blank lines fold to one and every line is individually stripped.
    """
    if value is None:
        return None
    cleaned = _HORIZONTAL_WS.sub(" ", value)
    cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
    cleaned = _MULTI_NEWLINE.sub("\n", cleaned).strip()
    return cleaned or None


def _slug(word: str) -> str:
    """Canonical word key. Lowercased ASCII, spaces/punct → hyphens.

    Multi-word entries (rare in the GRE lists) collapse to a hyphenated
    slug; ``"ad hoc"`` → ``ad-hoc``. The slug is the filename and the
    dedupe key — never the display word.
    """
    s = word.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_magoosh(rows: Iterable[list[str]]) -> Iterator[RawRow]:
    """Iterate Magoosh rows. Layout: ``[blank], word, definition, pos, example``.

    The first column is always empty in this export. We skip the header
    (its second column literally reads ``word``) and any row whose word
    cell is blank.
    """
    for idx, row in enumerate(rows):
        if idx == 0:
            continue  # header
        if len(row) < 5:
            continue
        word = _clean(row[1])
        if not word or word.lower() == "word":
            continue
        yield RawRow(
            word=word,
            source="Magoosh",
            pos=_clean(row[3]),
            definition=_clean(row[2]),
            example=_clean(row[4]),
        )


_GREGMAT_GROUP = re.compile(r"^Group\s*(\d+)$", re.IGNORECASE)


def parse_gregmat(rows: Iterable[list[str]]) -> Iterator[RawRow]:
    """Iterate GregMat rows. Layout: blank prelude, then repeating sections::

        Group<N>,
        Word,Definition
        word1,"def1 (may span\\nmultiple senses)"
        word2,def2
        ...

    Multi-sense definitions use numbered ``1. … \\n2. …`` markers inside one
    CSV cell — the newlines are preserved by ``csv.reader`` when quoted. We
    keep the body as-is so the renderer can format it.

    The group number stays in scope until the next ``Group<N>,`` marker;
    rows in that span carry it through ``RawRow.gregmat_group``.
    """
    current_group: int | None = None
    for row in rows:
        if not row:
            continue
        cell0 = _clean(row[0]) if row else None
        if not cell0:
            continue

        # Section marker: ``Group<N>,``
        group_match = _GREGMAT_GROUP.match(cell0)
        if group_match:
            current_group = int(group_match.group(1))
            continue

        # Per-section header: ``Word,Definition``
        if cell0.lower() == "word":
            continue

        definition = _clean(row[1]) if len(row) > 1 else None
        if not definition:
            continue

        yield RawRow(
            word=cell0,
            source="GregMat",
            pos=None,
            definition=definition,
            example=None,
            gregmat_group=current_group,
        )


def parse_manhattan(rows: Iterable[list[str]]) -> Iterator[RawRow]:
    """Iterate Manhattan rows. First row is a title cell, second is header.

    ``[title, , , , , , ]``
    ``[Word, Definition, Column 3, …]``
    ``[abase, "Degrade or humble; …", , , , , ]``
    """
    for idx, row in enumerate(rows):
        if idx < 2:
            continue  # title + header
        if not row:
            continue
        word = _clean(row[0]) if len(row) > 0 else None
        if not word or word.lower() == "word":
            continue
        definition = _clean(row[1]) if len(row) > 1 else None
        yield RawRow(
            word=word,
            source="Manhattan Prep",
            pos=None,
            definition=definition,
            example=None,
        )


def read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


# --- merging --------------------------------------------------------------


def merge(rows: Iterable[RawRow]) -> dict[str, MergedWord]:
    """Group raw rows by slug. Magoosh wins POS + example; both definitions kept.

    The merge order does not matter — within a slug we always prefer the
    Magoosh row's POS and example over Manhattan's (which has neither),
    and we keep both definitions when they're substantively different.
    """
    merged: dict[str, MergedWord] = {}
    for raw in rows:
        if not raw.definition:
            continue  # no point creating an empty card
        slug = _slug(raw.word)
        if not slug:
            continue
        existing = merged.get(slug)
        if existing is None:
            merged[slug] = MergedWord(
                word=raw.word.strip().lower(),
                pos=raw.pos,
                definition=raw.definition,
                example=raw.example,
                sources=[raw.source],
                gregmat_group=raw.gregmat_group,
            )
            continue

        # Already have an entry — fold in whatever raw adds.
        if raw.source not in existing.sources:
            existing.sources.append(raw.source)
        if existing.pos is None and raw.pos:
            existing.pos = raw.pos
        if existing.example is None and raw.example:
            existing.example = raw.example
        if existing.gregmat_group is None and raw.gregmat_group is not None:
            existing.gregmat_group = raw.gregmat_group

        # Definition merge: keep the longer / richer as primary; the other
        # goes into ``secondary_definitions`` if it adds material the
        # primary doesn't already contain (rough substring check).
        primary = existing.definition
        candidate = raw.definition
        if len(candidate) > len(primary) * 1.5:
            # Candidate is meaningfully longer — promote it.
            existing.definition = candidate
            primary = candidate
            candidate = primary  # secondary check below sees the displaced one
            # The displaced primary still counts as secondary if novel.
            if primary not in existing.secondary_definitions and primary != existing.definition:
                existing.secondary_definitions.append(primary)
        if (
            candidate.lower() not in primary.lower()
            and primary.lower() not in candidate.lower()
            and candidate not in existing.secondary_definitions
            and candidate != existing.definition
        ):
            existing.secondary_definitions.append(candidate)

    return merged


# --- rendering ------------------------------------------------------------


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    env.filters["yaml_scalar"] = yaml_scalar
    env.filters["yaml_list"] = yaml_list
    return env


def render(merged: MergedWord, *, added: str) -> str:
    """Render one merged word to markdown via ``vocab.md.j2``."""
    tags = ["gre", "vocab"]
    if "Magoosh" in merged.sources:
        tags.append("magoosh")
    if "Manhattan Prep" in merged.sources:
        tags.append("manhattan")
    if "GregMat" in merged.sources:
        tags.append("gregmat")
    # Cross-source signal: words in 2+ lists are "shared"; words in all 3
    # are "canonical" — likely high-frequency GRE picks worth prioritising.
    if len(merged.sources) >= 2:
        tags.append("shared")
    if len(merged.sources) >= 3:
        tags.append("canonical")
    template = _env().get_template("vocab.md.j2")
    return template.render(
        word=merged.word,
        pos=merged.pos,
        definition=merged.definition,
        secondary_definitions=merged.secondary_definitions,
        example=merged.example,
        sources=merged.sources,
        n_sources=len(merged.sources),
        gregmat_group=merged.gregmat_group,
        tags=tags,
        added=added,
    )


# --- vault write ----------------------------------------------------------

# Match a YAML ``review:`` block (and its indented children) so we can
# splice it back in on ``--force`` overwrite, preserving SRS state.
_REVIEW_BLOCK = re.compile(
    r"^review:\s*\n(?:[ \t]+\S.*\n?)*",
    re.MULTILINE,
)


def _existing_review_block(path: Path) -> str | None:
    """Return the existing ``review:`` block from a note's frontmatter, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _REVIEW_BLOCK.search(text)
    return match.group(0).rstrip() + "\n" if match else None


def _splice_review(rendered: str, review_block: str) -> str:
    """Replace the rendered template's ``review:`` block with a preserved one."""
    return _REVIEW_BLOCK.sub(review_block, rendered, count=1)


@dataclass(slots=True)
class WriteOutcome:
    created: int = 0
    skipped: int = 0
    overwritten: int = 0
    preserved_review: int = 0


def write_all(
    merged: dict[str, MergedWord],
    *,
    vault: Path,
    domain: str,
    force: bool,
    dry_run: bool,
    added: str,
) -> WriteOutcome:
    """Write one note per merged word under ``<vault>/knowledge/<domain>/vocab/``.

    Default behaviour: skip files that already exist. Hand-curated notes
    (e.g. the seeded ``perspicacious.md`` with its mnemonic and confusion
    set) survive a bulk re-ingest unmodified.

    With ``--force``: overwrite, but splice any existing ``review:`` block
    back in so SRS state is preserved.
    """
    target_dir = vault / "knowledge" / domain / "vocab"
    target_dir.mkdir(parents=True, exist_ok=True)

    outcome = WriteOutcome()
    for slug, word in sorted(merged.items()):
        path = target_dir / f"{slug}.md"
        rendered = render(word, added=added)

        if path.exists():
            if not force:
                outcome.skipped += 1
                continue
            review = _existing_review_block(path)
            if review is not None:
                rendered = _splice_review(rendered, review)
                outcome.preserved_review += 1
            outcome.overwritten += 1
        else:
            outcome.created += 1

        if not dry_run:
            path.write_text(rendered, encoding="utf-8")

    return outcome


# --- CLI ------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="gre_vocab",
        description="Bulk-ingest GRE vocab CSVs into the knowledge vault.",
    )
    p.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Path to the Obsidian vault root (the value of OBSIDIAN_VAULT_PATH).",
    )
    p.add_argument(
        "--domain",
        default="gre",
        help="Sub-namespace under knowledge/ (default: gre).",
    )
    p.add_argument(
        "--magoosh",
        type=Path,
        help="Path to the Magoosh CSV (5-col format).",
    )
    p.add_argument(
        "--manhattan",
        type=Path,
        help="Path to the Manhattan Prep CSV (title + header + 2-col data).",
    )
    p.add_argument(
        "--gregmat",
        type=Path,
        help="Path to the GregMat CSV (sectioned by ``Group<N>,`` markers).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing notes (preserving their review: blocks).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    raw: list[RawRow] = []
    if args.magoosh:
        raw.extend(parse_magoosh(read_csv(args.magoosh)))
    if args.manhattan:
        raw.extend(parse_manhattan(read_csv(args.manhattan)))
    if args.gregmat:
        raw.extend(parse_gregmat(read_csv(args.gregmat)))

    if not raw:
        print(
            "error: no source CSVs supplied (pass --magoosh, --manhattan, and/or --gregmat)",
            file=sys.stderr,
        )
        return 2

    merged = merge(raw)
    today = date.today().isoformat()
    outcome = write_all(
        merged,
        vault=args.vault,
        domain=args.domain,
        force=args.force,
        dry_run=args.dry_run,
        added=today,
    )

    raw_count = len(raw)
    print(
        f"sources: {raw_count} raw rows → {len(merged)} unique words",
        f"(--dry-run)" if args.dry_run else "",
    )
    print(
        f"  created:           {outcome.created}\n"
        f"  skipped (existing): {outcome.skipped}\n"
        f"  overwritten:       {outcome.overwritten}\n"
        f"  review preserved:  {outcome.preserved_review}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
