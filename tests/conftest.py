"""Shared fixtures. Sets the minimum env so Config() builds without a .env."""

from __future__ import annotations

import os

os.environ.setdefault("DELPHI_BEARER_TOKEN", "test-token-do-not-use-in-prod")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", "/tmp/delphi-test-vault")  # noqa: S108
os.environ.setdefault("LOG_DIR", "/tmp/delphi-test-logs")  # noqa: S108
# Tests don't have a real Ollama. Lifespan boot probes would fail otherwise.
os.environ.setdefault("BOOT_PROBE_ENABLED", "false")
