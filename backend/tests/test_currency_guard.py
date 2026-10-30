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
