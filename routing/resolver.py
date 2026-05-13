"""Resolver — the front half of routing.

Decides *which* model serves an incoming request and *why*. Pure async
function with no I/O of its own; composes the classifier and the roster.
Lives next to ``roster`` and ``soul``: resolver decides *what* model,
roster knows *how* to call it, soul shapes *what to say* to it.

See ``ResolvedModel`` and ``resolve_model`` for the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from routing.classifier import Classifier, ClassifyResult
from routing.roster import DEFAULT_TASK_TYPE, Roster

# Task type names stay loose at the type level — the canonical set is
# ``roster.TASK_TYPES`` and the validation gate is the roster lookup.
TaskType = str

ResolutionSource = Literal["explicit_model", "explicit_task", "classified", "default"]


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """The resolver's output. Everything ``main.py`` needs to call Ollama.

    ``source`` carries *why* this model was chosen — a low-confidence
    classification vs. an explicit client choice produce the same ``model``
    but very different operational signals. Telemetry needs both.
    """

    model: str
    task_type: TaskType
    source: ResolutionSource
    classifier_result: ClassifyResult | None = None


def _last_user_message(messages: list[dict[str, Any]] | None) -> str:
    """Pull the last entry with ``role == "user"`` out of the messages list.

    Returns the empty string when no messages or no user message exists —
    the classifier accepts empty input and fails open to ``DEFAULT_TASK_TYPE``.
    """
    if not messages:
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


async def resolve_model(
    request_body: dict[str, Any],
    classifier: Classifier,
    roster: Roster,
) -> ResolvedModel:
    """Decide which Ollama model serves this request.

    Decision tree (first match wins):

    1. ``request_body["model"]`` set and non-empty → ``source="explicit_model"``.
       Classifier is **not** called. ``task_type`` comes from reverse-lookup;
       unknown models still flow through with ``task_type=DEFAULT_TASK_TYPE``.
    2. ``request_body["task_type"]`` set, non-empty, ``!= "auto"``, **and**
       known to the roster → ``source="explicit_task"``. Classifier not called.
    3. ``"auto"`` / absent / unknown explicit task → classify the last user
       message → ``source="classified"`` (even at 0.0 confidence — telemetry
       distinguishes "classifier ran and was unsure" from "we didn't run it").
    4. Defensive fallback if even the classifier path can't find a roster
       entry → ``source="default"``, ``task_type=DEFAULT_TASK_TYPE``.

    Never raises. Inputs are user-controlled; resolution always succeeds.
    """
    # --- Case 1: explicit model ---
    explicit_model = request_body.get("model")
    if isinstance(explicit_model, str) and explicit_model.strip():
        model = explicit_model.strip()
        reversed_task = roster.reverse_lookup(model)
        return ResolvedModel(
            model=model,
            task_type=reversed_task or DEFAULT_TASK_TYPE,
            source="explicit_model",
        )

    # --- Case 2: explicit valid task_type ---
    explicit_task = request_body.get("task_type")
    if (
        isinstance(explicit_task, str)
        and explicit_task.strip()
        and explicit_task != "auto"
    ):
        entry = roster.lookup(explicit_task)
        if entry is not None:
            return ResolvedModel(
                model=entry.model,
                task_type=explicit_task,
                source="explicit_task",
            )
        # Unknown task_type → treat as absent and fall through to classifier.

    # --- Case 3: classifier ---
    last_user = _last_user_message(request_body.get("messages"))
    result = await classifier.classify(last_user)
    entry = roster.lookup(result.task_type)
    if entry is not None:
        return ResolvedModel(
            model=entry.model,
            task_type=result.task_type,
            source="classified",
            classifier_result=result,
        )

    # --- Case 4: defensive fallback ---
    # Reached only if classifier returned a task missing from the roster
    # (shouldn't happen given the classifier coerces unknown tasks, but
    # the roster could theoretically be misconfigured).
    default_entry = roster.lookup(DEFAULT_TASK_TYPE)
    if default_entry is None:
        # Last-ditch: roster has no entry for DEFAULT_TASK_TYPE. The contract
        # promises we never raise, so synthesize a minimal answer.
        return ResolvedModel(
            model=DEFAULT_TASK_TYPE,
            task_type=DEFAULT_TASK_TYPE,
            source="default",
        )
    return ResolvedModel(
        model=default_entry.model,
        task_type=DEFAULT_TASK_TYPE,
        source="default",
    )
