"""Tests for backend/net_worth_history.py -- Phase 22 Trend Series
Composition & Data-Model Decision (NWH-02).

LIVE AUDIT -- this file lives in backend/tests_live_audit/, outside
`testpaths` (pyproject.toml) and outside backend/tests/conftest.py's guard
(mirrors backend/tests_live_audit/test_investment_reconstruction.py's own
warning verbatim), so a default `pytest` run never collects it and it
never inherits the guarded conftest's monai_test default or its refusal.
It is re-run deliberately against live `monai`:
`DATABASE_URL=postgresql+psycopg://monai:monai@localhost:5434/monai .venv/bin/pytest backend/tests_live_audit/test_net_worth_history.py -x -q -p no:cacheprovider`

Every test in this file is either read-only against that database, or
performs its writes inside a transaction that is ALWAYS unwound in a
finally block. Seed rows, where any exist, are created with db.add(...)
followed by db.flush(), never a session-persist call, and the caller
always runs db_session.rollback() in a finally block -- the session is
NEVER persisted with a commit call.

Parity is verified per D-11 (22-CONTEXT.md), not ROADMAP SC2's literal
wording: half by half against like-typed sources, never the composed total
against a second live net_worth()/portfolio_summary() call.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

# ---------------------------------------------------------------------------
# DB fixtures -- copied verbatim from
# backend/tests_live_audit/test_investment_reconstruction.py (that file's own
# convention is copy, not import/share).
# ---------------------------------------------------------------------------


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


@pytest.fixture(scope="module")
def client():
    """This file no longer sees backend/tests/conftest.py's session-scoped
    `client` fixture (it lives outside testpaths), so define it locally --
    same TestClient(app) the guarded conftest builds."""
    from backend.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _current_month() -> str:
    """The current-month bucket, resolved dynamically -- never a literal
    'YYYY-MM' string, so this file does not silently rot (T-22-19)."""
    return date.today().strftime("%Y-%m")


def _end_excl_for_month(month: str) -> date:
    """Exclusive month-end boundary for a 'YYYY-MM' string -- copied
    verbatim from backend/tests_live_audit/test_investment_reconstruction.py, the same
    half-open convention `_MONTH_SQL` uses."""
    year, mon = (int(p) for p in month.split("-"))
    return date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)


def _months_back_to_ledger_start(db_session) -> int:
    """23.1 D-05 sampling adequacy. The `months=` window guaranteed to reach
    back through the Wallet ledger's own start, so non-vacuity guards over
    the pre-anchor archival range cannot rot as the calendar advances past a
    fixed lookback. Derived from the test's own independent SQL, never a
    module constant. The `+ 2` covers the partial first calendar month and
    today's not-yet-complete month."""
    first = db_session.connection().execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    today = date.today()
    return (today.year - first.year) * 12 + (today.month - first.month) + 2


# ---------------------------------------------------------------------------
# Task 1: envelope, SC4 both-halves, D-04/D-06 honesty
# ---------------------------------------------------------------------------


def test_envelope_mirrors_both_sibling_engines(db_session):
    """The composed envelope's five keys (23.1 D-06 adds
    `liquid_drift_estimate`), the composition's own tool name (never either
    engine's), and the zip-safety proof: the composed month vocabulary is
    set-equal to both sibling engines' month vocabularies for the same
    `months` argument."""
    from backend.investment_reconstruction import monthly_investment_series
    from backend.net_worth_history import monthly_net_worth_series
    from backend.reconstruction import liquid_drift_estimate, monthly_liquid_series

    months = 72
    conn = db_session.connection()

    composed = monthly_net_worth_series(months=months, db=db_session)
    liquid = monthly_liquid_series(months=months, conn=conn)
    investment = monthly_investment_series(months=months, db=db_session)

    assert list(composed.keys()) == ["tool", "rows", "honest_months", "gap_summary", "liquid_drift_estimate"]
    assert composed["tool"] == "net_worth_history_series"
    assert composed["tool"] not in (liquid["tool"], investment["tool"])
    assert len(composed["rows"]) == months
    assert composed["liquid_drift_estimate"] == liquid_drift_estimate(conn=conn)

    composed_months = [r["month"] for r in composed["rows"]]
    assert len(composed_months) == len(set(composed_months)), composed_months
    assert composed_months == sorted(composed_months), composed_months

    liquid_months = {r["month"] for r in liquid["rows"]}
    investment_months = {r["month"] for r in investment["rows"]}
    assert set(composed_months) == liquid_months == investment_months


