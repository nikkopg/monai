"""
QRY-01 tests: the recurring_charges read tool.

Two groups:
  - pure-logic tests of _norm_text_key / _recurring_groups: no DB needed.
  - DB tests (exclusions, clamps, result shape): run on monai_test through
    conftest; they seed their own rows by unique tag and delete them after.

Synthetic values only: fixed 2030 dates in the pure tests, relative dates in
the DB tests, plain integer amounts.
"""

import datetime
import inspect
import json
import uuid

import pytest

from backend.tools import _norm_text_key, _recurring_groups

TODAY = datetime.date(2030, 6, 15)
_ids = iter(range(1, 10**6))


def _dt(d: datetime.date) -> datetime.datetime:
    return datetime.datetime(d.year, d.month, d.day, 9, 0)


def _series(gaps, amounts, *, end_gap=10, merchant="Synthetic Stream", notes=None,
            cat=None, cat_name=None, extra=()):
    """Rows whose last occurrence is `end_gap` days before TODAY; `gaps` are the
    day gaps between consecutive occurrences (oldest first)."""
    last = TODAY - datetime.timedelta(days=end_gap)
    dates = [last]
    for g in reversed(gaps):
        dates.append(dates[-1] - datetime.timedelta(days=g))
    dates.reverse()
    if not isinstance(amounts, (list, tuple)):
        amounts = [amounts] * len(dates)
    assert len(amounts) == len(dates)
    rows = [(next(_ids), _dt(d), -a, 1, merchant, notes, cat, cat_name)
            for d, a in zip(dates, amounts)]
    for d, a in extra:
        rows.append((next(_ids), _dt(d), -a, 1, merchant, notes, cat, cat_name))
    return rows


def _one(rows):
    groups = _recurring_groups(rows, TODAY)
    assert len(groups) == 1, groups
    return groups[0]


# --------------------------------------------------------------------------
# Key normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Netflix  12345", "netflix"),
    ("Spotify *AB12CD", "spotify"),
    ("  ZZ   Gym  ", "zz gym"),
    ("7-Eleven", "7-eleven"),
    ("PLN #", "pln"),
    ("", None),
    (None, None),
])
def test_normalise_key_strips_trailing_refs(raw, expected):
    assert _norm_text_key(raw) == expected


# --------------------------------------------------------------------------
# Cadence
# --------------------------------------------------------------------------

def test_cadence_monthly_exact():
    g = _one(_series([30] * 4, 50000))
    assert g["cadence"] == "monthly"
    assert g["occurrences"] == 5
    assert g["confidence"] == "high"


def test_cadence_weekly_exact():
    assert _one(_series([7] * 5, 20000, end_gap=2))["cadence"] == "weekly"


def test_cadence_monthly_jitter():
    assert _one(_series([28, 31, 33, 29], 50000))["cadence"] == "monthly"


def test_cadence_quarterly():
    assert _one(_series([91, 91], 300000))["cadence"] == "quarterly"


def test_cadence_yearly_two_points_low():
    g = _one(_series([365], 900000, end_gap=100))
    assert g["cadence"] == "yearly"
    assert g["confidence"] == "low"


def test_cadence_yearly_three_points_text_key_low():
    g = _one(_series([365, 365], 900000, end_gap=100))
    assert g["cadence"] == "yearly"
    assert g["key_type"] == "text"
    assert g["confidence"] == "low"


def test_cadence_biweekly_dropped():
    assert _recurring_groups(_series([14] * 5, 20000, end_gap=3), TODAY) == []


def test_cadence_price_change_within_25pct_one_group():
    rows = _series([30] * 6, [100000] * 4 + [110000] * 3)
    g = _one(rows)
    assert g["cadence"] == "monthly"
    assert g["amount_min"] < g["amount_max"]


# --------------------------------------------------------------------------
# Status and ordering
# --------------------------------------------------------------------------

def test_status_lapsed_when_stopped():
    g = _one(_series([30] * 4, 50000, end_gap=120))
    assert g["status"] == "lapsed"
    assert "next_expected" not in g


def test_status_active_has_next_expected():
    g = _one(_series([30] * 4, 50000, end_gap=10))
    assert g["status"] == "active"
    assert datetime.date.fromisoformat(g["next_expected"]) > datetime.date.fromisoformat(g["last_date"])
    assert g["overdue"] is False


def test_status_active_overdue_flags_past_next_expected():
    # Monthly, last seen 40 days ago: still active (<= 1.5 x 30.44) but the
    # expected date has passed (WR-02).
    g = _one(_series([30] * 4, 50000, end_gap=40))
    assert g["status"] == "active"
    assert datetime.date.fromisoformat(g["next_expected"]) < TODAY
    assert g["overdue"] is True


