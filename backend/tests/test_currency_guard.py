"""GUARD-01: no backend total may add dollars to rupiah (Phase 43).

This file was committed RED first (D-01), before any conversion code: it is the
contract every later Phase 43 plan turns green slice by slice. Every value is
synthetic (ZZ43 / zz43- names, 1995 dates, round rates); expected figures are
computed here from the seeded numbers, never copied from a real database.

Three layers:
  1. Static: every SQL SUM( / AVG( in backend/*.py reads amount_idr, or is in
     ALLOW with a one-line reason. A failure prints file:line for each stray
     site; an ALLOW entry that no longer matches anything also fails, so the
     list cannot go stale. Fix the SQL, or add an ALLOW entry with a reason.
  2. Classification: every read tool is MONEY or NON_MONEY, and every MONEY
     tool has a test_money_<name> function below.
  3. Behavioural: seed IDR + USD liquid accounts in monai_test, call each
     MONEY tool, and compare with the IDR figure derived here.

The FX adapters are stubbed in every fixture: this file never touches the
network.
"""

import ast
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from backend import fx, mcp_writes, tools
from backend.db import SessionLocal
from backend.tools import READ_TOOL_NAMES

# ---------------------------------------------------------------------------
# Classification (D-03, D-20)
# ---------------------------------------------------------------------------

MONEY_TOOLS = frozenset({
    "spending_total", "income_total", "net_total", "spending_by_category",
    "spending_in_category", "spending_before_after_purchase",
    "largest_transactions", "average_daily_spending", "monthly_trend",
    "account_balances", "net_worth", "recurring_charges", "compare_periods",
    "find_transactions",
})

NON_MONEY_TOOLS = frozenset({
    "transaction_count",  # an integer count, no amounts
    "list_categories",    # the tree, no amounts
    "find_platforms",     # ids / names / kinds
    "find_accounts",      # account metadata incl. currency, no balances
})

_MCP_SURFACE = Path(__file__).with_name("mcp_tool_surface.json")

# ---------------------------------------------------------------------------
# Static layer (D-02)
# ---------------------------------------------------------------------------

# (filename, snippet) -> why a SUM/AVG without amount_idr is correct there.
ALLOW = {
    ("tools.py", "COALESCE(SUM(t.amount), 0) AS current_balance"):
        "native per-account balance, converted once at spot (D-11)",
    ("tools.py", "amount_idr IS NULL"):
        "native USD of unconverted rows, reported as USD and never added to IDR (D-05/D-06)",
    ("writes.py", "SELECT COALESCE(SUM(amount), 0) FROM transactions"):
        "balance-adjustment math is native by design",
    ("reconstruction.py", "COALESCE(SUM(t.amount), 0) FROM transactions t"):
        "per-account native ledger and adjustment sums, converted per account per month afterwards (D-14)",
    ("reconstruction.py", "FROM net_worth_corrections"):
        "archival corrections are IDR-only",
    ("net_worth_history.py", "SUM(market_value)"):
        "portfolio snapshot values are already IDR",
    ("investment_reconstruction.py", "FROM net_worth_corrections"):
        "archival corrections are IDR-only",
}

_SUM_AVG = re.compile(r"\b(?:SUM|AVG)\s*\(([^)]*)\)")