def test_every_row_carries_both_halves(db_session):
    """SC4/NWH-06. Every row -- honest or not -- carries both sub-objects
    with exactly their expected keys. Non-vacuous: asserts at least one
    gapped row exists, over a window guaranteed to reach the Wallet ledger's
    own pre-history (23.1 D-05) rather than a fixed 72-month lookback that
    could rot as the calendar advances."""
    from backend.net_worth_history import monthly_net_worth_series

    result = monthly_net_worth_series(months=_months_back_to_ledger_start(db_session), db=db_session)
    rows = result["rows"]

    liquid_keys = {"total", "by_account", "honest", "gap_reason", "valuation_basis"}
    investment_keys = {
        "total", "by_position", "honest", "gap_reason", "valuation_basis", "as_of_date",
    }

    gapped_seen = False
    for row in rows:
        assert isinstance(row["liquid"], dict), row
        assert isinstance(row["investment"], dict), row
        assert set(row["liquid"].keys()) == liquid_keys, row
        assert set(row["investment"].keys()) == investment_keys, row
        if not row["honest"]:
            gapped_seen = True

    assert gapped_seen, "expected at least one gapped row in the ledger-start window"


def test_combined_total_requires_both_halves_honest(db_session):
    """D-04/D-06. `honest` iff both halves honest; `total` is a Decimal sum
    when honest, `None` otherwise -- never a partial sum, never zero,
    never carried forward. `honest_months` mirrors the honest rows in
    order."""
    from backend.net_worth_history import monthly_net_worth_series

    result = monthly_net_worth_series(months=72, db=db_session)
    rows = result["rows"]

    expected_honest_months = []
    for row in rows:
        both_honest = bool(row["liquid"]["honest"]) and bool(row["investment"]["honest"])
        assert row["honest"] == both_honest, row
        if both_honest:
            expected_honest_months.append(row["month"])
            assert isinstance(row["total"], Decimal), row
            assert row["total"] == row["liquid"]["total"] + row["investment"]["total"], row
        else:
            assert row["total"] is None, row

    assert result["honest_months"] == expected_honest_months


def test_gap_reasons_are_members_of_their_enums(db_session):
    """Every non-None gap_reason belongs to its own enum, and the composed
    enum is disjoint from both sibling enums -- free text is never
    emitted."""
    from backend.investment_reconstruction import INVESTMENT_GAP_REASONS
    from backend.net_worth_history import COMPOSED_GAP_REASONS, monthly_net_worth_series
    from backend.reconstruction import GAP_REASONS

    result = monthly_net_worth_series(months=72, db=db_session)
    for row in result["rows"]:
        if row["gap_reason"] is not None:
            assert row["gap_reason"] in COMPOSED_GAP_REASONS, row
        if row["liquid"]["gap_reason"] is not None:
            assert row["liquid"]["gap_reason"] in GAP_REASONS, row
        if row["investment"]["gap_reason"] is not None:
            assert row["investment"]["gap_reason"] in INVESTMENT_GAP_REASONS, row

    assert set(COMPOSED_GAP_REASONS) & set(GAP_REASONS) == set()
    assert set(COMPOSED_GAP_REASONS) & set(INVESTMENT_GAP_REASONS) == set()


