"""Tests for the bearer-token dependency.

We mount the dependency on a tiny test app rather than threading it through
``main.app`` so this file can exercise auth in isolation.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth.bearer import require_bearer
from config import Config, get_config


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()

    @test_app.get("/protected", dependencies=[Depends(require_bearer)])
    def protected() -> dict[str, str]:
        return {"ok": "yes"}

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # Force a known token for these tests, independent of the env-derived default.
    app.dependency_overrides[get_config] = lambda: Config(  # type: ignore[call-arg]
        delphi_bearer_token="s3cret-token",
        obsidian_vault_path="/tmp/v",  # noqa: S108
        log_dir="/tmp/l",  # noqa: S108
    )
    return TestClient(app)


def test_missing_header_returns_401(client: TestClient) -> None:
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    # Detail must not leak the expected token or any other internal info.
    assert "s3cret-token" not in response.text


def test_malformed_header_returns_401(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": "Token s3cret-token"})
    assert response.status_code == 401


def test_wrong_token_returns_401(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_empty_token_returns_401(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


def test_correct_token_passes(client: TestClient) -> None:
    response = client.get("/protected", headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 200
    assert response.json() == {"ok": "yes"}
