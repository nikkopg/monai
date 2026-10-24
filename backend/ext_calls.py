"""
External tool call approvals and receipts (Phase 41), the Onyx pattern (D-13).

The `ext_calls` row is the truth and survives a reload: it holds what the owner
saw (args), what was decided and when, and the receipt of what happened. The
in-process Event in `_WAKE` is only a latency hint, valid because uvicorn runs
one worker (34 D-16); a waiter also re-reads the row every few seconds. Every
UPDATE that leaves 'pending' sets decided_via in the same statement (CHECK
ck_ext_decided). Audit rows carry the server, tool and an args hash, never the
args or a secret (D-22).
"""

import asyncio
import hashlib
import json
import logging
import os
import urllib.parse
import uuid
from datetime import datetime, timezone

import anyio
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend import config, mcp_client
from backend.db import get_session_sync
from backend.models import AuditLog, ExtCall

logger = logging.getLogger(__name__)

_WAKE: dict[str, asyncio.Event] = {}


def _canon(args) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def args_digest(args) -> str:
    return hashlib.sha256(_canon(args).encode()).hexdigest()


# ── policy and taint (D-18, D-19) ───────────────────────────────────────────

def effective(policy: str, ledger_touched: bool) -> tuple[str, str | None]:
    """Strictest wins: deny > ask > always. An Always tool asks once a ledger tool
    has run in the turn, because its args may now carry ledger data."""
    if policy == "deny":
        return "deny", None
    if policy == "always":
        return ("ask", "ledger_read") if ledger_touched else ("always", None)
    return "ask", None


# ── outbound guard (D-20) ───────────────────────────────────────────────────

def guard_secrets(db: Session) -> list[str]:
    """monai's own keys and the live proposal tokens and codes; read at call time."""
    found = [os.environ.get("MONAI_API_KEY", ""), os.environ.get("MONAI_APPROVER_KEY", "")]
    for token, code in db.execute(text("SELECT token, code FROM proposals WHERE status = 'pending'")):
        found += [token or "", code or ""]
    return [s for s in found if len(s) >= 8]  # shorter would match innocent text (Pitfall 9)


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def outbound_hit(args, secrets: list[str]) -> bool:
    """A secret inside the args, raw or URL-decoded, in any string or in the whole JSON."""
    hay = [_canon(args)]
    for s in _strings(args):
        hay += [s, urllib.parse.unquote(s)]
    return any(sec in h for sec in secrets for h in hay)


# ── audit ───────────────────────────────────────────────────────────────────

def _audit(db: Session, operation: str, server_slug: str, tool: str, args_sha256: str) -> None:
    db.add(AuditLog(
        entity="external_tool_call", entity_id=None, operation=operation, before=None,
        after={"server": server_slug, "tool": tool, "args_sha256": args_sha256},
    ))


# ── rows ────────────────────────────────────────────────────────────────────

_READ_FIELDS = ("id", "thread_id", "turn_id", "server_slug", "tool", "args", "args_sha256",
                "approval", "decided_via", "expires_at", "receipt", "reason")


def insert_call(*, thread_id, turn_id, conn, tool: str, args: dict, approved: bool,
                reason: str | None) -> uuid.UUID:
    """One row per call: pending with a TTL for an Ask, approved by policy for an Always."""
    digest = args_digest(args)
    ttl = config.EXT_APPROVAL_TTL_SECONDS  # read now so tests can patch it
    row = ExtCall(
        thread_id=thread_id, turn_id=turn_id, server_id=conn.server_id,
        server_slug=conn.slug, tool=tool, args=args, args_sha256=digest,
        destination=conn.destination, leaves_machine=conn.leaves_machine, reason=reason,
        approval="approved" if approved else "pending",
        decided_via="policy" if approved else None,
        decided_at=func.now() if approved else None,
        expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, ttl),
    )
    with get_session_sync() as db:
        db.add(row)
        if approved:
            _audit(db, "approved", conn.slug, tool, digest)
        db.flush()
        call_id = row.id
        db.commit()
    return call_id