def test_d05_spot_values_reproduce_preview(db_session):
    """23.1 D-05/D-06. Re-derives the composed total for the three
    user-approved D-05 preview months entirely from this test's own raw
    SQL -- never a module constant -- and proves the composed total equals
    the independently-derived liquid + investment sum exactly (research
    Pitfall 1's no-double-count proof). The liquid oracle's literal
    Adjustment exclusion doubles as the research Pitfall 4 tripwire: a
    back-dated anchor round landing before these months would move the
    engine's own honest total without moving this independently-derived
    oracle, making this test fail loudly -- the intended signal to
    re-derive the regime, never a signal to weaken this test."""
    from backend.net_worth_history import monthly_net_worth_series

    conn = db_session.connection()
    source = "corrections_260620"

    def _expected_liquid(end_excl):
        ledger = Decimal(
            str(
                conn.execute(
                    text(
                        "SELECT COALESCE(SUM(t.amount), 0) FROM transactions t "
                        "JOIN accounts a ON a.id = t.account_id "
                        "WHERE a.type = 'liquid' AND t.category IS DISTINCT FROM 'Adjustment' "
                        "AND t.date < :end_excl"
                    ),
                    {"end_excl": end_excl},
                ).scalar()
            )
        )
        corrections = Decimal(
            str(
                conn.execute(
                    text(
                        "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
                        "WHERE source = :source AND date < :end_excl "
                        "AND orig_account IN (SELECT name FROM accounts WHERE type = 'liquid')"
                    ),
                    {"source": source, "end_excl": end_excl},
                ).scalar()
            )
        )
        return ledger + corrections

    def _expected_deposits(end_excl):
        return Decimal(
            str(
                conn.execute(
                    text(
                        "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
                        "WHERE source = :source AND orig_account = 'Investements' AND date < :end_excl"
                    ),
                    {"source": source, "end_excl": end_excl},
                ).scalar()
            )
        )

    def _expected_snapshot(month):
        month_start = date.fromisoformat(f"{month}-01")
        end_excl = _end_excl_for_month(month)
        snapshot_day = conn.execute(
            text(
                "SELECT MAX(snapshot_date) FROM portfolio_value_history "
                "WHERE snapshot_date >= :start AND snapshot_date < :end_excl"
            ),
            {"start": month_start, "end_excl": end_excl},
        ).scalar()
        total = conn.execute(
            text(
                "SELECT COALESCE(SUM(market_value), 0) FROM portfolio_value_history "
                "WHERE snapshot_date = :snapshot_date AND currency = 'IDR'"
            ),
            {"snapshot_date": snapshot_day},
        ).scalar()
        return Decimal(str(total))

    result = monthly_net_worth_series(months=_months_back_to_ledger_start(db_session), db=db_session)
    rows_by_month = {r["month"]: r for r in result["rows"]}

    expected_investment_basis = {"2024-09": "deposits", "2026-06": "deposits", "2026-07": "snapshot"}
    for month, basis in expected_investment_basis.items():
        row = rows_by_month[month]
        end_excl = _end_excl_for_month(month)
        expected_liquid = _expected_liquid(end_excl)
        expected_investment = _expected_snapshot(month) if basis == "snapshot" else _expected_deposits(end_excl)

        assert row["honest"] is True, row
        assert row["liquid"]["total"] == expected_liquid, (month, row["liquid"]["total"], expected_liquid)
        assert row["investment"]["total"] == expected_investment, (
            month, row["investment"]["total"], expected_investment,
        )
        assert row["total"] == expected_liquid + expected_investment, row
        assert row["liquid"]["valuation_basis"] == "ledger_plus_corrections", row
        assert row["investment"]["valuation_basis"] == basis, row

    newest = result["rows"][-1]
    assert newest["honest"] is True, newest
    assert newest["liquid"]["valuation_basis"] is None, newest
    assert newest["investment"]["valuation_basis"] == "snapshot", newest
    assert newest["total"] == newest["liquid"]["total"] + newest["investment"]["total"], newest


