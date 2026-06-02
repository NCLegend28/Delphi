"""Unit tests for the GRE vocab bulk ingest.

Covers parsing both source layouts, the Magoosh-primary merge rule,
idempotent vault writes (skip existing, preserve hand-curated cards),
and the ``--force`` path that splices an existing ``review:`` block
back into a re-rendered note so SRS state survives a re-ingest.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.ingest.gre_vocab import (
    MergedWord,
    RawRow,
    merge,
    parse_gregmat,
    parse_magoosh,
    parse_manhattan,
    render,
    write_all,
)


# --- parsing --------------------------------------------------------------


def _magoosh_rows() -> list[list[str]]:
    return [
        ["", "word", "definition", "part of speech", "example"],
        ["", "aberrant", "markedly different from an accepted norm.", "adjective", "His behavior was aberrant."],
        ["", "abstain", "choose not to consume or take part in something.", "verb", ""],
        ["", "", "should be skipped", "", ""],  # blank word
    ]


def _manhattan_rows() -> list[list[str]]:
    return [
        ["GRE_Vocabulary", "", "", "", "", "", ""],
        ["Word", "Definition", "Column 3", "Column 4", "Column 5", "Column 6", "Column 7"],
        ["aberrant", "Abnormal, deviant", "", "", "", "", ""],
        ["abase", "Degrade or humble; to lower in rank.", "", "", "", "", ""],
        ["", "skip me", "", "", "", "", ""],
    ]


def test_parse_magoosh_skips_header_and_blanks() -> None:
    rows = list(parse_magoosh(_magoosh_rows()))
    words = [r.word for r in rows]
    assert words == ["aberrant", "abstain"]
    assert rows[0].source == "Magoosh"
    assert rows[0].pos == "adjective"
    assert rows[0].example == "His behavior was aberrant."
    # Empty example field becomes None, not "".
    assert rows[1].example is None


def _gregmat_rows() -> list[list[str]]:
    """A reduced GregMat sample: two groups, one ``Word,Definition`` header
    per group, a couple of word rows, plus a leading blank prelude (the
    real CSV has ~30 blank rows at the top)."""
    return [
        ["", ""],
        ["", ""],
        ["Group2", ""],
        ["Word", "Definition"],
        ["adulterate", "damage the quality of; corrupt"],
        ["advocate", "support; be in favor of\nsomeone who supports a cause"],
        ["Group3", ""],
        ["Word", "Definition"],
        ["aggrandize", "enhance one's power or standing"],
        ["", "skip — blank word"],
    ]


def test_parse_gregmat_tracks_group_and_skips_section_headers() -> None:
    rows = list(parse_gregmat(_gregmat_rows()))
    assert [r.word for r in rows] == ["adulterate", "advocate", "aggrandize"]
    assert all(r.source == "GregMat" for r in rows)
    # First two were under Group2, third moved to Group3.
    assert rows[0].gregmat_group == 2
    assert rows[1].gregmat_group == 2
    assert rows[2].gregmat_group == 3


def test_parse_gregmat_preserves_multisense_newlines() -> None:
    rows = list(parse_gregmat(_gregmat_rows()))
    advocate = next(r for r in rows if r.word == "advocate")
    assert "\n" in advocate.definition, "multi-sense newline must survive parsing"


def test_parse_manhattan_skips_title_and_header() -> None:
    rows = list(parse_manhattan(_manhattan_rows()))
    assert [r.word for r in rows] == ["aberrant", "abase"]
    assert all(r.source == "Manhattan Prep" for r in rows)
    assert all(r.pos is None for r in rows)
    assert all(r.example is None for r in rows)


# --- merging --------------------------------------------------------------


def test_merge_dedupes_on_lowercased_word() -> None:
    raws = [
        RawRow(word="Aberrant", source="Magoosh", pos="adjective", definition="norm-violating"),
        RawRow(word="aberrant", source="Manhattan Prep", definition="abnormal, deviant"),
    ]
    merged = merge(raws)
    assert list(merged.keys()) == ["aberrant"]
    out = merged["aberrant"]
    assert out.pos == "adjective", "Magoosh POS must win"
    assert "Magoosh" in out.sources and "Manhattan Prep" in out.sources


def test_merge_keeps_both_definitions_when_substantively_different() -> None:
    """Magoosh's definition stays primary; Manhattan's adds a secondary line
    if it's not already implied by the primary."""
    raws = [
        RawRow(word="abase", source="Magoosh", pos="verb", definition="degrade; humble; bring low."),
        RawRow(word="abase", source="Manhattan Prep", definition="lower in rank, status, or esteem"),
    ]
    out = merge(raws)["abase"]
    assert out.definition == "degrade; humble; bring low."
    assert out.secondary_definitions == ["lower in rank, status, or esteem"]


