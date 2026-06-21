"""
Backend authentication — API-key guard for state-changing endpoints.

Env vars:
  MONAI_API_KEY   Required. Static API key that write endpoints validate against.
                  Must be set (non-empty) before starting the server; if unset,
                  require_api_key raises RuntimeError (fail-closed — no silent
                  open writes are possible with a misconfigured deployment).

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


def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    FastAPI dependency that enforces API-key authentication on write endpoints.

    Raises:
        RuntimeError: if MONAI_API_KEY env var is unset/empty (fail-closed guard).
        HTTPException(401): if the header is absent or the value does not match.

    Returns None on success (side-effect only; callers do not use the return value).
    """
    if not _CONFIGURED_KEY:
        raise RuntimeError(
            "MONAI_API_KEY env var is not set. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it in your environment / docker-compose before starting the server."
        )

    if api_key is None or not hmac.compare_digest(api_key, _CONFIGURED_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