def test_archival_months_compose_honestly_and_pre_ledger_months_gap(db_session):
    """Replaces test_pre_investment_floor_month_still_gaps, whose premise
    (every live month before the investment floor still gaps) the D-01/D-05
    relaxations removed. Over a window reaching the Wallet ledger's own
    start: the very first bucket (pre-ledger) still gaps both halves
    honestly, and every archival month from the ledger start up to (not
    including) the month containing the independently-derived liquid anchor
    composes an honest total on a ledger_plus_corrections/deposits basis."""
    from backend.net_worth_history import monthly_net_worth_series

    conn = db_session.connection()
    result = monthly_net_worth_series(months=_months_back_to_ledger_start(db_session), db=db_session)
    rows = result["rows"]

    earliest = rows[0]
    end_excl = _end_excl_for_month(earliest["month"])
    month_end = end_excl - timedelta(days=1)
    earliest_liquid_tx = conn.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    assert month_end < earliest_liquid_tx, (
        f"earliest bucket {earliest['month']} (month_end={month_end}) does not "
        f"precede the ledger start ({earliest_liquid_tx}) -- widen the window "
        "or re-diagnose"
    )
    assert earliest["honest"] is False, earliest
    assert earliest["total"] is None, earliest
    assert earliest["gap_reason"] == "both_halves_gapped", earliest
    assert earliest["liquid"]["gap_reason"] == "pre_ledger", earliest
    assert earliest["investment"]["gap_reason"] == "no_investment_tracking_before_launch", earliest

    # Independently-derived liquid anchor: MAX over every live liquid
    # account's own first Adjustment date (same derivation as
    # backend/tests_live_audit/test_reconstruction.py's own anchor oracle).
    anchor_rows = conn.execute(
        text(
            "SELECT a.name, MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id "
            "WHERE a.type = 'liquid' AND t.category = 'Adjustment' "
            "GROUP BY a.name"
        )
    ).all()
    liquid_names = [
        r[0] for r in conn.execute(text("SELECT name FROM accounts WHERE type = 'liquid'")).all()
    ]
    anchor_by_account = dict(anchor_rows)
    assert all(name in anchor_by_account for name in liquid_names), (
        "expected every live liquid account to carry a full anchor on today's data"
    )
    liquid_anchor = max(anchor_by_account.values())

    snapshot_floor = conn.execute(text("SELECT MIN(snapshot_date) FROM portfolio_value_history")).scalar()

    archival_honest_count = 0
    for row in rows[1:]:
        row_end_excl = _end_excl_for_month(row["month"])
        row_month_end = row_end_excl - timedelta(days=1)
        if row_month_end >= liquid_anchor:
            break
        assert row["honest"] is True, row
        assert row["liquid"]["valuation_basis"] == "ledger_plus_corrections", row
        if snapshot_floor is not None and row_month_end < snapshot_floor:
            assert row["investment"]["valuation_basis"] == "deposits", row
        archival_honest_count += 1

    assert archival_honest_count >= 60, (
        f"expected at least 60 honest archival rows before the liquid anchor, "
        f"got {archival_honest_count}"
    )


def test_months_bound_rejects_out_of_range(db_session):
    """months outside 1-600 raises ValueError before any DB work; 1 and 600
    do not."""
    from backend.net_worth_history import monthly_net_worth_series

    for bad in (0, -1, 99999):
        with pytest.raises(ValueError):
            monthly_net_worth_series(months=bad, db=db_session)

    for good in (1, 600):
        monthly_net_worth_series(months=good, db=db_session)


# ---------------------------------------------------------------------------
# Task 2: D-11 parity tests and the D-08 forced-mismatch proof
# ---------------------------------------------------------------------------


def test_newest_bucket_liquid_half_matches_live_net_worth_liquid(db_session):
    """SC2-b, the genuinely failable half of D-11. The newest bucket's
    liquid total equals net_worth()'s live liquid half (a fresh SUM at call
    time, no snapshot lag), compared as Decimal quantized to whole IDR --
    that quantization IS the documented parity tolerance (D-11), never an
    unstated side effect."""
    from backend.net_worth_history import monthly_net_worth_series
    from backend.tools import account_balances

    result = monthly_net_worth_series(months=12, db=db_session)
    newest = result["rows"][-1]
    assert newest["month"] == _current_month(), newest["month"]

    if not newest["liquid"]["honest"]:
        pytest.fail(
            f"newest bucket {newest['month']}'s liquid half is not honest "
            f"(gap_reason={newest['liquid']['gap_reason']!r}) -- an "
            "unexpectedly gapped liquid half is itself the regression this "
            "test exists to catch"
        )

    live_liquid = sum(
        (Decimal(str(r["current_balance"])) for r in account_balances()["rows"] if r["type"] == "liquid"),
        Decimal("0"),
    )
    one = Decimal("1")
    assert newest["liquid"]["total"].quantize(one) == live_liquid.quantize(one), (
        newest["liquid"]["total"], live_liquid
    )


