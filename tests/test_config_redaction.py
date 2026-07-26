from __future__ import annotations

from config import Config


def test_redacted_masks_secret_like_config_values() -> None:
    cfg = Config(  # type: ignore[call-arg]
        delphi_bearer_token="bearer-secret",
        ollama_api_key="ollama-secret",
        ntfy_token="ntfy-secret",
    )

    redacted = cfg.redacted()

    assert redacted["delphi_bearer_token"] == "bear…<redacted>"
    assert redacted["ollama_api_key"] == "olla…<redacted>"
    assert redacted["ntfy_token"] == "ntfy…<redacted>"
    assert "secret" not in str(redacted)
