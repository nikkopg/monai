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


# ── run_call: the wrapper (in-memory synthetic server) ──────────────────────

import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

from fastmcp.client.transports import FastMCPTransport  # noqa: E402

from backend import main, mcp_client as mc, query  # noqa: E402
from backend.evals import ext_test_server as srv  # noqa: E402


class FakeTurn:
    def __init__(self, touched=False):
        self.lock = asyncio.Lock()
        self.seen = {}
        self.ledger_seq = int(touched)
        self.ledger_cleared = 0
        self.events = []
        self.holds = self.releases = 0

    @property
    def ledger_touched(self):
        return self.ledger_seq > self.ledger_cleared

    def emit(self, payload):
        self.events.append(payload)

    def hold_idle(self):
        self.holds += 1

    def release_idle(self):
        self.releases += 1

    def of(self, kind):
        return [e for e in self.events if e["type"] == kind]


@pytest.fixture()
async def conn(monkeypatch):
    monkeypatch.setattr(mc, "build_transport", lambda s: FastMCPTransport(srv.build()))
    spec = mc.ServerSpec(id=None, slug=SLUG, transport="http", url="https://zz.example.com/mcp",
                         headers={}, command=None, args=(), env={})
    client = await mc.open_client(spec)
    approved = {t.name: {"description": t.description, "inputSchema": t.inputSchema, "sha256": mc.tool_sha(t)}
                for t in await mc.list_server_tools(client)}
    c = mc.ServerConn(spec=spec, slug=SLUG, server_id=None, destination="zz.example.com",
                      leaves_machine=True, policies={}, approved=approved, client=client)
    srv.CALLS.clear()
    yield c
    await mc.close_client(c.client)


async def _until(pred, limit=3.0):
    end = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.02)


def _start(turn, conn, th, tool="echo", args=None):
    return asyncio.create_task(ec.run_call(turn, conn, tool, args or {"text": "ZZhi"},
                                           thread_id=th.id, turn_id=th.turn))


async def _answer(turn, th, approve, n=0):
    await _until(lambda: len(turn.of("approval_required")) > n)
    cid = turn.of("approval_required")[n]["call_id"]
    assert ec.decide(th.id, uuid.UUID(cid), approve) is not None
    ec.wake(cid)
    return uuid.UUID(cid)


def _rows(th):
    with SessionLocal() as db:
        return db.execute(text("SELECT count(*) FROM ext_calls WHERE thread_id = :t"), {"t": th.id}).scalar()


async def test_ask_flow_waits_then_sends(th, conn):
    turn = FakeTurn()
    task = _start(turn, conn, th)
    await _until(lambda: turn.of("approval_required"))
    card = turn.of("approval_required")[0]
    assert set(card) == {"type", "call_id", "server", "tool", "args", "destination",
                         "leaves_machine", "expires_at"}
    assert (card["server"], card["tool"], card["args"]) == (SLUG, "echo", {"text": "ZZhi"})
    assert (turn.holds, turn.releases) == (1, 0) and not task.done()
    cid = await _answer(turn, th, True)
    res = await asyncio.wait_for(task, 1)
    assert res["receipt"] == "confirmed" and "ZZhi" in res["result"]
    assert (turn.holds, turn.releases) == (1, 1)
    r = _row(cid)
    assert (r.receipt, r.result_bytes) == ("confirmed", 4) and len(r.result_sha256) == 64
    receipts = [e.get("receipt") for e in turn.of("ext_call") if "receipt" in e]
    assert receipts == ["pending", "confirmed"]
    assert any(e.get("approval") == "approved" for e in turn.of("ext_call"))


async def test_stored_args_are_what_is_sent(th, conn, monkeypatch):
    real = ec.read_call
    monkeypatch.setattr(ec, "read_call", lambda cid: {**real(cid), "args": {"text": "ZZstored"}})
    turn = FakeTurn()
    task = _start(turn, conn, th)
    await _answer(turn, th, True)
    res = await asyncio.wait_for(task, 1)
    assert "ZZstored" in res["result"] and "ZZhi" not in res["result"]


async def test_deny_sends_nothing(th, conn):
    turn = FakeTurn()
    task = _start(turn, conn, th, "send", {"text": "ZZx"})
    cid = await _answer(turn, th, False)
    assert await asyncio.wait_for(task, 1) == {"tool": "ext__zz-synth__send", "external": True,
                                              "error": "denied by owner"}
    assert srv.CALLS == [] and _row(cid).approval == "denied"