def _doc_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """(lineno, end_lineno) of every docstring expression in the module."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.append((first.lineno, first.end_lineno))
    return out


def _scan() -> tuple[list[str], set]:
    """Return (violations as 'file:line: text', ALLOW keys that matched)."""
    violations: list[str] = []
    used: set = set()
    for path in sorted(Path(__file__).resolve().parents[1].glob("*.py")):
        source = path.read_text()
        docs = _doc_ranges(ast.parse(source))
        for n, line in enumerate(source.splitlines(), start=1):
            if line.strip().startswith("#") or any(a <= n <= b for a, b in docs):
                continue
            for m in _SUM_AVG.finditer(line):
                if "amount_idr" in m.group(1):
                    continue
                keys = [k for k in ALLOW if k[0] == path.name and k[1] in line]
                if keys:
                    used.update(keys)
                else:
                    violations.append(f"{path.name}:{n}: {line.strip()}")
    return violations, used


def test_static_sum_avg_scan():
    violations, used = _scan()
    unused = sorted(k for k in ALLOW if k not in used)
    assert not violations and not unused, (
        "SUM/AVG sites that do not read amount_idr and are not in ALLOW:\n  "
        + "\n  ".join(violations)
        + "\nunused ALLOW entries (remove them):\n  " + "\n  ".join(map(str, unused))
    )


def test_tool_classification():
    assert not (MONEY_TOOLS & NON_MONEY_TOOLS)
    mcp_reads = {t["name"] for t in json.loads(_MCP_SURFACE.read_text())} - set(mcp_writes.WRITE_TOOLS)
    assert MONEY_TOOLS | NON_MONEY_TOOLS == set(READ_TOOL_NAMES) | mcp_reads
    missing = sorted(n for n in MONEY_TOOLS if f"test_money_{n}" not in globals())
    assert not missing, f"MONEY tools without a test_money_<name> function: {missing}"


# ---------------------------------------------------------------------------
# Seeding (D-04, D-25). Tools open their own connections, so seeds are committed
# and every fixture cleans up in finally (Pitfall 7).
# ---------------------------------------------------------------------------

D_FRI, D_SAT, D_MON = date(1995, 6, 9), date(1995, 6, 10), date(1995, 6, 12)
RATE_FRI, RATE_MON = Decimal("16000.000000"), Decimal("16100.000000")
RANGE = {"period": "custom", "start_date": "1995-06-09", "end_date": "1995-06-12"}

# Expected IDR figures, derived from the seeded numbers (Saturday uses Friday's rate).
SPEND = Decimal("50000.00") + Decimal("12.50") * RATE_FRI + Decimal("10.00") * RATE_FRI
INCOME = Decimal("100000.00") + Decimal("5.00") * RATE_MON
NET = INCOME - SPEND
NATIVE_SUM = Decimal("50000.00") + Decimal("12.50") + Decimal("10.00")  # dollars read as rupiah


def _stub_fx(monkeypatch, live=None, ranges=None):
    """Network-free adapters. live: USD->IDR spot Decimal or None; ranges: {date: Decimal} or None."""
    def _live(base, quote, as_of):
        if live is None or (base, quote) != ("USD", "IDR"):
            return None
        return (live, "test", as_of)

    def _range(base, quote, start, end):
        if not ranges or (base, quote) != ("USD", "IDR"):
            return None
        pts = sorted((d, r) for d, r in ranges.items() if start <= d <= end)
        return pts or None

    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", _live)
    monkeypatch.setitem(fx.FX_RANGE_ADAPTERS, "frankfurter", _range)


def _clean() -> None:
    s = SessionLocal()
    try:
        s.execute(text("DELETE FROM portfolio_events WHERE ticker = 'ZZ43T'"))
        s.execute(text(
            "DELETE FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'ZZ43 %')"))
        s.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ43 %'"))
        s.execute(text("DELETE FROM categories WHERE name LIKE 'zz43-%'"))
        s.execute(text("DELETE FROM platforms WHERE name LIKE 'ZZ43 %'"))
        s.execute(text(
            "DELETE FROM fx_rate_cache WHERE base_currency = 'USD' AND quote_currency = 'IDR' "
            "AND rate_date BETWEEN '1995-01-01' AND '1996-12-31'"))
        s.commit()
    finally:
        s.close()


def _seed_flows() -> dict:
    """Insert the ZZ43 accounts, category, transactions and cache rows; return ids."""
    s = SessionLocal()
    try:
        cat = s.execute(text(
            "INSERT INTO categories (name, parent_id, kind, is_system) "
            "VALUES ('zz43-Guard', NULL, 'expense', false) RETURNING id")).scalar()
        acc = {
            c: s.execute(text(
                "INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"),
                {"n": f"ZZ43 {c.lower()}", "c": c}).scalar()
            for c in ("IDR", "USD")
        }
        # (day, amount, currency, merchant, categorised)
        rows = [
            (D_FRI, "-50000.00", "IDR", "zz43 idr out", True),
            (D_MON, "100000.00", "IDR", "zz43 idr in", False),
            (D_FRI, "-12.50", "USD", "zz43 usd fri", True),
            (D_SAT, "-10.00", "USD", "zz43 usd sat", True),
            (D_MON, "5.00", "USD", "zz43 usd mon", False),
        ]
        for day, amt, cur, merchant, categorised in rows:
            s.execute(text(
                "INSERT INTO transactions (date, amount, currency, merchant, category, category_id, "
                "account_id, is_transfer) VALUES (:d, :a, :c, :m, :cat, :cid, :acc, false)"),
                {"d": datetime(day.year, day.month, day.day, 12), "a": amt, "c": cur, "m": merchant,
                 "cat": "zz43-Guard" if categorised else None,
                 "cid": cat if categorised else None, "acc": acc[cur]})
        for d, r in ((D_FRI, RATE_FRI), (D_MON, RATE_MON)):
            s.execute(text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, fetched_at) "
                "VALUES (:d, 'USD', 'IDR', :r, 'frankfurter', now())"), {"d": d, "r": r})
        s.commit()
    finally:
        s.close()
    return {"cat": cat, "acc": acc}


@pytest.fixture()
def flow_env(monkeypatch):
    """Clean slate + network-free FX; seeds nothing (delta tests read a baseline first)."""
    _stub_fx(monkeypatch, ranges={})
    _clean()
    try:
        yield
    finally:
        _clean()


@pytest.fixture()
def flow_seed(flow_env):
    yield _seed_flows()


# ---------------------------------------------------------------------------
# Behavioural layer: one test per MONEY tool. The IDR value is asserted before
# the currency label so a failure shows the wrong number.
# ---------------------------------------------------------------------------

def test_money_spending_total(flow_seed):
    r = tools.TOOLS["spending_total"](**RANGE)
    assert r["total"] == float(SPEND)  # HEAD adds dollars to rupiah (50022.5)
    assert r["currency"] == "IDR"


def test_money_income_total(flow_seed):
    r = tools.TOOLS["income_total"](**RANGE)
    assert r["total"] == float(INCOME)
    assert r["currency"] == "IDR"


def test_money_net_total(flow_seed):
    r = tools.TOOLS["net_total"](**RANGE)
    assert r["net"] == float(NET)
    assert r["currency"] == "IDR"


def test_money_average_daily_spending(flow_seed):
    r = tools.TOOLS["average_daily_spending"](**RANGE)
    assert r["days"] == 4
    assert r["total"] == float(SPEND)
    assert r["average"] == float(SPEND / 4)
    assert r["currency"] == "IDR"


def test_money_spending_by_category(flow_seed):
    r = tools.TOOLS["spending_by_category"](**RANGE)
    assert dict(r["rows"])["zz43-Guard"] == float(SPEND)
    assert sum(t for _, t in r["children"]["zz43-Guard"]) == pytest.approx(float(SPEND))
    assert r["currency"] == "IDR"


def test_money_spending_in_category(flow_seed):
    r = tools.TOOLS["spending_in_category"](category="zz43-Guard", **RANGE)
    assert r["total"] == float(SPEND)
    assert r["currency"] == "IDR"


def test_money_largest_transactions(flow_seed):
    """D-09: ranked by IDR; USD rows also carry native amount, rate and rate date."""
    r = tools.TOOLS["largest_transactions"](limit=3, kind="expense", **RANGE)
    assert [x["amount"] for x in r["rows"]] == [
        float(Decimal("12.50") * RATE_FRI), float(Decimal("10.00") * RATE_FRI), 50000.0]
    by = {x["merchant"]: x for x in r["rows"]}
    for merchant, native in (("zz43 usd fri", 12.5), ("zz43 usd sat", 10.0)):
        row = by[merchant]
        assert row["currency"] == "USD"
        assert row["amount_native"] == native
        assert row["fx_rate"] == float(RATE_FRI)
        assert row["fx_rate_date"] == "1995-06-09"  # Saturday falls back to Friday
    assert by["zz43 idr out"]["currency"] == "IDR"
    assert r["currency"] == "IDR"


def test_money_find_transactions(flow_seed):
    """D-20: rows keep the native signed amount and gain currency + amount_idr."""
    r = tools.TOOLS["find_transactions"](merchant="zz43", **RANGE)
    by = {x["merchant"]: x for x in r["rows"]}
    fri = by["zz43 usd fri"]
    assert fri["amount"] == -12.5
    assert fri.get("amount_idr") == float(Decimal("-12.50") * RATE_FRI)
    assert fri.get("currency") == "USD"
    for merchant in ("zz43 idr out", "zz43 idr in"):
        assert by[merchant].get("amount_idr") == by[merchant]["amount"]
    assert r.get("currency") == "IDR"


def test_money_compare_periods(flow_seed):
    r = tools.TOOLS["compare_periods"](
        period_a="custom", a_start_date="1995-06-09", a_end_date="1995-06-10",
        period_b="custom", b_start_date="1995-06-11", b_end_date="1995-06-12")
    t = r["totals"]
    assert (t["spending"]["base"], t["spending"]["current"]) == (float(SPEND), 0.0)
    assert (t["income"]["base"], t["income"]["current"]) == (0.0, float(INCOME))
    assert (t["net"]["base"], t["net"]["current"]) == (-float(SPEND), float(INCOME))
    assert r["currency"] == "IDR"


@pytest.fixture()
def purchase_seed(flow_seed):
    s = SessionLocal()
    try:
        pid = s.execute(text("INSERT INTO platforms (name, kind) VALUES ('ZZ43 plat', 'test') RETURNING id")).scalar()
        s.execute(text(
            "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id) "
            "VALUES (:d, 'ZZ43T', 'buy', 1, 50000, :p)"), {"d": date(1995, 6, 11), "p": pid})
        s.commit()
    finally:
        s.close()
    yield flow_seed


def test_money_spending_before_after_purchase(purchase_seed):
    r = tools.TOOLS["spending_before_after_purchase"]("ZZ43T", "zz43-Guard")
    assert r["before_total"] == float(SPEND)
    assert r["after_total"] == 0.0
    assert r["currency"] == "IDR"


# --- balances and net worth (D-11, D-12, D-13) -----------------------------

USD_NATIVE = Decimal("-12.50") + Decimal("-10.00") + Decimal("5.00")
IDR_NATIVE = Decimal("-50000.00") + Decimal("100000.00")
USD_PERIOD_NET = Decimal("-12.50") * RATE_FRI + Decimal("-10.00") * RATE_FRI + Decimal("5.00") * RATE_MON


def _pin(monkeypatch, day: date) -> None:
    monkeypatch.setattr(fx, "_jakarta_today", lambda: day)


def _row(rows: list, name: str) -> dict:
    return next(r for r in rows if r["name"] == name)


def test_money_account_balances(flow_seed, monkeypatch):
    spot = Decimal("16200")
    _pin(monkeypatch, date(1995, 6, 15))
    _stub_fx(monkeypatch, live=spot, ranges={})
    r = tools.TOOLS["account_balances"]()
    usd, idr = _row(r["rows"], "ZZ43 usd"), _row(r["rows"], "ZZ43 idr")
    assert usd["current_balance"] == pytest.approx(float(USD_NATIVE * spot))
    assert usd["native_balance"] == float(USD_NATIVE)
    assert usd["currency"] == "USD"
    assert usd["fx_rate"] == float(spot)
    assert usd["fx_as_of"] == "1995-06-15"
    assert usd["fx_stale"] is False
    assert usd["period_net"] == pytest.approx(float(USD_PERIOD_NET))  # flows at transaction-date rates
    assert idr["current_balance"] == idr["native_balance"] == float(IDR_NATIVE)
    assert (idr["currency"], idr["fx_rate"], idr["fx_as_of"]) == ("IDR", 1.0, None)
    assert r["currency"] == "IDR"


def test_money_net_worth(flow_env, monkeypatch):
    spot = Decimal("16200")
    _pin(monkeypatch, date(1995, 6, 15))
    _stub_fx(monkeypatch, live=spot, ranges={})
    before = tools.TOOLS["net_worth"]()["liquid_total"]
    _seed_flows()
    nw = tools.TOOLS["net_worth"]()
    assert nw["liquid_total"] - before == pytest.approx(float(IDR_NATIVE + USD_NATIVE * spot))
    assert nw["currency"] == "IDR"
    assert not [x for x in nw.get("fx_excluded", []) if x["name"].startswith("ZZ43")]


def test_balances_stale_rate_labelled(flow_seed, monkeypatch):
    """D-12: live fetch fails, cached rate 3 days old -> used and labelled."""
    _pin(monkeypatch, date(1995, 6, 15))
    _stub_fx(monkeypatch, live=None, ranges={})
    usd = _row(tools.TOOLS["account_balances"]()["rows"], "ZZ43 usd")
    assert usd["current_balance"] == pytest.approx(float(USD_NATIVE * RATE_MON))
    assert usd["fx_rate"] == float(RATE_MON)
    assert usd["fx_as_of"] == "1995-06-12"
    assert usd["fx_stale"] is True
    assert usd["fx_note"] == "stale, rate of 1995-06-12"
    assert tools.TOOLS["net_worth"]().get("fx_note") == "stale, rate of 1995-06-12"


def test_balances_excluded_beyond_7_days(flow_env, monkeypatch):
    """D-12/D-13/D-21: no rate within 7 days -> left out, listed, never guessed."""
    _pin(monkeypatch, date(1995, 7, 31))
    _stub_fx(monkeypatch, live=None, ranges={})
    before = tools.TOOLS["net_worth"]()["liquid_total"]
    _seed_flows()
    usd = _row(tools.TOOLS["account_balances"]()["rows"], "ZZ43 usd")
    assert usd["current_balance"] is None
    assert usd["native_balance"] == float(USD_NATIVE)
    assert usd["fx_rate"] != 1.0
    nw = tools.TOOLS["net_worth"]()
    assert {"name": "ZZ43 usd", "native_balance": float(USD_NATIVE), "currency": "USD"} in nw.get("fx_excluded", [])
    assert nw.get("notice")
    assert nw["accounts_covered"] == nw["accounts_total"]
    assert nw["liquid_total"] - before == pytest.approx(float(IDR_NATIVE))


# --- relative-date tools (Pitfall 8) ---------------------------------------

SUB_RATES = {4: Decimal("16000.000000"), 3: Decimal("16100.000000"),
             2: Decimal("16200.000000"), 1: Decimal("16300.000000")}


def _sub_day(k: int) -> date:
    return date.today() - timedelta(days=30 * k)


def _clean_sub_rates() -> None:
    """monai_test only: clear every cache row a stray rate could hide a gap behind."""
    s = SessionLocal()
    try:
        for k in SUB_RATES:
            s.execute(text(
                "DELETE FROM fx_rate_cache WHERE base_currency = 'USD' AND quote_currency = 'IDR' "
                "AND rate_date BETWEEN :a AND :b"), {"a": _sub_day(k) - timedelta(days=7), "b": _sub_day(k)})
        s.commit()
    finally:
        s.close()


def _trend_expense() -> float:
    return sum(r["expense"] for r in tools.TOOLS["monthly_trend"]().get("rows", []))


@pytest.fixture()
def recent_seed(monkeypatch):
    _stub_fx(monkeypatch, ranges={})
    _clean()
    _clean_sub_rates()
    s = SessionLocal()
    try:
        baseline = _trend_expense()
        for cur, name, amt in (("USD", "ZZ43 rec usd", "-9.99"), ("IDR", "ZZ43 rec idr", "-150000.00")):
            acc = s.execute(text(
                "INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"),
                {"n": name, "c": cur}).scalar()
            for k in SUB_RATES:
                d = _sub_day(k)
                s.execute(text(
                    "INSERT INTO transactions (date, amount, currency, merchant, account_id, is_transfer) "
                    "VALUES (:d, :a, :c, 'zz43-sub', :acc, false)"),
                    {"d": datetime(d.year, d.month, d.day, 9), "a": amt, "c": cur, "acc": acc})
        for k, r in SUB_RATES.items():
            s.execute(text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, fetched_at) "
                "VALUES (:d, 'USD', 'IDR', :r, 'frankfurter', now())"), {"d": _sub_day(k), "r": r})
        s.commit()
    finally:
        s.close()
    try:
        yield {"baseline": baseline}
    finally:
        _clean()
        _clean_sub_rates()


def test_money_monthly_trend(recent_seed):
    expected = 4 * Decimal("150000") + Decimal("9.99") * sum(SUB_RATES.values())
    assert _trend_expense() - recent_seed["baseline"] == pytest.approx(float(expected), abs=0.05)
    assert tools.TOOLS["monthly_trend"]()["currency"] == "IDR"


def test_money_recurring_charges(recent_seed):
    """D-10: grouped by currency first; USD group carries native + IDR typical amounts."""
    r = tools.TOOLS["recurring_charges"](months=24, limit=50)
    groups = [g for g in r["groups"] if g["label"] == "zz43-sub"]
    assert len(groups) == 2
    usd = next(g for g in groups if g.get("currency") == "USD")
    idr = next(g for g in groups if g.get("currency") == "IDR")
    mid = sorted(Decimal("9.99") * v for v in SUB_RATES.values())
    median = float((mid[1] + mid[2]) / 2)
    assert usd["typical_amount"] == 9.99
    assert usd["typical_amount_idr"] == pytest.approx(median)
    assert usd["est_monthly"] == pytest.approx(median)
    assert usd["occurrences"] == 4
    assert idr["typical_amount"] == 150000.0
    assert r["currency"] == "IDR"


# --- missing-rate policy (D-06) --------------------------------------------

_ARGS = {
    "spending_total": RANGE, "income_total": RANGE, "net_total": RANGE,
    "spending_by_category": RANGE, "largest_transactions": RANGE,
    "average_daily_spending": RANGE,
    "spending_in_category": {"category": "zz43-Guard", **RANGE},
    "compare_periods": {
        "period_a": "custom", "a_start_date": "1995-06-09", "a_end_date": "1995-06-10",
        "period_b": "custom", "b_start_date": "1995-06-11", "b_end_date": "1995-06-12"},
}


def _delete_rate(day: date) -> None:
    s = SessionLocal()
    try:
        s.execute(text(
            "DELETE FROM fx_rate_cache WHERE base_currency = 'USD' AND quote_currency = 'IDR' "
            "AND rate_date = :d"), {"d": day})
        s.commit()
    finally:
        s.close()


@pytest.mark.parametrize("name", list(_ARGS))
def test_flow_refuses_on_missing_rate(flow_seed, name):
    """Chat / MCP never return a short total: exactly {tool, error}, naming the date, no amounts."""
    _delete_rate(D_FRI)  # Friday and Saturday USD rows lose their rate
    r = tools.TOOLS[name](**_ARGS[name])
    assert set(r) == {"tool", "error"}
    assert r["tool"] == name
    assert "1995-06-09" in r["error"]


@pytest.mark.parametrize("name", ["monthly_trend", "recurring_charges"])
def test_relative_tools_refuse_on_missing_rate(recent_seed, name):
    _delete_rate(_sub_day(1))
    r = tools.TOOLS[name]()
    assert set(r) == {"tool", "error"}


def test_dashboard_partial_on_missing_rate(flow_seed, authed):
    """Dashboard keeps the IDR part and reports how many USD rows are unconverted."""
    _delete_rate(D_FRI)
    r = authed.get("/cashflow/summary", params=RANGE)
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["expense"] == 50000.0  # not 50022.5
    assert body["totals"]["income"] == float(INCOME)
    assert body["unconverted_count"] == 2
    assert body["unconverted_usd"] == float(Decimal("-12.50") + Decimal("-10.00"))
    assert body["currency"] == "IDR"
