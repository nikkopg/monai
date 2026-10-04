"""Phase 32 MCP write tests (propose, reject, replace, duplicate flags) against monai_test.

Synthetic values only. Every seeded account, transaction and proposal is deleted
in teardown. Never assert that a leftover row from another test is still pending:
any GET /proposals bulk-expires stale rows.
"""
import datetime
import inspect
import json
import secrets
import types
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import text

from backend import mcp_writes
from backend.mcp_writes import TxnRow
from backend.tests.test_write_endpoints import _cleanup_account

D = datetime.date(2026, 1, 10)


@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def track(db_session):
    """Proposal ids to delete at teardown (supersedes_id self-FK nulled first)."""
    ids: list = []
    yield ids
    db_session.rollback()
    uids = [uuid.UUID(str(i)) for i in ids]
    db_session.execute(
        text("UPDATE proposals SET supersedes_id = NULL WHERE id = ANY(:i) OR supersedes_id = ANY(:i)"),
        {"i": uids},
    )
    db_session.execute(text("DELETE FROM proposals WHERE id = ANY(:i)"), {"i": uids})
    db_session.commit()


@pytest.fixture()
def wallets(db_session, track):
    """Factory for synthetic accounts; returns SimpleNamespace(id, name, currency)."""
    from backend.models import Account
    made: list[str] = []

    def make(n=1, *, type="liquid", currency="IDR", name=None):
        out = []
        for _ in range(n):
            name = name or f"MCP Test Wallet {secrets.token_hex(4)}"
            acc = Account(name=name, type=type, currency=currency)
            db_session.add(acc)
            db_session.commit()
            made.append(name)
            out.append(types.SimpleNamespace(id=acc.id, name=name, currency=currency))
            name = None
        return out if n > 1 else out[0]

    yield make
    db_session.rollback()
    for name in made:
        _cleanup_account(db_session, name)


@pytest.fixture()
def mcp_proposal(db_session, track):
    """Create a channel='mcp' proposal straight from a payload; tracked for cleanup."""
    from backend.models import Proposal
    from backend.tools import _make_proposal

    def make(payload, channel="mcp"):
        pid, _ = _make_proposal(payload["operation"], payload, channel=channel)
        track.append(pid)
        return db_session.get(Proposal, uuid.UUID(pid))

    return make


def _txn_payload(*rows):
    """rows: (account_name, amount, 'YYYY-MM-DD'[, skip])."""
    out = []
    for r in rows:
        row = {"before": None, "after": {
            "date": r[2], "amount": str(r[1]), "account": r[0], "category": None,
            "merchant": "Coffee Shop", "notes": None, "currency": "IDR", "is_transfer": False,
        }}
        if len(r) > 3 and r[3]:
            row["skip"] = True
        out.append(row)
    return {"operation": "add_transaction", "rows": out}


def _xfer_payload(src, dst, amount, day):
    leg = lambda name, amt: {"account": name, "amount": str(amt), "currency": "IDR", "date": day, "notes": None}
    return {"operation": "add_transfer",
            "rows": [{"before": None, "after": {"leg_a": leg(src, -amount), "leg_b": leg(dst, amount)}}]}


def _ledger(db, acc_id, day, amount, merchant="Coffee Shop"):
    """Insert a ledger transaction (removed by _cleanup_account via the wallet)."""
    from backend.models import Transaction
    tx = Transaction(date=datetime.datetime.combine(day, datetime.time(12)), amount=amount,
                     currency="IDR", merchant=merchant, account_id=acc_id)
    db.add(tx)
    db.commit()
    return tx


def _flags(db, *proposals):
    from backend.mcp_writes import duplicate_flags
    db.expire_all()
    return duplicate_flags(db, list(proposals))


