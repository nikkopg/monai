"""Hand-run script converting one platform's open IDR positions to USD (quick 261108-bkz).

Runs only against per-process scratch databases `monai_test_closezero_<token>_conv...`,
created and dropped on the same server as conftest's guarded DATABASE_URL. Never touches
`monai` or `monai_test`. CLI tests run the owner's real command as a subprocess. All values
are synthetic; no test reaches the network (rates are cached, the in-process adapter is stubbed).

Platform P is converted; platform Q holds the same ticker as position A and must not move.
"""
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from backend.tests.test_close_zero_positions import (
    REPO_ROOT,
    REV_021,
    WIPE,
    _dump,
    _rows,
    _Scratch,
    _session,
)

Q12 = Decimal("1e-12")
D1 = date(2026, 3, 2)
D2 = date(2026, 4, 6)
D3 = date(2026, 5, 4)
D4 = date(2026, 6, 1)
RATES = {D1: "15800", D2: "16000", D3: "16250.5", D4: "16400"}  # USD -> IDR, made up
SNAP_DAY = date(2026, 5, 20)
LEFT_ALONE = {
    "ZZCUZ": "zero_quantity", "CASH": "cash", "ZZCUN": "no_events",
    "ZZCUM": "mixed_currency", "ZZCUT": "rate_not_final", "ZZCUL": "ledger_mismatch",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from backend import fx

    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", lambda base, quote, as_of: None)


@pytest.fixture(scope="module")
def scratch_conv():
    with _Scratch("conv", "head") as s:
        yield s


@pytest.fixture()
def seeded(scratch_conv):
    eng = scratch_conv.engine
    with eng.begin() as c:
        assert c.execute(text("SELECT current_database()")).scalar() == scratch_conv.name
        c.execute(text(WIPE))
    ids = _seed(eng)
    ids["engine"], ids["url"] = eng, scratch_conv.url
    return ids


def _seed(eng) -> dict:
    from backend.portfolio import recompute_holding_from_events

    ids: dict = {}
    with eng.begin() as c:
        def q(sql, **p):
            return c.execute(text(sql), p).scalar()

        P = ids["P"] = q("INSERT INTO platforms (name, kind) VALUES ('zzcu-p', 'exchange') RETURNING id")
        Q = ids["Q"] = q("INSERT INTO platforms (name, kind) VALUES ('zzcu-q', 'broker') RETURNING id")
        ids["idr_acct"] = q("INSERT INTO accounts (name, type, currency) VALUES ('zzcu-idr', 'liquid', 'IDR') RETURNING id")
        ids["usd_acct"] = q("INSERT INTO accounts (name, type, currency) VALUES ('zzcu-usd', 'liquid', 'USD') RETURNING id")
        for day, rate in RATES.items():
            c.execute(text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
                "VALUES (:d, 'USD', 'IDR', :r, 'zzcu')"), {"d": day, "r": rate})

        def ev(plat, ticker, kind, qty, price, day, ccy="IDR", tx=None, acct=None):
            return q(
                "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency, "
                "transaction_id, source_account_id) VALUES (:d, :t, :k, :q, :pr, :p, :c, :tx, :a) RETURNING id",
                d=day, t=ticker, k=kind, q=qty, pr=price, p=plat, c=ccy, tx=tx, a=acct)

        # A: IDR crypto. A first buy marked by migration 012, a funded buy, a partial sell, a dividend.
        ids["A_first"] = ev(P, "ZZCUA", "buy", "10", "15800", D1)
        tx = ids["A_tx"] = q(
            "INSERT INTO transactions (date, amount, currency, account_id, is_transfer, category) "
            "VALUES ('2026-04-06 10:00', -85000, 'IDR', :a, true, 'Investment') RETURNING id", a=ids["idr_acct"])
        ev(P, "ZZCUA", "buy", "5", "17000", D2, tx=tx, acct=ids["idr_acct"])
        ev(P, "ZZCUA", "sell", "4", "18000", D3)
        ev(P, "ZZCUA", "dividend", "1", "1000", D4)
        c.execute(text(
            "INSERT INTO audit_log (entity, entity_id, operation, before, after) "
            "VALUES ('portfolio_event', :i, 'add', NULL, CAST(:a AS jsonb))"),
            {"i": ids["A_first"], "a": json.dumps({"source": "opening_balance_backfill_012"})})
        # B: one buy whose price over the rate does not terminate.
        ev(P, "ZZCUB", "buy", "3", "100", D1)
        # Left alone.
        ev(P, "ZZCUZ", "buy", "1", "10", D1)
        ev(P, "ZZCUZ", "sell", "1", "10", D1)
        ev(P, "CASH", "deposit", "100", "1", D1)
        ev(P, "ZZCUM", "buy", "1", "10", D1)
        ev(P, "ZZCUM", "buy", "1", "5", D1, ccy="USD")
        ev(P, "ZZCUT", "buy", "1", "10", date(2099, 1, 1))
        ev(P, "ZZCUL", "buy", "2", "50", D1)
        ev(P, "ZZCUU", "buy", "2", "7", D1, ccy="USD")  # already USD
        ev(Q, "ZZCUA", "buy", "1", "100", D1)
        c.execute(text("INSERT INTO closed_positions (ticker, platform_id, realized_pnl, close_date) "
                       "VALUES ('ZZCUC', :p, 123, '2026-02-01')"), {"p": P})
        for t, price in (("ZZCUA", 20000), ("ZZCUB", 150)):
            c.execute(text("INSERT INTO price_cache (ticker, price, currency, source) VALUES (:t, :p, 'IDR', 'zzcu')"),
                      {"t": t, "p": price})

    db = _session(eng)
    for plat, t in ((P, "ZZCUA"), (P, "ZZCUB"), (P, "ZZCUZ"), (P, "ZZCUL"), (P, "ZZCUU"), (Q, "ZZCUA")):
        recompute_holding_from_events(db, t, plat)
    db.commit()
    db.close()
    with eng.begin() as c:
        c.execute(text("UPDATE holdings SET asset_type='crypto', coingecko_id='zz-coin' WHERE ticker='ZZCUA' AND platform_id=:p"), {"p": P})
        c.execute(text("UPDATE holdings SET asset_type='stock' WHERE ticker='ZZCUB'"))
        c.execute(text("UPDATE holdings SET quantity=3 WHERE ticker='ZZCUL'"))  # the stored row differs from its ledger
        for t, qty, avg, at in (("CASH", 100, 1, "cash"), ("ZZCUN", 5, 10, None), ("ZZCUM", 2, 7.5, None), ("ZZCUT", 1, 10, None)):
            c.execute(text("INSERT INTO holdings (ticker, quantity, avg_cost, currency, asset_type, platform_id) "
                           "VALUES (:t, :q, :a, 'IDR', :at, :p)"), {"t": t, "q": qty, "a": avg, "at": at, "p": P})
        for t, qty, mv in (("ZZCUA", 11, 220000), ("ZZCUB", 3, 450)):
            c.execute(text("INSERT INTO portfolio_value_history (snapshot_date, ticker, quantity, market_value, cost_basis, currency, platform_id) "
                           "VALUES (:d, :t, :q, :m, :m, 'IDR', :p)"), {"d": SNAP_DAY, "t": t, "q": qty, "m": mv, "p": P})
    return ids


