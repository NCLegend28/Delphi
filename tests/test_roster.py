"""Pure unit tests for ``routing/roster.py`` and ``routing/soul.py``.

No network. These guard the invariants that the rest of the system depends on:
every task type maps to a model, the soul is non-empty, and the coding
appendix is appended (never replacing) the base soul.
"""

from __future__ import annotations

import pytest

from config import Config
from routing import roster
from routing.soul import (
    BASE_SOUL,
    CODING_APPENDIX,
    CODING_TASK_TYPES,
    GRE_QUIZ_APPENDIX,
    GRE_QUIZ_TASK_TYPES,
    UI_CLIENT_IDS,
    UI_PROTOCOL_APPENDIX,
    VAULT_QUERY_APPENDIX,
    VAULT_QUERY_TASK_TYPES,
    soul_for,
)

# --- roster ---------------------------------------------------------------


def test_every_task_type_has_a_roster_entry() -> None:
    for task_type in roster.TASK_TYPES:
        entry = roster.resolve(task_type)
        assert entry.model, f"{task_type} has no model"


def test_resolve_unknown_task_type_raises_typed_error() -> None:
    with pytest.raises(roster.UnknownTaskType):
        roster.resolve("not-a-real-task")


def test_default_task_type_is_resolvable() -> None:
    roster.resolve(roster.DEFAULT_TASK_TYPE)


def test_all_models_includes_every_distinct_roster_model() -> None:
    expected = {entry.model for entry in roster.ROSTER.values()}
    assert set(roster.all_models()) == expected


def test_classifier_model_default_is_a_nonempty_tag() -> None:
    assert ":" in roster.CLASSIFIER_MODEL_DEFAULT


# --- env-driven roster ---------------------------------------------------


def test_from_config_uses_env_driven_model_tags() -> None:
    cfg = Config(  # type: ignore[call-arg]
        delphi_bearer_token="t",
        delphi_model_chat="chat-x:1",
        delphi_model_code="code-x:1",
        delphi_model_reason="reason-x:1",
        delphi_model_multilingual="ml-x:1",
        delphi_model_deep_code="dcode-x:1",
        delphi_model_deep_reason="dreason-x:1",
        delphi_model_vault_query="vault-x:1",
        delphi_model_gre_quiz="quiz-x:1",
    )
    r = roster.Roster.from_config(cfg)
    assert r.lookup("chat").model == "chat-x:1"
    assert r.lookup("code").model == "code-x:1"
    assert r.lookup("vault_query").model == "vault-x:1"
    assert r.lookup("gre_quiz").model == "quiz-x:1"


def test_from_config_preserves_per_task_options_and_notes() -> None:
    cfg = Config(delphi_bearer_token="t")  # type: ignore[call-arg]
    r = roster.Roster.from_config(cfg)
    for task_type, (opts, notes) in roster.TASK_METADATA.items():
        entry = r.lookup(task_type)
        assert entry is not None
        assert entry.options == opts
        assert entry.notes == notes


def test_from_config_covers_every_task_type() -> None:
    cfg = Config(delphi_bearer_token="t")  # type: ignore[call-arg]
    r = roster.Roster.from_config(cfg)
    assert set(r.task_types()) == set(roster.TASK_TYPES)


# --- soul -----------------------------------------------------------------


def test_base_soul_is_nonempty() -> None:
    assert BASE_SOUL.strip()


def test_coding_appendix_is_nonempty() -> None:
    assert CODING_APPENDIX.strip()


def test_soul_for_chat_returns_base_only() -> None:
    assert soul_for("chat") == BASE_SOUL


def test_soul_for_code_appends_coding_block() -> None:
    out = soul_for("code")
    assert out.startswith(BASE_SOUL), "coding tasks must keep the base soul intact"
    assert out.endswith(CODING_APPENDIX), "coding appendix must be appended last"


def test_soul_for_deep_code_appends_coding_block() -> None:
    assert soul_for("deep_code").endswith(CODING_APPENDIX)


def test_soul_for_unknown_task_type_falls_back_to_base() -> None:
    assert soul_for("never-heard-of-it") == BASE_SOUL


def test_coding_task_types_are_a_subset_of_known_task_types() -> None:
    assert CODING_TASK_TYPES.issubset(set(roster.TASK_TYPES))


# --- UI protocol appendix -------------------------------------------------


def test_ui_protocol_appendix_is_nonempty() -> None:
    assert UI_PROTOCOL_APPENDIX.strip()


def test_ui_protocol_appendix_documents_media_preview_directive() -> None:
    """The media preview directive must be advertised so the model emits it."""
    assert "[PREVIEW:media]" in UI_PROTOCOL_APPENDIX
    # And it must flow through to the rendered prompt:
    out = soul_for("chat", client_id="delphi-ui")
    assert "[PREVIEW:media]" in out


def test_ui_client_ids_includes_delphi_ui() -> None:
    assert "delphi-ui" in UI_CLIENT_IDS


def test_soul_for_unknown_client_id_omits_ui_appendix() -> None:
    out = soul_for("chat", client_id="some-other-client")
    assert UI_PROTOCOL_APPENDIX not in out


def test_soul_for_no_client_id_omits_ui_appendix() -> None:
    assert UI_PROTOCOL_APPENDIX not in soul_for("chat")


def test_soul_for_delphi_ui_appends_ui_block() -> None:
    out = soul_for("chat", client_id="delphi-ui")
    assert out.startswith(BASE_SOUL), "UI requests must keep the base soul intact"
    assert out.endswith(UI_PROTOCOL_APPENDIX), "UI appendix is appended last"