def test_status_ordering_active_first_then_monthly_cost():
    rows = (
        _series([30] * 4, 900000, end_gap=120, merchant="Lapsed Costly")
        + _series([30] * 4, 10000, merchant="Active Cheap")
        + _series([30] * 4, 70000, merchant="Active Mid")
    )
    labels = [g["label"] for g in _recurring_groups(rows, TODAY)]
    assert labels == ["Active Mid", "Active Cheap", "Lapsed Costly"]


# --------------------------------------------------------------------------
# Category + amount fallback
# --------------------------------------------------------------------------

def test_fallback_category_amount_group():
    g = _one(_series([30] * 4, 350000, merchant=None, cat=7, cat_name="Synthetic Bills"))
    assert g["key_type"] == "category"
    assert "Synthetic Bills" in g["label"] and "~" in g["label"]


def test_fallback_notes_key_when_no_merchant():
    g = _one(_series([30] * 4, 50000, merchant=None, notes="Synthetic Rent Note"))
    assert g["key_type"] == "text"
    assert g["label"] == "Synthetic Rent Note"


def test_fallback_boundary_pair_one_cluster():
    amounts = [100000, 104500] * 3
    g = _one(_series([30] * 5, amounts, merchant=None, cat=7, cat_name="Synthetic Bills"))
    assert g["occurrences"] == 6


def test_fallback_distinct_amounts_two_clusters():
    d = datetime.timedelta
    a = _series([30] * 4, 100000, merchant=None, cat=7, cat_name="Synthetic Bills")
    b = [(next(_ids), r[1] - d(days=15), r[2] * 2, 1, None, None, 7, "Synthetic Bills") for r in a]
    assert len(_recurring_groups(a + b, TODAY)) == 2


def test_rows_without_text_or_category_skipped():
    assert _recurring_groups(_series([30] * 4, 50000, merchant=None), TODAY) == []


# --------------------------------------------------------------------------
# Same-day duplicates and evidence
# --------------------------------------------------------------------------

def test_same_day_duplicates_one_occurrence_summed():
    rows = _series([30] * 4, 50000)
    day = rows[2][1].date()
    rows.append((next(_ids), _dt(day), -50000, 1, "Synthetic Stream", None, None, None))
    g = _one(rows)
    assert g["occurrences"] == 5
    assert g["amount_max"] == 100000.0
    assert len(g["evidence"]) == 6


def test_evidence_shape_and_cap():
    g = _one(_series([30] * 14, 50000))
    assert g["occurrences"] == 15
    ev = g["evidence"]
    assert len(ev) == 12
    assert [e["date"] for e in ev] == sorted((e["date"] for e in ev), reverse=True)
    for e in ev:
        assert set(e) == {"id", "date", "amount", "account_id"}
        assert isinstance(e["amount"], float) and e["amount"] < 0


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

def test_confidence_medium_text_three():
    assert _one(_series([30] * 2, 50000))["confidence"] == "medium"


def test_confidence_low_category_min_count():
    g = _one(_series([30] * 2, 50000, merchant=None, cat=7, cat_name="Synthetic Bills"))
    assert g["confidence"] == "low"


def test_confidence_medium_category_four_tight():
    g = _one(_series([30] * 3, 50000, merchant=None, cat=7, cat_name="Synthetic Bills"))
    assert g["confidence"] == "medium"


def test_confidence_outlier_demotes_to_low():
    g = _one(_series([30] * 5, [100000] * 5 + [140000]))
    assert g["confidence"] == "low"


def test_confidence_spread_gate_rejects():
    rows = _series([30] * 5, [30000, 40000, 100000, 100000, 100000, 200000])
    assert _recurring_groups(rows, TODAY) == []


@pytest.mark.parametrize("gaps,amounts", [
    ([7] * 7, [15000, 60000, 25000, 40000, 18000, 55000, 30000, 45000]),
    ([30] * 5, [100000, 110000, 95000, 105000, 120000, 90000]),
    ([7] * 5, [30000, 30000, 30000, 30000, 30000, 36000]),
    ([30] * 4, [40000, 52000, 44000, 60000, 41000]),
])
def test_confidence_variable_amount_never_high(gaps, amounts):
    for g in _recurring_groups(_series(gaps, amounts, end_gap=2), TODAY):
        assert g["confidence"] != "high"


