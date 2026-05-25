"""Queue wiring shared by the gateway (producer) and worker (consumer).

Keeps the arq/Redis surface in one place so the gateway never imports the
worker's task functions — it only needs the job name and a pool. Swapping the
broker later (Redis → something else) means touching this module and
``worker/main.py``, nothing in ``api/``.
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

# arq dispatches jobs by function name; producer and consumer must agree on it.
PERSIST_JOB = "persist_exchange"


def redis_settings(redis_url: str) -> RedisSettings:
    """Parse the configured ``redis://`` DSN into arq connection settings."""
    return RedisSettings.from_dsn(redis_url)


async def create_persist_pool(redis_url: str) -> ArqRedis:
    """Open a connection pool the gateway uses to enqueue persist jobs.

    Raises on connection failure — the caller (gateway lifespan) treats that as
    "run persist inline" rather than crashing. Memory is best-effort.
    """
    return await create_pool(redis_settings(redis_url))