def read_call(call_id) -> dict | None:
    with get_session_sync() as db:
        row = db.get(ExtCall, call_id)
        return None if row is None else {k: getattr(row, k) for k in _READ_FIELDS}


_DECIDE = text(
    "UPDATE ext_calls SET approval = :a, decided_via = 'user', decided_at = now() "
    "WHERE id = :id AND thread_id = :t AND approval = 'pending' AND expires_at > now() "
    "RETURNING server_slug, tool, args_sha256"
)


def decide(thread_id, call_id, approve: bool) -> str | None:
    """The owner's answer. One conditional UPDATE: the first writer wins, a replay, an
    expired call or another thread's call changes nothing and returns None (D-14)."""
    value = "approved" if approve else "denied"
    with get_session_sync() as db:
        row = db.execute(_DECIDE, {"a": value, "id": call_id, "t": thread_id}).first()
        if row is None:
            return None
        _audit(db, value, row.server_slug, row.tool, row.args_sha256)
        db.commit()
    return value


def _close(db: Session, where: str, params: dict, approval: str, via: str) -> list:
    """Move matching pending rows to expired or denied, one audit row each. Caller commits.
    `where` is built from constants in this module only."""
    rows = db.execute(
        text("UPDATE ext_calls SET approval = :a, decided_via = :via, decided_at = now() "
             f"WHERE approval = 'pending' AND {where} "
             "RETURNING id, server_slug, tool, args_sha256"),
        {**params, "a": approval, "via": via},
    ).all()
    for r in rows:
        _audit(db, "expired" if approval == "expired" else "denied", r.server_slug, r.tool, r.args_sha256)
    return rows


def _unknown(db: Session, where: str, params: dict) -> None:
    """A receipt still 'pending' whose call is no longer running cannot be known (D-21)."""
    db.execute(text(f"UPDATE ext_calls SET receipt = 'unknown' WHERE receipt = 'pending' AND {where}"), params)


def expire_one(call_id) -> bool:
    with get_session_sync() as db:
        rows = _close(db, "id = :id", {"id": call_id}, "expired", "expiry")
        db.commit()
    return bool(rows)


def expire_due(db: Session) -> None:
    """Expire every pending row past its TTL. Uses the caller's session and commits."""
    _close(db, "expires_at <= now()", {}, "expired", "expiry")
    db.commit()


def sweep_thread(db: Session, thread_id, active_turn: str | None) -> None:
    """Expire a thread's pending rows that no running turn is waiting on, and its stuck
    receipts. The active turn's own rows are left to its waiter (A-08). Commits."""
    where = "thread_id = :t AND (CAST(:active AS uuid) IS NULL OR turn_id <> CAST(:active AS uuid))"
    params = {"t": thread_id, "active": active_turn}
    _close(db, where, params, "expired", "expiry")
    _unknown(db, where, params)
    db.commit()


def end_run(turn_id, stopped: bool) -> list[str]:
    """A run ended: its pending rows are denied (Stop) or expired. Returns their ids so the
    caller can wake the waiters (D-15)."""
    approval, via = ("denied", "stop") if stopped else ("expired", "expiry")
    with get_session_sync() as db:
        rows = _close(db, "turn_id = :turn", {"turn": turn_id}, approval, via)
        _unknown(db, "turn_id = :turn", {"turn": turn_id})
        db.commit()
    return [str(r.id) for r in rows]


def sweep_at_boot() -> None:
    """No call survives a restart: every pending approval expires and every pending
    receipt becomes unknown (PC-14)."""
    with get_session_sync() as db:
        _close(db, "true", {}, "expired", "expiry")
        _unknown(db, "true", {})
        db.commit()


