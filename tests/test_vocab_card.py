"""Tests for the vocab card splicer — schema parsing + surgical rewrite."""

from __future__ import annotations

from datetime import datetime, timezone
from textwrap import dedent

import pytest

from memory.srs import ReviewState
from memory.vocab_card import VocabCardError, read, write_review

_CANONICAL_CARD = dedent(
    """\
    ---
    type: gre-vocab
    word: perspicacious
    pos: adjective
    difficulty: hard
    synonyms: [astute, shrewd, discerning]
    antonyms: [obtuse, dull]
    tags: [gre, vocab, intelligence]
    mnemonic: "PERSPECtacles let you see clearly"
    added: 2026-05-31
    sources: ["Magoosh", "Manhattan 500"]
    review:
      last_reviewed: null
      ease: 2.5
      interval_days: 0
    ---

    # perspicacious

    > Having keen insight; mentally sharp.

    ## Examples
    - *Her perspicacious analysis caught the flaw nobody else saw.*

    ## Confusion set
    - Not [[perspicuous]] (= "clearly expressed").
    """
)


# --- read() ---


def test_read_parses_canonical_card(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    card = read(p)
    assert card.word == "perspicacious"
    assert card.difficulty == "hard"
    assert "intelligence" in card.tags
    assert card.review.ease == 2.5
    assert card.review.interval_days == 0
    assert card.review.last_reviewed is None


def test_read_falls_back_to_filename_when_word_missing(tmp_path):
    p = tmp_path / "abjure.md"
    p.write_text("---\ntype: gre-vocab\ndifficulty: hard\n---\nbody\n", encoding="utf-8")
    card = read(p)
    assert card.word == "abjure"


def test_read_handles_string_last_reviewed(tmp_path):
    text = dedent(
        """\
        ---
        word: abjure
        review:
          last_reviewed: "2026-06-02T14:32:18+00:00"
          ease: 2.4
          interval_days: 6
        ---
        body
        """
    )
    p = tmp_path / "abjure.md"
    p.write_text(text, encoding="utf-8")
    card = read(p)
    assert card.review.last_reviewed == datetime(2026, 6, 2, 14, 32, 18, tzinfo=timezone.utc)
    assert card.review.ease == 2.4
    assert card.review.interval_days == 6


def test_read_defaults_when_review_missing(tmp_path):
    p = tmp_path / "abjure.md"
    p.write_text("---\nword: abjure\n---\nbody\n", encoding="utf-8")
    card = read(p)
    assert card.review.ease == 2.5
    assert card.review.interval_days == 0
    assert card.review.last_reviewed is None


def test_read_raises_on_bad_yaml(tmp_path):
    p = tmp_path / "broken.md"
    p.write_text("---\nthis: is: not: valid: yaml: [\n---\n", encoding="utf-8")
    with pytest.raises(VocabCardError):
        read(p)


def test_read_raises_on_missing_file(tmp_path):
    with pytest.raises(VocabCardError):
        read(tmp_path / "does-not-exist.md")


# --- write_review() ---


def test_write_review_preserves_body_byte_for_byte(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    new_state = ReviewState(
        ease=2.36,
        interval_days=6,
        last_reviewed=datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc),
    )
    write_review(p, new_state)
    updated = p.read_text(encoding="utf-8")
    # Everything after the closing fence must be unchanged.
    original_body = _CANONICAL_CARD.split("---\n", 2)[2]
    new_body = updated.split("---\n", 2)[2]
    assert original_body == new_body


def test_write_review_updates_the_block(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    new_state = ReviewState(
        ease=2.36,
        interval_days=6,
        last_reviewed=datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc),
    )
    write_review(p, new_state)
    card = read(p)
    assert card.review.ease == 2.36
    assert card.review.interval_days == 6
    assert card.review.last_reviewed == datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)


def test_write_review_preserves_unrelated_frontmatter(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    new_state = ReviewState(ease=2.36, interval_days=6, last_reviewed=None)
    write_review(p, new_state)
    text = p.read_text(encoding="utf-8")
    # Hand-curated fields must survive.
    assert "mnemonic: \"PERSPECtacles let you see clearly\"" in text
    assert "synonyms: [astute, shrewd, discerning]" in text
    assert "added: 2026-05-31" in text


def test_write_review_inserts_block_when_absent(tmp_path):
    text = dedent(
        """\
        ---
        word: abjure
        difficulty: hard
        ---

        body line one
        body line two
        """
    )
    p = tmp_path / "abjure.md"
    p.write_text(text, encoding="utf-8")
    new_state = ReviewState(ease=2.5, interval_days=1, last_reviewed=None)
    write_review(p, new_state)
    card = read(p)
    assert card.review.interval_days == 1
    # Body untouched.
    assert "body line one\nbody line two\n" in p.read_text(encoding="utf-8")


def test_write_review_handles_null_last_reviewed(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    write_review(p, ReviewState(ease=2.5, interval_days=0, last_reviewed=None))
    text = p.read_text(encoding="utf-8")
    assert "last_reviewed: null" in text


def test_write_review_is_idempotent(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    state = ReviewState(
        ease=2.36,
        interval_days=6,
        last_reviewed=datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc),
    )
    write_review(p, state)
    first = p.read_text(encoding="utf-8")
    write_review(p, state)
    second = p.read_text(encoding="utf-8")
    assert first == second


def test_write_review_atomic_no_tempfile_left_behind(tmp_path):
    p = tmp_path / "perspicacious.md"
    p.write_text(_CANONICAL_CARD, encoding="utf-8")
    write_review(p, ReviewState(ease=2.4, interval_days=3, last_reviewed=None))
    leftovers = [f for f in tmp_path.iterdir() if f.name != "perspicacious.md"]
    assert leftovers == []


def test_write_review_raises_on_missing_file(tmp_path):
    with pytest.raises(VocabCardError):
        write_review(tmp_path / "does-not-exist.md", ReviewState())
