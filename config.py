"""Typed configuration loaded from environment / .env.

See CLAUDE.md → Configuration for the source of truth on every variable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
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
    ollama_base_url: str = "http://localhost:11434"
    obsidian_vault_path: str = ""
    log_dir: str = "/var/log/delphi"
    timezone: str = "America/Chicago"

    # --- Optional ---
    classify_enabled: bool = True
    memory_enabled: bool = True
    classifier_model: str = "phi3.5:3.8b"
    default_model: str = "phi4:14b"
    entity_create_threshold: int = 2

    # When false, ``main.py``'s lifespan skips Ollama/vault probes. Used by
    # tests and by ad-hoc dev runs without a local Ollama running. CLAUDE.md
    # mandates fail-fast probes in production — leave this true there.
    boot_probe_enabled: bool = True

    # --- Server bind ---
    host: str = "0.0.0.0"
    port: int = 8080

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
