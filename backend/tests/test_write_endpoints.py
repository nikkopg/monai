"""
Direct REST write-endpoint tests for Phase 14's 5 new operations
(CHAT-09/XFER-01..04/ACCT-02).

Phase-14 Plan 01 (Wave 0, RED-first): every route below DOES NOT EXIST YET.
A POST to a nonexistent route returns 404 — the intended RED signal, mirroring
Phase 13's lazy-import RED idiom on the agent side. These tests turn GREEN
once Plan 14-03 adds the routes.

Fixtures `client`/`api_key` come from conftest.py (session-scoped TestClient +
monkeypatched MONAI_API_KEY). `db_available`/`db_session` are defined locally,
mirroring test_account_crud.py.

Requires a live Postgres. Tests seed + clean up their own `zz14test-`-prefixed
rows.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text


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


# ---------------------------------------------------------------------------
# Seed / cleanup helpers (mirror test_write_tools.py's idiom)
# ---------------------------------------------------------------------------

def _make_account(db, name: str) -> int:
    from backend.models import Account
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type="liquid", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _cleanup_account(db, name: str) -> None:
    from backend.models import Account, AuditLog, Transaction
    acc = db.query(Account).filter(Account.name == name).first()
    if acc is None:
        return
    tx_ids = [t.id for t in db.query(Transaction).filter(Transaction.account_id == acc.id).all()]
    if tx_ids:
        db.query(AuditLog).filter(
            AuditLog.entity == "transaction", AuditLog.entity_id.in_(tx_ids)
        ).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.id.in_(tx_ids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.entity == "account", AuditLog.entity_id == acc.id).delete()
    db.delete(acc)
    db.commit()


def _make_platform(db, name: str) -> int:
    from backend.models import Platform
    existing = db.query(Platform).filter(Platform.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    plat = Platform(name=name, kind="exchange")
    db.add(plat)
    db.commit()
    db.refresh(plat)
    return plat.id


def _cleanup_platform(db, platform_id: int) -> None:
    from backend.models import Platform
    plat = db.get(Platform, platform_id)
    if plat is not None:
        db.delete(plat)
        db.commit()


def _cleanup_ticker(db, ticker: str) -> None:
    from backend.models import AuditLog, Holding, PortfolioEvent, PriceCache
    hids = [h.id for h in db.query(Holding).filter(Holding.ticker == ticker).all()]
    if hids:
        db.query(AuditLog).filter(
            AuditLog.entity == "holding", AuditLog.entity_id.in_(hids)
        ).delete(synchronize_session=False)
    eids = [e.id for e in db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).all()]
    if eids:
        db.query(AuditLog).filter(
            AuditLog.entity == "portfolio_event", AuditLog.entity_id.in_(eids)
        ).delete(synchronize_session=False)
    db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).delete(synchronize_session=False)
    db.query(Holding).filter(Holding.ticker == ticker).delete(synchronize_session=False)
    db.query(PriceCache).filter(PriceCache.ticker == ticker).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Happy-path tests — 201, RED (404) until Plan 14-03 adds the route
# ---------------------------------------------------------------------------

def test_post_transfer(client, api_key, db_session):
    """POST /transactions/transfer -> 201, both legs paired (XFER-01)."""
    from backend.models import Transaction

    name_a, name_b = "zz14test-RestTransferA", "zz14test-RestTransferB"
    acc_a = _make_account(db_session, name_a)
    acc_b = _make_account(db_session, name_b)
    try:
        resp = client.post(
            "/transactions/transfer",
            json={
                "from_account": name_a, "to_account": name_b, "amount": 100000,
                "currency": "IDR", "date": "2024-03-10", "notes": "rest transfer",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "leg_a_id" in data and "leg_b_id" in data and "transfer_pair_id" in data

        db_session.expire_all()
        rows = db_session.query(Transaction).filter(Transaction.account_id.in_([acc_a, acc_b])).all()
        assert len(rows) == 2, f"expected exactly 2 paired legs, got {len(rows)}"
        assert all(r.is_transfer for r in rows)
        pair_ids = {r.transfer_pair_id for r in rows}
        assert len(pair_ids) == 1 and None not in pair_ids
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_post_investment_transfer(client, api_key, db_session):
    """POST /transactions/investment-transfer -> 201, cash leg + linked
    PortfolioEvent (ticker=='CASH', deposit sentinel, RESEARCH Q1) (XFER-02)."""
    from backend.models import Transaction, PortfolioEvent, AuditLog, Holding

    name = "zz14test-RestInvestSource"
    ticker = "CASH"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestInvestPlatform")
    try:
        resp = client.post(
            "/transactions/investment-transfer",
            json={
                "from_account": name, "platform_id": plat_id, "amount": 500000,
                "currency": "IDR", "date": "2024-03-11",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.is_transfer is True
        assert tx.amount == Decimal("-500000")

        ev = db_session.query(PortfolioEvent).filter(
            PortfolioEvent.platform_id == plat_id, PortfolioEvent.ticker == ticker
        ).one()
        assert ev.source_account_id == acc_id
        assert ev.event_type == "deposit"
    finally:
        db_session.rollback()
        # CASH is a shared production sentinel ticker — scope cleanup to this
        # test's own platform_id, never a global ticker purge.
        eids = [e.id for e in db_session.query(PortfolioEvent).filter(
            PortfolioEvent.platform_id == plat_id, PortfolioEvent.ticker == ticker
        ).all()]
        if eids:
            db_session.query(AuditLog).filter(
                AuditLog.entity == "portfolio_event", AuditLog.entity_id.in_(eids)
            ).delete(synchronize_session=False)
            db_session.query(PortfolioEvent).filter(PortfolioEvent.id.in_(eids)).delete(synchronize_session=False)
        hids = [h.id for h in db_session.query(Holding).filter(
            Holding.platform_id == plat_id, Holding.ticker == ticker
        ).all()]
        if hids:
            db_session.query(AuditLog).filter(
                AuditLog.entity == "holding", AuditLog.entity_id.in_(hids)
            ).delete(synchronize_session=False)
            db_session.query(Holding).filter(Holding.id.in_(hids)).delete(synchronize_session=False)
        db_session.commit()
        _cleanup_platform(db_session, plat_id)
        _cleanup_account(db_session, name)


def test_post_funded_buy(client, api_key, db_session):
    """POST /portfolio-events/funded-buy -> 201, cash leg debited + 'buy'
    event + holding recomputed (XFER-03)."""
    from backend.models import Transaction, PortfolioEvent, Holding

    name = "zz14test-RestFundedBuySource"
    ticker = "ZZ14RESTBUY"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestFundedBuyPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        resp = client.post(
            "/portfolio-events/funded-buy",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 1000000,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-12",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.amount == Decimal("-1000000")
        assert tx.is_transfer is True

        ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
        assert ev.event_type == "buy"
        assert ev.source_account_id == acc_id

        h = db_session.query(Holding).filter(
            Holding.ticker == ticker, Holding.platform_id == plat_id
        ).one()
        assert h.quantity == Decimal("10")
    finally:
        db_session.rollback()
        _cleanup_ticker(db_session, ticker)
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_post_funded_sell(client, api_key, db_session):
    """POST /portfolio-events/funded-sell -> 201, cash leg credited + 'sell'
    event (XFER-03)."""
    from backend.models import Transaction, PortfolioEvent

    name = "zz14test-RestFundedSellDest"
    ticker = "ZZ14RESTSELL"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestFundedSellPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        resp = client.post(
            "/portfolio-events/funded-sell",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 1000000,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-13",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.amount == Decimal("1000000")
        assert tx.is_transfer is True

        ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
        assert ev.event_type == "sell"
        assert ev.source_account_id == acc_id
    finally:
        db_session.rollback()
        _cleanup_ticker(db_session, ticker)
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_post_adjust_balance(client, api_key, db_session):
    """POST /accounts/{id}/adjust-balance -> 201, single Adjustment
    transaction with the correct delta (ACCT-02)."""
    import datetime as _dt
    from backend.models import Transaction

    name = "zz14test-RestAdjustAccount"
    acc_id = _make_account(db_session, name)
    try:
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 14, 12, 0, 0), amount=200000, currency="IDR",
            category="Salary", account_id=acc_id, is_transfer=False,
        ))
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 15, 12, 0, 0), amount=50000, currency="IDR",
            category=None, account_id=acc_id, is_transfer=True,
        ))
        db_session.commit()

        current = Decimal(str(db_session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
            {"id": acc_id},
        ).scalar()))
        target = current + Decimal("77777")
        expected_delta = target - current

        resp = client.post(
            f"/accounts/{acc_id}/adjust-balance",
            json={"target_balance": float(target)},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        all_rows = db_session.query(Transaction).filter(Transaction.account_id == acc_id).all()
        assert len(all_rows) == 3, f"expected exactly one new adjustment row, got {len(all_rows) - 2} new row(s)"

        adj_rows = [r for r in all_rows if r.category == "Adjustment"]
        assert len(adj_rows) == 1
        assert adj_rows[0].amount == expected_delta
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


# ---------------------------------------------------------------------------
# Input validation / auth tests — pin the V5/auth threat controls
# ---------------------------------------------------------------------------

def test_transfer_rejects_negative_amount(client, api_key, db_session):
    """POST /transactions/transfer with amount=-1 -> 422 (V5, schema-level
    Field(gt=0) guard — the apply_* primitive owns sign normalization, the
    schema must reject a negative/zero magnitude before it ever runs)."""
    name_a, name_b = "zz14test-NegAmtA", "zz14test-NegAmtB"
    acc_a = _make_account(db_session, name_a)
    acc_b = _make_account(db_session, name_b)
    try:
        resp = client.post(
            "/transactions/transfer",
            json={
                "from_account": name_a, "to_account": name_b, "amount": -1,
                "currency": "IDR", "date": "2024-03-16",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_funded_buy_rejects_zero_cash_amount(client, api_key, db_session):
    """POST /portfolio-events/funded-buy with cash_amount=0 -> 422 (V5)."""
    name = "zz14test-ZeroCashSrc"
    ticker = "ZZ14ZEROCASH"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-ZeroCashPlatform")
    try:
        resp = client.post(
            "/portfolio-events/funded-buy",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 0,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-17",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_funded_buy_rejects_nonexistent_platform(client, api_key, db_session):
    """POST /portfolio-events/funded-buy with a nonexistent platform_id ->
    422, not 500 (T-14-07)."""
    name = "zz14test-BadPlatformSrc"
    ticker = "ZZ14BADPLAT"
    acc_id = _make_account(db_session, name)
    try:
        resp = client.post(
            "/portfolio-events/funded-buy",
            json={
                "source_account_name": name, "platform_id": 999999999, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 1000000,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-19",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


def test_transfer_missing_api_key_401(client, api_key, db_session):
    """POST /transactions/transfer without MONAI_API_KEY header -> 401 (V2).

    Uses the api_key fixture to ensure _CONFIGURED_KEY is non-empty
    (fail-closed guard) but omits the header from the request, mirroring
    test_proposals.py::test_confirm_requires_api_key."""
    resp = client.post(
        "/transactions/transfer",
        json={
            "from_account": "zz14test-NoKeyA", "to_account": "zz14test-NoKeyB",
            "amount": 1000, "currency": "IDR", "date": "2024-03-18",
        },
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Phase 17 Plan 01 (Wave 0, RED-first) — extended GET /transactions filters,
# paging, hierarchy-aware category matching, and transfer_pair_id exposure
# (D-01/D-02, REC-01/REC-02/REC-05). All fail RED today: only `limit` exists
# on the endpoint, unknown query params are silently ignored, and
# transfer_pair_id is absent from TransactionOut JSON — until 17-03 lands.
# ---------------------------------------------------------------------------

def test_transactions_filter(client, db_session):
    """Each GET /transactions filter param narrows results: account_id, q
    (merchant/notes ilike), type=expense/income, amount_min/amount_max
    (abs), date_from/date_to, include_transfers=false (D-01/REC-02)."""
    import datetime as _dt
    from backend.models import Transaction

    name = "zz17test-FilterAcc"
    acc_id = _make_account(db_session, name)
    try:
        db_session.add_all([
            Transaction(date=_dt.datetime(2024, 6, 1, 12, 0, 0), amount=-15000, currency="IDR",
                        category="Food", merchant="zz17test-Merchant-Alpha", notes=None,
                        account_id=acc_id, is_transfer=False),
            Transaction(date=_dt.datetime(2024, 6, 2, 12, 0, 0), amount=250000, currency="IDR",
                        category="Salary", merchant="zz17test-Merchant-Beta", notes=None,
                        account_id=acc_id, is_transfer=False),
            Transaction(date=_dt.datetime(2024, 6, 3, 12, 0, 0), amount=-90000, currency="IDR",
                        category=None, merchant=None, notes="zz17test note keyword",
                        account_id=acc_id, is_transfer=True),
        ])
        db_session.commit()
        rows = (
            db_session.query(Transaction)
            .filter(Transaction.account_id == acc_id)
            .order_by(Transaction.date)
            .all()
        )
        expense_id, income_id, transfer_id = rows[0].id, rows[1].id, rows[2].id

        resp = client.get(f"/transactions?account_id={acc_id}&limit=500")
        assert resp.status_code == 200
        assert {r["id"] for r in resp.json()} == {expense_id, income_id, transfer_id}, (
            "account_id must scope results to this account only"
        )

        resp = client.get(f"/transactions?account_id={acc_id}&q=Merchant-Alpha&limit=500")
        assert {r["id"] for r in resp.json()} == {expense_id}, "q must ilike-match merchant"

        resp = client.get(f"/transactions?account_id={acc_id}&q=note keyword&limit=500")
        assert {r["id"] for r in resp.json()} == {transfer_id}, "q must ilike-match notes"

        resp = client.get(f"/transactions?account_id={acc_id}&type=expense&limit=500")
        assert {r["id"] for r in resp.json()} == {expense_id}

        resp = client.get(f"/transactions?account_id={acc_id}&type=income&limit=500")
        assert {r["id"] for r in resp.json()} == {income_id}

        resp = client.get(f"/transactions?account_id={acc_id}&amount_min=80000&amount_max=100000&limit=500")
        assert {r["id"] for r in resp.json()} == {transfer_id}, "amount_min/max must filter on abs(amount)"

        resp = client.get(f"/transactions?account_id={acc_id}&date_from=2024-06-02&date_to=2024-06-03&limit=500")
        assert {r["id"] for r in resp.json()} == {income_id, transfer_id}

        resp = client.get(f"/transactions?account_id={acc_id}&include_transfers=false&limit=500")
        assert {r["id"] for r in resp.json()} == {expense_id, income_id}, (
            "include_transfers=false must exclude is_transfer rows"
        )
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


def test_transaction_paging(client, db_session):
    """offset+limit page correctly (date-desc), and the 500-row hard cap
    holds regardless of a larger requested limit (Pitfall 4)."""
    import datetime as _dt
    from backend.models import Transaction

    name = "zz17test-PagingAcc"
    acc_id = _make_account(db_session, name)
    try:
        db_session.add_all([
            Transaction(date=_dt.datetime(2024, 7, 1, 12, 0, 0), amount=-1000, currency="IDR",
                        account_id=acc_id, is_transfer=False),
            Transaction(date=_dt.datetime(2024, 7, 2, 12, 0, 0), amount=-2000, currency="IDR",
                        account_id=acc_id, is_transfer=False),
            Transaction(date=_dt.datetime(2024, 7, 3, 12, 0, 0), amount=-3000, currency="IDR",
                        account_id=acc_id, is_transfer=False),
        ])
        db_session.commit()
        rows = (
            db_session.query(Transaction)
            .filter(Transaction.account_id == acc_id)
            .order_by(Transaction.date.desc())
            .all()
        )
        expected_order = [r.id for r in rows]

        page0 = client.get(f"/transactions?account_id={acc_id}&limit=1&offset=0").json()
        page1 = client.get(f"/transactions?account_id={acc_id}&limit=1&offset=1").json()
        page2 = client.get(f"/transactions?account_id={acc_id}&limit=1&offset=2").json()
        assert [r["id"] for r in page0] == [expected_order[0]]
        assert [r["id"] for r in page1] == [expected_order[1]]
        assert [r["id"] for r in page2] == [expected_order[2]]

        capped = client.get("/transactions?limit=10000")
        assert capped.status_code == 200
        assert len(capped.json()) <= 500, "hard cap of 500 must hold regardless of requested limit"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


def test_category_filter_hierarchy(client, db_session):
    """category filter matches the node + ALL descendants (hierarchy), not
    exact-string-only — derives the expected count live from the category
    tree, never a hard-coded number (Pitfall 3, critical item #3)."""
    from sqlalchemy import text as _text
    from backend.tools import _find_category_node, _descendant_ids
    from backend.models import Transaction
    import datetime as _dt

    cats = db_session.execute(_text("SELECT id, name, parent_id FROM categories")).fetchall()
    child_counts: dict[int, int] = {}
    for _id, _name, _pid in cats:
        if _pid is not None:
            child_counts[_pid] = child_counts.get(_pid, 0) + 1
    parent_row = next((c for c in cats if child_counts.get(c[0], 0) >= 1), None)
    assert parent_row is not None, "fixture requires at least one category with children"
    parent_name = parent_row[1]

    node = _find_category_node(parent_name)
    assert node is not None
    ids = _descendant_ids(node)
    assert len(ids) >= 2, "chosen category must have at least one descendant"

    name = "zz17test-CatHierarchyAcc"
    acc_id = _make_account(db_session, name)
    try:
        for i, cid in enumerate(ids):
            db_session.add(Transaction(
                date=_dt.datetime(2024, 5, 1 + i, 12, 0, 0), amount=-1000 - i, currency="IDR",
                category_id=cid, account_id=acc_id, is_transfer=False,
            ))
        db_session.commit()

        resp = client.get(f"/transactions?account_id={acc_id}&category={parent_name}&limit=500")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(ids), (
            f"expected {len(ids)} rows (node + descendants) for category={parent_name!r}, got {len(data)} "
            "— an exact-string-only filter would silently undercount subcategory rows"
        )
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


def test_transfer_pair_id_exposed(client, db_session):
    """transfer_pair_id key present in TransactionOut JSON (D-02); the
    type=transfer filter keys off transfer_pair_id IS NOT NULL, not
    is_transfer — an Adjustment row (is_transfer=true, transfer_pair_id=
    null) buckets by its sign under type=expense and is excluded from
    type=transfer (Pitfall 5, critical item #4)."""
    import datetime as _dt
    from backend.models import Transaction
    from backend.writes import apply_add_transfer

    name, other = "zz17test-PairExposedAcc", "zz17test-PairExposedOtherAcc"
    acc_id = _make_account(db_session, name)
    _make_account(db_session, other)
    try:
        leg_a, leg_b = apply_add_transfer(
            db_session,
            {"account": name, "amount": "-40000", "currency": "IDR"},
            {"account": other, "amount": "40000", "currency": "IDR"},
        )
        adj = Transaction(
            date=_dt.datetime(2024, 5, 20, 12, 0, 0), amount=-7777, currency="IDR",
            category="Adjustment", account_id=acc_id, is_transfer=True,
        )
        db_session.add(adj)
        db_session.commit()
        db_session.refresh(leg_a)
        db_session.refresh(adj)

        resp = client.get(f"/transactions?account_id={acc_id}&limit=500")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert all("transfer_pair_id" in row for row in data), (
            "transfer_pair_id key missing from TransactionOut JSON"
        )

        resp_exp = client.get(f"/transactions?account_id={acc_id}&type=expense&limit=500")
        exp_ids = {row["id"] for row in resp_exp.json()}
        assert adj.id in exp_ids, (
            "Adjustment row (is_transfer=true, transfer_pair_id=null) must bucket by sign under type=expense"
        )

        resp_xfer = client.get(f"/transactions?account_id={acc_id}&type=transfer&limit=500")
        xfer_ids = {row["id"] for row in resp_xfer.json()}
        assert adj.id not in xfer_ids, "Adjustment row must NOT appear under type=transfer"
        assert leg_a.id in xfer_ids, "real transfer leg (transfer_pair_id set) must appear under type=transfer"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)
        _cleanup_account(db_session, other)