def _d(offset):
    return (D + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------------------
# Duplicate flags (D-17, D-18)
# ---------------------------------------------------------------------------

def test_duplicate_ledger_window(db_session, wallets, mcp_proposal):
    w = wallets()
    tx = _ledger(db_session, w.id, D, -12500)
    p = mcp_proposal(_txn_payload((w.name, -12500, _d(-3)), (w.name, -12500, _d(3)), (w.name, -12500, _d(4))))
    rows = _flags(db_session, p)[p.id]
    assert rows[0] == [{"kind": "transaction", "id": tx.id, "date": D.isoformat(),
                        "amount": "-12500.00", "merchant": "Coffee Shop"}]
    # rows 1 and 2 are also within 3 days of each other (same batch), so assert the ledger side only
    ledger_ids = lambda r: [f["id"] for f in r if f["kind"] == "transaction"]
    assert ledger_ids(rows[1]) == [tx.id]
    assert ledger_ids(rows[2]) == []


def test_duplicate_other_pending_flags_each_other(db_session, wallets, mcp_proposal):
    w = wallets()
    a = mcp_proposal(_txn_payload((w.name, -12500, _d(0))))
    b = mcp_proposal(_txn_payload((w.name, -12500, _d(1))))
    res = _flags(db_session, a, b)
    assert res[a.id][0] == [{"kind": "proposal", "id": str(b.id), "row": 0}]
    assert res[b.id][0] == [{"kind": "proposal", "id": str(a.id), "row": 0}]


def test_duplicate_same_batch(db_session, wallets, mcp_proposal):
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -500, _d(0)), (w.name, -500, _d(0))))
    rows = _flags(db_session, p)[p.id]
    assert rows[0] == [{"kind": "proposal", "id": str(p.id), "row": 1}]
    assert rows[1] == [{"kind": "proposal", "id": str(p.id), "row": 0}]


def test_duplicate_no_match(db_session, wallets, mcp_proposal):
    w1, w2 = wallets(2)
    _ledger(db_session, w1.id, D, -12500)
    p = mcp_proposal(_txn_payload((w1.name, -12501, _d(0)), (w2.name, -12500, _d(0))))
    assert _flags(db_session, p)[p.id] == [[], []]


def test_duplicate_skipped_row_keeps_flags_but_is_not_a_target(db_session, wallets, mcp_proposal):
    w = wallets()
    a = mcp_proposal(_txn_payload((w.name, -700, _d(0), True)))
    b = mcp_proposal(_txn_payload((w.name, -700, _d(0))))
    res = _flags(db_session, a, b)
    assert res[a.id][0] == [{"kind": "proposal", "id": str(b.id), "row": 0}]
    assert res[b.id][0] == []


def test_duplicate_transfer_legs_match_both_ways(db_session, wallets, mcp_proposal):
    w1, w2 = wallets(2)
    x = mcp_proposal(_xfer_payload(w1.name, w2.name, 5000, _d(0)))
    t = mcp_proposal(_txn_payload((w1.name, -5000, _d(1))))
    res = _flags(db_session, x, t)
    assert res[t.id][0] == [{"kind": "proposal", "id": str(x.id), "row": 0}]
    assert res[x.id][0] == [{"kind": "proposal", "id": str(t.id), "row": 0}]
    tx = _ledger(db_session, w2.id, D, 5000)
    flag = _flags(db_session, x)[x.id][0][0]
    assert flag["kind"] == "transaction" and flag["id"] == tx.id


def test_duplicate_inactive_proposals_and_unknown_accounts_never_match(db_session, wallets, mcp_proposal):
    w = wallets()
    others = [mcp_proposal(_txn_payload((w.name, -900, _d(0)))) for _ in range(3)]
    db_session.execute(text("UPDATE proposals SET status = 'rejected' WHERE id = :i"), {"i": others[0].id})
    db_session.execute(text("UPDATE proposals SET status = 'superseded' WHERE id = :i"), {"i": others[1].id})
    db_session.execute(text("UPDATE proposals SET expires_at = now() - interval '1 hour' WHERE id = :i"),
                       {"i": others[2].id})
    db_session.commit()
    ghost = mcp_proposal(_txn_payload(("No Such Wallet " + secrets.token_hex(4), -900, _d(0))))
    p = mcp_proposal(_txn_payload((w.name, -900, _d(0))))
    res = _flags(db_session, p, ghost)
    assert res[p.id] == [[]]
    assert res[ghost.id] == [[]]


