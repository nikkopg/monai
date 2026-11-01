"""
Phase 45 (MOVE-01..04): money moves between USD and IDR with BOTH amounts entered.

Transfers, liquid->platform deposits and funded buys/sells reach the same
primitives from REST, chat confirm and MCP confirm, so the two-amount rules are
pinned here once. No FX rate is computed or stored: each leg keeps exactly the
amount the owner typed.

Synthetic values only: `ZZ45` account names, lowercase `zz45-` platform names,
round amounts, 1996 dates and made-up rates. Runs against monai_test only.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

_RATE_RANGE = ("1996-03-01", "1996-03-31")
_ISO_DAY = "1996-03-02"  # a Saturday: the cached rate comes from Friday 03-01 in the route tests


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


def _purge(db, proposal_ids=()) -> None:
    """Delete everything a ZZ45 test can have written, by prefix."""
    db.rollback()
    acc = "(SELECT id FROM accounts WHERE name LIKE 'ZZ45%')"
    plat = "(SELECT id FROM platforms WHERE name LIKE 'zz45-%')"
    for sql in (
        f"DELETE FROM audit_log WHERE entity = 'portfolio_event' AND entity_id IN "
        f"(SELECT id FROM portfolio_events WHERE platform_id IN {plat} OR source_account_id IN {acc})",
        f"DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id IN "
        f"(SELECT id FROM transactions WHERE account_id IN {acc})",
        f"DELETE FROM audit_log WHERE entity = 'holding' AND entity_id IN "
        f"(SELECT id FROM holdings WHERE platform_id IN {plat})",
        f"DELETE FROM portfolio_events WHERE platform_id IN {plat} OR source_account_id IN {acc}",
        f"DELETE FROM holdings WHERE platform_id IN {plat}",
        f"DELETE FROM transactions WHERE account_id IN {acc}",
        f"DELETE FROM platforms WHERE id IN {plat}",
        "DELETE FROM accounts WHERE name LIKE 'ZZ45%'",
        "DELETE FROM price_cache WHERE ticker LIKE 'ZZ45%'",
        f"DELETE FROM fx_rate_cache WHERE rate_date BETWEEN '{_RATE_RANGE[0]}' AND '{_RATE_RANGE[1]}' "
        "AND base_currency = 'USD' AND quote_currency = 'IDR'",
    ):
        db.execute(text(sql))
    for pid in proposal_ids:
        db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": pid})
    db.commit()


class _Zz45:
    """Factory handed to tests; the fixture purges by prefix before and after."""

    def __init__(self, db):
        self.db = db
        self.proposal_ids: list = []

    def account(self, label: str, currency: str = "IDR") -> str:
        from backend.models import Account
        name = f"ZZ45 {label}-{uuid.uuid4().hex[:6]}"
        self.db.add(Account(name=name, type="liquid", currency=currency))
        self.db.commit()
        return name

    def platform(self, label: str = "plat") -> int:
        from backend.models import Platform
        plat = Platform(name=f"zz45-{label}-{uuid.uuid4().hex[:6]}", kind="exchange")
        self.db.add(plat)
        self.db.commit()
        return plat.id

    def rate(self, day: str, rate: str = "16250.5") -> None:
        """Seed one cached USD->IDR rate (the position recompute reads it for USD events)."""
        self.db.execute(
            text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
                "VALUES (:d, 'USD', 'IDR', :r, 'zz45') ON CONFLICT DO NOTHING"
            ),
            {"d": day, "r": rate},
        )
        self.db.commit()

    def proposal(self, operation: str, after: dict) -> tuple[str, str]:
        from backend.models import Proposal
        token = secrets.token_urlsafe(32)
        p = Proposal(
            token=token, operation=operation,
            payload={"operation": operation, "rows": [{"after": after}]},
            status="pending", channel="chat",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.db.add(p)
        self.db.commit()
        self.proposal_ids.append(p.id)
        return str(p.id), token

    def tx_rows(self, *names: str) -> list:
        from backend.models import Account, Transaction
        ids = [a.id for a in self.db.query(Account).filter(Account.name.in_(names)).all()]
        self.db.expire_all()
        return self.db.query(Transaction).filter(Transaction.account_id.in_(ids)).order_by(Transaction.id).all()


@pytest.fixture()
def zz45(db_session):
    _purge(db_session)
    z = _Zz45(db_session)
    yield z
    _purge(db_session, z.proposal_ids)


def _post(client, api_key, path, body):
    return client.post(path, json=body, headers={"MONAI_API_KEY": api_key})


# ---------------------------------------------------------------------------
# Task 1: transfers (MOVE-01, D-06)
# ---------------------------------------------------------------------------

def test_rest_transfer_usd_to_idr_two_exact_legs(client, api_key, zz45):
    usd, idr = zz45.account("usd", "USD"), zz45.account("idr")
    resp = _post(client, api_key, "/transactions/transfer", {
        "from_account": usd, "to_account": idr, "amount": 100.00, "to_amount": 1631000, "date": _ISO_DAY,
    })
    assert resp.status_code == 201, resp.text
    leg_a_id = resp.json()["leg_a_id"]
    rows = zz45.tx_rows(usd, idr)
    assert len(rows) == 2
    by_ccy = {r.currency: r for r in rows}
    assert by_ccy["USD"].amount == Decimal("-100.00")
    assert by_ccy["IDR"].amount == Decimal("1631000")
    assert all(r.is_transfer for r in rows)
    assert all(r.transfer_pair_id == leg_a_id for r in rows)


def test_confirmed_proposal_transfer_with_to_amount(client, api_key, zz45):
    usd, idr = zz45.account("usd", "USD"), zz45.account("idr")
    pid, token = zz45.proposal("add_transfer", {
        "leg_a": {"account": usd, "amount": "-100.00", "date": _ISO_DAY},
        "leg_b": {"account": idr, "amount": "100.00", "date": _ISO_DAY},
        "to_amount": "1631000",
    })
    resp = _post(client, api_key, f"/proposals/{pid}/confirm", {"token": token})
    assert resp.status_code == 200, resp.text
    by_ccy = {r.currency: r for r in zz45.tx_rows(usd, idr)}
    assert by_ccy["USD"].amount == Decimal("-100.00")
    assert by_ccy["IDR"].amount == Decimal("1631000")  # from to_amount, not leg_b.amount


def test_cross_currency_without_to_amount_refused(client, api_key, zz45):
    from backend.writes import apply_add_transfer
    usd, idr = zz45.account("usd", "USD"), zz45.account("idr")
    for extra in ({}, {"currency": "USD"}):
        resp = _post(client, api_key, "/transactions/transfer", {
            "from_account": usd, "to_account": idr, "amount": 25, "date": _ISO_DAY, **extra,
        })
        assert resp.status_code == 422, f"{extra}: {resp.text}"
        detail = resp.json()["detail"]
        assert "USD" in detail and "IDR" in detail and "need both amounts" in detail
    with pytest.raises(ValueError, match="USD.*IDR.*need both amounts"):
        apply_add_transfer(
            zz45.db,
            {"account": usd, "amount": "-25", "date": _ISO_DAY},
            {"account": idr, "amount": "25", "date": _ISO_DAY},
        )
    zz45.db.rollback()
    assert zz45.tx_rows(usd, idr) == []


def test_same_currency_to_amount_rules(client, api_key, zz45):
    a, b = zz45.account("idr-a"), zz45.account("idr-b")
    body = {"from_account": a, "to_account": b, "amount": 5000, "date": _ISO_DAY}

    resp = _post(client, api_key, "/transactions/transfer", {**body, "to_amount": 5000})
    assert resp.status_code == 201, resp.text
    assert sorted(r.amount for r in zz45.tx_rows(a, b)) == [Decimal("-5000"), Decimal("5000")]
    assert {r.currency for r in zz45.tx_rows(a, b)} == {"IDR"}

    before = len(zz45.tx_rows(a, b))
    resp = _post(client, api_key, "/transactions/transfer", {**body, "to_amount": 4900})
    assert resp.status_code == 422
    assert len(zz45.tx_rows(a, b)) == before

    resp = _post(client, api_key, "/transactions/transfer", body)
    assert resp.status_code == 201, resp.text
    assert len(zz45.tx_rows(a, b)) == before + 2


def test_to_amount_bad_values_refused(client, api_key, zz45):
    from backend.writes import apply_add_transfer
    usd, idr = zz45.account("usd", "USD"), zz45.account("idr")
    for bad in (0, -5):
        resp = _post(client, api_key, "/transactions/transfer", {
            "from_account": usd, "to_account": idr, "amount": 10, "to_amount": bad, "date": _ISO_DAY,
        })
        assert resp.status_code == 422, f"to_amount={bad}: {resp.text}"
    for bad in ("0", "-5", "NaN", "Infinity"):
        with pytest.raises(ValueError, match="to_amount must be a positive amount"):
            apply_add_transfer(
                zz45.db,
                {"account": usd, "amount": "-10", "date": _ISO_DAY},
                {"account": idr, "amount": "10", "date": _ISO_DAY},
                to_amount=bad,
            )
    zz45.db.rollback()
    assert zz45.tx_rows(usd, idr) == []


def test_cross_currency_pair_leaves_cashflow_unchanged(client, api_key, zz45):
    from backend import tools
    usd, idr = zz45.account("usd", "USD"), zz45.account("idr")
    window = {"period": "custom", "start_date": "1996-03-01", "end_date": "1996-03-31"}
    before = (tools.TOOLS["spending_total"](**window), tools.TOOLS["income_total"](**window))
    resp = _post(client, api_key, "/transactions/transfer", {
        "from_account": usd, "to_account": idr, "amount": 100, "to_amount": 1631000, "date": _ISO_DAY,
    })
    assert resp.status_code == 201, resp.text
    after = (tools.TOOLS["spending_total"](**window), tools.TOOLS["income_total"](**window))
    assert after == before
    ids = [r.id for r in zz45.tx_rows(usd, idr)]
    assert len(ids) == 2  # no third (FX plug) row
    counted = zz45.db.execute(
        text("SELECT COUNT(*) FROM cashflow_transactions WHERE is_transfer = false AND id = ANY(:ids)"),
        {"ids": ids},
    ).scalar()
    assert counted == 0
