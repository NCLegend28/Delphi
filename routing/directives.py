"""UI directive parsing — strip ``[MODE:…]``, ``[TASK:…]``, and
``[PREVIEW:…]…[/PREVIEW]`` blocks from assistant text.

The directives are an out-of-band protocol between Delphi and ``delphi-ui``
(see ``routing.soul.UI_PROTOCOL_APPENDIX``). They tell the interface to set
the active mode, label the current task, or hand a body to the preview pane.
Only ``delphi-ui`` knows how to parse them; every other client (AgentRig,
``curl``, Open WebUI) sees brackets bleed into chat.

Two reasons a non-UI client might see a directive in practice:

1. The model invents a directive without being taught the protocol (the
   soul withholds the UI appendix from non-UI clients, but gpt-oss
   occasionally over-generalizes from training data and emits them anyway).
2. The model is mid-turn for a UI client and another client tails the same
   vault note for review.

Either way, the gateway should sanitize for non-UI consumers. This module
is the stripper. The conversation note we persist keeps the *unstripped*
text so vault notes remain a faithful record of what the model produced.

API:

* ``strip_ui_directives(text)`` — pure function over a complete string.
  Removes the directive tokens and any whitespace they left behind.
* ``DIRECTIVE_PATTERN`` — the regex used; exported for test pinning.

Streaming consumers (real-time SSE chunk-by-chunk) can't use this
directly because a directive can straddle chunk boundaries. A
chunk-aware stripper is a separate task; for now the
vault-query response path (which buffers the full answer before
framing as SSE) is the only path that needs sanitization, and this
function is enough for that case.
"""

from __future__ import annotations

import re

# Block-form ``[PREVIEW:<kind>[:<arg>]] … [/PREVIEW]`` — match lazily so back-
# to-back previews don't get merged into one. ``re.DOTALL`` lets ``.`` cross
# the newlines that separate the directive from its body. The trailing
# ``[ \t]*`` consumes the horizontal whitespace the directive leaves behind
# so the next sentence doesn't start with a stray space.
_PREVIEW_BLOCK = re.compile(
    r"\[PREVIEW:[^\]]*\].*?\[/PREVIEW\][ \t]*",
    re.DOTALL,
)

# Inline directives — ``[MODE:THINKING]``, ``[TASK: refactoring soul.py]``,
# etc. These are single-token: bracket, identifier, optional ``:<payload>``,
# closing bracket. We allow whatever the soul advertises plus any future
# additions that follow the same shape, so a new ``[STATUS:…]`` or
# ``[SOURCE:…]`` directive doesn't require a regex bump here. The trailing
# ``[ \t]*`` consumes the space the model usually leaves between a directive
# and the next token of prose.
_INLINE_DIRECTIVE = re.compile(
    r"\[(?:MODE|TASK|STATUS|SOURCE|HUD|PHASE|STEP)(?::[^\]]*)?\][ \t]*",
)

# Public alias so tests can assert against the exact regex if they want a
# tighter contract than "the function strips".
DIRECTIVE_PATTERN = re.compile(
    f"(?:{_PREVIEW_BLOCK.pattern})|(?:{_INLINE_DIRECTIVE.pattern})",
    re.DOTALL,
)


def strip_ui_directives(text: str) -> str:
    """Remove all UI directive tokens from ``text``.

    Strips block-form ``[PREVIEW:…]…[/PREVIEW]`` first (so a stray inline
    ``[MODE:…]`` inside a preview body doesn't get double-treated), then
    inline directives, then collapses the whitespace the removals leave
    behind. A line that becomes empty after stripping is dropped entirely,
    so a model that puts each directive on its own line doesn't leave a
    ladder of blank rows in chat.

    Returns the input unchanged if there is nothing to strip. The function
    is pure — no logging side effects, no state.
    """
    if not text or "[" not in text:
        return text
    cleaned = _PREVIEW_BLOCK.sub("", text)
    cleaned = _INLINE_DIRECTIVE.sub("", cleaned)
    if cleaned == text:
        return text
    # Drop the empty lines that bracket-removal left behind without touching
    # the user's own intentional blank lines (a paragraph break stays). We
    # also ``rstrip`` each line so a directive at end-of-line doesn't leave
    # the trailing space behind ("done [MODE:IDLE]" → "done", not "done ").
    lines = [line.rstrip() for line in cleaned.split("\n")]
    pruned: list[str] = []
    for line in lines:
        if line == "" and pruned and pruned[-1] == "":
            continue  # collapse runs of blank lines
        pruned.append(line)
    # Strip leading/trailing blank lines that pure-directive lines may have
    # introduced at the start or end of the message.
    while pruned and pruned[0] == "":
        pruned.pop(0)
    while pruned and pruned[-1] == "":
        pruned.pop()
    return "\n".join(pruned)