def test_duplicate_flag_cap_and_text_cleaning(db_session, wallets, mcp_proposal):
    w = wallets()
    for i in range(7):
        _ledger(db_session, w.id, D, -300, merchant="Shop" + str(i))
    p = mcp_proposal(_txn_payload((w.name, -300, _d(0))))
    assert len(_flags(db_session, p)[p.id][0]) == 5

    w2 = wallets()
    dirty = "Bad\x07Shop\nName‮" + "x" * 200
    _ledger(db_session, w2.id, D, -301, merchant=dirty)
    q = mcp_proposal(_txn_payload((w2.name, -301, _d(0))))
    merchant = _flags(db_session, q)[q.id][0][0]["merchant"]
    assert len(merchant) <= 80
    assert merchant.startswith("BadShopName")
    assert not any(c in merchant for c in "\x07\n‮")


def test_get_proposals_duplicates_per_row_without_mutating_stored_payload(client, db_session, wallets, mcp_proposal):
    w = wallets()
    _ledger(db_session, w.id, D, -12500)
    p = mcp_proposal(_txn_payload((w.name, -12500, _d(0)), (w.name, -1, _d(0))))
    r = client.get("/proposals")
    assert r.status_code == 200
    item = next(i for i in r.json() if i["id"] == str(p.id))
    assert "code" not in item
    assert len(item["payload"]["rows"][0]["duplicates"]) == 1
    assert item["payload"]["rows"][1]["duplicates"] == []
    db_session.expire_all()
    fresh = db_session.get(type(p), p.id)
    assert all("duplicates" not in row for row in fresh.payload["rows"])


# ---------------------------------------------------------------------------
# propose_transactions / propose_transfer (D-01..D-07)
# ---------------------------------------------------------------------------

GENERIC = "Could not complete this request. Nothing was changed."


def _today():
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Asia/Jakarta")).date()


def _row(account, **kw):
    kw.setdefault("date", "2026-01-10")
    kw.setdefault("amount", -12500)
    return TxnRow(account=account, **kw)


def _count(db):
    db.rollback()
    return db.execute(text("SELECT count(*) FROM proposals")).scalar()


def _db_row(db, pid):
    db.rollback()
    return db.execute(
        text("SELECT status, code, token, supersedes_id, failed_attempts, payload FROM proposals WHERE id = :i"),
        {"i": uuid.UUID(str(pid))},
    ).one()


def test_propose_single_row_shape_and_canonical_names(db_session, wallets, track):
    from backend.models import Category
    w = wallets()
    r = mcp_writes.propose_transactions([_row(w.name.lower(), merchant="Coffee Shop", category="uncategorized")])
    track.append(r["proposal_id"])
    assert set(r) == {"proposal_id", "summary", "row_count", "expires_at", "duplicates", "next_step"}
    assert r["next_step"] == mcp_writes.NEXT_STEP and r["row_count"] == 1 and r["duplicates"] == []
    st = _db_row(db_session, r["proposal_id"])
    assert st.status == "pending" and st.code and st.token
    assert st.token not in json.dumps(r) and st.code not in json.dumps(r)
    after = st.payload["rows"][0]["after"]
    assert after["account"] == w.name and after["currency"] == "IDR" and after["is_transfer"] is False
    assert Decimal(after["amount"]) == Decimal(-12500) and isinstance(after["amount"], str)
    assert after["category"] == db_session.query(Category).filter(Category.name == "Uncategorized").first().name
    exp = datetime.datetime.fromisoformat(r["expires_at"])
    assert abs((exp - datetime.datetime.now(datetime.timezone.utc)) - timedelta(hours=48)) < timedelta(minutes=2)


def test_propose_unknown_category_refused(db_session, wallets):
    w = wallets()
    n = _count(db_session)
    with pytest.raises(ToolError, match="list_categories"):
        mcp_writes.propose_transactions([_row(w.name, category="No Such Category " + secrets.token_hex(4))])
    assert _count(db_session) == n


def test_propose_unknown_account_refused_and_not_created(db_session):
    name = "MCP Test Ghost " + secrets.token_hex(4)
    with pytest.raises(ToolError, match="find_accounts"):
        mcp_writes.propose_transactions([_row(name)])
    assert db_session.execute(text("SELECT count(*) FROM accounts WHERE name = :n"), {"n": name}).scalar() == 0


def test_propose_ambiguous_and_investment_accounts_refused(db_session, wallets):
    base = "MCP Test Dupe " + secrets.token_hex(4)
    wallets(name=base)
    wallets(name=base.upper())
    with pytest.raises(ToolError, match="more than one account"):
        mcp_writes.propose_transactions([_row(base.lower())])
    inv = wallets(type="investment")
    with pytest.raises(ToolError, match="unknown account"):
        mcp_writes.propose_transactions([_row(inv.name)])


