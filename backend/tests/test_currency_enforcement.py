"""DB-level currency enforcement + the transactions_idr view (Phase 42, plan 01).

Covers migration 020 as applied to conftest's `monai_test`: IDR/USD CHECKs, the
composite (account_id, currency) foreign key, the view's honest 7-day
carry-back, and the column-drift guard (D-16). Synthetic values only: `ZZ42 `
account names, round rates, 1901 dates. Skips when Postgres is unreachable.
"""
import secrets
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def db():
    from backend.db import SessionLocal, engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    session = SessionLocal()

    def _clean():
        session.rollback()
        session.execute(text("DELETE FROM transactions WHERE date < '1902-01-01'"))
        session.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ42 %'"))
        session.execute(text("DELETE FROM fx_rate_cache WHERE rate_date < '1902-01-01'"))
        session.commit()

    _clean()
    try:
        yield session
    finally:
        _clean()
        session.close()


def _account(db, name: str, currency: str | None = "IDR") -> int:
    if currency is None:
        sql = "INSERT INTO accounts (name, type) VALUES (:n, 'liquid') RETURNING id"
    else:
        sql = "INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"
    return db.execute(text(sql), {"n": name, "c": currency}).scalar()


def _tx(db, when: date, amount: str, currency: str, account_id: int | None) -> int:
    return db.execute(
        text(
            "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
            "VALUES (:d, :a, :c, :acc, false) RETURNING id"
        ),
        {"d": datetime(when.year, when.month, when.day, 12), "a": amount, "c": currency, "acc": account_id},
    ).scalar()


def _rejected(db, fn) -> None:
    with pytest.raises(IntegrityError):
        fn()
    db.rollback()


def test_db_constraints_reject_mismatch_and_out_of_set(db):
    tag = secrets.token_hex(4)
    idr = _account(db, f"ZZ42 db idr {tag}")
    usd = _account(db, f"ZZ42 db usd {tag}", "USD")
    db.commit()

    _rejected(db, lambda: _tx(db, date(1901, 1, 1), "-1.00", "USD", idr))  # mismatch
    _rejected(db, lambda: _account(db, f"ZZ42 db eur {tag}", "EUR"))  # out of set
    _rejected(db, lambda: _tx(db, date(1901, 1, 1), "-1.00", "EUR", None))  # out of set
    _rejected(  # explicit NULL currency
        db,
        lambda: db.execute(
            text("INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', NULL)"),
            {"n": f"ZZ42 db null {tag}"},
        ),
    )

    defaulted = _account(db, f"ZZ42 db default {tag}", None)
    assert db.execute(text("SELECT currency FROM accounts WHERE id = :i"), {"i": defaulted}).scalar() == "IDR"
    _tx(db, date(1901, 1, 1), "-1.00", "IDR", None)  # MATCH SIMPLE: NULL account_id unchecked
    _tx(db, date(1901, 1, 1), "-1.00", "USD", usd)
    db.commit()


def _cols(db, table: str) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
            ),
            {"t": table},
        )
    ]


def test_view_columns_drift_guard(db):
    tx_cols = _cols(db, "transactions")
    assert tx_cols, "transactions table has no columns"
    assert _cols(db, "transactions_idr") == tx_cols + ["amount_idr", "fx_rate", "fx_rate_date"]
    assert _cols(db, "cashflow_transactions") == _cols(db, "transactions_idr")


def _rate(db, rate_date: date, rate: str, effective: date | None = None) -> None:
    db.execute(
        text(
            "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, rate_effective_date) "
            "VALUES (:d, 'USD', 'IDR', :r, 'test', :e)"
        ),
        {"d": rate_date, "r": rate, "e": effective},
    )


def _view(db, tx_id: int):
    return db.execute(
        text("SELECT amount_idr, fx_rate, fx_rate_date FROM transactions_idr WHERE id = :i"), {"i": tx_id}
    ).one()


