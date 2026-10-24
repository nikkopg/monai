"""Phase 39 upload-channel batch tests; synthetic values; monai_test only."""
import secrets
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend import mcp_writes, tools
from backend.mcp_writes import BatchRefused, UploadRow, propose_batch
from backend.models import Account, Proposal
from backend.tests.test_write_endpoints import _cleanup_account

SHA = "a" * 64
DAY = "2026-01-10"


@pytest.fixture()
def db():
    from backend.db import SessionLocal
    try:
        s = SessionLocal()
        s.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def env(db):
    """Liquid account ZZ39 Cash-<hex> plus an investment account; cleaned afterwards."""
    sfx = secrets.token_hex(3)
    cash = Account(name=f"ZZ39 Cash {sfx}", type="liquid", currency="IDR")
    broker = Account(name=f"ZZ39 Broker {sfx}", type="investment", currency="IDR")
    db.add_all([cash, broker])
    db.commit()
    aids: list[str] = []
    yield cash, broker, aids
    db.rollback()
    ids = db.execute(text("SELECT id FROM proposals WHERE payload->'attachment'->>'id' = ANY(:a)"),
                     {"a": aids}).scalars().all()
    db.execute(text("UPDATE proposals SET supersedes_id = NULL WHERE id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM proposals WHERE id = ANY(:i)"), {"i": ids})
    db.commit()
    for a in (cash, broker):
        _cleanup_account(db, a.name)


def _att(aids, **kw):
    aid = str(uuid.uuid4())
    aids.append(aid)
    return {"id": aid, "filename": "zz39.csv", "kind": "csv", "invariant": "none", "opening": None,
            "closing": None, "llm_read": False, "assumptions": [], **kw}


def _rows(cash, n=3, **kw):
    return [UploadRow(date=DAY, amount=f"-{50500 + i}.00", account=cash.name, merchant=f"ZZ39 shop {i}",
                      raw_line=f"line {i}", **kw) for i in range(n)]


def _run(db, cash, att, rows=None, **kw):
    prov = {"source": "upload:csv", "attachment_id": att["id"], "sha256": SHA, "filename": att["filename"],
            "invariant": "none"}
    return propose_batch(db, rows or _rows(cash), channel="upload", account=(cash.id, cash.name, "IDR"),
                         provenance=prov, attachment=att, **kw)


def _get(db, res):
    db.expire_all()
    return db.get(Proposal, uuid.UUID(res["proposal_id"]))


def test_upload_proposal_shape(db, env):
    cash, _, aids = env
    res = _run(db, cash, _att(aids))
    p = _get(db, res)
    assert (p.channel, p.code, p.status) == ("upload", None, "pending")
    assert timedelta(hours=47) < p.expires_at - datetime.now(timezone.utc) <= timedelta(hours=48)
    assert res["row_count"] == 3 and res["flagged"] == 0
    assert "next_step" not in res and not any("token" in k for k in res)
    after = p.payload["rows"][0]["after"]
    assert set(after) == {"date", "amount", "account", "category", "merchant", "notes", "currency",
                          "is_transfer", "source", "attachment_id", "sha256", "filename", "llm_read",
                          "invariant", "raw_line", "assumptions"}
    assert after["amount"] == "-50500.00" and after["account"] == cash.name and after["currency"] == "IDR"
    assert p.payload["attachment"]["row_count"] == 3


def test_flagged_count_and_result(db, env):
    cash, _, aids = env
    db.execute(text("INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
                    "VALUES (:d, -50500.00, 'IDR', :a, false)"), {"d": datetime(2026, 1, 9), "a": cash.id})
    db.commit()
    rows = _rows(cash)  # row 0 duplicates the seeded ledger row
    rows[1].llm_read = True
    rows[2].amount = "-99.00"
    rows[2].assumptions = ["year taken from period"]
    res = _run(db, cash, _att(aids), rows)
    assert res["flagged"] == 3 and len(res["duplicates"]) == 1
    assert _get(db, res).payload["attachment"]["flagged_count"] == 3