async def test_expiry_returns_error_and_releases_the_hold(th, conn, monkeypatch):
    monkeypatch.setattr(config, "EXT_APPROVAL_TTL_SECONDS", 1.0)
    turn = FakeTurn()
    res = await asyncio.wait_for(_start(turn, conn, th, "send", {"text": "ZZx"}), 5)
    assert res["error"] == "approval expired" and srv.CALLS == []
    cid = uuid.UUID(turn.of("approval_required")[0]["call_id"])
    r = _row(cid)
    assert (r.approval, r.decided_via) == ("expired", "expiry")
    assert (turn.holds, turn.releases) == (1, 1) and str(cid) not in ec._WAKE


async def test_always_policy_sends_with_no_card(th, conn):
    conn.policies = {"echo": "always"}
    turn = FakeTurn()
    res = await asyncio.wait_for(_start(turn, conn, th), 3)
    assert res["receipt"] == "confirmed" and turn.of("approval_required") == []
    assert turn.of("ext_call")[0] == {"type": "ext_call", "call_id": turn.of("ext_call")[0]["call_id"],
                                      "approval": "approved", "decided_via": "policy"}
    assert (turn.holds, turn.releases) == (0, 0)


async def test_taint_always_asks_after_a_ledger_read_and_approval_clears_it(th, conn):
    conn.policies = {"echo": "always"}
    turn = FakeTurn(touched=True)
    task = _start(turn, conn, th, args={"text": "ZZone"})
    await _until(lambda: turn.of("approval_required"))
    assert turn.of("approval_required")[0]["reason"] == "ledger_read"
    await _answer(turn, th, True)
    assert (await asyncio.wait_for(task, 1))["receipt"] == "confirmed"
    assert turn.ledger_touched is False
    again = await asyncio.wait_for(_start(turn, conn, th, args={"text": "ZZtwo"}), 3)
    assert again["receipt"] == "confirmed" and len(turn.of("approval_required")) == 1


async def test_taint_a_read_during_a_pending_card_is_not_cleared_by_its_approval(th, conn):
    conn.policies = {"echo": "ask"}
    turn = FakeTurn()
    task = _start(turn, conn, th, args={"text": "ZZone"})
    await _until(lambda: turn.of("approval_required"))
    turn.ledger_seq += 1  # a ledger read lands while the card waits
    await _answer(turn, th, True)
    assert (await asyncio.wait_for(task, 1))["receipt"] == "confirmed"
    assert turn.ledger_touched is True
    conn.policies = {"echo": "always"}
    task = _start(turn, conn, th, args={"text": "ZZtwo"})
    await _until(lambda: len(turn.of("approval_required")) == 2)
    assert turn.of("approval_required")[1]["reason"] == "ledger_read"
    await _answer(turn, th, False, n=1)
    await asyncio.wait_for(task, 1)


async def test_taint_a_parallel_read_finishing_after_the_card_is_not_cleared(th, conn):
    """CR-01: one step runs a ledger read and an Ask call concurrently; the read started
    before the card but finishes after it, so the card's approval must not clear it."""
    import threading

    conn.policies = {"echo": "ask"}
    turn = query.Turn()
    turn.events = []
    turn.emit = turn.events.append
    turn.of = lambda kind: [e for e in turn.events if e["type"] == kind]
    gate = threading.Event()
    read = query._llm_tool("list_categories", lambda: gate.wait(3) and {"tool": "list_categories"})
    token = query.TURN.set(turn)
    try:
        reading = asyncio.create_task(read.acall())
        await asyncio.sleep(0.05)  # the read is running, not finished
        task = _start(turn, conn, th, args={"text": "ZZone"})
        await _until(lambda: turn.of("approval_required"))
        gate.set()
        await asyncio.wait_for(reading, 3)
        await _answer(turn, th, True)
        assert (await asyncio.wait_for(task, 1))["receipt"] == "confirmed"
        assert turn.ledger_touched is True
        conn.policies = {"echo": "always"}
        task = _start(turn, conn, th, args={"text": "ZZtwo"})
        await _until(lambda: len(turn.of("approval_required")) == 2)
        assert turn.of("approval_required")[1]["reason"] == "ledger_read"
        await _answer(turn, th, False, n=1)
        await asyncio.wait_for(task, 1)
    finally:
        gate.set()
        query.TURN.reset(token)