def test_idr_view_values(db):
    tag = secrets.token_hex(4)
    idr = _account(db, f"ZZ42 view idr {tag}")
    usd = _account(db, f"ZZ42 view usd {tag}", "USD")
    _rate(db, date(1901, 1, 4), "16000.000000")
    _rate(db, date(1901, 2, 2), "16100.000000", effective=date(1901, 2, 1))
    _rate(db, date(1901, 3, 1), "16000.000000")
    _rate(db, date(1901, 3, 4), "16200.000000")

    sat = _tx(db, date(1901, 1, 5), "-12.50", "USD", usd)
    incl = _tx(db, date(1901, 1, 11), "-12.50", "USD", usd)  # d-7 inclusive
    excl = _tx(db, date(1901, 1, 12), "-12.50", "USD", usd)  # d-8 excluded
    eff = _tx(db, date(1901, 2, 2), "-1.00", "USD", usd)
    latest = _tx(db, date(1901, 3, 5), "-1.00", "USD", usd)
    idr_tx = _tx(db, date(1901, 1, 5), "-5000.00", "IDR", idr)
    db.commit()

    assert _view(db, sat) == (Decimal("-200000"), Decimal("16000"), date(1901, 1, 4))
    assert _view(db, incl)[1:] == (Decimal("16000"), date(1901, 1, 4))
    assert _view(db, excl) == (None, None, None)  # no default rate, ever
    assert _view(db, eff)[2] == date(1901, 2, 1)
    assert _view(db, latest)[1] == Decimal("16200")
    assert _view(db, idr_tx) == (Decimal("-5000"), Decimal("1"), None)


def test_models_are_db_light():
    from sqlalchemy.orm import configure_mappers

    from backend.models import Account, FxRateCache, Transaction

    acc = Account.__table__.c.currency
    assert acc.nullable is False and str(acc.server_default.arg) == "IDR"
    assert str(Transaction.__table__.c.currency.server_default.arg) == "IDR"
    eff = FxRateCache.__table__.c.rate_effective_date
    assert eff.nullable is True
    for fk in Transaction.__table__.foreign_key_constraints:
        assert {c.name for c in fk.columns} != {"account_id", "currency"}
    configure_mappers()


# ---------------------------------------------------------------------------
# Phase 42, plan 02: write-path currency gate (D-01..D-04, D-06)
# ---------------------------------------------------------------------------


@pytest.fixture()
def wdb(db):
    """`db` plus cleanup of the 2024-dated rows these tests create on ZZ42 accounts."""

    def _clean_writes():
        db.rollback()
        ids = [r[0] for r in db.execute(text(
            "SELECT t.id FROM transactions t JOIN accounts a ON a.id = t.account_id "
            "WHERE a.name LIKE 'ZZ42 %'"
        ))]
        if ids:
            db.execute(text("DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id = ANY(:ids)"), {"ids": ids})
            db.execute(text("DELETE FROM transactions WHERE id = ANY(:ids)"), {"ids": ids})
        db.execute(text(
            "DELETE FROM audit_log WHERE entity = 'account' AND entity_id IN "
            "(SELECT id FROM accounts WHERE name LIKE 'ZZ42 %')"
        ))
        db.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ42 %'"))
        db.commit()

    _clean_writes()
    try:
        yield db
    finally:
        _clean_writes()


def _body(account: str, **extra) -> dict:
    return {"date": "2024-03-10T12:00:00", "amount": -12.5, "account": account, **extra}


def _one(db, sql: str, **params):
    return db.execute(text(sql), params).first()