def set_receipt(call_id, receipt: str, *, result_sha256: str | None = None,
                result_bytes: int | None = None, error: str | None = None) -> None:
    """pending, then confirmed (hash and size of the result), failed (an error class) or
    unknown. Confirmed and failed are audited in the same commit (D-21, D-22)."""
    with get_session_sync() as db:
        row = db.execute(
            text("UPDATE ext_calls SET receipt = :r, result_sha256 = :h, result_bytes = :b, error = :e "
                 "WHERE id = :id RETURNING server_slug, tool, args_sha256"),
            {"r": receipt, "h": result_sha256, "b": result_bytes, "e": error, "id": call_id},
        ).first()
        if row is not None and receipt in ("confirmed", "failed"):
            _audit(db, receipt, row.server_slug, row.tool, row.args_sha256)
        db.commit()


def audit_blocked(conn, tool: str, args: dict) -> None:
    with get_session_sync() as db:
        _audit(db, "blocked", conn.slug, tool, args_digest(args))
        db.commit()


# ── wake registry (latency hint only) ───────────────────────────────────────

def wake(call_id) -> None:
    """Must run on the event loop thread: an asyncio.Event is not thread-safe."""
    ev = _WAKE.get(str(call_id))
    if ev is not None:
        ev.set()


def wake_all(ids) -> None:
    for i in ids:
        wake(i)


# ── the wrapper every external tool goes through ───────────────────────────

def _error(name: str, message: str) -> dict:
    return {"tool": name, "external": True, "error": message}


def _failed(name: str, slug: str, error_class: str) -> dict:
    """What the model sees when a call did not succeed: it can never claim success (D-21).
    Only a class name or fixed copy, never exception text (Pitfall 8)."""
    return {"tool": name, "source": f"external:{slug}", "external": True,
            "label": "external, unverified", "receipt": "failed", "error": error_class}


def _guard_hit(args) -> bool:
    with get_session_sync() as db:
        return outbound_hit(args, guard_secrets(db))


async def _await_decision(turn, conn, call_id, row: dict) -> dict:
    """Park until the row leaves 'pending'. The Event is registered before the card goes
    out; the 5 s re-read covers a lost wake and the TTL (D-13, D-15)."""
    key = str(call_id)
    ev = _WAKE[key] = asyncio.Event()
    card = {
        "type": "approval_required", "call_id": key, "server": row["server_slug"],
        "tool": row["tool"], "args": row["args"], "destination": conn.destination,
        "leaves_machine": conn.leaves_machine, "expires_at": row["expires_at"].isoformat(),
    }
    if row["reason"]:
        card["reason"] = row["reason"]
    turn.emit(card)
    turn.hold_idle()
    try:
        while row is not None and row["approval"] == "pending":
            left = (row["expires_at"] - datetime.now(timezone.utc)).total_seconds()
            if left <= 0:
                await asyncio.to_thread(expire_one, call_id)
            else:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=max(0.05, min(5, left)))
                except TimeoutError:
                    pass
                ev.clear()
            row = await asyncio.to_thread(read_call, call_id)
    finally:
        turn.release_idle()
        _WAKE.pop(key, None)
    return row


async def _receipt(turn, call_id, receipt: str, **kw) -> None:
    await asyncio.to_thread(set_receipt, call_id, receipt, **kw)
    turn.emit({"type": "ext_call", "call_id": str(call_id), "receipt": receipt,
               "error_class": kw.get("error")})


