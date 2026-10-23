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

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend import config
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
