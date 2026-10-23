"""
Phase 37 D-16 parity contract: a linked source chip's params on
GET /transactions (with cashflow=true) reproduce the number the chat tool
quoted, so clicking a chip shows exactly the rows behind the answer.

Seeds are synthetic `zz-src-*` rows in a far-past window (March 2001, plus one
Feb 2001 base row, one April 2001 outside row and one row dated today for
monthly_trend). Nothing is copied from the live DB. The seed includes the
rows that make the unfiltered Records view disagree with the tools: an
Investment-tagged transfer leg, an investment-account expense and a
transfer pair; plus the rows that must stay in: a NULL-account expense and a
23:59 row on the last day of the window.
"""

import datetime

import pytest
from sqlalchemy import text

from backend import sources, tools
from backend.db import engine

MAR = ("2001-03-01", "2001-03-31")
FEB = ("2001-02-01", "2001-02-28")
_PAIR = 987654321

_ACCOUNTS = ("zz-src-liquid", "zz-src-invest")
_CATS = ("zz-src-Dining", "zz-src-Food", "zz-src-Salary")

_IDS: dict = {}


def _purge(c):
    """Clear anything a killed prior run leaked (account and category names are UNIQUE)."""
    c.execute(text(
        "DELETE FROM transactions WHERE merchant LIKE 'zz-src-%' OR account_id IN "
        "(SELECT id FROM accounts WHERE name = ANY(:a))"), {"a": list(_ACCOUNTS)})
    c.execute(text("DELETE FROM accounts WHERE name = ANY(:a)"), {"a": list(_ACCOUNTS)})
    c.execute(text("DELETE FROM categories WHERE name = ANY(:c)"), {"c": list(_CATS[:1])})
    c.execute(text("DELETE FROM categories WHERE name = ANY(:c)"), {"c": list(_CATS[1:])})


@pytest.fixture(scope="module", autouse=True)
def _seed():
    today_noon = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 0))
    with engine.begin() as c:
        _purge(c)
        for key, name, kind in (("liquid", "zz-src-liquid", "liquid"), ("invest", "zz-src-invest", "investment")):
            _IDS[key] = c.execute(text(
                "INSERT INTO accounts (name, type, currency) VALUES (:n, :t, 'IDR') RETURNING id"),
                {"n": name, "t": kind}).scalar()
        _IDS["food"] = c.execute(text(
            "INSERT INTO categories (name, parent_id, kind, is_system) "
            "VALUES ('zz-src-Food', NULL, 'expense', false) RETURNING id")).scalar()
        _IDS["dining"] = c.execute(text(
            "INSERT INTO categories (name, parent_id, kind, is_system) "
            "VALUES ('zz-src-Dining', :p, 'expense', false) RETURNING id"), {"p": _IDS["food"]}).scalar()
        _IDS["salary"] = c.execute(text(
            "INSERT INTO categories (name, parent_id, kind, is_system) "
            "VALUES ('zz-src-Salary', NULL, 'income', false) RETURNING id")).scalar()
        liq, inv = _IDS["liquid"], _IDS["invest"]
        # (date, amount, merchant, category text, category key, account, is_transfer, pair)
        rows = [
            ("2001-03-05 10:00:00", -1000, "zz-src-dining", "zz-src-Dining", "dining", liq, False, None),
            ("2001-03-31 23:59:00", -400, "zz-src-lastday", "zz-src-Food", "food", liq, False, None),
            ("2001-03-01 00:00:00", -250, "zz-src-nullacct", "zz-src-Food", "food", None, False, None),
            ("2001-03-15 09:00:00", 5000, "zz-src-salary", "zz-src-Salary", "salary", liq, False, None),
            ("2001-03-10 08:00:00", -700, "zz-src-xfer-out", "Transfer", None, liq, True, _PAIR),
            ("2001-03-10 08:00:00", 700, "zz-src-xfer-in", "Transfer", None, liq, True, _PAIR),
            ("2001-03-12 08:00:00", -300, "zz-src-funded", "Investment", None, liq, True, None),
            ("2001-03-20 08:00:00", -200, "zz-src-invacct", "zz-src-Food", "food", inv, False, None),
            ("2001-04-01 00:00:00", -999, "zz-src-april", "zz-src-Food", "food", liq, False, None),
            ("2001-02-10 08:00:00", -150, "zz-src-feb", "zz-src-Food", "food", liq, False, None),
            (today_noon, -123, "zz-src-today", "zz-src-Food", "food", liq, False, None),
        ]
        for d, amt, merchant, cat, ckey, aid, tr, pair in rows:
            c.execute(text(
                "INSERT INTO transactions (date, amount, currency, merchant, category, category_id, "
                "account_id, is_transfer, transfer_pair_id) "
                "VALUES (:d, :amt, 'IDR', :m, :cat, :cid, :aid, :tr, :pair)"),
                {"d": d, "amt": amt, "m": merchant, "cat": cat, "cid": _IDS.get(ckey) if ckey else None,
                 "aid": aid, "tr": tr, "pair": pair})
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM transactions WHERE merchant LIKE 'zz-src-%'"))
        c.execute(text("DELETE FROM accounts WHERE id = ANY(:i)"), {"i": [liq, inv]})
        c.execute(text("DELETE FROM categories WHERE id = :i"), {"i": _IDS["dining"]})
        c.execute(text("DELETE FROM categories WHERE id = ANY(:i)"), {"i": [_IDS["food"], _IDS["salary"]]})


