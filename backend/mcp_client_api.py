"""
External MCP server routes (Phase 41): add, edit and delete the owner's servers.

Every route sits behind require_api_key and this module is the only writer of
server config (D-06): no chat or MCP tool reaches it. Secrets (header values, env
values, the URL query) are masked on every read and a masked value sent back keeps
the stored secret (D-04). A local (stdio) command needs the owner's explicit tick
on the server, not only in the UI (A-01). Audit rows hold names, counts and hashes
only, never a secret or a full URL, and are written in the same commit as the change.
"""

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import mcp_client, settings
from backend.auth import require_api_key
from backend.db import get_session
from backend.models import AuditLog, McpServer
from backend.schemas import McpServerCreate, McpServerOut, McpServerUpdate

router = APIRouter()

MASK = "••••"
_HEADER_NAME_RE = r"^[A-Za-z0-9-]{1,64}$"


def _validate(transport, url, headers: dict, command, args, env: dict) -> None:
    """Plain ValueError messages; the routes turn them into 422."""
    if transport == "stdio":
        if command not in mcp_client.ALLOWED_COMMANDS:
            raise ValueError("A local command must be npx or uvx.")
        if not args:
            raise ValueError("A local command needs at least one argument.")
        if url or headers:
            raise ValueError("A local command takes no URL or headers.")
        for name in env:
            if not mcp_client.env_name_allowed(name):
                raise ValueError(f"The environment variable name {name} is not allowed.")
        return
    if command or args or env:
        raise ValueError("A URL server takes no command, arguments or environment.")
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter an http or https URL.")
    if "@" in parts.netloc:
        raise ValueError("Put credentials in a header, not in the URL.")
    for name in headers:
        if not re.match(_HEADER_NAME_RE, name):
            raise ValueError(f"The header name {name} is not valid.")


def _merge_secrets(old: dict, rows) -> dict:
    """A masked value keeps the stored one; any other replaces; unsent names are dropped (D-04)."""
    out = {}
    for r in rows:
        if r.value.startswith(MASK):
            if r.name not in old:
                raise ValueError(f"{r.name} has no stored value to keep.")
            out[r.name] = old[r.name]
        else:
            out[r.name] = r.value
    return out


def _mask_url(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query=MASK)) if parts.query else url


def _out(row: McpServer) -> dict:
    return {
        "id": row.id, "slug": row.slug, "transport": row.transport,
        "url": _mask_url(row.url),
        "destination": mcp_client.destination(mcp_client.spec_from_row(row)),
        "command": row.command, "args": list(row.args or []),
        "headers": [{"name": k, "value_masked": settings.mask_key(v)} for k, v in (row.headers or {}).items()],
        "env": [{"name": k, "value_masked": settings.mask_key(v)} for k, v in (row.env or {}).items()],
        "enabled": row.enabled, "changed_count": row.changed_count,
    }


def _audit_view(row: McpServer, ack=None) -> dict:
    """Names and counts only: never a value, never the URL (D-04, D-08)."""
    view = {
        "slug": row.slug, "transport": row.transport,
        "destination": mcp_client.destination(mcp_client.spec_from_row(row)),
        "command": row.command, "arg_count": len(row.args or []),
        "header_names": sorted(row.headers or {}), "env_names": sorted(row.env or {}),
    }
    if ack is not None:
        view["acknowledged_local_read"] = ack
    return view


def _get(db: Session, server_id: uuid.UUID) -> McpServer:
    row = db.get(McpServer, server_id)
    if row is None:
        raise HTTPException(404, "No such server")
    return row


@router.get("/mcp-servers", response_model=list[McpServerOut], dependencies=[Depends(require_api_key)])
def list_servers(db: Session = Depends(get_session)):
    return [_out(r) for r in db.execute(select(McpServer).order_by(McpServer.slug)).scalars()]


@router.post("/mcp-servers", status_code=201, response_model=McpServerOut,
             dependencies=[Depends(require_api_key)])
def create_server(body: McpServerCreate, db: Session = Depends(get_session)):
    try:
        headers = _merge_secrets({}, body.headers)
        env = _merge_secrets({}, body.env)
        _validate(body.transport, body.url, headers, body.command, body.args, env)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if db.execute(select(McpServer.id).where(McpServer.slug == body.slug)).first():
        raise HTTPException(422, "That short name is already used.")
    if body.transport == "stdio" and not body.acknowledged_local_read:
        raise HTTPException(422, "Tick the acknowledgement to add a local command.")
    row = McpServer(
        slug=body.slug, transport=body.transport, url=body.url, headers=headers,
        command=body.command, args=list(body.args), env=env, enabled=False,
    )
    db.add(row)
    db.add(AuditLog(entity="mcp_server", entity_id=None, operation="create", before=None,
                    after=_audit_view(row, body.acknowledged_local_read if body.transport == "stdio" else None)))
    db.commit()
    return _out(row)


@router.put("/mcp-servers/{server_id}", response_model=McpServerOut,
            dependencies=[Depends(require_api_key)])
def update_server(server_id: uuid.UUID, body: McpServerUpdate, db: Session = Depends(get_session)):
    row = _get(db, server_id)
    before = _audit_view(row)
    try:
        url = body.url if body.url is not None else row.url
        command = body.command if body.command is not None else row.command
        args = list(body.args) if body.args is not None else list(row.args or [])
        headers = (_merge_secrets(row.headers or {}, body.headers)
                   if body.headers is not None else dict(row.headers or {}))
        env = (_merge_secrets(row.env or {}, body.env)
               if body.env is not None else dict(row.env or {}))
        _validate(row.transport, url, headers, command, args, env)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    ack_needed = row.transport == "stdio" and (command != row.command or args != list(row.args or []))
    if ack_needed and not body.acknowledged_local_read:
        raise HTTPException(422, "Tick the acknowledgement to change a local command.")
    # New objects: in-place JSONB mutation is not tracked.
    row.url, row.command, row.args, row.headers, row.env = url, command, args, headers, env
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditLog(entity="mcp_server", entity_id=None, operation="update", before=before,
                    after=_audit_view(row, body.acknowledged_local_read if ack_needed else None)))
    db.commit()
    return _out(row)


@router.delete("/mcp-servers/{server_id}", dependencies=[Depends(require_api_key)])
def delete_server(server_id: uuid.UUID, db: Session = Depends(get_session)):
    row = _get(db, server_id)
    slug = row.slug
    db.add(AuditLog(entity="mcp_server", entity_id=None, operation="delete",
                    before=_audit_view(row), after={"slug": slug}))
    db.delete(row)
    db.commit()
    return {"deleted": slug}