def _cli(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "backend.convert_platform_to_usd", *args],
        cwd=REPO_ROOT, env={**os.environ, "DATABASE_URL": url},
        capture_output=True, text=True, timeout=120,
    )


def _line(out: str, ticker: str) -> str:
    hits = [ln for ln in out.splitlines() if f"ticker={ticker} " in ln + " "]
    assert len(hits) == 1, (ticker, out)
    return hits[0]


def _field(line: str, name: str) -> str:
    return re.search(rf"{name}=(\S+)", line).group(1)


def _usd(idr_price, day) -> Decimal:
    return (Decimal(idr_price) / Decimal(RATES[day])).quantize(Q12, ROUND_HALF_UP)


# (ticker, event dates) of the two convertible positions with their IDR prices
EVENTS = {
    "ZZCUA": [("15800", D1, 10), ("17000", D2, 5), ("18000", D3, 4), ("1000", D4, 1)],
    "ZZCUB": [("100", D1, 3)],
}


def _tol(ticker) -> Decimal:
    return sum((Decimal(qty) * Decimal(RATES[d]) * Decimal("5e-13") for _, d, qty in EVENTS[ticker]), Decimal("1e-12"))


def _position(db, ticker, pid):
    """(IDR cost basis unrounded, realized) by recompute; the session is rolled back."""
    from backend.portfolio import recompute_holding_from_events

    r = recompute_holding_from_events(db, ticker, pid)
    out = (r["avg_cost"] * r["quantity"], r["realized_pnl"])
    db.rollback()
    return out