@pytest.fixture(autouse=True)
def _keyed(authed):
    """Phase 40.1: GET /transactions needs the key; every test reads through _rows."""
    yield


def _rows(client, params: dict) -> list[dict]:
    """Page GET /transactions (500-row cap) until a short page."""
    out: list[dict] = []
    while True:
        r = client.get("/transactions", params={**params, "limit": 500, "offset": len(out)})
        assert r.status_code == 200
        page = r.json()
        out += page
        if len(page) < 500:
            return out


def _chip_params(chip: dict, cashflow: bool = True) -> dict:
    p = {k: chip[k] for k in ("date_from", "date_to", "category", "type") if k in chip}
    if cashflow and chip.get("cashflow"):
        p["cashflow"] = "true"
    return p


def _spend(rows) -> float:
    return sum(-float(r["amount"]) for r in rows)


def _sum(rows) -> float:
    return sum(float(r["amount"]) for r in rows)


def _custom(**kw):
    return {"period": "custom", "start_date": kw.get("s", MAR[0]), "end_date": kw.get("e", MAR[1])}


def _chip(name, args, result):
    chips = sources.source_for(name, args, result)
    assert chips and all(c["linked"] and c["cashflow"] for c in chips)
    return chips


def test_spending_total_parity_and_filter_is_not_vacuous(client):
    args = _custom()
    res = tools.spending_total(**args)
    (chip,) = _chip("spending_total", args, res)
    assert res["total"] == 1650  # seeded liquid + NULL-account expenses only
    assert _spend(_rows(client, _chip_params(chip))) == res["total"]
    # Same params without cashflow also pull the Investment-tagged leg and the
    # investment-account row, so the filter is what makes parity hold.
    assert _spend(_rows(client, _chip_params(chip, cashflow=False))) == 2150


def test_inclusive_last_day_and_exclusive_next_day(client):
    rows = _rows(client, {"cashflow": "true", "date_from": MAR[1], "date_to": MAR[1]})
    assert [r["merchant"] for r in rows] == ["zz-src-lastday"]
    assert not [r for r in _rows(client, {"cashflow": "true", "date_to": MAR[1], "date_from": "2001-03-01"})
                if r["merchant"] == "zz-src-april"]


def test_income_and_net_parity(client):
    args = _custom()
    inc, net = tools.income_total(**args), tools.net_total(**args)
    (ci,), (cn,) = _chip("income_total", args, inc), _chip("net_total", args, net)
    assert inc["total"] == 5000 and net["net"] == 3350
    assert _sum(_rows(client, _chip_params(ci))) == inc["total"]
    assert _sum(_rows(client, _chip_params(cn))) == net["net"]
    assert "type" not in cn


@pytest.mark.parametrize("kind,expected", [("all", 4), ("expense", 3), ("income", 1)])
def test_transaction_count_parity(client, kind, expected):
    args = {**_custom(), "kind": kind}
    res = tools.transaction_count(**args)
    (chip,) = _chip("transaction_count", args, res)
    assert res["count"] == expected
    assert len(_rows(client, _chip_params(chip))) == res["count"]