async def test_taint_a_denial_keeps_it(th, conn):
    conn.policies = {"echo": "always"}
    turn = FakeTurn(touched=True)
    task = _start(turn, conn, th, args={"text": "ZZone"})
    await _answer(turn, th, False)
    assert (await asyncio.wait_for(task, 1))["error"] == "denied by owner"
    assert turn.ledger_touched is True
    task = _start(turn, conn, th, args={"text": "ZZtwo"})
    await _until(lambda: len(turn.of("approval_required")) == 2)
    await _answer(turn, th, False, n=1)
    await asyncio.wait_for(task, 1)


async def test_deny_policy_refuses_with_no_row(th, conn):
    conn.policies = {"echo": "deny"}
    res = await _start(FakeTurn(), conn, th)
    assert "error" in res and _rows(th) == 0


async def test_validation_error_returns_no_row_and_no_event(th, conn):
    turn = FakeTurn()
    res = await _start(turn, conn, th, "nested", {"filters": {"color": "purple", "inner": {"n": "x"}}})
    assert res["error"].startswith("invalid arguments: ")
    assert _rows(th) == 0 and turn.events == []


async def test_guard_blocks_a_monai_secret(th, conn, monkeypatch):
    monkeypatch.setenv("MONAI_API_KEY", KEY)
    turn = FakeTurn()
    res = await _start(turn, conn, th, "send", {"text": f"note {KEY}"})
    assert "refused" in res["error"] and KEY not in json.dumps(res)
    assert _rows(th) == 0 and srv.CALLS == []
    assert [a.operation for a in _audits()] == ["blocked"]
    assert len(turn.events) == 1
    n = turn.events[0]
    assert (n["type"], n["code"], n["server"]) == ("notice", "blocked", SLUG) and KEY not in n["message"]


class Spy:
    def __init__(self, inner):
        self.inner, self.cur, self.peak = inner, 0, 0

    async def call_tool(self, *a, **k):
        self.cur += 1
        self.peak = max(self.peak, self.cur)
        try:
            return await self.inner.call_tool(*a, **k)
        finally:
            self.cur -= 1

    def __getattr__(self, n):
        return getattr(self.inner, n)


async def test_serial_external_calls_never_overlap(th, conn):
    conn.policies = {"slow": "always"}
    conn.client = spy = Spy(conn.client)
    turn = FakeTurn()
    await asyncio.wait_for(asyncio.gather(
        _start(turn, conn, th, "slow", {"seconds": 0.2}),
        _start(turn, conn, th, "slow", {"seconds": 0.21}),
    ), 5)
    assert spy.peak == 1


async def test_dedupe_identical_call_returns_the_first_result(th, conn):
    conn.policies = {"echo": "always"}
    turn = FakeTurn()
    first = await _start(turn, conn, th)
    second = await _start(turn, conn, th)
    assert second["duplicate_of_earlier_call"] is True and second["result"] == first["result"]
    assert "duplicate_of_earlier_call" not in first and _rows(th) == 1


class Stub:
    """A client whose call_tool is scripted."""
    def __init__(self, outcome):
        self.outcome = outcome

    async def call_tool(self, *a, **k):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def ping(self):
        return True


async def test_receipt_failed_on_a_tool_error_result(th, conn):
    conn.policies = {"echo": "always"}
    conn.client = Stub(SimpleNamespace(is_error=True, content=[]))
    turn = FakeTurn()
    res = await _start(turn, conn, th)
    assert (res["receipt"], res["error"]) == ("failed", "ToolError") and "result" not in res
    cid = uuid.UUID(turn.of("ext_call")[0]["call_id"])
    assert (_row(cid).receipt, _row(cid).error) == ("failed", "ToolError")
    assert turn.of("ext_call")[-1]["error_class"] == "ToolError"


async def test_receipt_failed_on_an_exception_keeps_only_the_class(th, conn):
    conn.policies = {"echo": "always"}
    conn.client = Stub(RuntimeError("boom https://secret.example.com/x"))
    turn = FakeTurn()
    res = await _start(turn, conn, th)
    assert res["error"] == "RuntimeError" and "secret.example.com" not in json.dumps(turn.events + [res])


