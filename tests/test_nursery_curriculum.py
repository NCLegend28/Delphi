"""Tests for the static Delphi nursery seed curriculum."""

from __future__ import annotations

from nursery.curriculum import SEED_CURRICULUM, CurriculumItem, iter_seed_items
from routing.roster import TASK_TYPES


def test_every_roster_task_type_has_three_seed_prompts() -> None:
    assert set(SEED_CURRICULUM) == set(TASK_TYPES)
    for task_type in TASK_TYPES:
        assert len(SEED_CURRICULUM[task_type]) >= 3


def test_every_prompt_has_failure_modes() -> None:
    for item in iter_seed_items():
        assert isinstance(item, CurriculumItem)
        assert item.failure_modes
        assert item.prompt.strip()
        assert item.rubric.strip()


def test_vault_query_prompts_require_grounding_and_no_hallucinated_notes() -> None:
    combined = "\n".join(
        f"{item.prompt}\n{item.rubric}\n{' '.join(item.failure_modes)}"
        for item in SEED_CURRICULUM["vault_query"]
    ).lower()

    assert "ground" in combined
    assert "hallucinated" in combined
    assert "note" in combined


def test_code_prompts_include_debugging_and_implementation_requests() -> None:
    combined = "\n".join(item.prompt for item in SEED_CURRICULUM["code"]).lower()

    assert "debug" in combined or "failing" in combined
    assert "implement" in combined or "add" in combined


def test_seed_item_ids_are_unique_and_prefixed_by_task_type() -> None:
    seen: set[str] = set()
    for item in iter_seed_items():
        assert item.id.startswith(f"{item.task_type}-")
        assert item.id not in seen
        seen.add(item.id)
