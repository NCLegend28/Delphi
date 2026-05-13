"""Bearer-token authentication dependency.

Fail closed: any missing/malformed/mismatched header → 401 with no exception
detail leaked. Constant-time comparison via ``secrets.compare_digest`` so
timing leaks can't be used to recover the token byte-by-byte.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from config import Config, get_config

_BEARER_PREFIX = "Bearer "


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_bearer(
    authorization: Annotated[str | None, Header()] = None,
    config: Annotated[Config, Depends(get_config)] = ...,  # type: ignore[assignment]
) -> None:
    """FastAPI dependency. Raises 401 unless the header matches the configured token.

    Use as ``Depends(require_bearer)`` on any non-public route. Returns ``None``
    on success — callers don't need the token value.
    """
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise _unauthorized()

    presented = authorization[len(_BEARER_PREFIX) :].strip()
    expected = config.delphi_bearer_token

    if not presented or not secrets.compare_digest(presented, expected):
        raise _unauthorized()