def test_newest_bucket_investment_half_matches_its_own_snapshot(db_session):
    """SC2-c/c'. The sum comparison re-reads the exact snapshot_date the
    composition already selected -- near-tautological by construction and
    accepted by D-11, since it can only catch a dropped/double-counted row,
    never a mis-selected date. NEVER replace it with a second live
    portfolio_summary()/net_worth() call: snapshot and live prices routinely
    drift apart by a small amount, so that variant is flaky by
    construction, independent of correctness.

    The independent as_of_date == MAX(snapshot_date)-in-window assertion is
    the only part with real teeth -- it is what actually catches a
    mis-selected snapshot day. Do not delete it as "redundant" with the sum
    check above."""
    from backend.net_worth_history import monthly_net_worth_series

    result = monthly_net_worth_series(months=12, db=db_session)
    newest = result["rows"][-1]
    investment = newest["investment"]

    if investment["valuation_basis"] != "snapshot":
        pytest.fail(
            f"newest bucket {newest['month']} is on valuation_basis="
            f"{investment['valuation_basis']!r}, not 'snapshot' -- this "
            "comparison assumes a real portfolio_value_history snapshot"
        )

    conn = db_session.connection()
    one = Decimal("1")

    # Sum comparison -- near-tautological by construction (D-11).
    snapshot_total = conn.execute(
        text(
            "SELECT COALESCE(SUM(market_value), 0) FROM portfolio_value_history "
            "WHERE snapshot_date = :snapshot_date"
        ),
        {"snapshot_date": investment["as_of_date"]},
    ).scalar()
    live_investment = Decimal(str(snapshot_total))
    assert investment["total"].quantize(one) == live_investment.quantize(one), (
        investment["total"], live_investment
    )

    # Independent mis-selection check -- closes the blind spot the sum
    # comparison above cannot, by construction.
    month_start = date.fromisoformat(f"{newest['month']}-01")
    end_excl = _end_excl_for_month(newest["month"])
    max_snapshot_in_window = conn.execute(
        text(
            "SELECT MAX(snapshot_date) FROM portfolio_value_history "
            "WHERE snapshot_date >= :start AND snapshot_date < :end_excl"
        ),
        {"start": month_start, "end_excl": end_excl},
    ).scalar()
    assert investment["as_of_date"] == max_snapshot_in_window, (
        investment["as_of_date"], max_snapshot_in_window
    )


def test_newest_bucket_is_not_parity_gapped_on_live_data(db_session):
    """The standing regression pin. A failure here means either a real
    disagreement or that D-11's like-for-like rule regressed to a
    live-vs-snapshot comparison."""
    from backend.net_worth_history import monthly_net_worth_series

    result = monthly_net_worth_series(months=12, db=db_session)
    newest = result["rows"][-1]
    assert newest["gap_reason"] != "parity_mismatch", newest


def test_forced_parity_mismatch_gaps_one_row_and_spares_the_rest(db_session, monkeypatch):
    """SC2-d, the "does not silently proceed" proof and the only way to
    exercise the D-08 soft-gap path. Forces the parity helper itself
    (backend.net_worth_history._parity_verdict) to disagree unconditionally,
    then proves exactly one row (the newest) is affected and every other row
    is byte-identical to an unpatched call -- including both sub-objects on
    the gapped row itself, since the parity verdict is a statement about the
    combined number, not either half's own reconstruction."""
    from backend.net_worth_history import monthly_net_worth_series

    unpatched = monthly_net_worth_series(months=12, db=db_session)

    monkeypatch.setattr(
        "backend.net_worth_history._parity_verdict",
        lambda db, row: "parity_mismatch",
    )
    patched = monthly_net_worth_series(months=12, db=db_session)

    last = patched["rows"][-1]
    unpatched_last = unpatched["rows"][-1]

    assert last["honest"] is False, last
    assert last["total"] is None, last
    assert last["gap_reason"] == "parity_mismatch", last
    assert last["month"] not in patched["honest_months"], patched["honest_months"]
    assert patched["gap_summary"].get("parity_mismatch") == 1, patched["gap_summary"]

    assert patched["rows"][:-1] == unpatched["rows"][:-1]

    assert last["liquid"] == unpatched_last["liquid"], (last["liquid"], unpatched_last["liquid"])
    assert last["investment"] == unpatched_last["investment"], (
        last["investment"], unpatched_last["investment"]
    )