def test_post_transactions_audited_and_currency_from_account(authed, wdb):
    from backend.schemas import TransactionOut

    name = f"ZZ42 api idr {secrets.token_hex(4)}"
    _account(wdb, name)
    wdb.commit()

    resp = authed.post("/transactions", json=_body(name))
    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == set(TransactionOut.model_fields)
    tx_id = resp.json()["id"]
    assert _one(wdb, "SELECT currency FROM transactions WHERE id = :i", i=tx_id)[0] == "IDR"
    rows = wdb.execute(text(
        "SELECT after->>'currency' FROM audit_log "
        "WHERE entity = 'transaction' AND entity_id = :i AND operation = 'add'"
    ), {"i": tx_id}).all()
    assert [r[0] for r in rows] == ["IDR"]


def test_post_transactions_currency_mismatch_is_422(authed, wdb):
    name = f"ZZ42 api usd {secrets.token_hex(4)}"
    acc_id = _account(wdb, name, "USD")
    wdb.commit()

    resp = authed.post("/transactions", json=_body(name, currency="IDR"))
    assert resp.status_code == 422, resp.text
    assert "USD" in resp.text and "IDR" in resp.text
    assert _one(wdb, "SELECT COUNT(*) FROM transactions WHERE account_id = :a", a=acc_id)[0] == 0


def test_autocreate_usd_payload_refused_nothing_persisted(authed, wdb):
    name = f"ZZ42 new {secrets.token_hex(4)}"
    resp = authed.post("/transactions", json=_body(name, currency="USD"))
    assert resp.status_code == 422, resp.text
    wdb.rollback()
    assert _one(wdb, "SELECT COUNT(*) FROM accounts WHERE name = :n", n=name)[0] == 0


def test_autocreate_is_always_idr(authed, wdb):
    name = f"ZZ42 new {secrets.token_hex(4)}"
    resp = authed.post("/transactions", json=_body(name))
    assert resp.status_code == 201, resp.text
    assert _one(wdb, "SELECT currency FROM accounts WHERE name = :n", n=name)[0] == "IDR"


def test_post_transactions_naive_and_offset_dates(authed, wdb):
    name = f"ZZ42 api dates {secrets.token_hex(4)}"
    _account(wdb, name)
    wdb.commit()

    naive = authed.post("/transactions", json=_body(name))
    assert naive.status_code == 201, naive.text
    assert _one(wdb, "SELECT date FROM transactions WHERE id = :i", i=naive.json()["id"])[0] == datetime(2024, 3, 10, 12)

    offset = authed.post("/transactions", json=_body(name, date="2024-03-10T12:00:00+07:00"))
    assert offset.status_code == 201, offset.text
    assert _one(wdb, "SELECT date::date FROM transactions WHERE id = :i", i=offset.json()["id"])[0] == date(2024, 3, 10)


def test_apply_add_refusal_creates_no_account_without_rollback(wdb):
    from backend.writes import apply_add_transaction

    name = f"ZZ42 stray {secrets.token_hex(4)}"
    with pytest.raises(ValueError):
        apply_add_transaction(wdb, {"account": name, "amount": "-1", "currency": "USD"})
    assert _one(wdb, "SELECT COUNT(*) FROM accounts WHERE name = :n", n=name)[0] == 0


def test_apply_add_currency_rules(wdb):
    from backend.models import AuditLog
    from backend.writes import apply_add_transaction

    name = f"ZZ42 prim {secrets.token_hex(4)}"
    _account(wdb, name)
    wdb.commit()
    base = {"account": name, "amount": "-12.50", "date": "2024-03-10T12:00:00"}
    try:
        for extra in ({}, {"currency": None}, {"currency": ""}, {"currency": "  "}, {"currency": "idr"}):
            tx = apply_add_transaction(wdb, {**base, **extra})
            assert tx.currency == "IDR", extra
        wdb.flush()
        audit = wdb.query(AuditLog).filter_by(entity="transaction", entity_id=tx.id).one()
        assert audit.after["currency"] == "IDR"
        assert isinstance(audit.after["amount"], str)

        with pytest.raises(ValueError) as exc:
            apply_add_transaction(wdb, {**base, "currency": "USD"})
        assert "USD" in str(exc.value) and "IDR" in str(exc.value)
    finally:
        wdb.rollback()


