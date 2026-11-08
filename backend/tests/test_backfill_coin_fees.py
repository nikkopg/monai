"""Hand-run script recording a coin fee on one position's funded buys (quick 261108-gdf).

Runs only against per-process scratch databases `monai_test_closezero_<token>_fee...`,
created and dropped on the same server as conftest's guarded DATABASE_URL. Never touches
`monai` or `monai_test`. CLI tests run the owner's real command as a subprocess. All values
are synthetic; no test reaches the network (rates are cached, the in-process adapter is stubbed).

Platform P holds the positions below; platform Q holds the same ticker as ZZFEA and must not move.
"""
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from backend.tests.test_close_zero_positions import (
    REPO_ROOT,
    REV_022,
    WIPE,
    _dump,
    _rows,
    _Scratch,
    _session,
)

D1 = date(2026, 3, 2)
D2 = date(2026, 4, 6)
D3 = date(2026, 5, 4)
RATES = {D1: Decimal("15800"), D2: Decimal("16000"), D3: Decimal("16250.5")}  # USD -> IDR, made up
SNAP_DAY = date(2026, 5, 20)
TOL = Decimal("0.000001")
LEFT_ALONE = {
    "ZZFEN": "negative_running_quantity", "ZZFEL": "ledger_mismatch", "ZZFER": "no_rate",
    "ZZFEZ": "zero_quantity", "CASH": "cash", "ZZFEC": "no_position", "ZZFEX": "no_position",
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from backend import fx

    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", lambda base, quote, as_of: None)


@pytest.fixture(scope="module")
def scratch_fee():
    with _Scratch("fee", "head") as s:
        yield s


@pytest.fixture()
def seeded(scratch_fee):
    eng = scratch_fee.engine
    with eng.begin() as c:
        assert c.execute(text("SELECT current_database()")).scalar() == scratch_fee.name
        c.execute(text(WIPE))
    ids = _seed(eng)
    ids["engine"], ids["url"] = eng, scratch_fee.url
    return ids


def _seed(eng) -> dict:
    from backend.portfolio import recompute_holding_from_events

    ids: dict = {}
    with eng.begin() as c:
        def q(sql, **p):
            return c.execute(text(sql), p).scalar()

        P = ids["P"] = q("INSERT INTO platforms (name, kind) VALUES ('zzfe-p', 'exchange') RETURNING id")
        Q = ids["Q"] = q("INSERT INTO platforms (name, kind) VALUES ('zzfe-q', 'exchange') RETURNING id")
        acct = ids["acct"] = q("INSERT INTO accounts (name, type, currency) VALUES ('zzfe-usd', 'liquid', 'USD') RETURNING id")
        for day, rate in RATES.items():
            c.execute(text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
                "VALUES (:d, 'USD', 'IDR', :r, 'zzfe')"), {"d": day, "r": rate})

        def tx(amount, day):
            return q(
                "INSERT INTO transactions (date, amount, currency, account_id, is_transfer, category) "
                "VALUES (:d, :a, 'USD', :acc, true, 'Investment') RETURNING id", d=f"{day} 10:00", a=amount, acc=acct)

        def ev(plat, ticker, kind, qty, price, day, funded=None):
            tid = tx(funded, day) if funded is not None else None
            return q(
                "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency, "
                "transaction_id, source_account_id) VALUES (:d, :t, :k, :q, :pr, :p, 'USD', :tx, :a) RETURNING id",
                d=day, t=ticker, k=kind, q=qty, pr=price, p=plat, tx=tid, a=acct if tid else None)

        # A: an opening lot (unfunded), two funded buys, one funded sell.
        ids["A0"] = ev(P, "ZZFEA", "buy", "10", "100", D1)
        ids["A1"] = ev(P, "ZZFEA", "buy", "2.5", "120", D2, funded="-300")
        ids["A2"] = ev(P, "ZZFEA", "buy", "1.23456789", "130", D2, funded="-160.5")
        ids["A3"] = ev(P, "ZZFEA", "sell", "3", "150", D3, funded="450")
        ev(Q, "ZZFEA", "buy", "1", "100", D1, funded="-100")
        # N: a sell the net quantity could not cover.
        ev(P, "ZZFEN", "buy", "10", "50", D1, funded="-500")
        ev(P, "ZZFEN", "sell", "9.995", "60", D2)
        # L: the stored row differs from its ledger.
        ev(P, "ZZFEL", "buy", "2", "50", D1, funded="-100")
        # R: a past date no rate is cached for.
        ev(P, "ZZFER", "buy", "1", "40", date(2026, 2, 3), funded="-40")
        # Z: zero.
        ev(P, "ZZFEZ", "buy", "1", "10", D1, funded="-10")
        ev(P, "ZZFEZ", "sell", "1", "10", D2)
        # F: ends exactly flat once the fee is taken off.
        ev(P, "ZZFEF", "buy", "2", "10", D1, funded="-20")
        ev(P, "ZZFEF", "sell", "1.998", "12", D2)
        # U: nothing funded. T: a fee that rounds to nothing.
        ev(P, "ZZFEU", "buy", "4", "10", D1)
        ev(P, "ZZFET", "buy", "0.00000001", "10", D1, funded="-1")
        c.execute(text("INSERT INTO closed_positions (ticker, platform_id, realized_pnl, close_date) "
                       "VALUES ('ZZFEC', :p, 123, '2026-02-01')"), {"p": P})

    db = _session(eng)
    for plat, t in ((P, "ZZFEA"), (Q, "ZZFEA"), (P, "ZZFEN"), (P, "ZZFEL"), (P, "ZZFEZ"), (P, "ZZFEF"), (P, "ZZFEU"), (P, "ZZFET")):
        recompute_holding_from_events(db, t, plat)
    db.commit()
    db.close()
    with eng.begin() as c:
        c.execute(text("UPDATE holdings SET quantity=3 WHERE ticker='ZZFEL'"))
        for t, qty, avg, at in (("CASH", 100, 1, "cash"), ("ZZFER", 1, 40, None)):
            c.execute(text("INSERT INTO holdings (ticker, quantity, avg_cost, currency, asset_type, platform_id) "
                           "VALUES (:t, :q, :a, 'USD', :at, :p)"), {"t": t, "q": qty, "a": avg, "at": at, "p": P})
        c.execute(text("INSERT INTO portfolio_value_history (snapshot_date, ticker, quantity, market_value, cost_basis, currency, platform_id) "
                       "VALUES (:d, 'ZZFEA', 10, 100, 100, 'IDR', :p)"), {"d": SNAP_DAY, "p": P})
    return ids