def test_soul_for_delphi_ui_code_keeps_both_appendices_in_order() -> None:
    out = soul_for("code", client_id="delphi-ui")
    assert out.startswith(BASE_SOUL)
    # Coding block must precede the UI block, and the UI block must be last.
    coding_idx = out.index(CODING_APPENDIX)
    ui_idx = out.index(UI_PROTOCOL_APPENDIX)
    assert coding_idx < ui_idx, "coding appendix must come before UI appendix"
    assert out.endswith(UI_PROTOCOL_APPENDIX)


# --- vault-query appendix -------------------------------------------------


def test_vault_query_appendix_is_nonempty() -> None:
    assert VAULT_QUERY_APPENDIX.strip()


def test_vault_query_task_types_are_a_subset_of_known_task_types() -> None:
    assert VAULT_QUERY_TASK_TYPES.issubset(set(roster.TASK_TYPES))


def test_vault_query_appendix_compels_search_first() -> None:
    """The MUST-search rule is what forces gpt-oss out of confidence mode."""
    assert "MUST call ``search_vault``" in VAULT_QUERY_APPENDIX


def test_vault_query_appendix_requires_source_citation() -> None:
    assert "Source:" in VAULT_QUERY_APPENDIX


def test_soul_for_vault_query_appends_vault_block() -> None:
    out = soul_for("vault_query")
    assert out.startswith(BASE_SOUL), "vault_query must keep the base soul intact"
    assert out.endswith(VAULT_QUERY_APPENDIX), "vault-query appendix is appended"


def test_soul_for_non_vault_query_omits_vault_appendix() -> None:
    for task_type in ("chat", "code", "reason", "multilingual"):
        assert VAULT_QUERY_APPENDIX not in soul_for(task_type), task_type


def test_soul_for_vault_query_with_ui_keeps_both_appendices_in_order() -> None:
    out = soul_for("vault_query", client_id="delphi-ui")
    assert out.startswith(BASE_SOUL)
    # Vault block must precede the UI block; UI block must be last.
    vq_idx = out.index(VAULT_QUERY_APPENDIX)
    ui_idx = out.index(UI_PROTOCOL_APPENDIX)
    assert vq_idx < ui_idx, "vault-query appendix must come before UI appendix"
    assert out.endswith(UI_PROTOCOL_APPENDIX)


def test_vault_query_appendix_forbids_citing_conversations() -> None:
    """The agent must not cite its own past replies as if they were knowledge."""
    assert "may NOT cite a ``conversations/`` path" in VAULT_QUERY_APPENDIX


def test_vault_query_appendix_marks_knowledge_as_canonical() -> None:
    assert "canonical source" in VAULT_QUERY_APPENDIX
    assert "knowledge/" in VAULT_QUERY_APPENDIX


def test_ui_appendix_requires_preview_for_structured_output() -> None:
    """Long/structured responses must land in the preview pane, not chat."""
    assert "required (not optional)" in UI_PROTOCOL_APPENDIX
    assert "120 words" in UI_PROTOCOL_APPENDIX
    # The chat-visible portion must be a *short framing*, not the whole doc.
    assert "short framing" in UI_PROTOCOL_APPENDIX


# --- gre_quiz appendix ---------------------------------------------------


def test_gre_quiz_appendix_is_nonempty() -> None:
    assert GRE_QUIZ_APPENDIX.strip()


def test_gre_quiz_task_type_in_roster() -> None:
    """gre_quiz must be a known task type, not a soul-only string."""
    assert "gre_quiz" in roster.TASK_TYPES
    assert GRE_QUIZ_TASK_TYPES.issubset(set(roster.TASK_TYPES))


def test_gre_quiz_appendix_documents_grading_rubric() -> None:
    # The 0-5 scale must surface to the model.
    for grade in ("0", "1", "2", "3", "4", "5"):
        assert f"``{grade}``" in GRE_QUIZ_APPENDIX, f"grade {grade} missing from rubric"


def test_gre_quiz_appendix_lists_required_tools() -> None:
    for tool in (
        "list_due_cards",
        "record_review",
        "end_quiz_session",
        "search_vault",
        "read_note",
    ):
        assert tool in GRE_QUIZ_APPENDIX, f"{tool} missing from appendix"


def test_gre_quiz_appendix_warns_against_inflation() -> None:
    """SM-2 only works if the model grades honestly. The soul must say so."""
    assert "calibrated" in GRE_QUIZ_APPENDIX.lower()


def test_soul_for_gre_quiz_appends_quiz_block() -> None:
    out = soul_for("gre_quiz")
    assert out.startswith(BASE_SOUL)
    assert out.endswith(GRE_QUIZ_APPENDIX)


def test_soul_for_non_quiz_omits_quiz_appendix() -> None:
    for task_type in ("chat", "code", "vault_query", "reason"):
        assert GRE_QUIZ_APPENDIX not in soul_for(task_type), task_type


def test_soul_for_gre_quiz_with_ui_orders_appendices() -> None:
    out = soul_for("gre_quiz", client_id="delphi-ui")
    assert out.startswith(BASE_SOUL)
    quiz_idx = out.index(GRE_QUIZ_APPENDIX)
    ui_idx = out.index(UI_PROTOCOL_APPENDIX)
    assert quiz_idx < ui_idx, "quiz appendix must come before UI appendix"
    assert out.endswith(UI_PROTOCOL_APPENDIX)


def test_gre_quiz_appendix_disjoint_from_vault_query() -> None:
    """vault_query and gre_quiz are distinct protocols; appendices shouldn't overlap."""
    assert GRE_QUIZ_TASK_TYPES.isdisjoint(VAULT_QUERY_TASK_TYPES)
