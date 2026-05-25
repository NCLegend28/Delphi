"""arq worker entrypoint — the normal persist path.

Run with::

    uv run arq worker.main.WorkerSettings

It builds the memory components once on startup (vault writer, entity index,
request logger, metrics), exposes its Prometheus registry on
``WORKER_METRICS_PORT``, then drains persist jobs the gateway enqueues. Each
job is a serialized :class:`~memory.record.ConversationRecord`; the worker
rebuilds it and runs the same ``run_persist`` the gateway would have run
inline. No Ollama client here — persist touches only disk and metrics.

The worker is stateless across jobs beyond the long-lived component handles in
``ctx``; arq restarts it cleanly and reconnects to Redis on its own.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from config import get_config
from memory.entities import EntityIndex
from memory.persist import run_persist
from memory.vault import VaultWriter
from telemetry.logger import RequestLogger, configure_stdlib_logging
from telemetry.metrics import Metrics
from worker.queue import PERSIST_JOB, redis_settings
from worker.serde import from_payload

log = structlog.get_logger("delphi.worker")

_cfg = get_config()


async def persist_exchange(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    """Consume one serialized exchange and run the durable persist pipeline."""
    record = from_payload(payload)
    try:
        await run_persist(
            record,
            vault=ctx["vault"],
            logger=ctx["request_logger"],
            entity_index=ctx["entity_index"],
            metrics=ctx["metrics"],
        )
    except Exception as exc:
        log.error("persist_failed", request_id=record.request_id, error=str(exc))


async def startup(ctx: dict[str, Any]) -> None:
    configure_stdlib_logging()
    cfg = get_config()
    ctx["vault"] = VaultWriter(cfg.obsidian_vault_path, cfg.timezone)
    ctx["request_logger"] = RequestLogger(cfg.log_dir, cfg.timezone)
    ctx["entity_index"] = EntityIndex(
        cfg.obsidian_vault_path, threshold=cfg.entity_create_threshold
    )
    ctx["metrics"] = Metrics()
    # Normal-path metrics live here; Prometheus scrapes this alongside the
    # gateway's /metrics (which carries only the Redis-down fallback path).
    start_http_server(cfg.worker_metrics_port, registry=ctx["metrics"].registry)
    log.info("worker_boot", metrics_port=cfg.worker_metrics_port, redis=cfg.redis_url)


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_shutdown")


# Job names are referenced by string when enqueuing; keep the wiring honest.
assert persist_exchange.__name__ == PERSIST_JOB


# arq discovers this class by dotted path: ``worker.main.WorkerSettings``.
class WorkerSettings:
    functions: ClassVar = [persist_exchange]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings: ClassVar[RedisSettings] = redis_settings(_cfg.redis_url)
