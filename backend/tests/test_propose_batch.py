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


# ---------------------------------------------------------------------------
# quick 261101-fk9 -- upload-only merchant-history category suggestion
# ---------------------------------------------------------------------------

DAY_A, DAY_B = datetime(1997, 1, 1), datetime(1997, 2, 1)


def test_merchant_key():
    k = mcp_writes._merchant_key
    for m in ("ZZ SHOP 1234", "zz shop", "  ZZ   Shop  ", "ZZ SHOP #A12B", "ZZ SHOP1234"):
        assert k(m) == "zz shop", m
    assert k("ZZ7 MART 0042") == "zz7 mart"  # the first token is never dropped
    assert k("1234") == "1234"
    assert k(None) == "" and k("") == ""


@pytest.fixture()
def hist(db, env):
    """Three ZZ categories (A, B, C), a unique letters-only merchant stem and an insert helper."""
    from types import SimpleNamespace

    from backend.models import Category

    cash, _, _ = env
    sfx = secrets.token_hex(3)
    cats = [Category(name=f"ZZ Hist {k} {sfx}", parent_id=None, kind="expense", color="#112233",
                     icon=None, is_system=False) for k in "ABC"]
    db.add_all(cats)
    db.commit()
    A, B, C = (SimpleNamespace(id=c.id, name=c.name) for c in cats)
    stem = "zzh" + "".join(chr(97 + int(ch, 16)) for ch in secrets.token_hex(3))

    def add(merchant, c, day, *, transfer=False, category=None, account=None):
        db.execute(text("INSERT INTO transactions (date, amount, currency, account_id, is_transfer, merchant, "
                        "category, category_id) VALUES (:d, -10000.00, :cur, :a, :t, :m, :c, :cid)"),
                   {"d": day, "cur": account.currency if account else "IDR", "a": account.id if account else cash.id,
                    "t": transfer, "m": merchant, "c": category or c.name, "cid": c.id})
        db.commit()

    yield SimpleNamespace(A=A, B=B, C=C, stem=stem, add=add)
    db.rollback()
    ids = [A.id, B.id, C.id]
    db.execute(text("UPDATE transactions SET category_id = NULL WHERE category_id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM categories WHERE id = ANY(:i)"), {"i": ids})
    db.commit()


def _propose(db, env, hist, **row_kw):
    cash, _, aids = env
    row = UploadRow(date=DAY, amount="-50500.00", account=cash.name, merchant=f"{hist.stem} shop",
                    raw_line="l", **row_kw)
    return _run(db, cash, _att(aids), [row])


def _suggest(db, env, hist, **row_kw):
    return _get(db, _propose(db, env, hist, **row_kw)).payload["rows"][0]


def test_suggestion_is_the_mode_of_the_normalized_merchant(db, env, hist):
    hist.add(f"{hist.stem} SHOP 1234", hist.A, DAY_A)
    hist.add(f"{hist.stem} SHOP 5678", hist.A, DAY_A)
    hist.add(f"{hist.stem} shop", hist.B, DAY_B)  # newest, but an exact-match lookup is the only way B could win
    row = _suggest(db, env, hist)
    assert row["after"]["category"] == hist.A.name
    assert row["category_suggested"] is True
    assert "category_suggested" not in row["after"]


def test_suggestion_matches_within_the_rows_currency(db, env, hist):
    """POL-05: a USD row never takes a category from IDR history, and an IDR row never from USD."""
    _, _, aids = env
    usd = Account(name=f"ZZ39 Usd {secrets.token_hex(3)}", type="liquid", currency="USD")
    db.add(usd)
    db.commit()

    def usd_row():
        att = _att(aids)
        row = UploadRow(date=DAY, amount="-10.50", account=usd.name, merchant=f"{hist.stem} shop", raw_line="l")
        res = propose_batch(db, [row], channel="upload", account=(usd.id, usd.name, "USD"), attachment=att,
                            provenance={"source": "upload:csv", "attachment_id": att["id"], "sha256": SHA,
                                        "filename": att["filename"], "invariant": "none"})
        return _get(db, res).payload["rows"][0]

    try:
        hist.add(f"{hist.stem} shop", hist.A, DAY_A)
        idr_only = usd_row()
        assert idr_only["after"]["category"] is None and "category_suggested" not in idr_only
        hist.add(f"{hist.stem} shop", hist.B, DAY_B, account=usd)
        hist.add(f"{hist.stem} shop", hist.B, DAY_B, account=usd)  # most used overall, but in USD
        assert usd_row()["after"]["category"] == hist.B.name
        assert _suggest(db, env, hist)["after"]["category"] == hist.A.name
    finally:
        _cleanup_account(db, usd.name)


def test_suggestion_tie_goes_to_the_most_recent(db, env, hist):
    hist.add(f"{hist.stem} shop", hist.A, DAY_A)
    hist.add(f"{hist.stem} shop", hist.B, DAY_B)
    assert _suggest(db, env, hist)["after"]["category"] == hist.B.name


def test_suggestion_ignores_transfers_and_adjustments(db, env, hist):
    for _ in range(3):
        hist.add(f"{hist.stem} shop", hist.B, DAY_B, transfer=True)
    for _ in range(2):
        hist.add(f"{hist.stem} shop", hist.B, DAY_B, category="Adjustment")
    hist.add(f"{hist.stem} shop", hist.A, DAY_A)
    assert _suggest(db, env, hist)["after"]["category"] == hist.A.name


def test_no_history_leaves_none_and_no_flag(db, env, hist):
    row = _suggest(db, env, hist)
    assert row["after"]["category"] is None
    assert "category_suggested" not in row


def test_explicit_category_wins_and_unknown_text_still_gets_a_suggestion(db, env, hist):
    hist.add(f"{hist.stem} shop", hist.A, DAY_A)
    row = _suggest(db, env, hist, category=hist.C.name.upper())
    assert row["after"]["category"] == hist.C.name
    assert "category_suggested" not in row
    row = _suggest(db, env, hist, category="ZZ39 no such category")
    assert row["after"]["category"] == hist.A.name and row["category_suggested"] is True


def test_mcp_channel_never_suggests(db, env, hist):
    cash, _, _ = env
    hist.add(f"{hist.stem} shop", hist.A, DAY_A)
    res = propose_batch(db, [mcp_writes.TxnRow(date=DAY, amount="-1.00", account=cash.name,
                                               merchant=f"{hist.stem} shop")], channel="mcp")
    try:
        row = _get(db, res).payload["rows"][0]
        assert row["after"]["category"] is None
        assert "category_suggested" not in row
    finally:
        db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": uuid.UUID(res["proposal_id"])})
        db.commit()


def test_approving_keeps_the_suggestion(db, env, hist, client, approver_key):
    cash, _, _ = env
    hist.add(f"{hist.stem} shop", hist.A, DAY_A)
    res = _propose(db, env, hist)
    pid = res["proposal_id"]
    assert _get(db, res).payload["rows"][0]["category_suggested"] is True
    r = client.post(f"/proposals/{pid}/approve", headers={"MONAI_APPROVER_KEY": approver_key})
    assert r.status_code == 200, r.text
    got = db.execute(text("SELECT category, category_id FROM transactions WHERE account_id = :a "
                          "AND merchant = :m AND date > '2000-01-01'"), {"a": cash.id, "m": f"{hist.stem} shop"}).all()
    assert [tuple(g) for g in got] == [(hist.A.name, hist.A.id)]
