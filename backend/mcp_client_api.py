"""
External MCP server routes (Phase 41): add, edit and delete the owner's servers.

Every route sits behind require_api_key and this module is the only writer of
server config (D-06): no chat or MCP tool reaches it. Secrets (header values, env
values, the URL query) are masked on every read and a masked value sent back keeps
the stored secret (D-04). Test lists a server's tools and stores nothing but a
changed-tool count; Enable echoes the hash of the list the owner saw and answers
409 if the live list differs (D-09), so approval binds to exactly what was
reviewed. A local (stdio) command needs the owner's explicit tick
on the server, not only in the UI (A-01). Audit rows hold names, counts and hashes
only, never a secret or a full URL, and are written in the same commit as the change.
"""

import asyncio
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend import ext_calls, mcp_client, settings
from backend.auth import require_api_key
from backend.db import get_session, get_session_sync
from backend.models import AuditLog, McpServer, Thread, ThreadMcpServer
from backend.schemas import (
    ExtDecisionIn, McpEnableIn, McpPolicyIn, McpServerCreate, McpServerOut, McpServerUpdate, McpTestOut,
    ThreadServersIn,
)

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


# ── test, hash-bound enable, tool policy ────────────────────────────────────

def _snapshot(server_id: uuid.UUID):
    with get_session_sync() as db:
        row = _get(db, server_id)
        return mcp_client.spec_from_row(row), list(row.approved_tools or []), dict(row.tool_policies or {})


async def _live_tools(server_id: uuid.UUID):
    """(spec, approved_tools, policies, live tools). Errors carry fixed copy and the
    exception class only, never exception text or a URL (Pitfall 8)."""
    spec, approved, policies = await asyncio.to_thread(_snapshot, server_id)
    client = None
    try:
        client = await mcp_client.open_client(spec)
        tools = await mcp_client.list_server_tools(client)
    except mcp_client.TooManyTools:
        raise HTTPException(422, f"This server offers more than {mcp_client.MAX_TOOLS} tools.") from None
    except Exception as e:  # ExtUnavailable, a protocol error, a launcher ValueError: never a 500
        cls = getattr(e, "error_class", "") or type(e).__name__
        raise HTTPException(502, f"Couldn't connect ({cls})") from None
    finally:
        if client is not None:
            await mcp_client.close_client(client)
    return spec, approved, policies, tools


def _tool_status(t, known: dict) -> str:
    if t.name not in known:
        return "new"
    return "unchanged" if known[t.name] == mcp_client.tool_sha(t) else "changed"


def _store_changed_count(server_id: uuid.UUID, n: int) -> None:
    with get_session_sync() as db:
        row = db.get(McpServer, server_id)
        if row is not None:  # deleted while we were connecting
            row.changed_count = n
            db.commit()


@router.post("/mcp-servers/{server_id}/test", response_model=McpTestOut,
             dependencies=[Depends(require_api_key)])
async def test_server(server_id: uuid.UUID):
    spec, approved, policies, tools = await _live_tools(server_id)
    known = {a["name"]: a["sha256"] for a in approved}
    out = []
    for t in tools:
        ann = t.annotations.model_dump(exclude_none=True) if t.annotations is not None else None
        out.append({
            "name": t.name, "description": t.description or "", "input_schema": t.inputSchema,
            "annotations": ann or None, "usable_name": mcp_client.ext_name(spec.slug, t.name) is not None,
            "status": _tool_status(t, known),
        })
    if approved:  # the only write: a cache of how many tools need a second look (PC-16)
        await asyncio.to_thread(_store_changed_count, server_id, sum(o["status"] != "unchanged" for o in out))
    return {
        "tools_hash": mcp_client.tools_hash(tools), "tools": out,
        "removed": sorted(set(known) - {t.name for t in tools}), "policies": policies,
    }


def _set_enabled(server_id: uuid.UUID, tools=None, digest=None) -> dict:
    """tools None = disable. Setting and audit row share one commit."""
    with get_session_sync() as db:
        row = _get(db, server_id)
        row.updated_at = datetime.now(timezone.utc)
        if tools is None:
            db.add(AuditLog(entity="mcp_server", entity_id=None, operation="disable",
                            before={"slug": row.slug, "enabled": row.enabled},
                            after={"slug": row.slug, "enabled": False}))
            row.enabled = False
        else:
            row.approved_tools = [
                {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema,
                 "sha256": mcp_client.tool_sha(t)} for t in tools
            ]
            row.enabled, row.changed_count = True, 0
            db.add(AuditLog(entity="mcp_server", entity_id=None, operation="enable", before=None,
                            after={"slug": row.slug, "tools_hash": digest, "tool_count": len(tools)}))
        db.commit()
        return _out(row)


