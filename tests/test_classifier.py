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
from routing.classifier import Classifier, ClassifyResult
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
