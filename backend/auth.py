"""
Backend authentication — API-key guard for state-changing endpoints.

Env vars:
  MONAI_API_KEY   Required. Static API key that write endpoints validate against.
                  Must be set (non-empty) before starting the server; if unset,
                  require_api_key raises HTTPException(503) (fail-closed — no
                  silent open writes are possible with a misconfigured deployment).

Usage:
  Attach to write routes via dependencies=[Depends(require_api_key)].
  Read-only routes and POST /query intentionally omit this dependency (D-06).
"""

import hmac
import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

# Header name the client must include on write requests.
_API_KEY_HEADER = APIKeyHeader(name="MONAI_API_KEY", auto_error=False)

# Configured key, read once at import time.
# auto_error=False above means FastAPI will pass None instead of raising 403
# when the header is absent, so we can return a consistent 401 ourselves.
_CONFIGURED_KEY: str = os.environ.get("MONAI_API_KEY", "")


def key_ok(key: str | None) -> bool:
    """
    Constant-time API-key check — the single comparison shared by
    require_api_key (FastAPI dependency, write routes) and the /mcp auth
    middleware (backend/main.py). One secret, one check (D-04).

    Returns True only when _CONFIGURED_KEY is set AND key is not None AND
    hmac.compare_digest(key, _CONFIGURED_KEY) is True. Never logs the key.
    """
    return bool(_CONFIGURED_KEY) and key is not None and hmac.compare_digest(key, _CONFIGURED_KEY)


def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    FastAPI dependency that enforces API-key authentication on write endpoints.

    Raises:
        HTTPException(503): if MONAI_API_KEY env var is unset/empty (fail-closed guard).
        HTTPException(401): if the header is absent or the value does not match.

    Returns None on success (side-effect only; callers do not use the return value).
    """
    if not _CONFIGURED_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "Server misconfigured: MONAI_API_KEY env var is not set — "
                "generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" "
                "and set it before starting the server"
            ),
        )

    if not key_ok(api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