def test_turn_id_stamped_upload_not_mcp(db, env):
    cash, _, aids = env
    tid = uuid.uuid4()
    tok = tools.CURRENT_TURN_ID.set(tid)
    try:
        res = _run(db, cash, _att(aids))
        mcp = propose_batch(db, [mcp_writes.TxnRow(date=DAY, amount="-1.00", account=cash.name)],
                            channel="mcp")
    finally:
        tools.CURRENT_TURN_ID.reset(tok)
    assert _get(db, res).turn_id == tid
    assert _get(db, mcp).turn_id is None
    db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": uuid.UUID(mcp["proposal_id"])})
    db.commit()


def test_resubmit_supersedes_same_attachment_only(db, env):
    cash, _, aids = env
    a, b = _att(aids), _att(aids)
    first = _run(db, cash, a)
    other = _run(db, cash, b)
    second = _run(db, cash, a)
    assert _get(db, first).status == "superseded"
    assert _get(db, other).status == "pending"
    p2 = _get(db, second)
    assert p2.status == "pending" and str(p2.supersedes_id) == first["proposal_id"]


@pytest.mark.parametrize("kind", ["deleted", "investment"])
def test_account_must_still_be_liquid(db, env, kind):
    cash, broker, aids = env
    att = _att(aids)
    bad = broker if kind == "investment" else SimpleNamespace(id=cash.id + 10**6, name="ZZ39 Gone")
    with pytest.raises(BatchRefused, match="can't take transactions any more"):
        _run(db, bad, att)


def test_row_text_never_picks_the_account(db, env):
    cash, broker, aids = env
    rows = _rows(cash, 1)
    rows[0].account = broker.name
    res = _run(db, cash, _att(aids), rows)
    assert _get(db, res).payload["rows"][0]["after"]["account"] == cash.name


def test_unknown_category_is_none_for_upload_but_refused_for_mcp(db, env):
    cash, _, aids = env
    rows = _rows(cash, 1, category="ZZ39 no such category")
    res = _run(db, cash, _att(aids), rows)
    assert _get(db, res).payload["rows"][0]["after"]["category"] is None
    with pytest.raises(BatchRefused, match="unknown category"):
        propose_batch(db, [mcp_writes.TxnRow(date=DAY, amount="-1.00", account=cash.name,
                                             category="ZZ39 no such category")], channel="mcp")


def test_row_limits_and_bad_amount(db, env):
    cash, _, aids = env
    with pytest.raises(BatchRefused, match=r"Too many rows \(501\)"):
        _run(db, cash, _att(aids), _rows(cash, 501))
    rows = _rows(cash, 1)
    rows[0].amount = "0.001"
    with pytest.raises(BatchRefused, match="row 0"):
        _run(db, cash, _att(aids), rows)


def test_upload_proposal_token_403_approver_applies(db, env, client, api_key, approver_key):
    cash, _, aids = env
    res = _run(db, cash, _att(aids))
    pid = res["proposal_id"]
    token = _get(db, res).token
    r = client.post(f"/proposals/{pid}/confirm", json={"token": token}, headers={"MONAI_API_KEY": api_key})
    assert r.status_code == 403
    r = client.post(f"/proposals/{pid}/approve", headers={"MONAI_APPROVER_KEY": approver_key})
    assert r.status_code == 200, r.text
    rows = db.execute(text("SELECT id FROM transactions WHERE account_id = :a"), {"a": cash.id}).scalars().all()
    assert len(rows) == 3
    after = db.execute(text("SELECT after FROM audit_log WHERE entity = 'transaction' AND entity_id = ANY(:i)"),
                       {"i": rows}).scalars().all()
    assert all(a["sha256"] == SHA and a["attachment_id"] for a in after)