def test_batch_limits(db_session, wallets, track):
    w = wallets()
    r = mcp_writes.propose_transactions([_row(w.name, amount=-(i + 1)) for i in range(500)])
    track.append(r["proposal_id"])
    assert r["row_count"] == 500
    assert len(_db_row(db_session, r["proposal_id"]).payload["rows"]) == 500
    n = _count(db_session)
    with pytest.raises(ToolError, match="split"):
        mcp_writes.propose_transactions([_row(w.name)] * 501)
    with pytest.raises(ToolError):
        mcp_writes.propose_transactions([])
    assert _count(db_session) == n


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": "abc"}, {"amount": "NaN"}, {"amount": "1.234"},
    {"amount": str(Decimal(10) ** 16)}, {"date": "20260101"}, {"merchant": "m" * 513},
    {"date": "future"},
])
def test_batch_one_bad_row_refuses_everything(db_session, wallets, bad):
    w = wallets()
    if bad.get("date") == "future":
        bad = {"date": (_today() + timedelta(days=2)).isoformat()}
    n = _count(db_session)
    with pytest.raises(ToolError, match="row 1") as ei:
        mcp_writes.propose_transactions([_row(w.name), _row(w.name, **bad), _row(w.name)])
    assert "row 0" not in str(ei.value) and "row 2" not in str(ei.value)
    assert _count(db_session) == n


def test_propose_duplicate_is_flagged_not_blocked(db_session, wallets, track):
    w = wallets()
    _ledger(db_session, w.id, D, -12500)
    r = mcp_writes.propose_transactions([_row(w.name)])
    track.append(r["proposal_id"])
    assert r["duplicates"][0]["row"] == 0 and r["duplicates"][0]["matches"][0]["kind"] == "transaction"
    assert "flagged" in r["summary"]


def test_transfer_valid_and_refusals(db_session, wallets, track):
    a, b = wallets(2)
    usd = wallets(currency="USD")
    r = mcp_writes.propose_transfer(a.name.lower(), b.name, 25000, "2026-01-10")
    track.append(r["proposal_id"])
    assert set(r) == {"proposal_id", "summary", "row_count", "expires_at", "duplicates", "next_step"}
    after = _db_row(db_session, r["proposal_id"]).payload["rows"][0]["after"]
    assert after["leg_a"]["account"] == a.name and Decimal(after["leg_a"]["amount"]) == -25000
    assert after["leg_b"]["account"] == b.name and Decimal(after["leg_b"]["amount"]) == 25000
    assert after["leg_a"]["currency"] == after["leg_b"]["currency"] == "IDR"
    n = _count(db_session)
    for args, msg in [((a.name, a.name, 10, "2026-01-10"), "different"), ((a.name, b.name, 0, "2026-01-10"), "positive"),
                      ((a.name, b.name, -5, "2026-01-10"), "positive"), ((a.name, usd.name, 10, "2026-01-10"), "same currency")]:
        with pytest.raises(ToolError, match=msg):
            mcp_writes.propose_transfer(*args)
    assert _count(db_session) == n


# ---------------------------------------------------------------------------
# reject_proposal (D-13)
# ---------------------------------------------------------------------------

def test_reject_own_pending_and_locked(db_session, wallets, mcp_proposal):
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0))))
    locked = mcp_proposal(_txn_payload((w.name, -11, _d(0))))
    db_session.execute(text("UPDATE proposals SET failed_attempts = 5 WHERE id = :i"), {"i": locked.id})
    db_session.commit()
    for x in (p, locked):
        assert mcp_writes.reject_proposal(str(x.id)) == {"proposal_id": str(x.id), "status": "rejected"}
        assert _db_row(db_session, x.id).status == "rejected"
    with pytest.raises(ToolError, match="already rejected"):
        mcp_writes.reject_proposal(str(p.id))


