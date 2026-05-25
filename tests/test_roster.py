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
    UI_CLIENT_IDS,
    UI_PROTOCOL_APPENDIX,
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
    )
    r = roster.Roster.from_config(cfg)
    assert r.lookup("chat").model == "chat-x:1"
    assert r.lookup("code").model == "code-x:1"
    assert r.lookup("vault_query").model == "vault-x:1"


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