def test_average_daily_spending_parity(client):
    args = _custom()
    res = tools.average_daily_spending(**args)
    (chip,) = _chip("average_daily_spending", args, res)
    assert res["days"] == 31
    assert _spend(_rows(client, _chip_params(chip))) / res["days"] == pytest.approx(res["average"])


@pytest.mark.parametrize("category,expected", [("zz-src-Food", 1650), ("zz-src-Dining", 1000)])
def test_spending_in_category_parity(client, category, expected):
    args = {"category": category, **_custom()}
    res = tools.spending_in_category(**args)
    (chip,) = _chip("spending_in_category", args, res)
    assert chip["category"] == category and res["total"] == expected
    assert _spend(_rows(client, _chip_params(chip))) == res["total"]


def test_spending_by_category_parity(client):
    args = _custom()
    res = tools.spending_by_category(**args)
    (chip,) = _chip("spending_by_category", args, res)
    assert dict(res["rows"]) == {"zz-src-Food": 1650.0}
    assert _spend(_rows(client, _chip_params(chip))) == sum(v for _, v in res["rows"])


def test_largest_transactions_parity(client):
    for kind, mags in (("expense", [1000.0, 400.0, 250.0]), ("income", [5000.0])):
        args = {**_custom(), "kind": kind}
        res = tools.largest_transactions(**args)
        (chip,) = _chip("largest_transactions", args, res)
        assert [r["amount"] for r in res["rows"]] == mags
        rows = _rows(client, _chip_params(chip))
        top = sorted((abs(float(r["amount"])) for r in rows), reverse=True)[: len(res["rows"])]
        assert top == mags


def test_compare_periods_parity(client):
    res = tools.compare_periods("custom", "custom", FEB[0], FEB[1], MAR[0], MAR[1])
    base, cur = _chip("compare_periods", {}, res)
    assert (res["totals"]["spending"]["base"], res["totals"]["spending"]["current"]) == (150, 1650)
    assert _spend(_rows(client, _chip_params(base))) == res["totals"]["spending"]["base"]
    assert _spend(_rows(client, _chip_params(cur))) == res["totals"]["spending"]["current"]


def test_before_after_windows_parity(client):
    # Synthetic tool result: pivot 2001-03-11, 20-day windows, so the "after"
    # window ends on the 23:59 last-day row (inclusive date_to).
    result = {"tool": "spending_before_after_purchase", "pivot_date": "2001-03-11", "window_days": 20}
    args = {"ticker": "ZZ", "category": "zz-src-Food"}
    before, after = _chip("spending_before_after_purchase", args, result)
    assert (before["date_from"], before["date_to"]) == ("2001-02-19", "2001-03-10")
    assert (after["date_from"], after["date_to"]) == ("2001-03-11", "2001-03-31")
    for chip in (before, after):
        want = tools.spending_in_category(
            "zz-src-Food", period="custom", start_date=chip["date_from"], end_date=chip["date_to"])["total"]
        assert _spend(_rows(client, _chip_params(chip))) == want
    assert (tools.spending_in_category("zz-src-Food", **{"period": "custom", "start_date": "2001-02-19",
                                                         "end_date": "2001-03-10"})["total"],
            tools.spending_in_category("zz-src-Food", **{"period": "custom", "start_date": "2001-03-11",
                                                         "end_date": "2001-03-31"})["total"]) == (1250, 400)


def test_monthly_trend_parity(client):
    res = tools.monthly_trend(6)
    (chip,) = _chip("monthly_trend", {"months": 6}, res)
    assert "date_to" not in chip
    rows = _rows(client, _chip_params(chip))
    assert any(r["merchant"] == "zz-src-today" for r in rows)  # seeded precondition
    assert _sum(rows) == pytest.approx(sum(r["net"] for r in res["rows"]))


def test_default_leaves_existing_callers_unchanged(client):
    # No cashflow param: the full ledger, transfers and investment accounts included.
    rows = _rows(client, {"q": "zz-src-", "date_from": MAR[0], "date_to": MAR[1]})
    assert len(rows) == 8
    inv = _rows(client, {"account_id": _IDS["invest"]})
    assert [r["merchant"] for r in inv] == ["zz-src-invacct"]
    assert _rows(client, {"account_id": _IDS["invest"], "cashflow": "true"}) == []