def test_reject_refuses_other_channels_and_operations(db_session, wallets, mcp_proposal):
    w = wallets()
    chat = mcp_proposal(_txn_payload((w.name, -10, _d(0))), channel="chat")
    other = mcp_proposal({"operation": "edit_holding", "rows": []})
    with pytest.raises(ToolError, match="reject this in monai"):
        mcp_writes.reject_proposal(str(chat.id))
    with pytest.raises(ToolError, match="reject this in monai"):
        mcp_writes.reject_proposal(str(other.id))
    with pytest.raises(ToolError, match="No proposal"):
        mcp_writes.reject_proposal(str(uuid.uuid4()))
    assert _db_row(db_session, chat.id).status == "pending"


# ---------------------------------------------------------------------------
# replaces= (D-14, D-16)
# ---------------------------------------------------------------------------

def test_replace_supersedes_old_and_does_not_carry_skips(db_session, wallets, mcp_proposal, track):
    w = wallets()
    old = mcp_proposal(_txn_payload((w.name, -10, _d(0), True)))
    old_code = _db_row(db_session, old.id).code
    r = mcp_writes.propose_transactions([_row(w.name, amount=-10)], replaces=str(old.id))
    track.append(r["proposal_id"])
    assert _db_row(db_session, old.id).status == "superseded"
    new = _db_row(db_session, r["proposal_id"])
    assert new.supersedes_id == old.id and new.status == "pending" and new.code != old_code
    assert "skip" not in new.payload["rows"][0]
    assert r["duplicates"] == []  # not flagged against its own predecessor


def test_replace_across_operations(db_session, wallets, mcp_proposal, track):
    a, b = wallets(2)
    old = mcp_proposal(_txn_payload((a.name, -10, _d(0))))
    r = mcp_writes.propose_transfer(a.name, b.name, 10, "2026-01-10", replaces=str(old.id))
    track.append(r["proposal_id"])
    assert _db_row(db_session, old.id).status == "superseded"
    assert _db_row(db_session, r["proposal_id"]).payload["operation"] == "add_transfer"


def _make_target(kind, db, w, mcp_proposal):
    payload = _txn_payload((w.name, -10, _d(0)))
    if kind == "chat":
        return mcp_proposal(payload, channel="chat")
    if kind == "non_capture":
        return mcp_proposal({"operation": "edit_holding", "rows": []})
    p = mcp_proposal(payload)
    sql = {"locked": "UPDATE proposals SET failed_attempts = 5 WHERE id = :i",
           "rejected": "UPDATE proposals SET status = 'rejected' WHERE id = :i",
           "expired": "UPDATE proposals SET expires_at = now() - interval '1 hour' WHERE id = :i"}[kind]
    db.execute(text(sql), {"i": p.id})
    db.commit()
    return p


@pytest.mark.parametrize("kind", ["chat", "non_capture", "locked", "rejected", "expired"])
def test_replace_refused_targets_stay_untouched(kind, db_session, wallets, mcp_proposal):
    w = wallets()
    old = _make_target(kind, db_session, w, mcp_proposal)
    before = _db_row(db_session, old.id).status
    n = _count(db_session)
    with pytest.raises(ToolError):
        mcp_writes.propose_transactions([_row(w.name)], replaces=str(old.id))
    assert _count(db_session) == n
    assert _db_row(db_session, old.id).status == before


def test_replace_is_atomic_when_flagging_fails(db_session, wallets, mcp_proposal, monkeypatch):
    w = wallets()
    old = mcp_proposal(_txn_payload((w.name, -10, _d(0))))

    def boom(*a, **k):
        raise RuntimeError("marker-boom")

    monkeypatch.setattr(mcp_writes, "duplicate_flags", boom)
    with pytest.raises(ToolError) as ei:
        mcp_writes.propose_transactions([_row(w.name)], replaces=str(old.id))
    assert str(ei.value) == GENERIC
    assert _db_row(db_session, old.id).status == "pending"
    assert db_session.execute(text("SELECT count(*) FROM proposals WHERE supersedes_id = :i"), {"i": old.id}).scalar() == 0


# ---------------------------------------------------------------------------
# _safe (D-21) and surface (D-02, D-03)
# ---------------------------------------------------------------------------