def test_merge_collapses_redundant_definition() -> None:
    """When one definition is a substring of the other, no duplicate line."""
    raws = [
        RawRow(word="abate", source="Magoosh", definition="reduce, diminish, lessen in intensity"),
        RawRow(word="abate", source="Manhattan Prep", definition="reduce, diminish"),
    ]
    out = merge(raws)["abate"]
    assert out.secondary_definitions == []


def test_merge_promotes_substantially_longer_candidate_to_primary() -> None:
    """If the second source has a much richer definition, it becomes primary."""
    raws = [
        RawRow(word="acme", source="Manhattan Prep", definition="peak"),
        RawRow(word="acme", source="Magoosh", definition="the highest point or peak of something, esp. of achievement or excellence."),
    ]
    out = merge(raws)["acme"]
    assert out.definition.startswith("the highest point")


def test_merge_drops_rows_without_definition() -> None:
    raws = [RawRow(word="ghost", source="Manhattan Prep", definition=None)]
    assert merge(raws) == {}


def test_merge_captures_gregmat_group_when_present() -> None:
    raws = [
        RawRow(word="adulterate", source="Magoosh", pos="verb", definition="corrupt"),
        RawRow(word="adulterate", source="GregMat", definition="corrupt", gregmat_group=2),
    ]
    out = merge(raws)["adulterate"]
    assert out.gregmat_group == 2
    assert out.pos == "verb"  # Magoosh POS still wins


def test_merge_keeps_first_seen_group_when_only_gregmat_has_one() -> None:
    """Only GregMat carries a group, so the field round-trips intact even
    when GregMat is the second source folded in."""
    raws = [
        RawRow(word="aggrandize", source="Manhattan Prep", definition="boost up"),
        RawRow(word="aggrandize", source="GregMat", definition="enhance power", gregmat_group=3),
    ]
    out = merge(raws)["aggrandize"]
    assert out.gregmat_group == 3


# --- rendering ------------------------------------------------------------


def test_render_contains_expected_frontmatter() -> None:
    out = render(
        MergedWord(
            word="aberrant",
            pos="adjective",
            definition="markedly different from an accepted norm.",
            sources=["Magoosh", "Manhattan Prep"],
        ),
        added="2026-06-01",
    )
    assert "type: gre-vocab" in out
    assert 'word: "aberrant"' in out
    assert 'pos: "adjective"' in out
    assert "added: 2026-06-01" in out
    assert "# aberrant" in out
    assert "> markedly different" in out


def test_render_tags_include_source_markers() -> None:
    out = render(
        MergedWord(
            word="abase",
            pos="verb",
            definition="degrade.",
            sources=["Manhattan Prep"],
        ),
        added="2026-06-01",
    )
    assert '"manhattan"' in out
    assert '"magoosh"' not in out
    assert '"both"' not in out


