"""Tests for the read-only vault reader: search ranking + path-safe reads."""

from __future__ import annotations

import pytest

from memory.vault_reader import VaultReader


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "conversations" / "2026-05-12").mkdir(parents=True)
    (tmp_path / "conversations" / "2026-05-12" / "routing.md").write_text(
        "# Routing\nWe discussed cosine similarity routing and the classifier.\n",
        encoding="utf-8",
    )
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "cosine-similarity-routing.md").write_text(
        "Cosine similarity routing picks a model by embedding distance.\n",
        encoding="utf-8",
    )
    (tmp_path / "unrelated.md").write_text("Grocery list: milk, eggs.\n", encoding="utf-8")
    # Hidden bookkeeping dir that search must skip.
    (tmp_path / ".delphi").mkdir()
    (tmp_path / ".delphi" / "candidates.md").write_text("cosine cosine cosine\n", encoding="utf-8")
    return VaultReader(str(tmp_path), max_results=5)


def test_available_true_for_real_dir(vault):
    assert vault.available is True


def test_available_false_for_missing_path():
    assert VaultReader("/nonexistent/path/xyz").available is False
    assert VaultReader("").available is False


def test_search_ranks_filename_match_highest(vault):
    hits = vault.search("cosine similarity routing")
    assert hits, "expected matches"
    # The entity note is *named* for the query → filename boost wins.
    assert hits[0].path == "entities/cosine-similarity-routing.md"
    assert all(h.score > 0 for h in hits)


def test_search_drops_zero_matches(vault):
    hits = vault.search("cosine")
    paths = {h.path for h in hits}
    assert "unrelated.md" not in paths


def test_search_skips_hidden_dirs(vault):
    hits = vault.search("cosine")
    assert not any(h.path.startswith(".delphi") for h in hits)


def test_search_empty_query_returns_nothing(vault):
    assert vault.search("   ") == []


def test_search_returns_snippet(vault):
    hits = vault.search("classifier")
    assert hits
    assert "classifier" in hits[0].snippet.lower()


def test_read_returns_content(vault):
    text = vault.read("entities/cosine-similarity-routing.md")
    assert "embedding distance" in text


def test_read_rejects_traversal(vault):
    with pytest.raises(FileNotFoundError):
        vault.read("../../etc/passwd")


def test_read_rejects_absolute_escape(vault):
    # Leading slash is stripped → treated as vault-relative, so an absolute
    # system path can't be read.
    with pytest.raises(FileNotFoundError):
        vault.read("/etc/passwd")


def test_read_missing_note_raises(vault):
    with pytest.raises(FileNotFoundError):
        vault.read("conversations/nope.md")


def test_read_truncates_large_note(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 50_000, encoding="utf-8")
    reader = VaultReader(str(tmp_path), max_note_chars=1_000)
    out = reader.read("big.md")
    assert out.endswith("…[truncated]")
    assert len(out) < 1_100


# --- path-tier boosts (knowledge/ over conversations/) --------------------


@pytest.fixture
def tiered_vault(tmp_path):
    """A vault where the same term appears in both a knowledge card and an
    older conversation note. Used to verify ``knowledge/`` wins.

    The conversation note mentions ``perspicacious`` many times (high raw
    keyword score) but should still rank below the knowledge card thanks to
    the ``knowledge/`` path boost.
    """
    (tmp_path / "knowledge" / "gre" / "vocab").mkdir(parents=True)
    (tmp_path / "knowledge" / "gre" / "vocab" / "perspicacious.md").write_text(
        "# perspicacious\nHaving keen insight; mentally sharp.\n",
        encoding="utf-8",
    )
    (tmp_path / "conversations" / "2026-06-01").mkdir(parents=True)
    (tmp_path / "conversations" / "2026-06-01" / "old-turn.md").write_text(
        # Stuff the conversation note with the term so raw score is high.
        "perspicacious perspicacious perspicacious perspicacious perspicacious\n",
        encoding="utf-8",
    )
    return VaultReader(str(tmp_path), max_results=5)


def test_knowledge_outranks_conversation_on_same_term(tiered_vault):
    """Even when a conversation note mentions the term more times, the
    knowledge card wins — that's the whole point of the tier sort."""
    hits = tiered_vault.search("perspicacious")
    assert hits, "expected matches"
    assert hits[0].path == "knowledge/gre/vocab/perspicacious.md", (
        f"knowledge/ note should win; got {[h.path for h in hits]}"
    )


def test_knowledge_wins_even_with_pathological_conversation_density(tmp_path):
    """Strict-tier sort: a fifty-mention conversation note still loses to
    a single-mention knowledge note. The whole point is provenance, not
    keyword count."""
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "perspicacious.md").write_text(
        "perspicacious — keen.\n", encoding="utf-8"
    )
    (tmp_path / "conversations").mkdir()
    (tmp_path / "conversations" / "stuffed.md").write_text(
        "perspicacious " * 50, encoding="utf-8"
    )
    hits = VaultReader(str(tmp_path)).search("perspicacious")
    assert hits[0].path == "knowledge/perspicacious.md"


def test_conversation_note_still_searchable(tiered_vault):
    """Demotion is via score boost, not exclusion — conversation notes still
    appear in results so 'what did we decide about X' keeps working."""
    hits = tiered_vault.search("perspicacious")
    paths = {h.path for h in hits}
    assert "conversations/2026-06-01/old-turn.md" in paths


def test_zero_overlap_note_not_promoted_by_boost(tmp_path):
    """A knowledge note that doesn't actually mention the query term must
    not bubble up just because its path is privileged."""
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "unrelated.md").write_text(
        "completely different topic\n", encoding="utf-8"
    )
    (tmp_path / "conversations").mkdir()
    (tmp_path / "conversations" / "x.md").write_text(
        "perspicacious means keen insight\n", encoding="utf-8"
    )
    reader = VaultReader(str(tmp_path))
    hits = reader.search("perspicacious")
    paths = [h.path for h in hits]
    assert "knowledge/unrelated.md" not in paths
    assert paths == ["conversations/x.md"]