async def test_receipt_cancel_during_the_call_is_unknown(th, conn):
    conn.policies = {"slow": "always"}
    turn = FakeTurn()
    task = _start(turn, conn, th, "slow", {"seconds": 5})
    await _until(lambda: any(e.get("receipt") == "pending" for e in turn.of("ext_call")))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cid = uuid.UUID(turn.of("ext_call")[0]["call_id"])
    assert _row(cid).receipt == "unknown"


async def test_stale_session_is_reopened_once_and_sends(th, conn):
    turn = FakeTurn()
    task = _start(turn, conn, th)
    await _until(lambda: turn.of("approval_required"))
    await mc.close_client(conn.client)  # the session went away while parked
    await _answer(turn, th, True)
    res = await asyncio.wait_for(task, 3)
    assert res["receipt"] == "confirmed" and "ZZhi" in res["result"]


async def test_stale_session_with_a_changed_tool_sends_nothing(th, conn, monkeypatch):
    turn = FakeTurn()
    task = _start(turn, conn, th)
    await _until(lambda: turn.of("approval_required"))
    await mc.close_client(conn.client)
    monkeypatch.setattr(mc, "build_transport", lambda s: FastMCPTransport(srv.build("changed")))
    cid = await _answer(turn, th, True)
    res = await asyncio.wait_for(task, 3)
    assert (res["receipt"], res["error"]) == ("failed", "ToolChanged") and "result" not in res
    assert (_row(cid).receipt, _row(cid).error) == ("failed", "ToolChanged")


# ── the decision route ──────────────────────────────────────────────────────

def _url(th, cid):
    return f"/threads/{th.id}/ext-calls/{cid}"


@pytest.fixture()
def active(th):
    query._ACTIVE[str(th.id)] = SimpleNamespace(id=str(th.turn))
    yield
    query._ACTIVE.pop(str(th.id), None)


def test_route_requires_the_api_key(client, api_key, th):
    assert client.post(_url(th, uuid.uuid4()), json={"approve": True}).status_code == 401


def test_route_404_for_unknown_and_other_thread(authed, th):
    assert authed.post(_url(th, uuid.uuid4()), json={"approve": True}).status_code == 404
    cid = _ask(th)
    other = SimpleNamespace(id=uuid.uuid4())
    assert authed.post(_url(other, cid), json={"approve": True}).status_code == 404


def test_route_409_when_no_run_is_active_and_expires_the_row(authed, th):
    cid = _ask(th)
    assert authed.post(_url(th, cid), json={"approve": True}).status_code == 409
    assert _row(cid).approval == "expired"


def test_route_decides_once(authed, th, active):
    cid = _ask(th)
    r = authed.post(_url(th, cid), json={"approve": True})
    assert (r.status_code, r.json()) == (200, {"approval": "approved"})
    assert authed.post(_url(th, cid), json={"approve": False}).status_code == 409
    assert _row(cid).approval == "approved"


def test_route_409_for_an_expired_call(authed, th, active):
    cid = _ask(th)
    _age(cid)
    assert authed.post(_url(th, cid), json={"approve": True}).status_code == 409


async def test_route_wakes_the_waiter(async_client, api_key, th, conn, active):
    turn = FakeTurn()
    task = _start(turn, conn, th)
    await _until(lambda: turn.of("approval_required"))
    cid = turn.of("approval_required")[0]["call_id"]
    r = await async_client.post(_url(th, cid), json={"approve": True}, headers={"MONAI_API_KEY": api_key})
    assert r.status_code == 200
    assert (await asyncio.wait_for(task, 1))["receipt"] == "confirmed"  # well inside the 5 s re-read


# ── boot ────────────────────────────────────────────────────────────────────

async def test_boot_sweeps_once_and_a_failure_only_logs(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(ec, "sweep_at_boot", lambda: calls.append(1))
    async with main.lifespan(main.app):
        pass
    assert calls == [1]

    def boom():
        raise RuntimeError("db down https://secret.example.com")

    monkeypatch.setattr(ec, "sweep_at_boot", boom)
    with caplog.at_level(logging.WARNING):
        async with main.lifespan(main.app):
            pass
    assert "ext_calls boot sweep failed: RuntimeError" in caplog.text
    assert "secret.example.com" not in caplog.text
