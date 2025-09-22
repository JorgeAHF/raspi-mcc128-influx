"""Authentication helpers for the web API."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _token_from_file(path: str) -> Optional[str]:
    """Return the contents of ``path`` if it exists, otherwise ``None``."""

    try:
        with open(path, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:  # pragma: no cover - defensive best effort
        raise RuntimeError(f"No se pudo leer el token desde {path}: {exc}") from exc
    return token or None


def _expected_token() -> Optional[str]:
    """Lookup the configured bearer token."""

    token = os.environ.get("EDGE_WEBAPI_TOKEN")
    if token:
        return token.strip() or None
    token_file = os.environ.get("EDGE_WEBAPI_TOKEN_FILE")
    if token_file:
        return _token_from_file(token_file)
    return None


async def require_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Validate the Bearer token when authentication is enabled."""

    expected = _expected_token()
    if not expected:
        # Authentication disabled -> accept every request.
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.scheme.lower() != "bearer" or credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

