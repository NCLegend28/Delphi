"""Seed curriculum for evaluating Delphi nursery child models."""

from __future__ import annotations

from collections.abc import Iterator

from nursery.records import NurseryPromptRecord
from routing.roster import TASK_TYPES

CurriculumItem = NurseryPromptRecord


def _item(
    task_type: str,
    index: int,
    prompt: str,
    rubric: str,
    failure_modes: list[str],
) -> CurriculumItem:
    return CurriculumItem(
        id=f"{task_type}-{index}",
        task_type=task_type,
        prompt=prompt,
        rubric=rubric,
        failure_modes=failure_modes,
    )


SEED_CURRICULUM: dict[str, list[CurriculumItem]] = {
    "chat": [
        _item(
            "chat",
            1,
            "Explain quantization to Tali using one practical analogy and one caveat.",
            "Be direct, technically accurate, and concise without pretending certainty.",
            ["verbose", "incorrect_quantization_claim", "overconfident"],
        ),
        _item(
            "chat",
            2,
            "Help prioritize a small weekend build for Delphi without adding scope creep.",
            "Offer a short ranked list and call out the smallest useful first step.",
            ["scope_creep", "no_prioritization", "too_abstract"],
        ),
        _item(
            "chat",
            3,
            "Rewrite this status update so it sounds human and specific: progress was made.",
            "Avoid AI filler; produce concrete but non-fabricated wording.",
            ["ai_ism", "fabricated_detail", "generic"],
        ),
    ],
    "code": [
        _item(
            "code",
            1,
            "Debug a failing pytest where a URL builder returns duplicate /v1 segments.",
            "Identify the likely root cause and propose a small tested fix.",
            ["no_root_cause", "untested_fix", "overbroad_change"],
        ),
        _item(
            "code",
            2,
            "Implement a tiny Python function that appends one JSON object per line safely.",
            "Give minimal typed code and mention the focused pytest behavior to cover.",
            ["missing_test", "unsafe_write", "untyped_code"],
        ),
        _item(
            "code",
            3,
            "Add input validation to a Pydantic model for a 6 GB model-size ceiling.",
            "Keep the validator local, deterministic, and easy to test.",
            ["no_validation", "wrong_boundary", "unclear_error"],
        ),
    ],
    "reason": [
        _item(
            "reason",
            1,
            "Reason through whether a 4.68 GB GGUF always fits a 6 GB runtime envelope.",
            "Explain model file size versus runtime memory and KV cache clearly.",
            ["confuses_file_and_runtime_memory", "missing_kv_cache", "overconfident"],
        ),
        _item(
            "reason",
            2,
            "Compare two promotion gates: mean score >= 0.8 and hallucination rate = 0.",
            "State why each gate protects a different failure class.",
            ["blends_gates", "misses_safety_reason", "vague"],
        ),
        _item(
            "reason",
            3,
            "Decide which child model should handle code if one is faster but less accurate.",
            "Use explicit tradeoffs and recommend an escalation rule.",
            ["no_tradeoff", "no_escalation_rule", "unsupported_choice"],
        ),
    ],
    "multilingual": [
        _item(
            "multilingual",
            1,
            "Explain 'model nursery' in English, then summarize it in Spanish.",
            "Preserve technical meaning across both languages.",
            ["meaning_drift", "missing_language", "awkward_translation"],
        ),
        _item(
            "multilingual",
            2,
            "Translate a short Delphi operator note into Spanish without translating code tags.",
            "Keep model names, env vars, and command flags unchanged.",
            ["translated_code", "lost_instruction", "overlocalized"],
        ),
        _item(
            "multilingual",
            3,
            "Answer a mixed English/Spanish question about fitting a model in 6 GB.",
            "Code-switch naturally while keeping the technical answer correct.",
            ["ignores_spanish", "incorrect_memory_claim", "too_wordy"],
        ),
    ],
    "deep_code": [
        _item(
            "deep_code",
            1,
            "Design a small eval harness that compares child and parent model outputs.",
            "Break the implementation into typed modules and testable boundaries.",
            ["monolith", "no_tests", "coupled_runtime"],
        ),
        _item(
            "deep_code",
            2,
            "Debug why a mocked async HTTP client test passes but live llama-server fails.",
            "Separate test double behavior from real OpenAI-compatible API behavior.",
            ["mock_confusion", "no_live_check", "wrong_endpoint"],
        ),
        _item(
            "deep_code",
            3,
            "Propose a refactor to keep nursery code out of Delphi request latency paths.",
            "Maintain the independent child runtime boundary and avoid gateway coupling.",
            ["gateway_coupling", "latency_regression", "scope_creep"],
        ),
    ],
    "deep_reason": [
        _item(
            "deep_reason",
            1,
            "Analyze how parent critique can bias a child model evaluation loop.",
            "List risks and practical mitigations for held-out evals.",
            ["no_bias_discussion", "no_mitigation", "handwavy"],
        ),
        _item(
            "deep_reason",
            2,
            "Reason about when to fine-tune before quantization versus after quantization.",
            "Explain why quantization is deployment and fine-tuning is learning.",
            ["wrong_order", "confuses_learning_and_deployment", "missing_exception"],
        ),
        _item(
            "deep_reason",
            3,
            "Evaluate whether a child should self-grade or use a stronger parent judge.",
            "Compare incentives, cost, reliability, and escalation behavior.",
            ["one_sided", "no_reliability_analysis", "no_recommendation"],
        ),
    ],
    "vault_query": [
        _item(
            "vault_query",
            1,
            "Do I have notes on symbolic regression? Answer only if grounded in notes.",
            "Require vault grounding, cite note titles, and avoid hallucinated notes.",
            ["missing_grounding", "hallucinated_note", "no_note_title"],
        ),
        _item(
            "vault_query",
            2,
            "Find prior Delphi model-serving notes and summarize what is actually present.",
            "Say when evidence is absent; do not invent notes or paths.",
            ["hallucinated_note", "invented_path", "overconfident_absence"],
        ),
        _item(
            "vault_query",
            3,
            "Check whether the vault mentions QLoRA for Delphi and cite grounded evidence.",
            "Ground every claim in note content and separate evidence from inference.",
            ["ungrounded_claim", "hallucinated_note", "blurred_inference"],
        ),
    ],
    "gre_quiz": [
        _item(
            "gre_quiz",
            1,
            "Grade a GRE vocab answer from 0 to 5 and explain the score briefly.",
            "Use a stable rubric and do not drift into a full lesson unless needed.",
            ["inconsistent_score", "too_verbose", "no_rubric"],
        ),
        _item(
            "gre_quiz",
            2,
            "Ask one GRE vocab recall question and wait for the learner's answer.",
            "Produce exactly one question; do not reveal the answer prematurely.",
            ["reveals_answer", "multiple_questions", "no_wait"],
        ),
        _item(
            "gre_quiz",
            3,
            "Give a mnemonic for a missed GRE word without inventing its definition.",
            "Keep the definition accurate and the mnemonic memorable.",
            ["invented_definition", "bad_mnemonic", "too_long"],
        ),
    ],
    "gre_practice_test": [
        _item(
            "gre_practice_test",
            1,
            "Generate one GRE-style sentence equivalence item with answer choices.",
            "Return a clear question, choices, correct answer, and explanation.",
            ["no_correct_answer", "ambiguous_choices", "invalid_format"],
        ),
        _item(
            "gre_practice_test",
            2,
            "Grade a short GRE practice-test response using strict JSON fields.",
            "Preserve schema validity and justify the score from the answer text.",
            ["invalid_json", "unsupported_score", "missing_explanation"],
        ),
        _item(
            "gre_practice_test",
            3,
            "Create a mini reading-comprehension question from a provided passage.",
            "Base the answer only on the passage and avoid outside facts.",
            ["outside_fact", "ambiguous_answer", "bad_distractor"],
        ),
    ],
}


def iter_seed_items(task_type: str | None = None) -> Iterator[CurriculumItem]:
    """Yield seed curriculum items, optionally restricted to one task type."""
    if task_type is not None:
        yield from SEED_CURRICULUM.get(task_type, [])
        return

    for known_task_type in TASK_TYPES:
        yield from SEED_CURRICULUM[known_task_type]
