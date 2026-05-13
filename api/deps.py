"""FastAPI ``Depends`` factories pulling shared components off ``app.state``.

In production the lifespan in ``main.py`` populates these. In tests, fixtures
build a minimal app and assign the same attributes — so routes don't care
which path got them there.
"""

from __future__ import annotations

from fastapi import Request

from memory.entities import EntityIndex
from memory.vault import VaultWriter
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


def get_metrics(request: Request) -> Metrics:
    return request.app.state.metrics
