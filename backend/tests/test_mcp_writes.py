"""Phase 32 MCP write tests (propose, reject, replace, duplicate flags) against monai_test.

Synthetic values only. Every seeded account, transaction and proposal is deleted
in teardown. Never assert that a leftover row from another test is still pending:
any GET /proposals bulk-expires stale rows.
"""
import datetime
import secrets
import types
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

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

    def make(n=1, *, type="liquid", currency="IDR"):
        out = []
        for _ in range(n):
            name = f"MCP Test Wallet {secrets.token_hex(4)}"
            acc = Account(name=name, type=type, currency=currency)
            db_session.add(acc)
            db_session.commit()
            made.append(name)
            out.append(types.SimpleNamespace(id=acc.id, name=name, currency=currency))
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

    def make(payload):
        pid, _ = _make_proposal(payload["operation"], payload, channel="mcp")
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
