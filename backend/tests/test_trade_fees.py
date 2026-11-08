"""
Quick 261108-gdf: a fee on funded buys and sells.

One cost rule everywhere: a buy adds (price x stored quantity + fee value) x trade-date
rate to cost; a sell realizes (price x stored quantity - fee value) x rate - average cost
x stored quantity. A coin fee is paid in the asset (the stored quantity is the real
movement: net on a buy, sold + fee on a sell), a cash fee in the position's currency.

Synthetic values only: `ZZ45` accounts, `zz45-` platforms, round amounts, 1996 dates and a
made-up rate. Runs against monai_test only; the rate adapter is stubbed, so no network.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

from backend.tests.test_cross_currency_moves import (  # noqa: F401 — fixtures + helpers
    _ISO_DAY,
    _events,
    _funded,
    _holding,
    _post,
    _seed_event,
    db_available,
    db_session,
    zz45,
)

RATE = Decimal("16250.5")  # what zz45.rate() seeds by default
TOL = Decimal("0.000001")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    from backend import fx
    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", lambda base, quote, as_of: None)


def _ledger(zz45, plat, ticker="ZZ45T"):
    """(recompute result, native average cost, realized) read from the committed ledger."""
    from backend.portfolio import _realized_for_position, recompute_holding_from_events
    zz45.db.expire_all()
    result = recompute_holding_from_events(zz45.db, ticker, plat)
    zz45.db.flush()
    native = _realized_for_position(zz45.db, ticker, plat)
    return result, native


def _close(a, b):
    assert abs(Decimal(str(a)) - Decimal(str(b))) < TOL, (a, b)


def _buy(client, api_key, zz45, account, plat, **body):
    base = {"source_account_name": account, "platform_id": plat, "ticker": "ZZ45T",
            "quantity": 2, "price": 100, "cash_amount": 200, "date": _ISO_DAY}
    return _funded(client, api_key, "buy", **{**base, **body})


def _sell(client, api_key, zz45, account, plat, **body):
    base = {"source_account_name": account, "platform_id": plat, "ticker": "ZZ45T",
            "quantity": 1, "price": 120, "cash_amount": 120, "date": _ISO_DAY}
    return _funded(client, api_key, "sell", **{**base, **body})


# --- the tracer --------------------------------------------------------------------------


def test_tracer_coin_fee_buy_lands_net_and_costs_price_times_filled(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    resp = _buy(client, api_key, zz45, usd, plat, quantity=2, price=30000, cash_amount=60000,
                fee=0.002, fee_kind="coin")
    assert resp.status_code == 201, resp.text
    (ev,) = _events(zz45, plat)
    assert ev.quantity == Decimal("1.998") and ev.fee == Decimal("0.002") and ev.fee_kind == "coin"
    (leg,) = zz45.tx_rows(usd)
    assert leg.amount == Decimal("-60000")
    result, native = _ledger(zz45, plat)
    assert result["quantity"] == Decimal("1.998")
    _close(result["avg_cost"] * result["quantity"], Decimal(30000) * 2 * RATE)
    _close(native["native_avg_cost"], Decimal(60000) / Decimal("1.998"))


# --- buys and sells ----------------------------------------------------------------------


def test_cash_fee_buy_keeps_quantity_and_adds_the_fee_to_cost(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    resp = _buy(client, api_key, zz45, usd, plat, cash_amount=201.5, fee=1.5, fee_kind="cash")
    assert resp.status_code == 201, resp.text
    (ev,) = _events(zz45, plat)
    assert ev.quantity == Decimal("2") and ev.fee == Decimal("1.5") and ev.fee_kind == "cash"
    result, native = _ledger(zz45, plat)
    _close(result["avg_cost"] * result["quantity"], (Decimal(200) + Decimal("1.5")) * RATE)
    _close(native["native_avg_cost"], Decimal("100.75"))


def test_cash_fee_on_an_idr_funded_usd_position_leaves_the_typed_cash_leg(client, api_key, zz45):
    idr, plat = zz45.account("idr"), zz45.platform()
    zz45.rate(_ISO_DAY)
    resp = _buy(client, api_key, zz45, idr, plat, event_currency="USD", cash_amount=3300000,
                fee=1.5, fee_kind="cash")
    assert resp.status_code == 201, resp.text
    (leg,) = zz45.tx_rows(idr)
    assert leg.amount == Decimal("-3300000") and leg.currency == "IDR"
    result, _ = _ledger(zz45, plat)
    _close(result["avg_cost"] * result["quantity"], (Decimal(200) + Decimal("1.5")) * RATE)


def test_cash_fee_sell_realizes_net_of_the_fee(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    _seed_event(zz45, plat, "ZZ45T", "buy", 2, 100, "USD")
    resp = _sell(client, api_key, zz45, usd, plat, quantity=1, price=120, cash_amount=118,
                 fee=2, fee_kind="cash")
    assert resp.status_code == 201, resp.text
    (leg,) = zz45.tx_rows(usd)
    assert leg.amount == Decimal("118")  # exactly as sent
    result, _ = _ledger(zz45, plat)
    assert result["quantity"] == Decimal("1")
    _close(result["realized_pnl"], (Decimal(120) - 2) * RATE - Decimal(100) * RATE)


def test_coin_fee_sell_stores_sold_plus_fee_and_prices_it(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    _seed_event(zz45, plat, "ZZ45T", "buy", 2, 100, "USD")
    resp = _sell(client, api_key, zz45, usd, plat, quantity="0.5", price=120, cash_amount=60,
                 fee="0.01", fee_kind="coin")
    assert resp.status_code == 201, resp.text
    sell = [e for e in _events(zz45, plat) if e.event_type == "sell"][0]
    assert sell.quantity == Decimal("0.51") and sell.fee == Decimal("0.01")
    result, _ = _ledger(zz45, plat)
    assert result["quantity"] == Decimal("1.49")
    _close(result["realized_pnl"], Decimal(120) * Decimal("0.5") * RATE - Decimal(100) * RATE * Decimal("0.51"))


def test_coin_fee_sell_of_everything_closes_with_the_fee_in_realized(client, api_key, zz45):
    from backend.models import ClosedPosition
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    _seed_event(zz45, plat, "ZZ45T", "buy", 1, 100, "USD")
    resp = _sell(client, api_key, zz45, usd, plat, quantity="0.99", price=120, cash_amount="118.8",
                 fee="0.01", fee_kind="coin")
    assert resp.status_code == 201, resp.text
    zz45.db.expire_all()
    (rec,) = zz45.db.query(ClosedPosition).filter(ClosedPosition.platform_id == plat).all()
    expected = Decimal(120) * Decimal("0.99") * RATE - Decimal(100) * RATE
    assert abs(rec.realized_pnl - expected) < Decimal("0.01")  # stored to 2 decimals
    assert _holding(zz45, plat, "ZZ45T") is None and _events(zz45, plat) == []
    (leg,) = zz45.tx_rows(usd)
    assert leg.amount == Decimal("118.8")  # the cash leg is kept


def test_coin_fee_sell_beyond_the_holding_is_refused_and_saves_nothing(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    _seed_event(zz45, plat, "ZZ45T", "buy", 1, 100, "USD")
    resp = _sell(client, api_key, zz45, usd, plat, quantity=1, fee="0.01", fee_kind="coin")
    assert resp.status_code == 422, resp.text
    assert zz45.tx_rows(usd) == [] and len(_events(zz45, plat)) == 1


def test_fee_less_ledger_computes_as_before(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    assert _buy(client, api_key, zz45, usd, plat).status_code == 201
    assert _sell(client, api_key, zz45, usd, plat).status_code == 201
    assert all(e.fee is None and e.fee_kind is None for e in _events(zz45, plat))
    result, native = _ledger(zz45, plat)
    _close(result["avg_cost"], Decimal(100) * RATE)
    _close(result["realized_pnl"], (Decimal(120) * RATE - Decimal(100) * RATE) * 1)
    _close(native["native_avg_cost"], Decimal(100))


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize("extra", [
    {"fee": 0.5},                                  # a fee without a kind
    {"fee": 0.5, "fee_kind": "zzcoin"},            # a kind outside coin and cash
    {"fee": 2, "fee_kind": "coin"},                # a coin fee that eats the whole quantity
    {"fee": 3, "fee_kind": "coin"},                # ... or more
    {"fee": -1, "fee_kind": "cash"},               # negative
])
def test_bad_fees_are_refused_and_save_nothing(client, api_key, zz45, extra):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    resp = _buy(client, api_key, zz45, usd, plat, **extra)
    assert resp.status_code == 422, resp.text
    assert zz45.tx_rows(usd) == [] and _events(zz45, plat) == []


def test_a_zero_fee_stores_nothing(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    assert _buy(client, api_key, zz45, usd, plat, fee=0, fee_kind="coin").status_code == 201
    (ev,) = _events(zz45, plat)
    assert ev.fee is None and ev.fee_kind is None and ev.quantity == Decimal("2")


# --- reads and audit ---------------------------------------------------------------------


def test_get_returns_fee_kind_and_filled_quantity(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    assert _buy(client, api_key, zz45, usd, plat, fee=0.002, fee_kind="coin").status_code == 201
    assert _sell(client, api_key, zz45, usd, plat, quantity=1, fee="0.01", fee_kind="coin").status_code == 201
    assert _buy(client, api_key, zz45, usd, plat, quantity=3, cash_amount=300).status_code == 201
    rows = client.get(f"/portfolio-events?platform_id={plat}", headers={"MONAI_API_KEY": api_key}).json()
    by = {(r["event_type"], r["quantity"]): r for r in rows}
    coin_buy = by[("buy", 1.998)]
    assert coin_buy["fee"] == 0.002 and coin_buy["fee_kind"] == "coin" and coin_buy["filled_quantity"] == 2
    coin_sell = by[("sell", 1.01)]
    assert coin_sell["filled_quantity"] == 1
    plain = by[("buy", 3)]
    assert plain["fee"] is None and plain["filled_quantity"] == 3


def test_audit_carries_the_fee_as_a_string_and_fee_less_snapshots_are_unchanged(client, api_key, zz45):
    from backend.models import AuditLog
    from backend.writes import _portfolio_event_snapshot
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    assert _buy(client, api_key, zz45, usd, plat, fee=0.002, fee_kind="coin").status_code == 201
    assert _buy(client, api_key, zz45, usd, plat).status_code == 201
    with_fee, plain = _events(zz45, plat)
    row = zz45.db.query(AuditLog).filter(
        AuditLog.entity == "portfolio_event", AuditLog.entity_id == with_fee.id).one()
    assert row.after["fee"] == "0.002" and row.after["fee_kind"] == "coin"
    snap = _portfolio_event_snapshot(with_fee)
    assert isinstance(snap["fee"], str) and Decimal(snap["fee"]) == Decimal("0.002") and snap["fee_kind"] == "coin"
    assert Decimal(snap["quantity"]) == Decimal("1.998")
    assert "fee" not in _portfolio_event_snapshot(plain) and "fee_kind" not in _portfolio_event_snapshot(plain)


# --- edits never apply a fee twice ------------------------------------------------------


def _put(client, api_key, event_id, body):
    return client.put(f"/portfolio-events/{event_id}", json=body, headers={"MONAI_API_KEY": api_key})


def _coin_fee_buy(client, api_key, zz45):
    usd, plat = zz45.account("usd", "USD"), zz45.platform()
    zz45.rate(_ISO_DAY)
    assert _buy(client, api_key, zz45, usd, plat, fee=0.002, fee_kind="coin").status_code == 201
    (ev,) = _events(zz45, plat)
    return usd, plat, ev.id


def test_edit_of_the_price_alone_keeps_quantity_and_fee(client, api_key, zz45):
    usd, plat, eid = _coin_fee_buy(client, api_key, zz45)
    assert _put(client, api_key, eid, {"price": 110}).status_code == 200
    (ev,) = _events(zz45, plat)
    assert ev.quantity == Decimal("1.998") and ev.fee == Decimal("0.002") and ev.price == Decimal("110")


def test_edit_sending_the_filled_quantity_twice_gives_the_same_row(client, api_key, zz45):
    usd, plat, eid = _coin_fee_buy(client, api_key, zz45)
    for _ in range(2):
        filled = client.get(f"/portfolio-events?platform_id={plat}", headers={"MONAI_API_KEY": api_key}).json()[0]["filled_quantity"]
        assert filled == 2
        assert _put(client, api_key, eid, {"quantity": filled}).status_code == 200
        (ev,) = _events(zz45, plat)
        assert ev.quantity == Decimal("1.998") and ev.fee == Decimal("0.002")


def test_edit_with_a_new_fee_rederives_and_leaves_the_cash_leg(client, api_key, zz45):
    usd, plat, eid = _coin_fee_buy(client, api_key, zz45)
    assert _put(client, api_key, eid, {"fee": 0.004}).status_code == 200
    (ev,) = _events(zz45, plat)
    assert ev.quantity == Decimal("1.996") and ev.fee == Decimal("0.004") and ev.fee_kind == "coin"
    assert zz45.tx_rows(usd)[0].amount == Decimal("-200")
    assert _put(client, api_key, eid, {"cash_amount": 199}).status_code == 200
    assert zz45.tx_rows(usd)[0].amount == Decimal("-199")


def test_edit_with_a_zero_fee_clears_it_and_stores_the_filled_quantity(client, api_key, zz45):
    usd, plat, eid = _coin_fee_buy(client, api_key, zz45)
    assert _put(client, api_key, eid, {"fee": 0}).status_code == 200
    (ev,) = _events(zz45, plat)
    assert ev.quantity == Decimal("2") and ev.fee is None and ev.fee_kind is None


def test_a_fee_on_an_unfunded_event_is_refused(client, api_key, zz45):
    plat = zz45.platform()
    zz45.rate(_ISO_DAY)
    _seed_event(zz45, plat, "ZZ45T", "buy", 2, 100, "USD")
    (ev,) = _events(zz45, plat)
    resp = _put(client, api_key, ev.id, {"fee": 0.5, "fee_kind": "cash"})
    assert resp.status_code == 422, resp.text
    (ev,) = _events(zz45, plat)
    assert ev.fee is None


def test_the_fee_never_touches_a_cash_leg_it_was_not_sent_with(client, api_key, zz45):
    usd, plat, eid = _coin_fee_buy(client, api_key, zz45)
    before = zz45.tx_rows(usd)[0].amount
    assert _put(client, api_key, eid, {"fee": 0.01}).status_code == 200
    assert zz45.tx_rows(usd)[0].amount == before
