"""The vault-query agent — a bounded tool-calling loop over the vault.

When a request resolves to ``vault_query``, the answer should come from Tali's
notes, not the model's training. So instead of a plain proxy call, we hand the
model two tools — ``search_vault`` and ``read_note`` — and let it drive: search
for relevant notes, read the promising ones, then answer grounded in what it
found. The same search→read→reason loop a person uses against the vault.

The loop is **bounded** (``max_steps``): a model that keeps calling tools is
cut off and forced to answer with what it has, so a confused or adversarial
turn can't spin forever or run up unbounded cloud cost. Tool execution is
read-only (see ``memory.vault_reader``) and every failure is handed back to the
model as text rather than raised — the model can recover (try a different
query) the way it would from any empty result.

Requires a tool-capable model for ``DELPHI_MODEL_VAULT_QUERY``. If the model
ignores the tools and just answers, that answer flows through ungrounded —
graceful, if not ideal; pick a tool-capable cloud tag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from memory.record import TokenCounts
from memory.vault_reader import VaultReader
from proxy.ollama_client import OllamaClient

# OpenAI-style function schemas. Descriptions are written *for the model* —
# they teach it the search-then-read workflow and the path round-trip.
VAULT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Search the user's Obsidian vault (personal markdown notes) by keyword. "
                "Returns ranked matches as JSON, each with a vault-relative `path`, a "
                "`score`, and a `snippet`. Call this FIRST to locate relevant notes, then "
                "use read_note on the paths worth reading in full."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords describing what to look for.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (optional; default 8).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": (
                "Read the full text of one vault note, given the vault-relative `path` "
                "returned by search_vault (e.g. 'conversations/2026-05-12/note.md')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative path of the note to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
]


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Outcome of the loop: the grounded answer plus how it got there."""

    content: str
    steps: int  # model round-trips taken
    tool_calls_made: int
    token_counts: TokenCounts | None


def _usage_from(resp: dict[str, Any]) -> TokenCounts | None:
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        return None
    it = usage.get("prompt_tokens", usage.get("input_tokens"))
    ot = usage.get("completion_tokens", usage.get("output_tokens"))
    if isinstance(it, int) and isinstance(ot, int):
        return TokenCounts(input_tokens=it, output_tokens=ot)
    return None


def _execute_tool(name: str, raw_args: Any, reader: VaultReader) -> str:
    """Run one tool call and return a string result for the model.

    Never raises — a bad path, unknown tool, or unparseable arguments come back
    as an error string the model can read and react to.
    """
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
    except (json.JSONDecodeError, TypeError):
        return "error: could not parse tool arguments as JSON"

    if name == "search_vault":
        query = str(args.get("query", "")).strip()
        if not query:
            return "error: search_vault requires a non-empty 'query'"
        limit = args.get("limit")
        hits = reader.search(query, limit=limit if isinstance(limit, int) else None)
        if not hits:
            return json.dumps({"results": [], "note": "no matching notes found"})
        return json.dumps(
            {"results": [{"path": h.path, "score": h.score, "snippet": h.snippet} for h in hits]}
        )

    if name == "read_note":
        path = str(args.get("path", "")).strip()
        if not path:
            return "error: read_note requires a 'path'"
        try:
            return reader.read(path)
        except FileNotFoundError as exc:
            return f"error: {exc}"

    return f"error: unknown tool '{name}'"


async def run_vault_agent(
    *,
    ollama: OllamaClient,
    model: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any] | None,
    reader: VaultReader,
    max_steps: int = 5,
) -> AgentResult:
    """Drive the search→read→answer loop and return the grounded answer."""
    convo: list[dict[str, Any]] = list(messages)
    token_counts: TokenCounts | None = None
    tool_calls_made = 0

    for step in range(1, max_steps + 1):
        resp = await ollama.chat(model=model, messages=convo, options=options, tools=VAULT_TOOLS)
        token_counts = _usage_from(resp) or token_counts
        message = resp["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return AgentResult(
                content=message.get("content") or "",
                steps=step,
                tool_calls_made=tool_calls_made,
                token_counts=token_counts,
            )

        # Record the assistant's tool-request turn verbatim, then answer each
        # call with a tool-role message keyed by the same id.
        convo.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            tool_calls_made += 1
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            result = _execute_tool(fn.get("name", ""), fn.get("arguments"), reader)
            convo.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
            )

    # Budget exhausted — force a final answer with tools withheld so the model
    # must conclude from what it has gathered rather than calling again.
    convo.append(
        {
            "role": "user",
            "content": "Answer now using the notes you've gathered. Do not call any more tools.",
        }
    )
    final = await ollama.chat(model=model, messages=convo, options=options)
    token_counts = _usage_from(final) or token_counts
    return AgentResult(
        content=final["choices"][0]["message"].get("content") or "",
        steps=max_steps,
        tool_calls_made=tool_calls_made,
        token_counts=token_counts,
    )