def test_safe_hides_unexpected_exception_text(db_session, wallets, monkeypatch, caplog):
    w = wallets()
    monkeypatch.setattr(mcp_writes, "_make_proposal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("marker-secret")))
    with caplog.at_level("ERROR"), pytest.raises(ToolError) as ei:
        mcp_writes.propose_transactions([_row(w.name)])
    assert str(ei.value) == GENERIC and "marker-secret" not in str(ei.value)
    assert "marker-secret" not in caplog.text and "RuntimeError" in caplog.text


def test_wrappers_are_not_registered_as_agent_tools_and_have_fixed_params():
    from backend import tools
    for name in ("propose_transactions", "propose_transfer", "reject_proposal"):
        assert name not in tools.TOOLS and name not in tools.READ_TOOL_NAMES
    params = lambda f: list(inspect.signature(f).parameters)
    assert params(mcp_writes.propose_transactions) == ["rows", "replaces"]
    assert params(mcp_writes.propose_transfer) == ["from_account", "to_account", "amount", "date", "notes", "replaces"]
    assert params(mcp_writes.reject_proposal) == ["proposal_id"]


# ---------------------------------------------------------------------------
# confirm_proposal (D-09..D-12, D-20, D-21)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_cap_rows(db_available):
    """The hourly cap counts audit rows, so no test may inherit another's failures (Pitfall 6)."""
    from backend.db import SessionLocal

    def wipe():
        with SessionLocal() as s:
            s.execute(text("DELETE FROM audit_log WHERE entity = 'proposal' AND operation = 'mcp_confirm_failed'"))
            s.commit()

    wipe()
    yield
    wipe()


def _wrong(code):
    return "ZZZZZZ" if code != "ZZZZZZ" else "YYYYYY"


def _confirm(p, code):
    return mcp_writes.confirm_proposal(str(p.id), code)


def _fail_rows(db):
    db.rollback()
    return db.execute(text("SELECT after FROM audit_log WHERE entity = 'proposal' "
                           "AND operation = 'mcp_confirm_failed'")).scalars().all()


def _tx_count(db, acc_id):
    db.rollback()
    return db.execute(text("SELECT count(*) FROM transactions WHERE account_id = :a"), {"a": acc_id}).scalar()


@pytest.mark.parametrize("raw", ["k0m1pq", "K-0M 1PQ", "kOmlpq", "KOMIPQ"])
def test_code_normalizes_crockford_confusables(raw):
    assert mcp_writes._normalize_code(raw) == "K0M1PQ"


def test_code_normalize_int_and_blank():
    assert mcp_writes._normalize_code(483920) == "483920"
    assert [mcp_writes._normalize_code(c) for c in ("", "  ", "-")] == ["", "", ""]


def test_code_blank_is_refused_and_not_an_attempt(db_session, wallets, mcp_proposal):
    p = mcp_proposal(_txn_payload((wallets().name, -10, _d(0))))
    for blank in ("", "  ", "-"):
        with pytest.raises(ToolError, match="code is required"):
            _confirm(p, blank)
    assert _db_row(db_session, p.id).failed_attempts == 0 and _fail_rows(db_session) == []


def test_confirm_unknown_and_malformed_id():
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        with pytest.raises(ToolError, match="No proposal with that id"):
            mcp_writes.confirm_proposal(bad, "ABC123")


def test_confirm_refuses_chat_and_codeless_proposals(db_session, wallets, mcp_proposal):
    w = wallets()
    chat = mcp_proposal(_txn_payload((w.name, -10, _d(0))), channel="chat")
    codeless = mcp_proposal(_txn_payload((w.name, -11, _d(0))))
    db_session.execute(text("UPDATE proposals SET code = NULL WHERE id = :i"), {"i": codeless.id})
    db_session.commit()
    for p in (chat, codeless):
        with pytest.raises(ToolError, match="approve this in monai"):
            _confirm(p, "ABC123")
        assert _db_row(db_session, p.id).failed_attempts == 0
    assert _fail_rows(db_session) == []


def test_confirm_refuses_already_confirmed_and_expired(db_session, wallets, mcp_proposal):
    w = wallets()
    done = mcp_proposal(_txn_payload((w.name, -10, _d(0))))
    gone = mcp_proposal(_txn_payload((w.name, -11, _d(0))))
    code = _db_row(db_session, done.id).code
    _confirm(done, code)
    with pytest.raises(ToolError, match="already confirmed"):
        _confirm(done, code)
    db_session.execute(text("UPDATE proposals SET expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": gone.id})
    db_session.commit()
    with pytest.raises(ToolError, match="expired"):
        _confirm(gone, _db_row(db_session, gone.id).code)


def test_code_wrong_counts_durably_and_audit_row_has_no_codes(db_session, wallets, mcp_proposal):
    p = mcp_proposal(_txn_payload((wallets().name, -10, _d(0))))
    stored = _db_row(db_session, p.id).code
    guess = _wrong(stored)
    with pytest.raises(ToolError, match="4 attempts left") as ei:
        _confirm(p, guess)
    assert stored not in str(ei.value) and guess not in str(ei.value)
    row = _db_row(db_session, p.id)
    assert row.failed_attempts == 1 and row.status == "pending"
    after = _fail_rows(db_session)
    assert after == [{"proposal_id": str(p.id), "failed_attempts": 1}]
    blob = json.dumps(after)
    assert stored not in blob and guess not in blob


def test_lock_five_wrong_codes_then_correct_refused_but_approver_key_works(
        client, approver_key, db_session, wallets, mcp_proposal):
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0))))
    stored = _db_row(db_session, p.id).code
    for left in (4, 3, 2, 1):
        with pytest.raises(ToolError, match=f"{left} attempts left"):
            _confirm(p, _wrong(stored))
    with pytest.raises(ToolError, match="now locked"):
        _confirm(p, _wrong(stored))
    with pytest.raises(ToolError, match="approve it in monai"):
        _confirm(p, stored)
    assert _db_row(db_session, p.id).status == "pending" and _tx_count(db_session, w.id) == 0
    r = client.post(f"/proposals/{p.id}/approve", headers={"MONAI_APPROVER_KEY": approver_key})
    assert r.status_code == 200 and _tx_count(db_session, w.id) == 1


