"""
QRY-02 tests: compare_periods (two periods side by side, deltas in code).

Runs on the isolated `monai_test` DB through conftest (never the live DB).
Every value is synthetic: a far-past 2015 window with `zzcmp <tag>` rows and
plain integer amounts, so expected numbers come from the seed list or from the
spending_total / income_total / net_total oracle functions, never from the
live ledger.
"""

import datetime
import inspect
import json
import uuid

import pytest
from sqlalchemy import text

from backend.db import engine
from backend.tools import (
    compare_periods,
    income_total,
    net_total,
    spending_total,
)

JAN = ("2015-01-01", "2015-01-31")  # 31 days
FEB = ("2015-02-01", "2015-02-28")  # 28 days
MAR = ("2015-03-01", "2015-03-31")  # 31 days
EMPTY = ("1999-01-01", "1999-01-31")


def _cmp(a, b, **kw):
    return compare_periods("custom", "custom", a[0], a[1], b[0], b[1], **kw)


# (date, amount, category key | None, is_transfer). Negative = expense.
_SEED = [
    ("2015-01-05", -100, "alpha_sub", False),
    ("2015-01-06", -50, "alpha", False),
    ("2015-01-07", -30, "beta", False),
    ("2015-01-08", 500, None, False),
    ("2015-01-09", -7, None, False),
    ("2015-01-10", -11, "sys", False),
    ("2015-01-11", -999, "alpha", True),
    ("2015-02-05", -80, "alpha", False),
    ("2015-02-06", -40, "gamma", False),
    ("2015-02-07", 700, None, False),
    ("2015-02-08", -20, None, False),
    ("2015-02-09", -3, "sys", False),
    ("2015-02-10", -888, "alpha", True),
]


@pytest.fixture(scope="module")
def seeded_compare():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres not available: {e}")
        return

    tag = uuid.uuid4().hex[:8]
    names = {
        "alpha": f"zzcmp {tag} alpha",
        "alpha_sub": f"zzcmp {tag} alpha sub",
        "beta": f"zzcmp {tag} beta",
        "gamma": f"zzcmp {tag} gamma",
        "sys": f"zzcmp {tag} sys",
    }
    ids: dict[str, int] = {}
    with engine.begin() as c:
        ids["account"] = c.execute(text(
            "INSERT INTO accounts (name, type, currency) "
            "VALUES (:n, 'liquid', 'IDR') RETURNING id"),
            {"n": f"zzcmp {tag} wallet"}).scalar()
        for key in ("alpha", "beta", "gamma", "sys"):
            ids[key] = c.execute(text(
                "INSERT INTO categories (name, parent_id, kind, is_system) "
                "VALUES (:n, NULL, 'expense', :sys) RETURNING id"),
                {"n": names[key], "sys": key == "sys"}).scalar()
        ids["alpha_sub"] = c.execute(text(
            "INSERT INTO categories (name, parent_id, kind, is_system) "
            "VALUES (:n, :pid, 'expense', false) RETURNING id"),
            {"n": names["alpha_sub"], "pid": ids["alpha"]}).scalar()
        for d, amt, key, is_tr in _SEED:
            c.execute(text(
                "INSERT INTO transactions "
                "(date, amount, currency, category, category_id, account_id, is_transfer) "
                "VALUES (:d, :amt, 'IDR', :cat, :cid, :aid, :tr)"),
                {"d": d, "amt": amt, "cat": names.get(key), "cid": ids.get(key),
                 "aid": ids["account"], "tr": is_tr})
    try:
        yield {"names": names, "seed": _SEED}
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM transactions WHERE account_id = :a"),
                      {"a": ids["account"]})
            c.execute(text("DELETE FROM categories WHERE id = :i"), {"i": ids["alpha_sub"]})
            c.execute(text("DELETE FROM categories WHERE id = ANY(:i)"),
                      {"i": [ids[k] for k in ("alpha", "beta", "gamma", "sys")]})
            c.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": ids["account"]})


def _oracle(period, start=None, end=None):
    return (spending_total(period, start, end)["total"],
            income_total(period, start, end)["total"],
            net_total(period, start, end)["net"])


def test_signature_is_flat_and_db_free():
    sig = inspect.signature(compare_periods)
    assert list(sig.parameters) == [
        "period_a", "period_b", "a_start_date", "a_end_date",
        "b_start_date", "b_end_date", "limit"]
    assert sig.parameters["period_a"].default is inspect.Parameter.empty
    assert sig.parameters["period_b"].default is inspect.Parameter.empty
    assert "db" not in sig.parameters


