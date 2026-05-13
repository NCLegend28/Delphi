"""Tests for ``memory/entities.py``.

Each test gets its own ``tmp_path``-backed vault so the candidate JSON file
and any promoted entity stubs are fully isolated.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from memory.entities import EntityIndex, _slugify


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "entities").mkdir()
    (tmp_path / "projects").mkdir()
    return tmp_path


def _touch(directory: Path, name: str) -> Path:
    path = directory / f"{name}.md"
    path.write_text(f"# {name}\n")
    return path


# --- helpers --------------------------------------------------------------


def test_slugify_normalizes() -> None:
    assert _slugify("Pydantic v2") == "pydantic-v2"
    assert _slugify("  AgentRig  ") == "agentrig"
    assert _slugify("cosine-similarity-routing") == "cosine-similarity-routing"
    assert _slugify("!!!") == ""


# --- known entities + projects -------------------------------------------


async def test_known_entities_reads_directory(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    _touch(vault / "entities", "cosine-similarity-routing")
    idx = EntityIndex(vault)
    known = await idx.known_entities()
    assert known == {
        "pydantic": "Pydantic",
        "cosine-similarity-routing": "cosine-similarity-routing",
    }


async def test_known_projects_is_separate_from_entities(vault: Path) -> None:
    _touch(vault / "projects", "AgentRig")
    _touch(vault / "entities", "Pydantic")
    idx = EntityIndex(vault)
    assert await idx.known_projects() == {"agentrig": "AgentRig"}
    assert await idx.known_entities() == {"pydantic": "Pydantic"}


# --- project resolution --------------------------------------------------


async def test_project_resolution_matches_filename(vault: Path) -> None:
    _touch(vault / "projects", "AgentRig")
    idx = EntityIndex(vault)
    assert await idx.resolve_project("AgentRig") == "[[AgentRig]]"
    # Case-insensitive: still resolves.
    assert await idx.resolve_project("agentrig") == "[[AgentRig]]"


async def test_project_resolution_unknown_returns_none(vault: Path) -> None:
    _touch(vault / "projects", "AgentRig")
    idx = EntityIndex(vault)
    assert await idx.resolve_project("Nope") is None
    assert await idx.resolve_project(None) is None
    assert await idx.resolve_project("") is None


# --- candidate extraction ------------------------------------------------


def test_extract_candidates_finds_multi_word_capitalized(vault: Path) -> None:
    idx = EntityIndex(vault)
    text = "We're using Federated Learning for the experiment."
    slugs = {slug for slug, _ in idx.extract_candidates(text)}
    assert "federated-learning" in slugs


def test_extract_candidates_finds_pascal_case(vault: Path) -> None:
    idx = EntityIndex(vault)
    text = "Built on FastAPI and AgentRig with OpenAI underneath."
    slugs = {slug for slug, _ in idx.extract_candidates(text)}
    assert {"fastapi", "agentrig", "openai"} <= slugs


def test_extract_candidates_finds_backtick_identifiers(vault: Path) -> None:
    idx = EntityIndex(vault)
    text = "Use `cosine-similarity-routing` in the resolver."
    slugs = {slug for slug, _ in idx.extract_candidates(text)}
    assert "cosine-similarity-routing" in slugs


def test_extract_candidates_skips_stopwords(vault: Path) -> None:
    idx = EntityIndex(vault)
    text = "The quick approach. This works. That fails."
    slugs = {slug for slug, _ in idx.extract_candidates(text)}
    assert slugs.isdisjoint({"the", "this", "that"})


# --- wikilink rewriting --------------------------------------------------


async def test_annotate_replaces_known_entities(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    idx = EntityIndex(vault)
    text, seen = await idx.annotate("I love Pydantic, it's clean.")
    assert text == "I love [[Pydantic]], it's clean."
    assert seen == ["Pydantic"]


async def test_annotate_skips_already_wrapped_links(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    idx = EntityIndex(vault)
    text, seen = await idx.annotate("[[Pydantic]] is the source of truth.")
    assert text == "[[Pydantic]] is the source of truth."
    assert seen == []  # Existing wikilinks aren't re-collected.


async def test_annotate_uses_canonical_casing(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    idx = EntityIndex(vault)
    text, _ = await idx.annotate("we use pydantic, PYDANTIC, and Pydantic.")
    assert text.count("[[Pydantic]]") == 3
    assert "[[pydantic]]" not in text


async def test_annotate_prefers_longer_match(vault: Path) -> None:
    """Both ``Pydantic`` and ``Pydantic v2`` are entities — the longer wins."""
    _touch(vault / "entities", "Pydantic")
    _touch(vault / "entities", "Pydantic v2")
    idx = EntityIndex(vault)
    text, _ = await idx.annotate("Pydantic v2 changed a lot.")
    assert text == "[[Pydantic v2]] changed a lot."


# --- candidate tracking + promotion --------------------------------------


async def test_record_mentions_below_threshold_does_not_promote(vault: Path) -> None:
    idx = EntityIndex(vault, threshold=2)
    promoted = await idx.record_mentions([("federated-learning", "Federated Learning")])
    assert promoted == []
    assert not list((vault / "entities").iterdir())
    store = json.loads((vault / ".delphi" / "entity_candidates.json").read_text())
    assert store["federated-learning"]["count"] == 1


async def test_record_mentions_promotes_at_threshold(vault: Path) -> None:
    idx = EntityIndex(vault, threshold=2)
    await idx.record_mentions(
        [("federated-learning", "Federated Learning")], when=date(2026, 5, 4)
    )
    promoted = await idx.record_mentions(
        [("federated-learning", "Federated Learning")], when=date(2026, 5, 11)
    )
    assert promoted == ["Federated Learning"]
    stub = vault / "entities" / "Federated Learning.md"
    assert stub.exists()
    text = stub.read_text()
    assert "type: entity" in text
    assert "status: stub" in text
    assert "first_mentioned: 2026-05-04" in text  # Preserves earliest mention.
    # Candidate file no longer carries the promoted slug.
    store = json.loads((vault / ".delphi" / "entity_candidates.json").read_text())
    assert "federated-learning" not in store


async def test_record_mentions_skips_already_known_entities(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    idx = EntityIndex(vault, threshold=2)
    promoted = await idx.record_mentions([("pydantic", "Pydantic")])
    assert promoted == []
    # No candidate row created for an entity that already exists.
    cand = vault / ".delphi" / "entity_candidates.json"
    if cand.exists():
        assert "pydantic" not in json.loads(cand.read_text())


# --- end-to-end process() ------------------------------------------------


async def test_process_full_pipeline(vault: Path) -> None:
    _touch(vault / "entities", "Pydantic")
    _touch(vault / "projects", "AgentRig")
    idx = EntityIndex(vault, threshold=2)

    # First conversation: mentions Pydantic (known) and "FastAPI" (new candidate).
    result1 = await idx.process(
        user_text="how should I structure the AgentRig handler?",
        assistant_text="Use Pydantic v2 models inside FastAPI handlers.",
        project_hint="AgentRig",
    )
    assert "[[Pydantic]]" in result1.annotated_assistant
    assert "[[AgentRig]]" in result1.annotated_user
    assert result1.project == "[[AgentRig]]"
    assert result1.promoted == []  # FastAPI only seen once so far.

    # Second conversation: FastAPI mentioned again → promoted.
    result2 = await idx.process(
        user_text="show me a FastAPI example.",
        assistant_text="FastAPI's dependency injection is the win.",
        project_hint=None,
    )
    assert result2.promoted == ["FastAPI"]
    # The newly-promoted entity is wikilinked in its own promotion turn.
    assert "[[FastAPI]]" in result2.annotated_assistant


async def test_process_concurrent_calls_do_not_double_promote(vault: Path) -> None:
    """The asyncio.Lock around record_mentions prevents racy double-creations."""
    idx = EntityIndex(vault, threshold=2)
    cands = [("federated-learning", "Federated Learning")]
    # Fire two concurrent record_mentions — the second crosses the threshold.
    await idx.record_mentions(cands)
    promoted_lists = await asyncio.gather(
        idx.record_mentions(cands), idx.record_mentions(cands)
    )
    flat = [name for names in promoted_lists for name in names]
    # Exactly one promotion regardless of interleaving.
    assert flat.count("Federated Learning") == 1
    # Stub exists exactly once.
    stubs = list((vault / "entities").glob("Federated Learning.md"))
    assert len(stubs) == 1