@router.put("/mcp-servers/{server_id}/enabled", response_model=McpServerOut,
            dependencies=[Depends(require_api_key)])
async def set_enabled(server_id: uuid.UUID, body: McpEnableIn):
    if not body.enabled:
        return await asyncio.to_thread(_set_enabled, server_id)
    if not body.tools_hash:
        raise HTTPException(422, "Test the server and review its tools first.")
    *_, tools = await _live_tools(server_id)
    digest = mcp_client.tools_hash(tools)
    if digest != body.tools_hash:
        raise HTTPException(409, "This server's tools changed after you opened this list. Review them again.")
    return await asyncio.to_thread(_set_enabled, server_id, tools, digest)


@router.put("/mcp-servers/{server_id}/tools/{tool}", dependencies=[Depends(require_api_key)])
def set_policy(server_id: uuid.UUID, tool: Annotated[str, Path(min_length=1, max_length=128)],
               body: McpPolicyIn, db: Session = Depends(get_session)):
    """Per tool only; there is no per-server Always (D-18)."""
    row = _get(db, server_id)
    policies = dict(row.tool_policies or {})
    old = policies.get(tool, "ask")
    policies[tool] = body.policy
    row.tool_policies = policies  # a new dict: in-place JSONB mutation is not tracked
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditLog(entity="mcp_server", entity_id=None, operation="policy",
                    before={"tool": tool, "policy": old},
                    after={"slug": row.slug, "tool": tool, "policy": body.policy}))
    db.commit()
    return {"tool": tool, "policy": body.policy}


# ── per-thread selection ────────────────────────────────────────────────────

@router.put("/threads/{thread_id}/mcp-servers", dependencies=[Depends(require_api_key)])
def set_thread_servers(thread_id: uuid.UUID, body: ThreadServersIn, db: Session = Depends(get_session)):
    """Replace the thread's external servers; applies from the next turn (PC-17: no audit row)."""
    if db.get(Thread, thread_id) is None:
        raise HTTPException(404, "Thread not found")
    ids = list(dict.fromkeys(body.server_ids))
    for sid in ids:
        if db.get(McpServer, sid) is None:  # explicit: a missing FK would leak a 500
            raise HTTPException(422, "Unknown MCP server.")
    db.execute(delete(ThreadMcpServer).where(ThreadMcpServer.thread_id == thread_id))
    db.add_all(ThreadMcpServer(thread_id=thread_id, server_id=sid) for sid in ids)
    db.commit()
    return {"server_ids": ids}


def _sweep_orphans(thread_id: uuid.UUID, active_turn: str | None) -> None:
    with get_session_sync() as db:
        ext_calls.sweep_thread(db, thread_id, active_turn)


@router.post("/threads/{thread_id}/ext-calls/{call_id}", dependencies=[Depends(require_api_key)])
async def decide_ext_call(thread_id: uuid.UUID, call_id: uuid.UUID, body: ExtDecisionIn):
    """Allow or deny a waiting external call. Async because the waiter's Event must be set
    on the loop thread (Pitfall 4). Not on the approver allowlist: the owner decides in
    the app (D-14). The first answer wins; a replay, an expired call or a call whose turn
    is no longer running answers 409."""
    from backend import query

    row = await asyncio.to_thread(ext_calls.read_call, call_id)
    if row is None or row["thread_id"] != thread_id:
        raise HTTPException(404, "Call not found.")
    run = query._ACTIVE.get(str(thread_id))
    if run is None or run.id != str(row["turn_id"]):
        await asyncio.to_thread(_sweep_orphans, thread_id, run.id if run else None)
        raise HTTPException(409, "This turn is no longer running.")
    value = await asyncio.to_thread(ext_calls.decide, thread_id, call_id, body.approve)
    if value is None:
        raise HTTPException(409, "That request was already answered or has expired.")
    ext_calls.wake(call_id)
    return {"approval": value}