def _holding_row(summary, pid, ticker):
    return next(h for g in summary["groups"] if g["platform_id"] == pid for h in g["holdings"] if h["ticker"] == ticker)


# --- boot: nothing runs ----------------------------------------------------------------


def test_script_not_wired_to_boot():
    files = [
        "backend/entrypoint.sh", "backend/Dockerfile", "docker-compose.yml",
        "backend/main.py", "backend/scheduler.py", "alembic/env.py",
        *(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "alembic" / "versions").glob("*.py")),
    ]
    for f in files:
        assert "convert_platform_to_usd" not in (REPO_ROOT / f).read_text(), f


# --- the CLI ----------------------------------------------------------------------------


def test_cli_defaults_to_dry_run(seeded):
    before = _dump(seeded["engine"])
    r = _cli(seeded["url"], "--platform-id", str(seeded["P"]))
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    lines = out.splitlines()
    assert lines[0].startswith(f"database: {make_url(seeded['url']).database} ")
    assert "mode: dry run" in lines[1] and "name=zzcu-p" in out
    assert "convert: 2" in out and "left alone: 6" in out
    for t, reason in LEFT_ALONE.items():
        assert _field(_line(out, t), "left_alone") == reason, (t, out)
    a = _line(out, "ZZCUA")
    assert _field(a, "events") == "4" and _field(a, "events_before_snapshot_floor") == "3"
    for f in ("cost_idr_before", "cost_idr_after", "realized_idr_before", "realized_idr_after", "tolerance"):
        assert f"{f}=" in a
    assert "platform currency: IDR -> USD" in out
    assert "Dry run" in out
    assert _dump(seeded["engine"]) == before  # byte-identical


