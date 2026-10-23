"""Phase 41-05: approvals, receipts, policy and taint, outbound guard. Synthetic values only;
the isolated monai_test DB only. The server under test is backend/evals/ext_test_server.py."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend import config, ext_calls as ec
from backend.db import SessionLocal
from backend.models import Proposal, Thread

SLUG = "zz-synth"
KEY = "zz-api-key-0123456789abcdef"  # 27 chars, synthetic


def _conn(**kw):
    base = dict(slug=SLUG, server_id=None, destination="zz.example.com", leaves_machine=True)
    return SimpleNamespace(**{**base, **kw})


def _purge():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM threads WHERE title = 'zz ext'"))
        db.execute(text("DELETE FROM audit_log WHERE entity = 'external_tool_call' "
                        "AND after->>'server' = :s"), {"s": SLUG})
        db.commit()


@pytest.fixture()
def th():
    _purge()
    with SessionLocal() as db:
        t = Thread(title="zz ext")
        db.add(t)
        db.commit()
        tid = t.id
    yield SimpleNamespace(id=tid, turn=uuid.uuid4())
    _purge()


def _row(call_id, cols="approval, decided_via, receipt, error, result_sha256, result_bytes"):
    with SessionLocal() as db:
        return db.execute(text(f"SELECT {cols} FROM ext_calls WHERE id = :i"), {"i": call_id}).one()


def _audits():
    with SessionLocal() as db:
        return db.execute(text(
            "SELECT operation, after FROM audit_log WHERE entity = 'external_tool_call' "
            "AND after->>'server' = :s ORDER BY id"), {"s": SLUG}).all()


def _ask(th, args=None, turn=None, tool="echo"):
    return ec.insert_call(thread_id=th.id, turn_id=turn or th.turn, conn=_conn(), tool=tool,
                          args=args or {"text": "ZZhi"}, approved=False, reason=None)


# ── policy and taint ────────────────────────────────────────────────────────

def test_policy_strictest_wins():
    assert ec.effective("ask", False) == ("ask", None)
    assert ec.effective("always", False) == ("always", None)
    assert ec.effective("deny", False) == ("deny", None)
    assert ec.effective("deny", True) == ("deny", None)
    assert ec.effective("bogus", False) == ("ask", None)


def test_taint_turns_always_into_ask():
    assert ec.effective("always", True) == ("ask", "ledger_read")
    assert ec.effective("ask", True) == ("ask", None)


# ── outbound guard ──────────────────────────────────────────────────────────

def test_guard_finds_key_nested_and_url_encoded(monkeypatch):
    monkeypatch.setenv("MONAI_API_KEY", "zz key/with+chars=24-long!")
    monkeypatch.delenv("MONAI_APPROVER_KEY", raising=False)
    with SessionLocal() as db:
        secrets = ec.guard_secrets(db)
    assert "zz key/with+chars=24-long!" in secrets
    assert ec.outbound_hit({"a": [{"b": "x zz key/with+chars=24-long! y"}]}, secrets)
    assert ec.outbound_hit({"u": "https://h/?k=zz%20key%2Fwith%2Bchars%3D24-long%21"}, secrets)
    assert not ec.outbound_hit({"a": "nothing here"}, secrets)


def test_guard_skips_empty_and_short_secrets(monkeypatch):
    monkeypatch.setenv("MONAI_API_KEY", "")
    monkeypatch.setenv("MONAI_APPROVER_KEY", "short")
    with SessionLocal() as db:
        secrets = ec.guard_secrets(db)
    assert "short" not in secrets and "" not in secrets  # other pending proposals may add theirs
    assert not ec.outbound_hit({"a": "short and anything"}, [s for s in secrets if s in ("", "short")])


def test_guard_includes_pending_proposal_token_and_code(monkeypatch):
    monkeypatch.delenv("MONAI_API_KEY", raising=False)
    monkeypatch.delenv("MONAI_APPROVER_KEY", raising=False)
    tok, code = "zz-token-" + "a" * 20, "zzcode-77"
    with SessionLocal() as db:
        db.add(Proposal(token=tok, code=code, operation="zz_guard", payload={}, channel="mcp",
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
    try:
        with SessionLocal() as db:
            secrets = ec.guard_secrets(db)
        assert tok in secrets and code in secrets
        assert ec.outbound_hit({"x": f"see {tok}"}, secrets)
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM proposals WHERE token = :t"), {"t": tok})
            db.commit()


# ── rows ────────────────────────────────────────────────────────────────────

def test_insert_ask_row_is_pending_with_ttl(th, monkeypatch):
    monkeypatch.setattr(config, "EXT_APPROVAL_TTL_SECONDS", 120.0)
    cid = ec.insert_call(thread_id=th.id, turn_id=th.turn, conn=_conn(), tool="echo",
                         args={"b": 1, "a": 2}, approved=False, reason="ledger_read")
    r = _row(cid, "approval, decided_via, decided_at, args_sha256, destination, leaves_machine, reason, "
                  "extract(epoch FROM expires_at - now()) AS left")
    assert (r.approval, r.decided_via, r.decided_at) == ("pending", None, None)
    assert r.args_sha256 == ec.args_digest({"a": 2, "b": 1})
    assert (r.destination, r.leaves_machine, r.reason) == ("zz.example.com", True, "ledger_read")
    assert 100 < r.left <= 120
    assert _audits() == []


def test_insert_always_row_is_approved_by_policy(th):
    cid = ec.insert_call(thread_id=th.id, turn_id=th.turn, conn=_conn(), tool="echo",
                         args={"text": "ZZhi"}, approved=True, reason=None)
    r = _row(cid, "approval, decided_via, decided_at")
    assert (r.approval, r.decided_via) == ("approved", "policy") and r.decided_at is not None
    assert [a.operation for a in _audits()] == ["approved"]


def test_decide_first_writer_wins_and_audits(th):
    cid = _ask(th)
    assert ec.decide(th.id, cid, True) == "approved"
    assert ec.decide(th.id, cid, True) is None
    assert ec.decide(th.id, cid, False) is None
    assert _row(cid).decided_via == "user"
    assert [a.operation for a in _audits()] == ["approved"]


def test_decide_deny_and_wrong_thread(th):
    other = uuid.uuid4()
    cid = _ask(th)
    assert ec.decide(other, cid, True) is None
    assert _row(cid).approval == "pending"
    assert ec.decide(th.id, cid, False) == "denied"
    assert [a.operation for a in _audits()] == ["denied"]


def test_decide_refuses_an_expired_row(th, monkeypatch):
    cid = _ask(th)
    with SessionLocal() as db:
        db.execute(text("UPDATE ext_calls SET expires_at = now() - interval '1 second' WHERE id = :i"), {"i": cid})
        db.commit()
    assert ec.decide(th.id, cid, True) is None
    assert _row(cid).approval == "pending"


# ── expiry and sweeps ───────────────────────────────────────────────────────

def _age(cid):
    with SessionLocal() as db:
        db.execute(text("UPDATE ext_calls SET expires_at = now() - interval '1 second' WHERE id = :i"), {"i": cid})
        db.commit()


def test_expiry_expire_one_only_touches_pending(th):
    cid = _ask(th)
    _age(cid)
    assert ec.expire_one(cid) is True
    r = _row(cid)
    assert (r.approval, r.decided_via) == ("expired", "expiry")
    assert [a.operation for a in _audits()] == ["expired"]
    done = _ask(th, {"text": "ZZtwo"})
    ec.decide(th.id, done, True)
    assert ec.expire_one(done) is False
    assert _row(done).approval == "approved"


def test_expiry_expire_due_leaves_live_rows(th):
    old, live = _ask(th), _ask(th, {"text": "ZZlive"})
    _age(old)
    with SessionLocal() as db:
        ec.expire_due(db)
    assert (_row(old).approval, _row(live).approval) == ("expired", "pending")


def test_sweep_thread_spares_the_active_turn(th):
    mine, orphan = _ask(th), _ask(th, {"text": "ZZorphan"}, turn=uuid.uuid4())
    with SessionLocal() as db:
        ec.sweep_thread(db, th.id, str(th.turn))
    assert (_row(mine).approval, _row(orphan).approval) == ("pending", "expired")
    with SessionLocal() as db:
        ec.sweep_thread(db, th.id, None)
    assert _row(mine).approval == "expired"


def test_sweep_thread_makes_orphan_receipt_unknown(th):
    cid = _ask(th, turn=uuid.uuid4())
    ec.decide(th.id, cid, True)
    ec.set_receipt(cid, "pending")
    with SessionLocal() as db:
        ec.sweep_thread(db, th.id, str(th.turn))
    assert _row(cid).receipt == "unknown"


def test_sweep_end_run_stop_denies_and_expiry_expires(th):
    a, b = _ask(th), _ask(th, {"text": "ZZb"}, turn=uuid.uuid4())
    ids = ec.end_run(th.turn, stopped=True)
    assert ids == [str(a)]
    r = _row(a)
    assert (r.approval, r.decided_via) == ("denied", "stop")
    assert _row(b).approval == "pending"
    assert [str(i) for i in ec.end_run(_turn_of(b), stopped=False)] == [str(b)]
    assert (_row(b).approval, _row(b).decided_via) == ("expired", "expiry")


def _turn_of(cid):
    return _row(cid, "turn_id").turn_id


def test_sweep_at_boot_expires_pending_and_unknowns_receipts(th):
    pend, sent = _ask(th), _ask(th, {"text": "ZZsent"})
    ec.decide(th.id, sent, True)
    ec.set_receipt(sent, "pending")
    ec.sweep_at_boot()
    assert _row(pend).approval == "expired"
    r = _row(sent)
    assert (r.approval, r.receipt) == ("approved", "unknown")


# ── receipts and audit ──────────────────────────────────────────────────────

def test_receipt_pending_then_confirmed(th):
    cid = _ask(th)
    ec.decide(th.id, cid, True)
    ec.set_receipt(cid, "pending")
    assert _row(cid).receipt == "pending"
    ec.set_receipt(cid, "confirmed", result_sha256="a" * 64, result_bytes=7)
    r = _row(cid)
    assert (r.receipt, r.result_sha256, r.result_bytes, r.error) == ("confirmed", "a" * 64, 7, None)


def test_receipt_failed_keeps_the_class_name(th):
    cid = _ask(th)
    ec.decide(th.id, cid, True)
    ec.set_receipt(cid, "failed", error="ToolError")
    r = _row(cid)
    assert (r.receipt, r.error) == ("failed", "ToolError")
    assert [a.operation for a in _audits()] == ["approved", "failed"]


def test_audit_rows_hold_hash_only(th):
    secret_arg = "ZZ-private-note-12345"
    cid = _ask(th, {"text": secret_arg})
    ec.decide(th.id, cid, True)
    ec.set_receipt(cid, "confirmed", result_sha256="b" * 64, result_bytes=1)
    ec.audit_blocked(_conn(), "echo", {"text": secret_arg})
    rows = _audits()
    assert [a.operation for a in rows] == ["approved", "confirmed", "blocked"]
    for a in rows:
        assert set(a.after) == {"server", "tool", "args_sha256"}
        assert secret_arg not in json.dumps(a.after)