def _cli(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "backend.backfill_coin_fees", *args],
        cwd=REPO_ROOT, env={**os.environ, "DATABASE_URL": url},
        capture_output=True, text=True, timeout=120,
    )


def _fix(seeded, *args, ticker="ZZFEA"):
    return _cli(seeded["url"], "--platform-id", str(seeded["P"]), "--ticker", ticker, *args)


def _before_after(out: str, key: str) -> tuple[str, str]:
    m = re.search(rf"^{key}: before=(\S+) after=(\S+)$", out, re.M)
    assert m, (key, out)
    return m.group(1), m.group(2)


def _close(a, b):
    assert abs(Decimal(str(a)) - Decimal(str(b))) < TOL, (a, b)


def _expected():
    """Hand calculation of ZZFEA with the half-up fee: (quantity, idr cost, usd avg cost, realized)."""
    r1, r2, r3 = RATES[D1], RATES[D2], RATES[D3]
    total_cost = Decimal(100) * 10 * r1 + Decimal(120) * Decimal("2.5") * r2 + Decimal(130) * Decimal("1.23456789") * r2
    native_cost = Decimal(100) * 10 + Decimal(120) * Decimal("2.5") + Decimal(130) * Decimal("1.23456789")
    qty_pre = Decimal(10) + Decimal("2.4975") + Decimal("1.23333332")
    avg = total_cost / qty_pre
    realized = (Decimal(150) * r3 - avg) * 3
    qty = qty_pre - 3
    return qty, avg * qty, native_cost / qty_pre, realized


