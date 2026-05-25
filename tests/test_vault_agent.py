"""Tests for the vault-query agent: the bounded search→read→answer loop."""

from __future__ import annotations

import json

import pytest

from memory.vault_reader import VaultReader
from routing.vault_agent import _execute_tool, run_vault_agent


@pytest.fixture
def reader(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "msa.md").write_text(
        "MSA is multi-head sparse attention for long context.\n", encoding="utf-8"
    )
    return VaultReader(str(tmp_path))


class ScriptedOllama:
    """Stub OllamaClient.chat that replays a fixed list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, options=None, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._responses.pop(0)


def _tool_call(name, args, call_id="c1"):
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
            }
        ]
    }


def _final(content, usage=None):
    msg = {"choices": [{"message": {"content": content}}]}
    if usage:
        msg["usage"] = usage
    return msg


# --- _execute_tool -------------------------------------------------------


def test_execute_search_returns_json(reader):
    out = _execute_tool("search_vault", {"query": "sparse attention"}, reader)
    payload = json.loads(out)
    assert payload["results"]
    assert payload["results"][0]["path"] == "notes/msa.md"


def test_execute_read_returns_text(reader):
    out = _execute_tool("read_note", {"path": "notes/msa.md"}, reader)
    assert "sparse attention" in out


def test_execute_read_traversal_returns_error_not_raise(reader):
    out = _execute_tool("read_note", {"path": "../../etc/passwd"}, reader)
    assert out.startswith("error:")


def test_execute_unknown_tool(reader):
    assert _execute_tool("delete_everything", {}, reader).startswith("error: unknown tool")


def test_execute_bad_json_args(reader):
    assert _execute_tool("search_vault", "{not json", reader).startswith("error:")


# --- run_vault_agent -----------------------------------------------------


async def test_agent_searches_then_answers(reader):
    ollama = ScriptedOllama(
        [
            _tool_call("search_vault", {"query": "MSA"}),
            _final(
                "MSA is multi-head sparse attention.",
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
        ]
    )
    result = await run_vault_agent(
        ollama=ollama, model="m", messages=[{"role": "user", "content": "what is MSA?"}],
        options=None, reader=reader, max_steps=5,
    )
    assert result.content == "MSA is multi-head sparse attention."
    assert result.tool_calls_made == 1
    assert result.steps == 2
    assert result.token_counts is not None and result.token_counts.input_tokens == 50
    # Second call must carry the tool result back to the model.
    assert any(m.get("role") == "tool" for m in ollama.calls[1]["messages"])


async def test_agent_answers_without_tools(reader):
    ollama = ScriptedOllama([_final("Direct answer, no search needed.")])
    result = await run_vault_agent(
        ollama=ollama, model="m", messages=[{"role": "user", "content": "hi"}],
        options=None, reader=reader, max_steps=5,
    )
    assert result.content == "Direct answer, no search needed."
    assert result.tool_calls_made == 0
    assert result.steps == 1


async def test_agent_bounded_by_max_steps(reader):
    # Model keeps calling tools; the loop must cut it off and force an answer.
    responses = [_tool_call("search_vault", {"query": "x"}) for _ in range(3)]
    responses.append(_final("Forced final answer."))
    ollama = ScriptedOllama(responses)
    result = await run_vault_agent(
        ollama=ollama, model="m", messages=[{"role": "user", "content": "q"}],
        options=None, reader=reader, max_steps=3,
    )
    assert result.content == "Forced final answer."
    assert result.steps == 3
    # Final forced call withholds tools.
    assert ollama.calls[-1]["tools"] is None
