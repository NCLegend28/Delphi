"""Tests for the active-quiz state file — round-trip + atomicity."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.quiz_state import (
    QuizCard,
    QuizSession,
    QuizStateError,
    QuizStateStore,
    append_log,
)


def _fresh_session(**overrides) -> QuizSession:
    defaults = {
        "session_id": "01HXPQ9TESTULID",
        "client_id": "delphi-ui",
        "started_at": datetime(2026, 6, 2, 14, 23, tzinfo=timezone.utc),
        "domain": "gre",
        "filters": {"difficulty": "hard", "tags_any": ["canonical"], "only_due": True},
        "deck": [
            QuizCard(path="knowledge/gre/vocab/abjure.md", word="abjure"),
            QuizCard(path="knowledge/gre/vocab/extol.md", word="extol"),
            QuizCard(path="knowledge/gre/vocab/obviate.md", word="obviate"),
        ],
        "current_index": 0,
        "n_target": 3,
    }
    defaults.update(overrides)
    return QuizSession(**defaults)


def test_load_returns_none_when_no_state_file(tmp_path):
    store = QuizStateStore(tmp_path)
    assert store.load() is None
    assert store.exists() is False


def test_save_then_load_round_trips(tmp_path):
    store = QuizStateStore(tmp_path)
    session = _fresh_session()
    store.save(session)

    loaded = store.load()
    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.client_id == "delphi-ui"
    assert loaded.domain == "gre"
    assert loaded.filters["difficulty"] == "hard"
    assert loaded.filters["tags_any"] == ["canonical"]
    assert len(loaded.deck) == 3
    assert loaded.deck[0].word == "abjure"
    assert loaded.current_index == 0
    assert loaded.n_target == 3


def test_save_creates_state_dir(tmp_path):
    store = QuizStateStore(tmp_path)
    assert not (tmp_path / "state").exists()
    store.save(_fresh_session())
    assert (tmp_path / "state" / "active-quiz.md").is_file()


def test_save_overwrites_existing_state(tmp_path):
    store = QuizStateStore(tmp_path)
    store.save(_fresh_session())
    updated = _fresh_session(current_index=2)
    updated.deck[0].asked = True
    updated.deck[0].grade = 4
    updated.deck[0].user_answer = "to renounce"
    store.save(updated)

    loaded = store.load()
    assert loaded is not None
    assert loaded.current_index == 2
    assert loaded.deck[0].asked is True
    assert loaded.deck[0].grade == 4
    assert loaded.deck[0].user_answer == "to renounce"


def test_clear_removes_file(tmp_path):
    store = QuizStateStore(tmp_path)
    store.save(_fresh_session())
    assert store.exists()
    store.clear()
    assert not store.exists()
    assert store.load() is None


def test_clear_is_idempotent(tmp_path):
    store = QuizStateStore(tmp_path)
    store.clear()  # no file
    store.clear()  # still no file
    assert store.load() is None


def test_transcript_round_trips(tmp_path):
    store = QuizStateStore(tmp_path)
    session = _fresh_session()
    append_log(session, "**abjure** — user: \"to renounce\" — grade 4 (Good). ✓")
    append_log(session, "**extol** — user: \"to praise\" — grade 5 (Easy). ✓")
    store.save(session)

    loaded = store.load()
    assert loaded is not None
    assert len(loaded.transcript) == 2
    assert "abjure" in loaded.transcript[0]
    assert "extol" in loaded.transcript[1]


def test_append_log_normalizes_bullet_prefix():
    session = _fresh_session()
    append_log(session, "no leading dash")
    append_log(session, "- already has dash")
    assert session.transcript[0].startswith("- ")
    assert session.transcript[1].startswith("- ")


def test_is_complete_when_index_past_deck(tmp_path):
    session = _fresh_session(current_index=3, n_target=3)
    assert session.is_complete is True


def test_is_complete_when_n_target_hit():
    session = _fresh_session(n_target=2, current_index=2)
    assert session.is_complete is True


def test_is_complete_false_mid_session():
    session = _fresh_session(current_index=1, n_target=3)
    assert session.is_complete is False


def test_graded_count_reflects_deck():
    session = _fresh_session()
    session.deck[0].grade = 4
    session.deck[1].grade = 3
    assert session.graded_count == 2


def test_load_raises_on_bad_frontmatter(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "active-quiz.md").write_text(
        "---\nnot: valid: yaml: [\n---\nbody\n", encoding="utf-8"
    )
    store = QuizStateStore(tmp_path)
    with pytest.raises(QuizStateError):
        store.load()


def test_load_raises_on_missing_started_at(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "active-quiz.md").write_text(
        "---\nsession_id: x\ndeck: []\n---\n", encoding="utf-8"
    )
    store = QuizStateStore(tmp_path)
    with pytest.raises(QuizStateError):
        store.load()


def test_save_is_atomic_no_tempfile_leftover(tmp_path):
    store = QuizStateStore(tmp_path)
    store.save(_fresh_session())
    state_dir = tmp_path / "state"
    leftover = [p for p in state_dir.iterdir() if p.name != "active-quiz.md"]
    assert leftover == []