def _events(eng, ticker="ZZFEA", plat=None):
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "SELECT id, quantity, fee, fee_kind, transaction_id FROM portfolio_events "
            "WHERE ticker=:t AND (:p IS NULL OR platform_id=:p) ORDER BY date, id"), {"t": ticker, "p": plat})]


# --- boot: nothing runs ----------------------------------------------------------------


def test_script_not_wired_to_boot():
    files = [
        "backend/entrypoint.sh", "backend/Dockerfile", "docker-compose.yml",
        "backend/main.py", "backend/scheduler.py", "alembic/env.py",
        *(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "alembic" / "versions").glob("*.py")),
    ]
    for f in files:
        assert "backfill_coin_fees" not in (REPO_ROOT / f).read_text(), f


# --- the CLI ----------------------------------------------------------------------------


def test_cli_defaults_to_dry_run_and_prints_both_totals(seeded):
    before = _dump(seeded["engine"])
    r = _fix(seeded)
    assert r.returncode == 0, r.stdout + r.stderr
    out, lines = r.stdout, r.stdout.splitlines()
    assert lines[0].startswith(f"database: {make_url(seeded['url']).database} ")
    assert "mode: dry run" in lines[1] and "name=zzfe-p" in out
    assert "fee total half-up=0.00373457 down=0.00373456 (using half-up)" in out
    assert out.count("filled=") == 2 and "fee=0.0025" in out and "fee=0.00123457" in out
    assert "skipped_unfunded=1 skipped_with_fee=0" in out
    assert "events_before_snapshot_floor=2" in out
    assert "Dry run" in out
    qty, cost, native, realized = _expected()
    b, a = _before_after(out, "quantity")
    _close(b, Decimal("10") + Decimal("2.5") + Decimal("1.23456789") - 3)
    _close(a, qty)
    _close(_before_after(out, "cost_idr")[1], cost)
    _close(_before_after(out, "usd_avg_cost")[1], native)
    _close(_before_after(out, "realized_idr")[1], realized)
    assert _dump(seeded["engine"]) == before  # byte-identical