def test_cli_apply_then_second_apply_changes_nothing(seeded):
    eng, P = seeded["engine"], seeded["P"]
    r = _cli(seeded["url"], "--platform-id", str(P), "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Applied: one transaction committed." in r.stdout
    assert _rows(eng, "platforms", "id=:i", i=P)[0].count('"currency": "USD"') == 1
    mid = _dump(eng)
    r2 = _cli(seeded["url"], "--platform-id", str(P), "--apply")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "Nothing to convert." in r2.stdout and "already USD" in r2.stdout
    assert _dump(eng) == mid


def test_cli_usage_errors_write_nothing(seeded):
    before = _dump(seeded["engine"])
    r = _cli(seeded["url"], "--apply")  # --platform-id is required
    assert r.returncode != 0
    r = _cli(seeded["url"], "--platform-id", "999999", "--apply")
    assert r.returncode == 1 and "No platform" in r.stdout
    assert _dump(seeded["engine"]) == before


def test_cli_refuses_a_database_at_021():
    with _Scratch("old021", REV_021) as s:
        r = _cli(s.url, "--platform-id", "1", "--apply")
        assert r.returncode == 1
        assert "alembic upgrade head" in r.stdout
        assert "Traceback" not in r.stdout + r.stderr


# --- run(): values, audit, trend ---------------------------------------------------------


def _before(seeded):
    """IDR facts before conversion, read through a throwaway session."""
    from backend.portfolio import portfolio_summary, value_history_series

    db = _session(seeded["engine"])
    try:
        out = {
            "summary": portfolio_summary(db),
            "pos": {t: _position(db, t, seeded["P"]) for t in EVENTS},
            "history": value_history_series(db),
            "ev": {r[0]: r for r in db.execute(text(
                "SELECT id, date, ticker, quantity, price FROM portfolio_events WHERE platform_id=:p AND ticker IN ('ZZCUA','ZZCUB')"),
                {"p": seeded["P"]})},
            "holding": {r[0]: r for r in db.execute(text(
                "SELECT ticker, quantity, avg_cost, asset_type, coingecko_id FROM holdings WHERE platform_id=:p AND ticker IN ('ZZCUA','ZZCUB')"),
                {"p": seeded["P"]})},
        }
    finally:
        db.close()
    return out


def test_apply_converts_and_keeps_idr_values(seeded):
    import backend.convert_platform_to_usd as cpu
    from backend.portfolio import portfolio_summary

    P = seeded["P"]
    before = _before(seeded)
    db = _session(seeded["engine"])
    try:
        rep = cpu.run(db, P, apply=True)
    finally:
        db.close()
    assert [c["ticker"] for c in rep["convert"]] == ["ZZCUA", "ZZCUB"]
    assert {x["ticker"]: x["reason"] for x in rep["left"]} == LEFT_ALONE

    db = _session(seeded["engine"])
    try:
        after = portfolio_summary(db)
        for t in EVENTS:
            # each event: price over its own date's rate, quantized half up; ids unchanged
            now = {r[0]: r for r in db.execute(text(
                "SELECT id, price, currency FROM portfolio_events WHERE platform_id=:p AND ticker=:t"), {"p": P, "t": t})}
            old = {i: r for i, r in before["ev"].items() if r[2] == t}
            assert set(now) == set(old)
            for i, r in old.items():
                assert now[i][2] == "USD"
                assert now[i][1] == _usd(r[4], r[1])  # computed from the seeds, never hardcoded
            h = db.execute(text("SELECT currency, quantity, avg_cost, asset_type, coingecko_id FROM holdings "
                                "WHERE platform_id=:p AND ticker=:t"), {"p": P, "t": t}).one()
            b = before["holding"][t]
            assert h.currency == "USD"
            assert (h.quantity, h.avg_cost, h.asset_type, h.coingecko_id) == (b[1], b[2], b[3], b[4])

            cost_b, real_b = before["pos"][t]
            cost_a, real_a = _position(db, t, P)
            assert abs(cost_a - cost_b) <= _tol(t) and abs(real_a - real_b) <= _tol(t)
            r = next(c for c in rep["convert"] if c["ticker"] == t)
            assert r["tolerance"] == _tol(t) and r["events"] == len(EVENTS[t])

            row_b, row_a = _holding_row(before["summary"], P, t), _holding_row(after, P, t)
            price = db.execute(text("SELECT price FROM price_cache WHERE ticker=:t"), {"t": t}).scalar()
            assert row_a["current_value"] == price * row_a["quantity"]  # priced once, in IDR
            assert row_a["current_value"] == row_b["current_value"]
            assert row_a["unrealized_pnl"] == row_b["unrealized_pnl"]
            assert row_a["currency"] == "USD"
        total_tol = sum(_tol(t) for t in EVENTS)
        assert abs(after["total_realized_pnl"] - before["summary"]["total_realized_pnl"]) <= total_tol
        assert db.execute(text("SELECT currency FROM platforms WHERE id=:p"), {"p": P}).scalar() == "USD"
        assert db.execute(text("SELECT currency FROM platforms WHERE id=:q"), {"q": seeded["Q"]}).scalar() == "IDR"
    finally:
        db.close()


def test_apply_leaves_everything_else_alone_and_audits(seeded):
    import backend.convert_platform_to_usd as cpu
    from backend.investment_reconstruction import _synthetic_event_ids

    eng, P = seeded["engine"], seeded["P"]
    keep = {
        "closed_positions": ("closed_positions", "true"),
        "transactions": ("transactions", "true"),
        "price_cache": ("price_cache", "true"),
        "portfolio_value_history": ("portfolio_value_history", "true"),
        "fx_rate_cache": ("fx_rate_cache", "true"),
        "q_holdings": ("holdings", f"platform_id={seeded['Q']}"),
        "q_events": ("portfolio_events", f"platform_id={seeded['Q']}"),
        "p_left_holdings": ("holdings", f"platform_id={P} AND ticker NOT IN ('ZZCUA','ZZCUB')"),
        "p_left_events": ("portfolio_events", f"platform_id={P} AND ticker NOT IN ('ZZCUA','ZZCUB')"),
        "other_platform": ("platforms", f"id={seeded['Q']}"),
    }
    held = {k: _rows(eng, t, w) for k, (t, w) in keep.items()}
    audit_before = _rows(eng, "audit_log", "true")
    with eng.connect() as c:
        syn_before = _synthetic_event_ids(c)
    assert seeded["A_first"] in syn_before

    db = _session(eng)
    try:
        cpu.run(db, P, apply=True)
    finally:
        db.close()

    for k, (t, w) in keep.items():
        assert _rows(eng, t, w) == held[k], k
    with eng.connect() as c:
        assert _synthetic_event_ids(c) == syn_before  # ids unchanged, still excluded
    new = [json.loads(r) for r in set(_rows(eng, "audit_log", "true")) - set(audit_before)]
    assert len(new) == 5 + 2 + 1
    assert {n["operation"] for n in new} == {"edit"}
    by_entity = {e: sum(1 for n in new if n["entity"] == e) for e in ("portfolio_event", "holding", "platform")}
    assert by_entity == {"portfolio_event": 5, "holding": 2, "platform": 1}

    def scalars(v):
        assert v is None or isinstance(v, (str, int)) and not isinstance(v, bool), v

    for n in new:
        for side in (n["before"], n["after"]):
            for v in side.values():
                scalars(v)
        if n["entity"] == "portfolio_event":
            assert n["before"]["currency"] == "IDR" and n["after"]["currency"] == "USD"
            assert n["after"]["source"] == "usd_conversion" and Decimal(n["after"]["rate"]) > 0


def test_trend_does_not_move(seeded):
    import backend.convert_platform_to_usd as cpu
    from backend.investment_reconstruction import monthly_investment_series
    from backend.portfolio import value_history_series

    def series():
        db = _session(seeded["engine"])
        try:
            return monthly_investment_series(months=12, db=db)["rows"], value_history_series(db)
        finally:
            db.close()

    rows_b, hist_b = series()
    db = _session(seeded["engine"])
    try:
        cpu.run(db, seeded["P"], apply=True)
    finally:
        db.close()
    rows_a, hist_a = series()
    assert hist_a == hist_b
    assert [r["month"] for r in rows_a] == [r["month"] for r in rows_b]
    tol = sum(_tol(t) for t in EVENTS) * 4  # a month sums several replayed positions
    assert any(r["investment_total"] is not None for r in rows_b)
    for b, a in zip(rows_b, rows_a):
        for k in ("honest", "gap_reason", "valuation_basis"):
            assert a[k] == b[k], (b["month"], k)
        if b["investment_total"] is None:
            assert a["investment_total"] is None
        else:
            assert abs(a["investment_total"] - b["investment_total"]) <= tol, b["month"]


def test_position_without_a_cached_rate_is_left_alone(seeded):
    import backend.convert_platform_to_usd as cpu
    from backend.portfolio import recompute_holding_from_events

    P, eng = seeded["P"], seeded["engine"]
    with eng.begin() as c:  # a past date no rate is cached for; the adapter is stubbed to None
        c.execute(text("INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency) "
                       "VALUES ('2026-02-03', 'ZZCUR', 'buy', 1, 40, :p, 'IDR')"), {"p": P})
    db = _session(eng)
    recompute_holding_from_events(db, "ZZCUR", P)
    db.commit()
    db.close()
    mine = lambda: (_rows(eng, "holdings", "ticker='ZZCUR'"), _rows(eng, "portfolio_events", "ticker='ZZCUR'"))  # noqa: E731
    r_before = mine()

    db = _session(eng)
    try:
        rep = cpu.run(db, P, apply=True)
    finally:
        db.close()
    assert [x["reason"] for x in rep["left"] if x["ticker"] == "ZZCUR"] == ["no_rate"]
    assert [c["ticker"] for c in rep["convert"]] == ["ZZCUA", "ZZCUB"]
    assert mine() == r_before


def test_apply_is_one_transaction(seeded, monkeypatch):
    import backend.convert_platform_to_usd as cpu

    real, calls = cpu.recompute_holding_from_events, []

    def boom(db, ticker, platform_id):
        calls.append(ticker)
        if ticker == "ZZCUB":  # the second position
            raise RuntimeError("synthetic failure on the second position")
        return real(db, ticker, platform_id)

    monkeypatch.setattr(cpu, "recompute_holding_from_events", boom)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(RuntimeError, match="nothing was changed"):
            cpu.run(db, seeded["P"], apply=True)
    finally:
        db.close()
    assert "ZZCUA" in calls and "ZZCUB" in calls
    assert _dump(seeded["engine"]) == before  # the first position was rolled back too


def test_apply_aborts_if_cash_changes(seeded, monkeypatch):
    import backend.convert_platform_to_usd as cpu
    from backend.models import Transaction

    real = cpu.recompute_holding_from_events

    def sneaky(db, ticker, platform_id):
        out = real(db, ticker, platform_id)
        tx = db.get(Transaction, seeded["A_tx"])
        if tx is not None and ticker == "ZZCUB":
            db.delete(tx)
        return out

    monkeypatch.setattr(cpu, "recompute_holding_from_events", sneaky)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(Exception, match="nothing was changed"):
            cpu.run(db, seeded["P"], apply=True)
    finally:
        db.close()
    assert _dump(seeded["engine"]) == before


# --- trading a converted ticker afterwards -----------------------------------------------


def test_new_trades_on_a_converted_ticker(seeded):
    import backend.convert_platform_to_usd as cpu
    from backend.writes import apply_add_funded_buy

    P, eng = seeded["P"], seeded["engine"]
    db = _session(eng)
    try:
        cpu.run(db, P, apply=True)
    finally:
        db.close()

    def buy(account, **extra):
        return {"source_account_name": account, "ticker": "ZZCUB", "quantity": "1", "price": "0.123456789012",
                "cash_amount": Decimal("0.12"), "platform_id": P, "date": "2026-06-01", **extra}

    db = _session(eng)
    try:
        r = apply_add_funded_buy(db, buy("zzcu-usd"))  # one amount
        assert r["portfolio_event"].currency == "USD" and r["transaction"].currency == "USD"
        db.commit()
        with eng.connect() as c:
            stored = c.execute(text("SELECT price FROM portfolio_events WHERE id=:i"), {"i": r["portfolio_event"].id}).scalar()
        assert stored == Decimal("0.123456789012")

        r = apply_add_funded_buy(db, buy("zzcu-idr", cash_amount=Decimal("2000")))  # two amounts
        assert r["portfolio_event"].currency == "USD"
        assert r["transaction"].currency == "IDR" and r["transaction"].amount == Decimal("-2000")
        db.commit()

        with pytest.raises(ValueError, match="does not match holding currency"):
            apply_add_funded_buy(db, buy("zzcu-idr", event_currency="IDR", cash_amount=Decimal("100")))
    finally:
        db.rollback()
        db.close()