def test_parity_check_fails_closed_on_error(db_session, monkeypatch):
    """T-22-07. Fault injected at exactly backend.tools.account_balances --
    NOT a backend.net_worth_history attribute of the same name, which the
    parity helper's lazy in-function import would make a silent no-op. An
    exception inside the comparison must never yield an unverified total.
    The baseline call before patching sanity-checks that the injection
    actually fired: unpatched, the newest row is not parity-gapped; patched,
    it must be."""
    from backend.net_worth_history import monthly_net_worth_series

    baseline = monthly_net_worth_series(months=12, db=db_session)
    assert baseline["rows"][-1]["gap_reason"] != "parity_mismatch", baseline["rows"][-1]

    def _raiser(*args, **kwargs):
        raise RuntimeError("forced account_balances failure")

    monkeypatch.setattr("backend.tools.account_balances", _raiser)

    result = monthly_net_worth_series(months=12, db=db_session)
    newest = result["rows"][-1]

    assert newest["gap_reason"] == "parity_mismatch", newest
    assert newest["honest"] is False, newest
    assert newest["total"] is None, newest


def test_liquid_only_gap_nulls_the_total_but_keeps_the_investment_half(db_session, monkeypatch):
    """D-04 + D-06, made data-independent (23.1). The pre-anchor relaxation
    means no live month is guaranteed any more to have a real liquid-only
    gap, so this test forces one via a monkeypatched wrapper around
    `backend.net_worth_history.monthly_liquid_series` rather than searching
    for a naturally-occurring one. The composed target row must still null
    the total while the investment sub-object stays byte-identical to the
    unpatched call and honest, and every other row must be untouched."""
    from backend import net_worth_history
    from backend.net_worth_history import monthly_net_worth_series

    # WR-06: the whole ledger span, not a fixed 12-month lookback -- the
    # combined-honest past rows this test needs are pre-anchor months, which
    # age out of any fixed window as the calendar advances.
    months = _months_back_to_ledger_start(db_session)
    unpatched = monthly_net_worth_series(months=months, db=db_session)
    rows = unpatched["rows"]

    target_month = None
    for row in rows[:-1]:
        if row["honest"]:
            target_month = row["month"]
            break

    if target_month is None:
        pytest.fail(
            "no combined-honest, non-newest month since the ledger start to "
            "force a liquid-only gap onto"
        )

    real_monthly_liquid_series = net_worth_history.monthly_liquid_series

    def _wrapper(months, *, conn):
        result = real_monthly_liquid_series(months=months, conn=conn)
        for row in result["rows"]:
            if row["month"] == target_month:
                row["liquid_by_account"] = None
                row["liquid_total"] = None
                row["valuation_basis"] = None
                row["honest"] = False
                row["gap_reason"] = "no_closing_anchor"
        return result

    monkeypatch.setattr("backend.net_worth_history.monthly_liquid_series", _wrapper)
    patched = monthly_net_worth_series(months=months, db=db_session)

    unpatched_by_month = {r["month"]: r for r in unpatched["rows"]}
    patched_by_month = {r["month"]: r for r in patched["rows"]}

    target = patched_by_month[target_month]
    unpatched_target = unpatched_by_month[target_month]

    assert target["total"] is None, target
    assert target["honest"] is False, target
    assert target["gap_reason"] == "liquid_half_gapped", target
    assert target["investment"] == unpatched_target["investment"], (
        target["investment"], unpatched_target["investment"],
    )
    assert target["investment"]["honest"] is True, target

    for month, row in patched_by_month.items():
        if month == target_month:
            continue
        assert row == unpatched_by_month[month], (month, row, unpatched_by_month[month])


# ---------------------------------------------------------------------------
# Task 3: SC3 regenerability, static no-write scan, migration head,
# endpoint contract, blast radius
# ---------------------------------------------------------------------------


def test_double_call_is_identical(db_session):
    """D-09, SC3-a. Two calls on one session return ==-equal output --
    compute-on-read means every call regenerates the series from source
    tables, so re-running and diffing the output IS the regenerability
    proof."""
    from backend.net_worth_history import monthly_net_worth_series

    first = monthly_net_worth_series(months=6, db=db_session)
    second = monthly_net_worth_series(months=6, db=db_session)
    assert first == second