async def _send(turn, conn, tool: str, call_id, args: dict, name: str, reopen: bool) -> dict:
    """Send exactly the stored args. A call that may have been sent is never retried (A-09)."""
    if reopen:  # the session sat parked through the approval wait
        try:
            await asyncio.wait_for(conn.client.ping(), timeout=5)
        except Exception:
            try:
                same = await mcp_client.reopen(conn, tool)
            except Exception:
                same, why = False, "Unreachable"
            else:
                why = "ToolChanged"
            if not same:
                await _receipt(turn, call_id, "failed", error=why)
                return _failed(name, conn.slug, why)
    await _receipt(turn, call_id, "pending")
    try:
        res = await conn.client.call_tool(
            tool, args, timeout=config.EXT_CALL_TIMEOUT_SECONDS, raise_on_error=False)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await asyncio.to_thread(set_receipt, call_id, "unknown")
        raise
    except Exception as e:
        await _receipt(turn, call_id, "failed", error=type(e).__name__)
        return _failed(name, conn.slug, type(e).__name__)
    if res.is_error:
        await _receipt(turn, call_id, "failed", error="ToolError")
        return _failed(name, conn.slug, "ToolError")
    digest, size = mcp_client.result_digest(res)
    await _receipt(turn, call_id, "confirmed", result_sha256=digest, result_bytes=size)
    return mcp_client.wrap_result(conn.slug, tool, res, "confirmed")


async def _approve_and_send(turn, conn, tool: str, args: dict, name: str, thread_id, turn_id,
                            seq: int) -> dict:
    decision, reason = effective(conn.policies.get(tool, "ask"), turn.ledger_touched)
    if decision == "deny":
        return _error(name, "this tool is turned off")
    call_id = await asyncio.to_thread(
        insert_call, thread_id=thread_id, turn_id=turn_id, conn=conn, tool=tool, args=args,
        approved=decision == "always", reason=reason)
    row = await asyncio.to_thread(read_call, call_id)
    if decision == "ask":
        row = await _await_decision(turn, conn, call_id, row)
    if row is None:  # the thread was deleted while the call waited
        return _error(name, "approval expired")
    turn.emit({"type": "ext_call", "call_id": str(call_id), "approval": row["approval"],
               "decided_via": row["decided_via"]})
    if row["approval"] == "denied":
        return _error(name, "denied by owner")
    if row["approval"] != "approved":
        return _error(name, "approval expired")
    if row["decided_via"] == "user":
        # only an owner approval clears the taint (A-07), and only the ledger reads seen
        # before it: a read finishing while the card waits keeps the turn tainted
        turn.ledger_cleared = max(turn.ledger_cleared, seq)
    # shown == sent == hashed: the args come back from the row, not from the model (D-13)
    return await _send(turn, conn, tool, call_id, row["args"], name, reopen=decision == "ask")


async def run_call(turn, conn, tool: str, args: dict, *, thread_id, turn_id) -> dict:
    """Validate, guard, serialise, ask or apply policy, wait on the stored decision, send
    the stored args, receipt the outcome. `turn` supplies lock, seen, ledger_touched, ledger_seq, ledger_cleared,
    emit, hold_idle and release_idle."""
    # Before any await: an approval covers only the ledger reads finished by now. A read
    # still running (or started later) counts when it finishes and keeps the taint (CR-01).
    seq = turn.ledger_seq
    from backend.query import _call_key

    name = mcp_client.ext_name(conn.slug, tool)
    errors = mcp_client.validate_args(conn.approved[tool]["inputSchema"], args)
    if errors:  # no row, no card: the model retries (A-06)
        return _error(name, "invalid arguments: " + "; ".join(errors))
    if await asyncio.to_thread(_guard_hit, args):
        await asyncio.to_thread(audit_blocked, conn, tool, args)
        turn.emit({"type": "notice", "code": "blocked", "server": conn.slug,
                   "message": f"monai blocked a call to {conn.slug} because its arguments contained a monai secret."})
        return _error(name, "refused: the arguments contained a monai secret")
    async with turn.lock:  # one external call at a time (D-17)
        key = _call_key(name, args)
        if key in turn.seen:
            return {**turn.seen[key], "duplicate_of_earlier_call": True,
                    "note": "identical call already made this turn; no second call was sent"}
        result = await _approve_and_send(turn, conn, tool, args, name, thread_id, turn_id, seq)
        turn.seen[key] = result
        return result