def test_parity_totals_named():
    r = compare_periods("last_month", "this_month")
    assert "error" not in r
    for side, period in (("base", "last_month"), ("current", "this_month")):
        sp, inc, net = _oracle(period)
        assert r["totals"]["spending"][side] == pytest.approx(sp, abs=1e-6)
        assert r["totals"]["income"][side] == pytest.approx(inc, abs=1e-6)
        assert r["totals"]["net"][side] == pytest.approx(net, abs=1e-6)


def test_parity_totals_custom(seeded_compare):
    r = _cmp(JAN, FEB)
    assert r["base"]["start"] == "2015-01-01" and r["current"]["start"] == "2015-02-01"
    for side, win in (("base", JAN), ("current", FEB)):
        sp, inc, net = _oracle("custom", *win)
        assert r["totals"]["spending"][side] == pytest.approx(sp, abs=1e-6)
        assert r["totals"]["income"][side] == pytest.approx(inc, abs=1e-6)
        assert r["totals"]["net"][side] == pytest.approx(net, abs=1e-6)
    for k in ("spending", "income", "net"):
        t = r["totals"][k]
        assert t["delta"] == pytest.approx(t["current"] - t["base"], abs=1e-6)
    # Seed arithmetic, independent of the oracle: transfers count nowhere.
    jan_spend = sum(-a for d, a, _k, tr in _SEED if d.startswith("2015-01") and a < 0 and not tr)
    assert r["totals"]["spending"]["base"] == pytest.approx(jan_spend)


def test_order_reversal_same_signs(seeded_compare):
    first = _cmp(JAN, FEB)
    swapped = _cmp(FEB, JAN)
    assert first["totals"] == swapped["totals"]
    assert first["base"]["start"] == swapped["base"]["start"] == "2015-01-01"
    assert first["current"]["start"] == swapped["current"]["start"] == "2015-02-01"
    assert first["base"]["input"] == "a" and swapped["base"]["input"] == "b"
    assert first["current"]["input"] == "b" and swapped["current"]["input"] == "a"


def test_base_zero_pct_none(seeded_compare):
    r = _cmp(EMPTY, JAN)
    assert r["totals"]["spending"]["base"] == 0
    assert r["totals"]["spending"]["pct"] is None
    assert r["totals"]["spending"]["delta"] > 0


@pytest.mark.parametrize("kwargs", [
    dict(period_a="all_time", period_b="this_month"),
    dict(period_a="custom", period_b="this_month", a_start_date="2015-01-01"),
    dict(period_a="custom", period_b="this_month",
         a_start_date="2015-13-45", a_end_date="2015-01-31"),
    dict(period_a="fortnight", period_b="this_month"),
    dict(period_a="custom", period_b="this_month",
         a_start_date="2015-02-01", a_end_date="2015-01-01"),
])
def test_refuse(kwargs):
    r = compare_periods(**kwargs)
    assert r["tool"] == "compare_periods"
    assert "error" in r
    assert "totals" not in r


def test_in_progress_flagged(seeded_compare):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=5)
    end = today + datetime.timedelta(days=10)
    r = compare_periods("custom", "custom", *JAN, start.isoformat(), end.isoformat())
    cur = r["current"]
    assert cur["in_progress"] is True
    assert cur["days_elapsed"] == 6
    assert cur["days"] == 16
    assert r["comparable"] is False
    past = r["base"]
    assert past["in_progress"] is False
    assert past["days_elapsed"] == past["days"]


def test_comparable_false_when_days_differ(seeded_compare):
    r = _cmp(JAN, FEB)
    assert r["comparable"] is False
    for side in ("base", "current"):
        assert "per_day" in r[side]
    assert r["base"]["per_day"] == pytest.approx(
        r["totals"]["spending"]["base"] / 31, abs=0.01)


def test_comparable_true_equal_days(seeded_compare):
    r = _cmp(JAN, MAR)
    assert r["comparable"] is True
    for side in ("base", "current"):
        assert "per_day" not in r[side]


def test_result_json_serialisable(seeded_compare):
    json.dumps(compare_periods("last_month", "this_month"))
    json.dumps(_cmp(JAN, FEB))