def test_net_worth_history_module_has_no_write_imports():
    """D-09, SC3-b. Static scan of backend/net_worth_history.py's own
    source, the `_offending()` idiom copied from
    backend/tests_live_audit/test_reconstruction.py:575-600. No write-module import, no
    write statement, no session-commit call. Positive half: module-level
    backend.* imports are limited to the two sibling engines + db module,
    and the only lazy in-function backend.* import is the read-side parity
    helper's own account_balances lookup."""
    import re
    from pathlib import Path

    from backend import net_worth_history

    source_lines = Path(net_worth_history.__file__).read_text(encoding="utf-8").splitlines()

    def _offending(pattern, flags=0):
        rx = re.compile(pattern, flags)
        return [(i + 1, ln) for i, ln in enumerate(source_lines) if rx.search(ln)]

    write_imports = _offending(r"^[ \t]*(from|import)[ \t]+backend\.writes\b")
    assert not write_imports, f"write-module import(s): {write_imports}"

    write_stmts = _offending(
        r"(INSERT[ \t]+INTO|UPDATE[ \t]+[a-z_]+[ \t]+SET|DELETE[ \t]+FROM)", re.IGNORECASE
    )
    assert not write_stmts, f"write statement(s): {write_stmts}"

    commit_calls = _offending(r"\.commit\(\)")
    assert not commit_calls, f"session-commit call(s): {commit_calls}"

    module_level_imports = _offending(r"^(from|import)[ \t]+backend\.")
    allowed_module_level = {
        "from backend.db import SessionLocal",
        "from backend.investment_reconstruction import monthly_investment_series",
        "from backend.reconstruction import liquid_drift_estimate, monthly_liquid_series",
    }
    for lineno, line in module_level_imports:
        assert line.strip() in allowed_module_level, f"unexpected module-level import at {lineno}: {line}"

    lazy_imports = _offending(r"^[ \t]+(from|import)[ \t]+backend\.")
    allowed_lazy = {"from backend.tools import account_balances"}
    for lineno, line in lazy_imports:
        assert line.strip() in allowed_lazy, f"unexpected lazy import at {lineno}: {line}"


def test_no_migration_was_added_this_phase():
    """D-03, SC3-c. The highest-sorted REVISION FILE (never a bare
    directory listing, which sorts __pycache__ last) in alembic/versions/ is
    still the Phase 20 correction-table migration."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    versions_dir = repo_root / "alembic" / "versions"
    revision_files = sorted(versions_dir.glob("[0-9]*.py"))
    assert revision_files, f"no revision files found under {versions_dir} -- selector regressed"
    newest = revision_files[-1].name
    assert newest == "014_recon_backfill.py", (
        f"newest alembic revision is {newest!r}, not '014_recon_backfill.py' -- "
        "this phase is compute-on-read (D-03); a new migration means the "
        "superseded persisted-table design crept back in"
    )


def test_endpoint_returns_both_halves_per_row(client):
    """D-07, the HTTP contract. GET /cashflow/networth-history returns both
    sub-objects per row, the D-06 `liquid_drift_estimate` envelope field, and
    rejects out-of-range/non-integer `months` with 422."""
    resp = client.get("/cashflow/networth-history", params={"months": 12})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) == {"rows", "honest_months", "gap_summary", "liquid_drift_estimate"}
    assert body["liquid_drift_estimate"] is None or isinstance(body["liquid_drift_estimate"], float), (
        body["liquid_drift_estimate"]
    )
    assert len(body["rows"]) == 12
    for row in body["rows"]:
        assert row.get("liquid") is not None, row
        assert row.get("investment") is not None, row
        assert "valuation_basis" in row["liquid"], row
        if not row["honest"]:
            assert row["total"] is None, row

    for bad_months in (0, 99999):
        bad_resp = client.get("/cashflow/networth-history", params={"months": bad_months})
        assert bad_resp.status_code == 422, bad_resp.text

    abc_resp = client.get("/cashflow/networth-history", params={"months": "abc"})
    assert abc_resp.status_code == 422, abc_resp.text


def test_blast_radius_zero(db_session, client):
    """The live-DB safety proof. Row counts for five candidate tables are
    unchanged before/after a full 72-month composition call and one endpoint
    call."""
    from backend.net_worth_history import monthly_net_worth_series

    tables = ("transactions", "accounts", "holdings", "portfolio_events", "portfolio_value_history")
    conn = db_session.connection()

    def _counts():
        return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}

    before = _counts()
    monthly_net_worth_series(months=72, db=db_session)
    client.get("/cashflow/networth-history", params={"months": 12})
    after = _counts()

    for table in tables:
        delta = after[table] - before[table]
        assert delta == 0, f"{table} changed by {delta} (before={before[table]}, after={after[table]})"
