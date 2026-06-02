"""Unit tests for the classifier.

The real-Ollama 80%-accuracy bar from CLAUDE.md lives in a separate file we'll
add when Ollama is wired into CI. These tests pin the parsing contract: what
happens when the tiny model gives us valid JSON, bad JSON, prose, or errors.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from proxy.ollama_client import OllamaClient
from routing.classifier import Classifier, ClassifyResult, _system_prompt
from routing.roster import DEFAULT_TASK_TYPE

BASE = "http://ollama.test:11434"
CLASSIFIER_MODEL = "phi3.5:3.8b"


def _ollama_reply(content: str) -> httpx.Response:
    """Build the JSON envelope Ollama returns from /v1/chat/completions."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


@pytest.fixture
async def classifier() -> Classifier:
    ollama = OllamaClient(BASE)
    return Classifier(ollama, CLASSIFIER_MODEL)


@respx.mock
async def test_clean_json_is_parsed(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply(
            '{"task_type": "code", "confidence": 0.92, "project": "AgentRig"}'
        )
    )
    result = await classifier.classify("refactor this Python function")
    assert result == ClassifyResult(task_type="code", confidence=0.92, project="AgentRig")
    await classifier._ollama.aclose()


@respx.mock
async def test_json_embedded_in_prose_is_extracted(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply(
            'Sure! Here is my answer: {"task_type":"reason","confidence":0.8,"project":null}'
        )
    )
    result = await classifier.classify("prove the pigeonhole principle")
    assert result.task_type == "reason"
    assert result.project is None
    await classifier._ollama.aclose()


@respx.mock
async def test_unknown_task_type_falls_back_to_default(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply('{"task_type": "haiku", "confidence": 0.99}')
    )
    result = await classifier.classify("write me a haiku about the moon")
    assert result.task_type == DEFAULT_TASK_TYPE
    await classifier._ollama.aclose()


@respx.mock
async def test_confidence_is_clamped_to_unit_interval(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply('{"task_type": "chat", "confidence": 12.5}')
    )
    result = await classifier.classify("hello")
    assert result.confidence == 1.0
    await classifier._ollama.aclose()


@respx.mock
async def test_garbage_response_returns_zero_confidence_default(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply("I'm not sure how to answer that.")
    )
    result = await classifier.classify("???")
    assert result.task_type == DEFAULT_TASK_TYPE
    assert result.confidence == 0.0
    await classifier._ollama.aclose()


@respx.mock
async def test_ollama_500_does_not_raise(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(return_value=httpx.Response(500))
    result = await classifier.classify("hello")
    assert result == ClassifyResult(task_type=DEFAULT_TASK_TYPE, confidence=0.0)
    await classifier._ollama.aclose()


@respx.mock
async def test_empty_project_string_becomes_none(classifier: Classifier) -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=_ollama_reply('{"task_type": "chat", "confidence": 0.5, "project": "   "}')
    )
    result = await classifier.classify("hi")
    assert result.project is None
    await classifier._ollama.aclose()


# --- system-prompt rubric -------------------------------------------------
#
# The classifier's accuracy lives in the prompt. These tests pin the
# exemplars so that a future rewrite can't silently drop the vault_query
# coverage that lets meta-prompts ("help me study X", "quiz me") route
# to the vault-agent loop. The real-Ollama 80%-accuracy bar is enforced
# in a separate suite when Ollama is wired into CI.


def test_system_prompt_lists_every_task_type() -> None:
    prompt = _system_prompt()
    from routing.roster import TASK_TYPES

    for task_type in TASK_TYPES:
        assert task_type in prompt, f"{task_type} missing from classifier rubric"


def test_system_prompt_covers_vault_query_retrieval_exemplars() -> None:
    prompt = _system_prompt()
    # Lookup-shaped prompts must teach the classifier to route to vault_query.
    assert '"what does perspicacious mean?" → vault_query' in prompt
    assert '"define laconic" → vault_query' in prompt


def test_system_prompt_covers_vault_query_meta_exemplars() -> None:
    """Meta-prompts (study help / do I have notes) must reach vault_query.

    These are the exact prompts that were misclassified as 'chat' before
    Phase 3 landed. Don't let that regress.
    """
    prompt = _system_prompt()
    assert '"help me with my GRE vocabulary" → vault_query' in prompt
    assert '"do I have notes on permutations vs combinations?" → vault_query' in prompt


def test_system_prompt_covers_explicit_vault_directive() -> None:
    prompt = _system_prompt()
    assert "check my vault" in prompt.lower()


def test_system_prompt_keeps_chat_default_for_smalltalk() -> None:
    prompt = _system_prompt()
    assert '"hey, how are you" → chat' in prompt


def test_system_prompt_covers_gre_quiz_exemplars() -> None:
    """Phase 5: 'quiz me' / 'drill me' must reach gre_quiz, not vault_query.

    The distinction matters because gre_quiz wires up a different agent
    (stateful, with grading + writeback). vault_query handles a single
    lookup; gre_quiz handles the multi-turn drill.
    """
    prompt = _system_prompt()
    assert '"quiz me on 10 hard GRE words" → gre_quiz' in prompt
    assert '"drill me on canonical GRE vocab" → gre_quiz' in prompt
    assert '"start a vocab review session" → gre_quiz' in prompt


def test_system_prompt_distinguishes_gre_quiz_from_vault_query() -> None:
    """The rubric must explain *why* gre_quiz is its own bucket.

    Otherwise a future model swap may collapse them and we lose the
    tutor loop. Pin the wording so the regression is obvious.
    """
    prompt = _system_prompt()
    # The rubric must call out that gre_quiz is multi-turn / drill-shaped.
    assert "multi-turn" in prompt
    assert "ask-grade-advance" in prompt
