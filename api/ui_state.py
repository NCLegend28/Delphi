"""Backend state contract for Delphi's web interface.

The UI is not allowed to invent telemetry. This route computes the interface
readouts from the same durable sources the backend already maintains: request
JSONL logs, roster config, vault files, and live dependency probes.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from api.deps import get_arq_pool, get_ollama, get_request_logger, get_roster
from auth.bearer import require_bearer
from config import Config, get_config
from proxy.ollama_client import OllamaClient, OllamaError
from routing.roster import Roster
from telemetry.logger import RequestLogger

router = APIRouter(prefix="/ui", tags=["ui"], dependencies=[Depends(require_bearer)])

_ZONE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Code & models", ("code", "model", "nursery", "judge", "roster", "classifier", "eval")),
    ("Trading", ("trading", "financio", "market", "position", "broker", "webull")),
    ("Language", ("gre", "vocab", "language", "word", "mnemonic", "verbal")),
    ("Infra & deploy", ("infra", "deploy", "caddy", "docker", "redis", "tailscale", "server")),
    ("Delphi herself", ("delphi", "soul", "memory", "voice", "interface")),
)


@router.get("/state")
async def ui_state(
    cfg: Annotated[Config, Depends(get_config)],
    roster: Annotated[Roster, Depends(get_roster)],
    ollama: Annotated[OllamaClient, Depends(get_ollama)],
    logger: Annotated[RequestLogger, Depends(get_request_logger)],
    arq_pool: Annotated[Any, Depends(get_arq_pool)],
) -> dict[str, Any]:
    """Return the real backend state backing the Nocturne interface."""

    records = _read_request_log(logger.path)
    today_records = _records_for_today(records, cfg.timezone)
    vault = _vault_stats(Path(cfg.obsidian_vault_path), cfg.delphi_vault_bitspace_bytes)
    vault["last_vault_write"] = _last_vault_write_from_records(today_records) or vault[
        "last_vault_write"
    ]
    inference = await _probe_inference(ollama)

    return {
        "system": _system_summary(
            today_records, context_window_tokens=cfg.delphi_context_window_tokens
        ),
        "services": _service_cards(
            inference=inference,
            arq_pool=arq_pool,
            vault=vault,
            cfg=cfg,
        ),
        "roster": _roster_rows(roster, today_records),
        "requests": _last_requests(today_records),
        "memory": vault,
        "practice": _practice_summary(Path(cfg.obsidian_vault_path)),
        "cue_cards": _cue_cards(vault=vault, records=today_records, roster=roster),
        "not_built_yet": _not_built_yet(),
    }


def _read_request_log(path: Path, *, limit: int = 1000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _timezone_or_default(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone or "America/Chicago")
    except ValueError:
        return ZoneInfo("America/Chicago")


def _records_for_today(records: list[dict[str, Any]], timezone: str) -> list[dict[str, Any]]:
    tz = _timezone_or_default(timezone)
    today = datetime.now(tz).date()
    out: list[dict[str, Any]] = []
    for record in records:
        ts = record.get("ts")
        if not isinstance(ts, str):
            continue
        try:
            when = datetime.fromisoformat(ts).astimezone(tz)
        except ValueError:
            continue
        if when.date() == today:
            out.append(record)
    return out


def _num(record: dict[str, Any], key: str) -> float | None:
    value = record.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float) and math.isfinite(value):
        return float(value)
    return None


def _system_summary(
    records: list[dict[str, Any]], *, context_window_tokens: int
) -> dict[str, Any]:
    failures = [r for r in records if r.get("error")]
    last = records[-1] if records else None
    ttft = _num(last, "ttft_ms") if last else None
    latency = _num(last, "latency_ms") if last else None
    output_tokens = _num(last, "output_tokens") if last else None
    tps = None
    if latency and output_tokens:
        tps = round(output_tokens / (latency / 1000), 1)

    return {
        "requests_today": len(records),
        "failures_today": len(failures),
        "last_request": last,
        "context": _context_summary(last, window_tokens=context_window_tokens),
        "uplink": {
            "last_ttft_ms": int(ttft) if ttft is not None else None,
            "last_latency_ms": int(latency) if latency is not None else None,
            "last_tokens_per_second": tps,
            "hourly_counts": _hourly_counts(records),
        },
    }


def _context_summary(last: dict[str, Any] | None, *, window_tokens: int) -> dict[str, Any]:
    input_tokens = _num(last, "input_tokens") if last else None
    output_tokens = _num(last, "output_tokens") if last else None
    total = None
    if input_tokens is not None or output_tokens is not None:
        total = int((input_tokens or 0) + (output_tokens or 0))
    return {
        "last_request_tokens": total,
        "window_tokens": window_tokens,
        "fill": round(min(total / window_tokens, 1.0), 4) if total is not None else None,
        "source": "last completed request input_tokens + output_tokens",
    }


def _hourly_counts(records: list[dict[str, Any]]) -> list[int]:
    counts = Counter()
    for record in records:
        ts = record.get("ts")
        if isinstance(ts, str):
            try:
                counts[datetime.fromisoformat(ts).hour] += 1
            except ValueError:
                pass
    return [counts[h] for h in range(24)]


def _roster_rows(roster: Roster, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        task = record.get("task_type")
        if isinstance(task, str):
            by_task[task].append(record)

    rows: list[dict[str, Any]] = []
    for task_type, entry in roster.items():
        task_records = by_task.get(task_type, [])
        latencies = [v for r in task_records if (v := _num(r, "latency_ms")) is not None]
        rows.append(
            {
                "task_type": task_type,
                "model": entry.model,
                "request_count": len(task_records),
                "p50_latency_ms": int(median(latencies)) if latencies else None,
                "error_count": sum(1 for r in task_records if r.get("error")),
                "notes": entry.notes,
            }
        )
    return rows


def _last_requests(records: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    return [
        {
            "ts": r.get("ts"),
            "request_id": r.get("request_id"),
            "task_type": r.get("task_type"),
            "model": r.get("model"),
            "latency_ms": r.get("latency_ms"),
            "ttft_ms": r.get("ttft_ms"),
            "input_tokens": r.get("input_tokens"),
            "output_tokens": r.get("output_tokens"),
            "error": r.get("error"),
        }
        for r in records[-limit:][::-1]
    ]


def _vault_stats(vault: Path, allotted_bytes: int) -> dict[str, Any]:
    files = [p for p in vault.rglob("*") if p.is_file()] if vault.is_dir() else []
    bytes_used = sum(_safe_size(path) for path in files)
    md_files = [p for p in files if p.suffix.lower() == ".md"]
    entity_count = _count_md(vault / "entities")
    project_count = _count_md(vault / "projects")
    last_write = _last_vault_write(files)
    zones = _zone_counts(md_files)
    fill = min(bytes_used / allotted_bytes, 1.0) if allotted_bytes > 0 else 0.0
    return {
        "vault_path": str(vault),
        "vault_available": vault.is_dir(),
        "vault_bytes": bytes_used,
        "vault_allotted_bytes": allotted_bytes,
        "fill": round(fill, 4),
        "note_count": len(md_files),
        "entity_count": entity_count,
        "project_count": project_count,
        "zones": zones,
        "active_zone_index": _active_zone_index(zones),
        "active_zone_source": "largest vault note-count zone",
        "last_vault_write": last_write,
    }


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _count_md(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.glob("*.md") if path.is_file())


def _last_vault_write(files: list[Path]) -> dict[str, Any] | None:
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    return {
        "path": str(latest),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "ok": True,
    }


def _last_vault_write_from_records(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for record in reversed(records):
        vault_write = record.get("vault_write")
        if isinstance(vault_write, dict):
            return {
                "path": vault_write.get("path"),
                "modified_at": record.get("ts"),
                "ok": bool(vault_write.get("ok")),
                "error": vault_write.get("error"),
                "request_id": record.get("request_id"),
            }
    return None


def _zone_counts(md_files: list[Path]) -> list[dict[str, Any]]:
    counts = {name: 0 for name, _ in _ZONE_RULES}
    for path in md_files:
        text = "/".join(path.parts).lower()
        matched = False
        for name, needles in _ZONE_RULES:
            if any(needle in text for needle in needles):
                counts[name] += 1
                matched = True
                break
        if not matched:
            counts["Delphi herself"] += 1
    return [{"name": name, "count": counts[name]} for name, _ in _ZONE_RULES]


def _active_zone_index(zones: list[dict[str, Any]]) -> int:
    if not zones:
        return 0
    return max(range(len(zones)), key=lambda idx: int(zones[idx].get("count") or 0))


async def _probe_inference(ollama: OllamaClient) -> dict[str, Any]:
    try:
        models = await ollama.list_models()
    except OllamaError as exc:
        return {"status": "fault", "model_count": 0, "detail": str(exc)}
    model_count = len(models)
    return {
        "status": "ok",
        "model_count": model_count,
        "detail": f"{model_count} model{'s' if model_count != 1 else ''} available",
        "models": models,
    }


def _service_cards(
    *,
    inference: dict[str, Any],
    arq_pool: Any,
    vault: dict[str, Any],
    cfg: Config,
) -> list[dict[str, Any]]:
    worker_ok = cfg.worker_enabled and arq_pool is not None
    return [
        {"id": "caddy", "name": "Caddy", "status": "ok", "detail": "serving this UI"},
        {"id": "gateway", "name": "Gateway", "status": "ok", "detail": "healthz ok"},
        {
            "id": "worker",
            "name": "Worker",
            "status": "ok" if worker_ok else "not_configured",
            "detail": "queue connected" if worker_ok else "inline persistence or unavailable",
        },
        {
            "id": "redis",
            "name": "Redis",
            "status": "ok" if arq_pool is not None else "not_configured",
            "detail": cfg.redis_url if arq_pool is not None else "no active queue pool",
        },
        {
            "id": "inference",
            "name": "Inference",
            "status": inference["status"],
            "detail": inference["detail"],
        },
        {
            "id": "vault",
            "name": "Vault",
            "status": "ok" if vault["vault_available"] else "fault",
            "detail": f"{vault['note_count']} notes",
        },
        {
            "id": "whisper",
            "name": "Whisper",
            "status": "idle" if cfg.speech_to_text_enabled else "not_configured",
            "detail": cfg.speech_to_text_model if cfg.speech_to_text_enabled else "disabled",
        },
    ]


def _practice_summary(vault: Path) -> dict[str, Any]:
    vocab_dir = vault / "knowledge" / "gre" / "vocab"
    vocab_count = _count_md(vocab_dir)
    return {
        "vocab_card_count": vocab_count,
        "due_cards": None,
        "accuracy_percent": None,
        "streak_days": None,
        "source": "vault vocabulary files; SRS scheduling is not built yet",
    }


def _cue_cards(
    *,
    vault: dict[str, Any],
    records: list[dict[str, Any]],
    roster: Roster,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if vault["fill"] >= 0.75:
        cards.append(
            {
                "kind": "memory",
                "title": "Vault bitspace is nearing its configured allotment",
                "detail": f"{vault['fill']:.0%} full",
            }
        )
    failures = [r for r in records if r.get("error")]
    if failures:
        cards.append(
            {
                "kind": "system",
                "title": "Request failures today",
                "detail": f"{len(failures)} failed request{'s' if len(failures) != 1 else ''}",
            }
        )
    if len(set(roster.all_models())) == 1:
        cards.append(
            {
                "kind": "routing",
                "title": "All routes currently point at one model",
                "detail": next(iter(roster.all_models()), "no model"),
            }
        )
    return cards


def _not_built_yet() -> list[str]:
    return [
        "SRS due-card scheduling and streak calculation",
        "Semantic vault graph links",
        "Per-request retrieved-note discipline logging",
        "Tool-call trace chips in request telemetry",
        "Per-client roster pinning UI",
    ]
