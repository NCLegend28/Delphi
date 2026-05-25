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