# --------------------------------------------------------------------------
# DB-seeded tests (monai_test)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded():
    from sqlalchemy import text
    from backend.db import engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
        return

    tag = uuid.uuid4().hex[:8]
    ticker = f"ZZR{tag[:6].upper()}"
    plat = f"zzrec {tag} platform"
    today = datetime.date.today()
    ids: dict = {}
    try:
        with engine.begin() as c:
            def acct(name, typ):
                return c.execute(text(
                    "INSERT INTO accounts (name, type, currency) VALUES (:n, :t, 'IDR') RETURNING id"),
                    {"n": name, "t": typ}).scalar()

            def cat(name, system):
                return c.execute(text(
                    "INSERT INTO categories (name, parent_id, kind, is_system) "
                    "VALUES (:n, NULL, 'expense', :s) RETURNING id"),
                    {"n": name, "s": system}).scalar()

            ids["liquid"] = acct(f"ZZRec {tag} Liquid", "liquid")
            ids["inv"] = acct(f"ZZRec {tag} Inv", "investment")
            ids["cat"] = cat(f"ZZRec {tag} Cat", False)
            ids["sys"] = cat(f"ZZRec {tag} Sys", True)
            ids["plat"] = c.execute(text(
                "INSERT INTO platforms (name, kind) VALUES (:n, 'test') "
                "ON CONFLICT (name) DO UPDATE SET kind = 'test' RETURNING id"), {"n": plat}).scalar()

            def series(name, *, account, category, transfer=False, link=False):
                merchant = f"ZZRec {tag} {name}"
                for k in range(5):
                    d = datetime.datetime.combine(
                        today - datetime.timedelta(days=30 * k), datetime.time(9, 0))
                    tid = c.execute(text(
                        "INSERT INTO transactions (date, amount, currency, category_id, merchant, "
                        "account_id, is_transfer) VALUES (:d, -50000, 'IDR', :cid, :m, :aid, :tr) "
                        "RETURNING id"),
                        {"d": d, "cid": category, "m": merchant, "aid": account, "tr": transfer}).scalar()
                    if link:
                        c.execute(text(
                            "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, "
                            "platform_id, transaction_id) VALUES (:d, :t, 'buy', 1, 50000, :p, :tid)"),
                            {"d": d.date(), "t": ticker, "p": ids["plat"], "tid": tid})

            series("Control", account=ids["liquid"], category=ids["cat"])
            series("Nocat", account=ids["liquid"], category=None)
            series("Transfer", account=ids["liquid"], category=ids["cat"], transfer=True)
            series("Linked", account=ids["liquid"], category=ids["cat"], link=True)
            series("Invacct", account=ids["inv"], category=ids["cat"])
            series("System", account=ids["liquid"], category=ids["sys"])
            # Unlinked event: a NULL transaction_id must not empty the result.
            c.execute(text(
                "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id) "
                "VALUES (:d, :t, 'buy', 1, 50000, :p)"),
                {"d": today, "t": ticker, "p": ids["plat"]})
        yield tag
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM portfolio_events WHERE ticker = :t"), {"t": ticker})
            c.execute(text("DELETE FROM transactions WHERE account_id = ANY(:a)"),
                      {"a": [v for k, v in ids.items() if k in ("liquid", "inv")]})
            c.execute(text("DELETE FROM platforms WHERE name = :n"), {"n": plat})
            c.execute(text("DELETE FROM categories WHERE id = ANY(:i)"),
                      {"i": [v for k, v in ids.items() if k in ("cat", "sys")]})
            c.execute(text("DELETE FROM accounts WHERE id = ANY(:a)"),
                      {"a": [v for k, v in ids.items() if k in ("liquid", "inv")]})


def test_exclusion_structural(seeded):
    from backend.tools import recurring_charges
    tag = seeded
    labels = {g["label"].lower(): g for g in recurring_charges(limit=50)["groups"]}
    mine = {k.split(f"zzrec {tag} ")[1]: v for k, v in labels.items() if f"zzrec {tag} " in k}
    assert set(mine) == {"control", "nocat"}
    assert mine["control"]["status"] == "active"


def test_limit_and_months_clamped(seeded):
    from backend.tools import recurring_charges
    assert recurring_charges(months=0)["months"] == 3
    assert recurring_charges(months=999)["months"] == 60
    assert len(recurring_charges(limit=0)["groups"]) <= 1
    assert len(recurring_charges(limit=999)["groups"]) <= 50


def test_recurring_result_shape_and_json(seeded):
    from backend.tools import recurring_charges
    r = recurring_charges()
    assert r["tool"] == "recurring_charges"
    assert {"groups", "months", "total_detected", "note"} <= set(r)
    json.dumps(r)


def test_signature_is_db_free():
    from backend.tools import recurring_charges
    sig = inspect.signature(recurring_charges)
    assert list(sig.parameters) == ["months", "limit"]
    assert all(p.annotation is int for p in sig.parameters.values())