def test_apply_records_the_fee_and_leaves_cash_and_others_alone(seeded):
    eng, P = seeded["engine"], seeded["P"]
    before = _dump(eng)
    other = _rows(eng, "holdings", "ticker='ZZFEA' AND platform_id=:q", q=seeded["Q"])
    other_events = _rows(eng, "portfolio_events", "platform_id=:q", q=seeded["Q"])
    r = _fix(seeded, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Applied: one transaction committed." in r.stdout
    evs = {e["id"]: e for e in _events(eng, plat=P)}
    assert evs[seeded["A0"]]["fee"] is None and evs[seeded["A0"]]["quantity"] == Decimal("10")
    assert (evs[seeded["A1"]]["quantity"], evs[seeded["A1"]]["fee"], evs[seeded["A1"]]["fee_kind"]) == (
        Decimal("2.4975"), Decimal("0.0025"), "coin")
    assert (evs[seeded["A2"]]["quantity"], evs[seeded["A2"]]["fee"]) == (Decimal("1.23333332"), Decimal("0.00123457"))
    assert evs[seeded["A3"]]["fee"] is None
    after = _dump(eng)
    assert after["transactions"] == before["transactions"]  # cash untouched
    assert _rows(eng, "holdings", "ticker='ZZFEA' AND platform_id=:q", q=seeded["Q"]) == other
    assert _rows(eng, "portfolio_events", "platform_id=:q", q=seeded["Q"]) == other_events

    # Trade value (price x quantity + fee value) equals price x filled, per buy and in total.
    with eng.connect() as c:
        rows = c.execute(text("SELECT price, quantity, fee FROM portfolio_events WHERE id IN (:a, :b)"),
                         {"a": seeded["A1"], "b": seeded["A2"]}).all()
    assert sum(p * q + f * p for p, q, f in rows) == Decimal(120) * Decimal("2.5") + Decimal(130) * Decimal("1.23456789")

    # The holding is the new ledger and realized matches the hand calculation.
    from backend.portfolio import _realized_for_position, recompute_holding_from_events

    qty, cost, native, realized = _expected()
    db = _session(eng)
    try:
        h = db.execute(text("SELECT quantity, avg_cost FROM holdings WHERE ticker='ZZFEA' AND platform_id=:p"), {"p": P}).one()
        res = recompute_holding_from_events(db, "ZZFEA", P)
        nat = _realized_for_position(db, "ZZFEA", P)
        db.rollback()
    finally:
        db.close()
    assert h.quantity == qty
    _close(res["quantity"] * res["avg_cost"], cost)
    _close(res["realized_pnl"], realized)
    _close(nat["native_avg_cost"], native)

    # One audit edit per changed event, all strings.
    with eng.connect() as c:
        audits = [r[0] for r in c.execute(text(
            "SELECT after FROM audit_log WHERE entity='portfolio_event' AND operation='edit' ORDER BY entity_id"))]
    assert len(audits) == 2
    for a in audits:
        assert a["source"] == "coin_fee_backfill" and a["fee_rate"] == "0.001" and a["rounding"] == "half-up"
        assert a["fee_kind"] == "coin" and isinstance(a["fee"], str) and isinstance(a["quantity"], str)
    assert len(after["audit_log"]) == len(before["audit_log"]) + 2
    for t in before:
        if t not in ("portfolio_events", "holdings", "audit_log"):
            assert after[t] == before[t], t


def test_second_apply_changes_nothing(seeded):
    eng = seeded["engine"]
    assert _fix(seeded, "--apply").returncode == 0
    mid = _dump(eng)
    r = _fix(seeded, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nothing to fix." in r.stdout and "skipped_with_fee=2" in r.stdout
    assert _dump(eng) == mid


def test_rounding_down_and_rate(seeded):
    eng = seeded["engine"]
    r = _fix(seeded, "--rounding", "down")
    assert r.returncode == 0 and "fee total half-up=0.00373457 down=0.00373456 (using down)" in r.stdout
    r = _fix(seeded, "--rate", "0.002")
    assert r.returncode == 0 and "fee=0.005 " in r.stdout + " " and "fee=0.00246914" in r.stdout
    assert _fix(seeded, "--rounding", "down", "--rate", "0.002", "--apply").returncode == 0
    fees = {e["id"]: e["fee"] for e in _events(eng, plat=seeded["P"])}
    assert fees[seeded["A1"]] == Decimal("0.005") and fees[seeded["A2"]] == Decimal("0.00246913")


@pytest.mark.parametrize("args", [
    ["--rate", "0"], ["--rate", "1"], ["--rate", "1.5"], ["--rate", "-0.1"], ["--rate", "abc"],
    ["--rounding", "up"],
])
def test_bad_options_write_nothing(seeded, args):
    before = _dump(seeded["engine"])
    r = _fix(seeded, "--apply", *args)
    assert r.returncode != 0
    assert _dump(seeded["engine"]) == before


def test_usage_and_unknown_platform_write_nothing(seeded):
    before = _dump(seeded["engine"])
    assert _cli(seeded["url"], "--apply").returncode != 0
    assert _cli(seeded["url"], "--platform-id", str(seeded["P"]), "--apply").returncode != 0  # --ticker is required
    r = _cli(seeded["url"], "--platform-id", "999999", "--ticker", "ZZFEA", "--apply")
    assert r.returncode == 1 and "No platform" in r.stdout
    assert _dump(seeded["engine"]) == before


def test_expect_quantity_reports_and_never_refuses(seeded):
    r = _fix(seeded, "--expect-quantity", "9.5")
    assert r.returncode == 0, r.stdout + r.stderr
    m = re.search(r"expected_quantity=(\S+) after=(\S+) difference=(\S+)", r.stdout)
    assert m and Decimal(m.group(1)) == Decimal("9.5")
    _close(Decimal(m.group(2)) - Decimal("9.5"), m.group(3))
    qty, *_ = _expected()
    _close(m.group(2), qty)


def test_cli_refuses_a_database_without_the_fee_column():
    with _Scratch("fee022", REV_022) as s:
        r = _cli(s.url, "--platform-id", "1", "--ticker", "ZZFEA", "--apply")
        assert r.returncode == 1
        assert "alembic upgrade head" in r.stdout
        assert "Traceback" not in r.stdout + r.stderr


# --- run(): left alone, flat, failure ----------------------------------------------------


def test_positions_left_alone_with_a_reason_and_nothing_written(seeded):
    import backend.backfill_coin_fees as bcf

    eng = seeded["engine"]
    before = _dump(eng)
    for ticker, reason in LEFT_ALONE.items():
        db = _session(eng)
        try:
            rep = bcf.run(db, seeded["P"], ticker, apply=True)
        finally:
            db.close()
        assert rep["left"] == reason, (ticker, rep)
        assert _dump(eng) == before, ticker
    r = _fix(seeded, "--apply", ticker="ZZFEN")
    assert r.returncode == 0 and "left alone: negative_running_quantity" in r.stdout


def test_a_position_with_nothing_funded_or_a_zero_fee_has_nothing_to_fix(seeded):
    import backend.backfill_coin_fees as bcf

    before = _dump(seeded["engine"])
    for ticker, key in (("ZZFEU", "skipped_unfunded"), ("ZZFET", "skipped_tiny_fee")):
        db = _session(seeded["engine"])
        try:
            rep = bcf.run(db, seeded["P"], ticker, apply=True)
        finally:
            db.close()
        assert rep["nothing"] is True and rep[key] == 1, (ticker, rep)
    assert _dump(seeded["engine"]) == before


def test_flat_after_the_fix_is_applied_and_reported(seeded):
    eng = seeded["engine"]
    r = _fix(seeded, "--apply", ticker="ZZFEF")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "flat after the fix: run python -m backend.close_zero_positions" in r.stdout
    assert "Applied: one transaction committed." in r.stdout
    with eng.connect() as c:
        assert c.execute(text("SELECT quantity FROM holdings WHERE ticker='ZZFEF'")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM closed_positions WHERE ticker='ZZFEF'")).scalar() == 0


def test_apply_is_one_transaction(seeded, monkeypatch):
    import backend.backfill_coin_fees as bcf

    real, calls = bcf.recompute_holding_from_events, []

    def boom(db, ticker, platform_id):
        calls.append(ticker)
        if len(calls) == 2:  # after the events were changed
            raise RuntimeError("synthetic failure after the change")
        return real(db, ticker, platform_id)

    monkeypatch.setattr(bcf, "recompute_holding_from_events", boom)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(RuntimeError, match="nothing was changed"):
            bcf.run(db, seeded["P"], "ZZFEA", apply=True)
    finally:
        db.close()
    assert len(calls) == 2
    assert _dump(seeded["engine"]) == before


def test_apply_aborts_if_cash_changes(seeded, monkeypatch):
    import backend.backfill_coin_fees as bcf
    from backend.models import Transaction

    real = bcf.recompute_holding_from_events

    def sneaky(db, ticker, platform_id):
        out = real(db, ticker, platform_id)
        tx = db.get(Transaction, _events(seeded["engine"], plat=seeded["P"])[1]["transaction_id"])
        if tx is not None:
            db.delete(tx)
        return out

    monkeypatch.setattr(bcf, "recompute_holding_from_events", sneaky)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(Exception, match="nothing was changed"):
            bcf.run(db, seeded["P"], "ZZFEA", apply=True)
    finally:
        db.close()
    assert _dump(seeded["engine"]) == before


def test_rounding_unit_cases():
    import backend.backfill_coin_fees as bcf

    assert bcf.fee_for(Decimal("1.23456789"), Decimal("0.001"), "half-up") == Decimal("0.00123457")
    assert bcf.fee_for(Decimal("1.23456789"), Decimal("0.001"), "down") == Decimal("0.00123456")
    assert bcf.fee_for(Decimal("2.5"), Decimal("0.001"), "half-up") == Decimal("0.0025")
