"""Typed configuration loaded from environment / .env.

See CLAUDE.md → Configuration for the source of truth on every variable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Runtime configuration. Built once at process start."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Required ---
    delphi_bearer_token: str = Field(..., min_length=1)
    # Inference backend. Local Ollama (``http://localhost:11434``) for a GPU box,
    # or Ollama Cloud (``https://ollama.com``) when the host has no GPU — set
    # ``OLLAMA_API_KEY`` and point this at the cloud URL. Same wire protocol; the
    # only difference is the bearer header the proxy attaches.
    ollama_base_url: str = "http://localhost:11434"
    # Bearer token for Ollama Cloud. Empty for a local Ollama (no auth needed).
    ollama_api_key: str = ""
    obsidian_vault_path: str = ""
    log_dir: str = "/var/log/delphi"
    timezone: str = "America/Chicago"

    # --- Optional ---
    classify_enabled: bool = True
    memory_enabled: bool = True
    entity_create_threshold: int = 2

    # --- Worker / queue ---
    # The persist pipeline (entity extraction, vault write, JSONL log, metrics)
    # runs out-of-process on the worker, fed by a Redis-backed arq queue. When
    # ``worker_enabled`` is false (tests, single-process dev) the gateway runs
    # persist inline — the historical behavior. When true but Redis is
    # unreachable, the gateway falls back to inline persist (fail-open: the API
    # contract is sacred, memory is best-effort).
    worker_enabled: bool = False
    redis_url: str = "redis://localhost:6379"
    # Port the worker exposes its Prometheus registry on (normal-path metrics).
    # The gateway keeps :DELPHI_PORT/metrics for the inline fallback path.
    worker_metrics_port: int = 9100

    # --- Models (per task type) ---
    # Override any of these in .env to swap the model serving a task type
    # without code changes. ``routing.roster.Roster.from_config`` reads these.
    delphi_model_chat: str = "phi4:14b"
    delphi_model_code: str = "qwen2.5-coder:14b"
    delphi_model_reason: str = "deepseek-r1:14b"
    delphi_model_multilingual: str = "gemma3:12b"
    delphi_model_deep_code: str = "qwen2.5-coder:32b"
    delphi_model_deep_reason: str = "deepseek-r1:32b"
    delphi_model_vault_query: str = "phi4:14b"
    delphi_model_classifier: str = "phi3.5:3.8b"

    # When false, ``main.py``'s lifespan skips Ollama/vault probes. Used by
    # tests and by ad-hoc dev runs without a local Ollama running. CLAUDE.md
    # mandates fail-fast probes in production — leave this true there.
    boot_probe_enabled: bool = True

    # --- Server bind ---
    # Aliased to ``DELPHI_HOST`` / ``DELPHI_PORT`` so they don't collide with
    # the famously contended bare ``PORT`` env var (Heroku, Cloud Run, and
    # several IDE "Run server" hooks all export it, which silently overrides
    # this service's ``.env`` until we namespace the field).
    host: str = Field(default="0.0.0.0", validation_alias="DELPHI_HOST")
    port: int = Field(default=8090, validation_alias="DELPHI_PORT")

    @field_validator("obsidian_vault_path", "log_dir")
    @classmethod
    def _expand_user(cls, v: str) -> str:
        """Expand a leading ``~`` to the user's home.

        Without this, ``OBSIDIAN_VAULT_PATH=~/vault`` is read as a *relative*
        path and the vault writer creates a literal ``~`` directory under the
        process CWD instead of writing to the home dir. Empty stays empty (it
        signals "unset" to tests and the boot probe).
        """
        return str(Path(v).expanduser()) if v else v

    def redacted(self) -> dict[str, object]:
        """Dump config for boot logging with the bearer token masked."""
        data = self.model_dump()
        token = data.get("delphi_bearer_token", "")
        if isinstance(token, str) and token:
            data["delphi_bearer_token"] = f"{token[:4]}…<redacted>"
        return data


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Cached config accessor. Tests override via dependency_overrides."""
    return Config()  # type: ignore[call-arg]