def test_render_tags_mark_shared_when_in_two_sources() -> None:
    out = render(
        MergedWord(
            word="aberrant",
            pos="adjective",
            definition="abnormal.",
            sources=["Magoosh", "Manhattan Prep"],
        ),
        added="2026-06-01",
    )
    assert '"magoosh"' in out
    assert '"manhattan"' in out
    assert '"shared"' in out
    assert '"canonical"' not in out  # only 2 sources, not 3
    assert "n_sources: 2" in out


def test_render_tags_mark_canonical_when_in_all_three_sources() -> None:
    """A word in all three lists earns the ``canonical`` tag — the strongest
    signal that it's worth prioritising."""
    out = render(
        MergedWord(
            word="aberrant",
            pos="adjective",
            definition="abnormal.",
            sources=["Magoosh", "Manhattan Prep", "GregMat"],
            gregmat_group=4,
        ),
        added="2026-06-01",
    )
    assert '"magoosh"' in out
    assert '"manhattan"' in out
    assert '"gregmat"' in out
    assert '"shared"' in out
    assert '"canonical"' in out
    assert "n_sources: 3" in out
    assert "gregmat_group: 4" in out


def test_render_omits_gregmat_group_when_absent() -> None:
    out = render(
        MergedWord(
            word="abase",
            pos="verb",
            definition="degrade.",
            sources=["Manhattan Prep"],
        ),
        added="2026-06-01",
    )
    assert "gregmat_group" not in out


def test_render_includes_secondary_definitions() -> None:
    out = render(
        MergedWord(
            word="abate",
            pos="verb",
            definition="primary def",
            secondary_definitions=["secondary def one", "secondary def two"],
            sources=["Magoosh", "Manhattan Prep"],
        ),
        added="2026-06-01",
    )
    assert "> primary def" in out
    assert "> secondary def one" in out
    assert "> secondary def two" in out


def test_render_includes_review_skeleton() -> None:
    out = render(
        MergedWord(word="abate", pos="verb", definition="x", sources=["Magoosh"]),
        added="2026-06-01",
    )
    assert "review:" in out
    assert "ease: 2.5" in out


# --- vault write ----------------------------------------------------------


@pytest.fixture
def merged_two_words() -> dict[str, MergedWord]:
    return {
        "aberrant": MergedWord(
            word="aberrant",
            pos="adjective",
            definition="markedly different from an accepted norm.",
            sources=["Magoosh", "Manhattan Prep"],
        ),
        "abase": MergedWord(
            word="abase",
            pos="verb",
            definition="degrade or humble.",
            sources=["Manhattan Prep"],
        ),
    }


def test_write_all_creates_notes_at_canonical_path(tmp_path: Path, merged_two_words) -> None:
    outcome = write_all(
        merged_two_words,
        vault=tmp_path,
        domain="gre",
        force=False,
        dry_run=False,
        added="2026-06-01",
    )
    assert outcome.created == 2
    assert outcome.skipped == 0
    assert (tmp_path / "knowledge" / "gre" / "vocab" / "aberrant.md").is_file()
    assert (tmp_path / "knowledge" / "gre" / "vocab" / "abase.md").is_file()


def test_write_all_skips_existing_by_default(tmp_path: Path, merged_two_words) -> None:
    """Hand-curated notes (perspicacious.md etc.) must survive a bulk re-ingest."""
    target = tmp_path / "knowledge" / "gre" / "vocab"
    target.mkdir(parents=True)
    (target / "aberrant.md").write_text("HAND CURATED CONTENT", encoding="utf-8")

    outcome = write_all(
        merged_two_words,
        vault=tmp_path,
        domain="gre",
        force=False,
        dry_run=False,
        added="2026-06-01",
    )
    assert outcome.created == 1, "abase is new"
    assert outcome.skipped == 1, "aberrant already exists → skip"
    assert (target / "aberrant.md").read_text(encoding="utf-8") == "HAND CURATED CONTENT"


