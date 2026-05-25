"""FastAPI ``Depends`` factories pulling shared components off ``app.state``.

In production the lifespan in ``main.py`` populates these. In tests, fixtures
build a minimal app and assign the same attributes — so routes don't care
which path got them there.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from memory.entities import EntityIndex
from memory.vault import VaultWriter
from memory.vault_reader import VaultReader
from proxy.ollama_client import OllamaClient
from routing.classifier import Classifier
from routing.roster import Roster
from telemetry.logger import RequestLogger
from telemetry.metrics import Metrics


def get_classifier(request: Request) -> Classifier:
    return request.app.state.classifier


def get_roster(request: Request) -> Roster:
    return request.app.state.roster


def get_ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


def get_vault(request: Request) -> VaultWriter:
    return request.app.state.vault


def get_request_logger(request: Request) -> RequestLogger:
    return request.app.state.request_logger


def get_entity_index(request: Request) -> EntityIndex:
    return request.app.state.entity_index


def get_vault_reader(request: Request) -> VaultReader | None:
    """The read-only vault reader, or ``None`` when unset (minimal test apps).

    Returns ``None`` rather than raising so the chat route can skip the
    vault-query agent and fall back to a normal completion.
    """
    return getattr(request.app.state, "vault_reader", None)


def get_metrics(request: Request) -> Metrics:
    return request.app.state.metrics


def get_arq_pool(request: Request) -> Any:
    """The persist-queue pool, or ``None`` when the worker is disabled/unreachable.

    Returns ``None`` rather than raising so the chat route can fall back to
    inline persist without special-casing missing state.
    """
    return getattr(request.app.state, "arq_pool", None)
