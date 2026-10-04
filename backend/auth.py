"""
Backend authentication — API-key guard for state-changing endpoints.

Env vars:
  MONAI_API_KEY   Required. Static API key that write endpoints validate against.
                  Must be set (non-empty) before starting the server; if unset,
                  require_api_key raises HTTPException(503) (fail-closed — no
                  silent open writes are possible with a misconfigured deployment).
  MONAI_APPROVER_KEY
                  Optional. Approves or rejects any pending proposal whatever its
                  channel (APPR-01). Must differ from MONAI_API_KEY and must never
                  go into any MCP client config (MCP clients hold MONAI_API_KEY).
                  Unset, or equal to MONAI_API_KEY, makes the approver routes
                  answer 503 (fail-closed).

Usage:
  Attach to write routes via dependencies=[Depends(require_api_key)].
  Read-only routes and POST /query-stream intentionally omit this dependency (D-06).
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

# Second secret for approving/rejecting proposals across channels (D-15).
# Read at call time through the module global (tests monkeypatch it).
_APPROVER_HEADER = APIKeyHeader(name="MONAI_APPROVER_KEY", auto_error=False)
_CONFIGURED_APPROVER_KEY: str = os.environ.get("MONAI_APPROVER_KEY", "")


def key_ok(key: str | None) -> bool:
    """
    Constant-time API-key check — the single comparison shared by
    require_api_key (FastAPI dependency, write routes) and the /mcp auth
    middleware (backend/main.py). One secret, one check (D-04).

    Returns True only when _CONFIGURED_KEY is set AND key is not None AND
    hmac.compare_digest(key, _CONFIGURED_KEY) is True. Never logs the key.
    """
    return bool(_CONFIGURED_KEY) and key is not None and hmac.compare_digest(key.encode(), _CONFIGURED_KEY.encode())


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


def _approver_configured() -> bool:
    """Approver key is usable only when set and distinct from MONAI_API_KEY."""
    return bool(_CONFIGURED_APPROVER_KEY) and _CONFIGURED_APPROVER_KEY != _CONFIGURED_KEY


def approver_key_ok(key: str | None) -> bool:
    """Constant-time approver-key check. Never logs the key."""
    return (
        _approver_configured()
        and key is not None
        and hmac.compare_digest(key.encode(), _CONFIGURED_APPROVER_KEY.encode())
    )


def require_approver_key(approver_key: str | None = Security(_APPROVER_HEADER)) -> None:
    """Dependency for approver-only routes (D-15).

    Raises 503 when MONAI_APPROVER_KEY is unset or equals MONAI_API_KEY
    (fail-closed), 401 when the header is missing or wrong. MONAI_API_KEY alone
    never satisfies it.
    """
    if not _approver_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Server misconfigured: MONAI_APPROVER_KEY is unset or equals MONAI_API_KEY; "
                "generate a separate key with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            ),
        )
    if not approver_key_ok(approver_key):
        raise HTTPException(status_code=401, detail="Invalid or missing approver key")


def optional_approver(approver_key: str | None = Security(_APPROVER_HEADER)) -> bool:
    """True when the request carries a valid approver key; never raises (code visibility)."""
    return approver_key_ok(approver_key)


def require_reject_scope(
    api_key: str | None = Security(_API_KEY_HEADER),
    approver_key: str | None = Security(_APPROVER_HEADER),
) -> str:
    """Return "approver" or "chat" scope for /reject.

    A present approver header is validated strictly and never falls back to
    API-key scope (D-17): a wrong approver header is 401 even with a valid API key.
    """
    if approver_key is not None:
        require_approver_key(approver_key)
        return "approver"
    require_api_key(api_key)
    return "chat"
