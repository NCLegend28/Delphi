"""Delphi FastAPI entrypoint.

This file is glue. The lifespan builds the shared components, the routes
delegate every decision to a sibling module. If something here grows into
logic, it probably belongs in routing/ or memory/ or proxy/.

Boot sequence (per CLAUDE.md → Boot sequence):
1. Load ``Config`` from env/.env.
2. Configure structlog → JSON to stderr for app-level events.
3. Build Ollama client, classifier, roster, vault writer, request logger;
   stash on ``app.state``.
4. If ``boot_probe_enabled``: probe Ollama tags, warn on missing roster
   models, verify the vault path is writable. Fail-fast if Ollama is
   unreachable. Tests set ``BOOT_PROBE_ENABLED=false`` to skip this.
5. Yield.
6. Close the Ollama client on shutdown.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator, Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Response, status

from api.chat import router as chat_router
from api.deps import get_metrics, get_ollama, get_roster
from auth.bearer import require_bearer
from config import Config, get_config
from memory.entities import EntityIndex
from memory.vault import VaultWriter
from proxy.ollama_client import OllamaClient, OllamaError
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger, configure_stdlib_logging
from telemetry.metrics import Metrics

log = structlog.get_logger("delphi.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_stdlib_logging()
    cfg = get_config()
    log.info("delphi_boot", config=cfg.redacted())

    ollama = OllamaClient(cfg.ollama_base_url)
    classifier = Classifier(ollama, cfg.classifier_model)
    roster = Roster()
    vault = VaultWriter(cfg.obsidian_vault_path, cfg.timezone)
    request_logger = RequestLogger(cfg.log_dir, cfg.timezone)
    entity_index = EntityIndex(cfg.obsidian_vault_path, threshold=cfg.entity_create_threshold)
    metrics = Metrics()

    app.state.ollama = ollama
    app.state.classifier = classifier
    app.state.roster = roster
    app.state.vault = vault
    app.state.request_logger = request_logger
    app.state.entity_index = entity_index
    app.state.metrics = metrics

    if cfg.boot_probe_enabled:
        try:
            available = await ollama.list_models()
        except OllamaError as exc:
            log.error("ollama_unreachable", error=str(exc), base_url=cfg.ollama_base_url)
            raise SystemExit(f"Ollama unreachable at {cfg.ollama_base_url}: {exc}") from exc

        missing = sorted(set(roster.all_models()) - set(available))
        if missing:
            log.warning("roster_models_missing", missing=missing)

        vault_dir = Path(cfg.obsidian_vault_path)
        try:
            vault_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.error("vault_path_unwritable", path=str(vault_dir), error=str(exc))
            raise SystemExit(f"Vault path not writable: {vault_dir}: {exc}") from exc
        if not os.access(vault_dir, os.W_OK):
            raise SystemExit(f"Vault path not writable: {vault_dir}")

    try:
        yield
    finally:
        await ollama.aclose()
        log.info("delphi_shutdown")


app = FastAPI(title="Delphi", version="0.1.0", lifespan=lifespan)
app.include_router(chat_router)


# --- public liveness ------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — no auth, no dependencies. Always cheap."""
    return {"status": "ok"}


# --- authenticated readiness + roster ------------------------------------


@app.get("/readyz", dependencies=[Depends(require_bearer)])
async def readyz(
    ollama: Annotated[OllamaClient, Depends(get_ollama)],
) -> dict[str, Any]:
    """Readiness probe: confirm Ollama is reachable. 503 if not."""
    try:
        available = await ollama.list_models()
    except OllamaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ollama unreachable: {exc}",
        ) from exc
    return {"status": "ok", "ollama_models": len(available)}


@app.get("/v1/models", dependencies=[Depends(require_bearer)])
async def list_models(
    roster: Annotated[Roster, Depends(get_roster)],
) -> dict[str, Any]:
    """OpenAI-style ``/v1/models`` listing — clients use it for discovery."""
    return {
        "object": "list",
        "data": [
            {
                "id": entry.model,
                "object": "model",
                "owned_by": "delphi",
                "task_type": task_type,
            }
            for task_type, entry in roster.items()
        ],
    }


@app.get("/metrics")
async def metrics_endpoint(
    metrics: Annotated[Metrics, Depends(get_metrics)],
) -> Response:
    """Prometheus exposition. Unauthenticated by design — Caddy + Tailscale
    restrict who can reach this port, and Prometheus scrapers don't speak
    bearer-auth out of the box."""
    body, content_type = metrics.expose()
    return Response(content=body, media_type=content_type)


def main() -> None:
    """Local dev entrypoint: ``uv run python main.py``."""
    import uvicorn

    cfg = get_config()
    uvicorn.run("main:app", host=cfg.host, port=cfg.port, reload=False)


if __name__ == "__main__":
    main()
