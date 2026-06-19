"""Push notifications via ntfy.

A thin async client over an ntfy server (``ntfy.sh`` or a self-hosted binary
behind Tailscale). Delphi's failures currently land only in the JSONL log; this
turns the ones worth a human's attention into a push on Tali's phone.

Design mirrors the rest of ``telemetry/``:

* **Fail-open, always.** ``send()`` never raises. A notifier that's down must
  not take a request — or a persist job — with it. Errors re-emit to stderr via
  the same fallback structlog logger ``RequestLogger`` uses.
* **Async, never blocking.** One shared ``httpx.AsyncClient`` (we use httpx
  everywhere; never ``requests``). Disk/network on the request path is offloaded
  or fire-and-forget upstream of this module.
* **Disable cleanly.** ``Notifier.disabled`` (no base URL / no default topic)
  short-circuits ``send()`` to a no-op, so call sites need no ``if`` guards.

ntfy's wire model is a CB radio: a *topic* is a channel, and the topic name is
the only access control on the public server. Pick unguessable names, or
self-host behind the tailnet. We publish via the JSON endpoint (POST the server
root with a ``{"topic": ..., "message": ...}`` body) because it expresses
action buttons — needed for the approval hook — far more cleanly than the
header-encoded form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import httpx
import structlog


class Priority(IntEnum):
    """ntfy priority levels (1=min … 5=max). Maps to push urgency + sound."""

    MIN = 1
    LOW = 2
    DEFAULT = 3
    HIGH = 4
    MAX = 5


@dataclass(frozen=True)
class Action:
    """A notification action button.

    ``action`` is ntfy's verb — ``"view"`` (open ``url``) or ``"http"`` (fire a
    request to ``url``). The approval hook uses ``"http"`` so an Approve/Deny tap
    POSTs straight back to a Delphi endpoint without opening a browser.
    """

    action: str
    label: str
    url: str
    method: str | None = None
    body: str | None = None
    clear: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "label": self.label,
            "url": self.url,
            "clear": self.clear,
        }
        if self.method is not None:
            payload["method"] = self.method
        if self.body is not None:
            payload["body"] = self.body
        return payload


@dataclass(frozen=True)
class Notification:
    """One push. ``topic`` defaults to the notifier's default topic when None."""

    message: str
    title: str | None = None
    priority: Priority = Priority.DEFAULT
    tags: tuple[str, ...] = ()
    click: str | None = None
    actions: tuple[Action, ...] = ()
    topic: str | None = None

    def to_payload(self, default_topic: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "topic": self.topic or default_topic,
            "message": self.message,
            "priority": int(self.priority),
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.click is not None:
            payload["click"] = self.click
        if self.actions:
            payload["actions"] = [a.to_payload() for a in self.actions]
        return payload


class Notifier:
    """Async ntfy publisher. Construct once at boot, ``aclose()`` on shutdown.

    Topic routing is per *event class*, not per message: ops alerts, GRE nudges,
    and approval requests each get their own topic so Tali can subscribe (and
    mute) them independently. A topic of ``None`` falls back to the default.
    """

    def __init__(
        self,
        base_url: str,
        *,
        default_topic: str,
        token: str | None = None,
        topics: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_topic = default_topic
        self._token = token or None
        self._topics = dict(topics or {})
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._fallback = structlog.get_logger("delphi.telemetry.notify")

    @classmethod
    def from_config(cls, cfg: Any) -> Notifier:
        """Build from a ``Config`` (same pattern as ``Roster.from_config``).

        Per-event topics fall back to ``ntfy_default_topic`` when their env var
        is empty, so a stock build can point everything at one channel and split
        them out later. An empty base URL or default topic yields a notifier
        whose ``disabled`` is True — every ``send()`` becomes a no-op.
        """
        default = cfg.ntfy_default_topic
        topics = {
            "ops": cfg.ntfy_topic_ops or default,
            "gre": cfg.ntfy_topic_gre or default,
            "jobs": cfg.ntfy_topic_jobs or default,
            "approvals": cfg.ntfy_topic_approvals or default,
        }
        return cls(
            cfg.ntfy_base_url,
            default_topic=default,
            token=cfg.ntfy_token or None,
            topics=topics,
        )

    @property
    def disabled(self) -> bool:
        """No base URL or no default topic → every ``send()`` is a no-op."""
        return not self._base_url or not self._default_topic

    def topic_for(self, event_class: str) -> str | None:
        """Resolve an event class (``"ops"``, ``"gre"``, …) to its topic."""
        return self._topics.get(event_class)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.AsyncClient(timeout=self._timeout, headers=headers)
        return self._client

    async def send(self, notification: Notification) -> bool:
        """Publish one notification. Returns ``True`` on a 2xx, never raises."""
        if self.disabled:
            return False
        payload = notification.to_payload(self._default_topic)
        try:
            client = self._ensure_client()
            resp = await client.post(self._base_url, json=payload)
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001 — notifications must not break callers
            self._fallback.warning(
                "ntfy_send_failed",
                error=f"{type(exc).__name__}: {exc}",
                topic=payload.get("topic"),
            )
            return False

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- semantic helpers: the events Delphi actually emits ---------------
    # Each maps a domain event onto a Notification with sensible priority,
    # tags (ntfy renders known tag names as emoji), and topic. Call sites stay
    # one-liners; the policy (how loud, which channel) lives here.

    async def ops_alert(
        self, message: str, *, title: str = "Delphi", critical: bool = False
    ) -> bool:
        """Operational problem — Ollama down, VRAM exhausted, probe failed."""
        return await self.send(
            Notification(
                message=message,
                title=title,
                priority=Priority.MAX if critical else Priority.HIGH,
                tags=("rotating_light",) if critical else ("warning",),
                topic=self.topic_for("ops"),
            )
        )

    async def vault_write_failed(self, path: str, error: str) -> bool:
        """Best-effort memory dropped a note — silent in the log otherwise."""
        return await self.send(
            Notification(
                message=f"Vault write failed for {path}: {error}",
                title="Delphi · memory",
                priority=Priority.HIGH,
                tags=("floppy_disk", "warning"),
                topic=self.topic_for("ops"),
            )
        )

    async def gre_due(self, due_count: int, *, click: str | None = None) -> bool:
        """Spaced-repetition nudge: N cards due. ``click`` deep-links the quiz."""
        if due_count <= 0:
            return False
        return await self.send(
            Notification(
                message=f"{due_count} GRE card{'s' if due_count != 1 else ''} due for review.",
                title="Delphi · GRE",
                priority=Priority.DEFAULT,
                tags=("books",),
                click=click,
                topic=self.topic_for("gre"),
            )
        )

    async def job_done(
        self, what: str, *, latency_ms: int | None = None, click: str | None = None
    ) -> bool:
        """A long deep_code/deep_reason job finished — stop babysitting the stream."""
        suffix = f" in {latency_ms / 1000:.0f}s" if latency_ms is not None else ""
        return await self.send(
            Notification(
                message=f"{what} finished{suffix}.",
                title="Delphi · job",
                priority=Priority.DEFAULT,
                tags=("white_check_mark",),
                click=click,
                topic=self.topic_for("jobs"),
            )
        )

    async def approval_request(
        self, summary: str, *, approve_url: str, deny_url: str, token_header: str | None = None
    ) -> bool:
        """Human-in-the-loop: a proxied tool call wants a real-world action.

        Renders Approve/Deny buttons that POST back to Delphi. ``token_header``
        (e.g. ``"Bearer …"``) is attached so the callback survives the bearer
        auth the service enforces on its own endpoints.
        """
        headers = f"\nAuthorization: {token_header}" if token_header else ""
        return await self.send(
            Notification(
                message=summary,
                title="Delphi · approval needed",
                priority=Priority.MAX,
                tags=("warning",),
                actions=(
                    Action("http", "Approve", approve_url, method="POST", body=headers.strip()),
                    Action("http", "Deny", deny_url, method="POST", body=headers.strip()),
                ),
                topic=self.topic_for("approvals"),
            )
        )