def test_confirm_messy_code_applies_and_skips_are_not_applied(client, approver_key, db_session, wallets, mcp_proposal):
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0)), (w.name, -20, _d(1)), (w.name, -30, _d(2))))
    r = client.patch(f"/proposals/{p.id}/rows/1", json={"skip": True}, headers={"MONAI_APPROVER_KEY": approver_key})
    assert r.status_code == 200
    stored = _db_row(db_session, p.id).code
    messy = f"{stored[:3].lower()}-{stored[3:].lower()}"
    out = _confirm(p, messy)
    assert out == {"proposal_id": str(p.id), "status": "confirmed", "message": "Applied: added 2 transactions (1 skipped)"}
    assert _db_row(db_session, p.id).status == "confirmed"
    amounts = db_session.execute(text("SELECT amount FROM transactions WHERE account_id = :a ORDER BY amount"),
                                 {"a": w.id}).scalars().all()
    assert amounts == [Decimal("-30"), Decimal("-10")]


def test_confirm_transfer_applies(db_session, wallets, mcp_proposal):
    a, b = wallets(2)
    p = mcp_proposal(_xfer_payload(a.name, b.name, 10, "2026-01-10"))
    assert _confirm(p, _db_row(db_session, p.id).code)["message"] == "Applied: added 1 transfer"
    assert _tx_count(db_session, a.id) == 1 and _tx_count(db_session, b.id) == 1


def test_confirm_all_skipped_is_refused_with_fixed_text(client, approver_key, db_session, wallets, mcp_proposal):
    from backend.proposals import ALL_SKIPPED_MSG
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0), True)))
    with pytest.raises(ToolError) as ei:
        _confirm(p, _db_row(db_session, p.id).code)
    assert str(ei.value) == ALL_SKIPPED_MSG
    row = _db_row(db_session, p.id)
    assert row.status == "pending" and row.failed_attempts == 0 and _tx_count(db_session, w.id) == 0


def test_confirm_executor_failure_maps_to_fixed_text(db_session, wallets, mcp_proposal, monkeypatch):
    import backend.main as main_mod
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0))))
    stored = _db_row(db_session, p.id).code

    def boom(*a, **k):
        raise RuntimeError(f"disk exploded {stored}")

    monkeypatch.setattr(main_mod, "apply_add_transaction", boom)
    with pytest.raises(ToolError) as ei:
        _confirm(p, stored)
    assert str(ei.value) == mcp_writes._APPLY_FAILED
    assert stored not in str(ei.value) and "Write failed" not in str(ei.value)
    assert _db_row(db_session, p.id).status == "pending"