# ---------------------------------------------------------------------------
# Phase 17 Plan 01 (Wave 0, RED-first) — bulk-delete / bulk-recategorize
# (D-03/D-04, REC-03/REC-05). Both routes 404 today — RED until 17-03.
# ---------------------------------------------------------------------------

def test_bulk_delete(client, api_key, db_session):
    """POST /transactions/bulk-delete removes every listed id atomically; a
    selected transfer leg cascades to its sibling even though the sibling
    was NOT in `ids` (D-04, critical item #1); a bad id lands in skipped[]
    with a reason, never a 500; one AuditLog delete row per deleted entity."""
    import datetime as _dt
    from backend.models import Transaction, AuditLog
    from backend.writes import apply_add_transfer

    name_a, name_b = "zz17test-BulkDelA", "zz17test-BulkDelB"
    acc_a = _make_account(db_session, name_a)
    _make_account(db_session, name_b)
    try:
        leg_a, leg_b = apply_add_transfer(
            db_session,
            {"account": name_a, "amount": "-25000", "currency": "IDR"},
            {"account": name_b, "amount": "25000", "currency": "IDR"},
        )
        plain = Transaction(
            date=_dt.datetime(2024, 8, 1, 12, 0, 0), amount=-5000, currency="IDR",
            category="Food", account_id=acc_a, is_transfer=False,
        )
        db_session.add(plain)
        db_session.commit()
        db_session.refresh(leg_a)
        db_session.refresh(leg_b)
        db_session.refresh(plain)
        leg_a_id, leg_b_id, plain_id = leg_a.id, leg_b.id, plain.id
        bad_id = 999999999

        resp = client.post(
            "/transactions/bulk-delete",
            json={"ids": [leg_a_id, plain_id, bad_id]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert set(data["deleted"]) == {leg_a_id, leg_b_id, plain_id}, (
            "bulk-delete must cascade to the sibling leg even though it was not in ids"
        )
        assert any(s["id"] == bad_id for s in data["skipped"]), (
            "nonexistent id must be reported in skipped[], never a 500"
        )

        db_session.expire_all()
        assert db_session.get(Transaction, leg_a_id) is None
        assert db_session.get(Transaction, leg_b_id) is None
        assert db_session.get(Transaction, plain_id) is None

        audit_rows = db_session.query(AuditLog).filter(
            AuditLog.entity == "transaction",
            AuditLog.entity_id.in_([leg_a_id, leg_b_id, plain_id]),
            AuditLog.operation == "delete",
        ).count()
        assert audit_rows == 3, "expected one AuditLog delete row per deleted entity"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_bulk_delete_missing_api_key_401(client, db_session):
    """POST /transactions/bulk-delete without MONAI_API_KEY -> 401 (V2)."""
    resp = client.post("/transactions/bulk-delete", json={"ids": [1]})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


def test_bulk_recategorize(client, api_key, db_session):
    """POST /transactions/bulk-recategorize sets category on non-transfer
    rows; a selected transfer leg is SKIPPED (system-categorized) — its
    category is unchanged and no error is raised (D-03, critical item #6)."""
    import datetime as _dt
    from backend.models import Transaction
    from backend.writes import apply_add_transfer

    name_a, name_b = "zz17test-BulkRecatA", "zz17test-BulkRecatB"
    acc_a = _make_account(db_session, name_a)
    _make_account(db_session, name_b)
    try:
        leg_a, leg_b = apply_add_transfer(
            db_session,
            {"account": name_a, "amount": "-30000", "currency": "IDR"},
            {"account": name_b, "amount": "30000", "currency": "IDR"},
        )
        plain = Transaction(
            date=_dt.datetime(2024, 8, 5, 12, 0, 0), amount=-6000, currency="IDR",
            category="Uncategorized", account_id=acc_a, is_transfer=False,
        )
        db_session.add(plain)
        db_session.commit()
        db_session.refresh(leg_a)
        db_session.refresh(plain)
        leg_a_id, plain_id = leg_a.id, plain.id
        original_leg_category = leg_a.category

        resp = client.post(
            "/transactions/bulk-recategorize",
            json={"ids": [leg_a_id, plain_id], "category": "Food"},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert any(s["id"] == leg_a_id for s in data["skipped"]), (
            "a transfer-leg id must be reported in skipped[]"
        )

        db_session.expire_all()
        updated_plain = db_session.get(Transaction, plain_id)
        assert updated_plain.category == "Food"
        updated_leg = db_session.get(Transaction, leg_a_id)
        assert updated_leg.category == original_leg_category, "transfer-leg category must be unchanged"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_bulk_recategorize_missing_api_key_401(client, db_session):
    """POST /transactions/bulk-recategorize without MONAI_API_KEY -> 401 (V2)."""
    resp = client.post("/transactions/bulk-recategorize", json={"ids": [1], "category": "Food"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