def test_write_all_dry_run_writes_nothing(tmp_path: Path, merged_two_words) -> None:
    outcome = write_all(
        merged_two_words,
        vault=tmp_path,
        domain="gre",
        force=False,
        dry_run=True,
        added="2026-06-01",
    )
    assert outcome.created == 2
    assert not (tmp_path / "knowledge" / "gre" / "vocab" / "aberrant.md").exists()


def test_force_preserves_review_block(tmp_path: Path, merged_two_words) -> None:
    """``--force`` overwrites, but the existing ``review:`` SRS state must
    survive the re-render so a re-ingest doesn't reset accumulated practice."""
    target = tmp_path / "knowledge" / "gre" / "vocab"
    target.mkdir(parents=True)
    existing = """\
---
type: gre-vocab
word: "aberrant"
pos: "adjective"
difficulty: hard
tags: ["gre", "vocab"]
sources: ["Magoosh"]
added: 2026-05-10
review:
  last_reviewed: 2026-05-25
  ease: 2.8
  interval_days: 14
---

# aberrant

> earlier hand-written body
"""
    (target / "aberrant.md").write_text(existing, encoding="utf-8")

    outcome = write_all(
        merged_two_words,
        vault=tmp_path,
        domain="gre",
        force=True,
        dry_run=False,
        added="2026-06-01",
    )
    # aberrant.md pre-existed → overwritten; abase.md was new → created.
    assert outcome.overwritten == 1
    assert outcome.created == 1
    assert outcome.preserved_review == 1  # only the existing aberrant had a review block

    rewritten = (target / "aberrant.md").read_text(encoding="utf-8")
    # New body content landed:
    assert "markedly different from an accepted norm" in rewritten
    # Old review state survived:
    assert "last_reviewed: 2026-05-25" in rewritten
    assert "ease: 2.8" in rewritten
    assert "interval_days: 14" in rewritten
    # And the default skeleton (ease: 2.5) did NOT win.
    assert "ease: 2.5" not in rewritten


# --- end-to-end against the real fixture CSVs -----------------------------
# Uses the shipped ``scripts/data/gre/*.csv`` snapshots; cheap sanity check
# that nothing in the pipeline regresses against the data we ship with the
# repo.


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MAGOOSH = _REPO_ROOT / "scripts" / "data" / "gre" / "magoosh-1000.csv"
_MANHATTAN = _REPO_ROOT / "scripts" / "data" / "gre" / "manhattan-1000.csv"
_GREGMAT = _REPO_ROOT / "scripts" / "data" / "gre" / "gregmat.csv"


@pytest.mark.skipif(
    not _MAGOOSH.exists() or not _MANHATTAN.exists() or not _GREGMAT.exists(),
    reason="fixture CSVs not present in this checkout",
)
def test_e2e_unique_word_count_is_in_expected_range() -> None:
    """A regression guard: the union of all three lists is ~2000 words; if
    it drops far below, parsing broke for one of the sources."""
    with _MAGOOSH.open() as f:
        magoosh = list(parse_magoosh(list(csv.reader(f))))
    with _MANHATTAN.open() as f:
        manhattan = list(parse_manhattan(list(csv.reader(f))))
    with _GREGMAT.open() as f:
        gregmat = list(parse_gregmat(list(csv.reader(f))))
    merged = merge([*magoosh, *manhattan, *gregmat])
    assert 1900 <= len(merged) <= 2100, f"merged count {len(merged)} outside expected range"


@pytest.mark.skipif(
    not _GREGMAT.exists(), reason="GregMat fixture not present in this checkout"
)
def test_e2e_gregmat_groups_span_expected_range() -> None:
    """GregMat is organized into ~30 groups (group 2 through ~32 in our
    snapshot). Catch a parser change that lost the group tracking."""
    with _GREGMAT.open() as f:
        rows = list(parse_gregmat(list(csv.reader(f))))
    groups = {r.gregmat_group for r in rows if r.gregmat_group is not None}
    assert len(groups) >= 25, f"only {len(groups)} GregMat groups parsed"
    assert min(groups) >= 1 and max(groups) <= 40