def _seed_cap(db, n=mcp_writes.HOURLY_CAP):
    from backend.models import AuditLog
    db.add_all([AuditLog(entity="proposal", entity_id=None, operation="mcp_confirm_failed", before=None,
                         after={"proposal_id": str(uuid.uuid4()), "failed_attempts": 1}) for _ in range(n)])
    db.commit()


def test_cap_blocks_even_a_correct_code(db_session, wallets, mcp_proposal):
    w = wallets()
    p = mcp_proposal(_txn_payload((w.name, -10, _d(0))))
    _seed_cap(db_session)
    with pytest.raises(ToolError, match=r"reopen at \d{4}-\d{2}-\d{2}T\d{2}:00.*owner can approve in monai"):
        _confirm(p, _db_row(db_session, p.id).code)
    row = _db_row(db_session, p.id)
    assert row.status == "pending" and row.failed_attempts == 0 and _tx_count(db_session, w.id) == 0


def test_confirm_is_not_an_agent_tool_and_write_tools_are_exactly_four():
    from backend import tools
    assert "confirm_proposal" not in tools.TOOLS and "confirm_proposal" not in tools.READ_TOOL_NAMES
    assert list(inspect.signature(mcp_writes.confirm_proposal).parameters) == ["proposal_id", "code"]
    assert set(mcp_writes.WRITE_TOOLS) == {"propose_transactions", "propose_transfer", "confirm_proposal", "reject_proposal"}


# ---------------------------------------------------------------------------
# Cap durability and concurrency (D-12, D-25)
# ---------------------------------------------------------------------------

def test_cap_survives_restart_and_reopens_next_hour(db_session, wallets, mcp_proposal):
    from backend.db import engine
    w = wallets()
    guessed, target = (mcp_proposal(_txn_payload((w.name, -10 - i, _d(0)))) for i in range(2))
    _seed_cap(db_session, mcp_writes.HOURLY_CAP - 1)
    with pytest.raises(ToolError, match="attempts left"):
        _confirm(guessed, _wrong(_db_row(db_session, guessed.id).code))
    good = _db_row(db_session, target.id).code
    with pytest.raises(ToolError, match="reopen at"):
        _confirm(target, good)
    engine.dispose()  # a restart: all cap state lives in Postgres
    with pytest.raises(ToolError, match="reopen at"):
        _confirm(target, good)
    db_session.rollback()
    db_session.execute(text("UPDATE audit_log SET created_at = created_at - interval '1 hour' "
                            "WHERE entity = 'proposal' AND operation = 'mcp_confirm_failed'"))
    db_session.commit()
    _confirm(target, good)
    assert _db_row(db_session, target.id).status == "confirmed"


def test_cap_counts_only_current_hour(db_session, wallets, mcp_proposal):
    p = mcp_proposal(_txn_payload((wallets().name, -10, _d(0))))
    _seed_cap(db_session)
    db_session.execute(text("UPDATE audit_log SET created_at = created_at - interval '1 hour' "
                            "WHERE entity = 'proposal' AND operation = 'mcp_confirm_failed'"))
    db_session.commit()
    _confirm(p, _db_row(db_session, p.id).code)
    assert _db_row(db_session, p.id).status == "confirmed"


def test_cap_parallel_guesses_never_overshoot(db_session, mcp_proposal):
    from concurrent.futures import ThreadPoolExecutor
    props = [mcp_proposal({"operation": "add_transaction", "rows": []}) for _ in range(10)]
    ids = [str(p.id) for p in props]
    codes = {str(p.id): _db_row(db_session, p.id).code for p in props}

    def guess(n):
        pid = ids[n % len(ids)]
        try:
            mcp_writes.confirm_proposal(pid, _wrong(codes[pid]))
        except ToolError as e:
            return str(e)
        return "NO ERROR"

    with ThreadPoolExecutor(max_workers=12) as ex:
        texts = list(ex.map(guess, range(60)))
    assert all(t.startswith("Wrong code") or "locked" in t or "Too many wrong codes" in t for t in texts)
    assert len(_fail_rows(db_session)) == mcp_writes.HOURLY_CAP
    rows = [_db_row(db_session, i) for i in ids]
    assert sum(r.failed_attempts for r in rows) == mcp_writes.HOURLY_CAP
    assert all(r.status == "pending" for r in rows)
