"""Jinja2 templates for the markdown Delphi writes into the vault.

Three documents flow out of this module:

- ``conversation_note.md.j2`` — one per ``/v1/chat/completions`` exchange
- ``entity_stub.md.j2`` — auto-created when a noun-phrase crosses the threshold
- ``daily_bullet.md.j2`` — appended to ``daily/YYYY-MM-DD.md`` per exchange

User overrides live in a directory passed to ``TemplateRenderer``. Any
template found there shadows the built-in default with the same filename;
the rest fall back to the in-module defaults. This is how you'd ever
customise the conversation note shape without forking the service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined

CONVERSATION_NOTE_TEMPLATE = "conversation_note.md.j2"
ENTITY_STUB_TEMPLATE = "entity_stub.md.j2"
DAILY_BULLET_TEMPLATE = "daily_bullet.md.j2"


_CONVERSATION_NOTE_DEFAULT = """\
---
date: {{ date }}
task_type: {{ task_type | yaml_scalar }}
models: {{ models | yaml_list }}
classifier_confidence: {{ classifier_confidence | yaml_scalar }}
latency_ms: {{ latency_ms }}
input_tokens: {{ input_tokens }}
output_tokens: {{ output_tokens }}
project: {{ project | yaml_scalar }}
entities: {{ entities | yaml_list }}
tags: {{ tags | yaml_list }}
client_id: {{ client_id | yaml_scalar }}
truncated: {{ truncated | yaml_scalar }}
---

## User

{{ user_message }}

## Assistant

{{ assistant_message }}
"""


_ENTITY_STUB_DEFAULT = """\
---
type: entity
status: stub
created: {{ created }}
first_mentioned: {{ first_mentioned }}
---

# {{ display }}

Auto-created stub. First mentioned in a conversation on {{ first_mentioned }}.
"""


_DAILY_BULLET_DEFAULT = "- {{ time }} [[{{ rel_path }}]] — {{ task_type }} ({{ latency_ms }}ms)\n"


_DEFAULT_TEMPLATES: dict[str, str] = {
    CONVERSATION_NOTE_TEMPLATE: _CONVERSATION_NOTE_DEFAULT,
    ENTITY_STUB_TEMPLATE: _ENTITY_STUB_DEFAULT,
    DAILY_BULLET_TEMPLATE: _DAILY_BULLET_DEFAULT,
}


def yaml_scalar(value: Any) -> str:
    """Render a YAML scalar. Strings get quoted; ``None`` becomes ``null``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def yaml_list(items: Any) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(yaml_scalar(item) for item in items) + "]"


class TemplateRenderer:
    """Render Delphi's vault documents.

    Pass ``override_dir`` to allow per-deployment template customisation;
    a file with the same name as one of the built-ins (e.g. ``conversation_note.md.j2``)
    overrides it. Missing override files fall through to the defaults.
    """

    def __init__(self, override_dir: Path | str | None = None) -> None:
        loaders: list[Any] = []
        if override_dir is not None:
            override_path = Path(override_dir)
            if override_path.is_dir():
                loaders.append(FileSystemLoader(override_path))
        loaders.append(DictLoader(_DEFAULT_TEMPLATES))

        self._env = Environment(
            loader=ChoiceLoader(loaders),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        self._env.filters["yaml_scalar"] = yaml_scalar
        self._env.filters["yaml_list"] = yaml_list

    def render_conversation_note(self, **context: Any) -> str:
        return self._env.get_template(CONVERSATION_NOTE_TEMPLATE).render(**context)

    def render_entity_stub(self, **context: Any) -> str:
        return self._env.get_template(ENTITY_STUB_TEMPLATE).render(**context)

    def render_daily_bullet(self, **context: Any) -> str:
        return self._env.get_template(DAILY_BULLET_TEMPLATE).render(**context)