def test_apply_add_transfer_usd_leg_on_idr_account_refused(wdb):
    from backend.writes import apply_add_transfer

    tag = secrets.token_hex(4)
    a, b = f"ZZ42 xfer a {tag}", f"ZZ42 xfer b {tag}"
    a_id = _account(wdb, a)
    b_id = _account(wdb, b)
    wdb.commit()
    leg = {"amount": "-12.50", "date": "2024-03-10T12:00:00"}
    try:
        with pytest.raises(ValueError) as exc:
            apply_add_transfer(
                wdb,
                {**leg, "account": a, "currency": "IDR"},
                {**leg, "account": b, "currency": "USD", "amount": "12.50"},
            )
        assert "USD" in str(exc.value) and "IDR" in str(exc.value)
    finally:
        wdb.rollback()
    assert _one(wdb, "SELECT COUNT(*) FROM transactions WHERE account_id IN (:a, :b)", a=a_id, b=b_id)[0] == 0


def test_edit_transaction_cannot_reach_account_or_currency(wdb):
    from backend.writes import apply_edit_transaction

    tag = secrets.token_hex(4)
    a_id = _account(wdb, f"ZZ42 edit a {tag}")
    b_id = _account(wdb, f"ZZ42 edit b {tag}")
    tx_id = _tx(wdb, date(2024, 3, 10), "-12.50", "IDR", a_id)
    wdb.commit()
    try:
        tx = apply_edit_transaction(wdb, tx_id, {"account": f"ZZ42 edit b {tag}", "account_id": b_id, "currency": "USD", "notes": "zz"}, None)
        wdb.flush()
        assert (tx.notes, tx.account_id, tx.currency) == ("zz", a_id, "IDR")
    finally:
        wdb.rollback()


# ---------------------------------------------------------------------------
# Plan 03: CSV importer skips and counts a row whose currency differs from its account (D-07)
# ---------------------------------------------------------------------------

_CSV_HEAD = "account;category;currency;amount;type;note;date;transfer\n"


def _csv_row(account: str, currency: str) -> str:
    return f"{account};Food;{currency};-12.50;Expenses;zz42;2024-02-01 10:00:00;false\n"


def _post_csv(authed, body: str):
    return authed.post("/import", files={"file": ("zz42.csv", body.encode(), "text/csv")})


def test_import_usd_primary_csv_skips_all_and_creates_no_account(authed, wdb):
    name = f"ZZ42 imp usd {secrets.token_hex(4)}"
    resp = _post_csv(authed, _CSV_HEAD + _csv_row(name, "USD") * 2)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"parsed": 2, "inserted": 0, "skipped": 2, "currency": "USD"}
    wdb.rollback()
    assert _one(wdb, "SELECT COUNT(*) FROM accounts WHERE name = :n", n=name)[0] == 0


def test_import_mixed_counts_only_mismatches(authed, wdb):
    tag = secrets.token_hex(4)
    idr_name, usd_name = f"ZZ42 imp idr {tag}", f"ZZ42 imp usdacct {tag}"
    usd_id = _account(wdb, usd_name, "USD")
    wdb.commit()
    body = _CSV_HEAD + _csv_row(idr_name, "IDR") + _csv_row(usd_name, "IDR") + _csv_row(idr_name, "IDR")
    resp = _post_csv(authed, body)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"parsed": 3, "inserted": 2, "skipped": 1, "currency": "IDR"}
    wdb.rollback()
    cur, n = _one(wdb, "SELECT a.currency, COUNT(t.id) FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id "
                       "WHERE a.name = :n GROUP BY a.currency", n=idr_name)
    assert (cur, n) == ("IDR", 2)
    assert _one(wdb, "SELECT COUNT(*) FROM transactions WHERE account_id = :a", a=usd_id)[0] == 0
