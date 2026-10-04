"""Tests for backend/investment_reconstruction.py -- Phase 21 Investment-Value
Backfill (RECON-04, RECON-05, RECON-06).

LIVE AUDIT -- this file lives in backend/tests_live_audit/, outside
`testpaths` (pyproject.toml) and outside backend/tests/conftest.py's guard
(mirrors backend/tests_live_audit/test_reconstruction.py's own warning
verbatim), so a default `pytest` run never collects it and it never
inherits the guarded conftest's monai_test default or its refusal. It is
re-run deliberately against live `monai`:
`DATABASE_URL=postgresql+psycopg://monai:monai@localhost:5434/monai .venv/bin/pytest backend/tests_live_audit/test_investment_reconstruction.py -x -q -p no:cacheprovider`

Every test in this file is either read-only against that database, or
performs its writes inside a transaction that is ALWAYS unwound in a
finally block. Seed rows are created with db.add(...) followed by
db.flush(), never a session-persist call, on any receiver.

Wave 0 scaffold: tests 1-6 and 9 import backend.investment_reconstruction
inside the test body (not at module import time), so collection succeeds
before that module exists -- the ModuleNotFoundError they raise until Task 2
lands is the intended RED state, not a defect in this file.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

_TEST_PREFIX = "zzInvTest"


# ---------------------------------------------------------------------------
# DB fixtures -- copied verbatim from backend/tests_live_audit/test_reconstruction.py
# (that file's own convention is copy, not import/share).
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


# ---------------------------------------------------------------------------
# Seed / spy helpers
# ---------------------------------------------------------------------------

def _make_event(
    db, *, ticker, platform_id, on_date, event_type, quantity, price, currency="IDR"
) -> int:
    """db.add(...) + db.flush() only -- never a session-persist call, so the
    caller's finally: db_session.rollback() always undoes it (T-21-08)."""
    from backend.models import PortfolioEvent

    ev = PortfolioEvent(
        date=on_date,
        ticker=ticker,
        event_type=event_type,
        quantity=quantity,
        price=price,
        platform_id=platform_id,
        currency=currency,
    )
    db.add(ev)
    db.flush()
    return ev.id


def _end_excl_for_month(month: str) -> date:
    """Exclusive month-end boundary for a 'YYYY-MM' string -- the same
    half-open convention `_MONTH_SQL` uses, so tests can derive `month_end`
    without reaching into the module's private SQL."""
    year, mon = (int(p) for p in month.split("-"))
    return date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)


def _fx_spy(monkeypatch, rate):
    """Replace backend.fx.get_rate with a recorder returning `rate` for every
    call. Patches the attribute on the backend.fx module object so the
    engine's `fx.get_rate(...)` call site resolves to it. Returns the list of
    (base, quote, as_of) triples recorded, in call order."""
    calls: list[tuple[str, str, date]] = []

    def _fake_get_rate(base, quote, as_of, db):
        calls.append((base, quote, as_of))
        return rate

    monkeypatch.setattr("backend.fx.get_rate", _fake_get_rate)
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_replay_uses_last_transacted_price_and_event_date_fx(db_session, monkeypatch):
    """RECON-04 / Pitfall 4. Value = running qty * LAST price-bearing event's
    price * FX rate at that event's OWN date -- never today, never the
    bucket's month-end. Asserted by exact-argument spy equality, not a
    plausibility range."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-price"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 1),
            event_type="buy", quantity=Decimal("10"), price=Decimal("100.00"), currency="USD",
        )
        second_date = date(2026, 9, 1)
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=second_date,
            event_type="buy", quantity=Decimal("5"), price=Decimal("200.00"), currency="USD",
        )
        calls = _fx_spy(monkeypatch, Decimal("15000"))

        result = recon.reconstructed_investment_by_month(months=1, db=db_session)
        bucket = result[-1]
        pos = bucket["replay_by_position"][f"{ticker}@67"]

        assert pos["quantity"] == Decimal("15")
        assert pos["value"] == Decimal("15") * Decimal("200") * Decimal("15000")

        matching = [c for c in calls if c == ("USD", "IDR", second_date)]
        assert matching, calls
        assert not any(c[2] == date.today() for c in calls), calls
        month_end = bucket["end_excl"] - timedelta(days=1)
        assert not any(c[2] == month_end for c in calls), calls
    finally:
        db_session.rollback()


def test_deposit_increases_quantity_and_dividend_does_not(db_session, monkeypatch):
    """Buy + deposit increase quantity; a dividend changes neither the
    quantity nor the price basis used for valuation."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-depdiv"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 1),
            event_type="buy", quantity=Decimal("10"), price=Decimal("100.00"), currency="USD",
        )
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 15),
            event_type="deposit", quantity=Decimal("5"), price=Decimal("100.00"), currency="USD",
        )
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 9, 1),
            event_type="dividend", quantity=Decimal("1"), price=Decimal("999.00"), currency="USD",
        )
        _fx_spy(monkeypatch, Decimal("15000"))

        result = recon.reconstructed_investment_by_month(months=1, db=db_session)
        bucket = result[-1]
        pos = bucket["replay_by_position"][f"{ticker}@67"]

        assert pos["quantity"] == Decimal("15")  # 10 buy + 5 deposit
        # The dividend's price (999.00) must never become the mark -- the
        # basis stays the deposit's own price (100.00).
        assert pos["value"] == Decimal("15") * Decimal("100") * Decimal("15000")
    finally:
        db_session.rollback()


def test_sell_decreases_quantity_and_closed_position_is_not_held(db_session):
    """A full sell closes the position -- excluded entirely from the held
    set for a later bucket, never reported with quantity zero."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-sellclose"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 1),
            event_type="buy", quantity=Decimal("10"), price=Decimal("100.00"), currency="USD",
        )
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 15),
            event_type="sell", quantity=Decimal("10"), price=Decimal("120.00"), currency="USD",
        )

        result = recon.reconstructed_investment_by_month(months=1, db=db_session)
        bucket = result[-1]

        assert f"{ticker}@67" not in bucket["replay_by_position"]
    finally:
        db_session.rollback()


def test_unknown_event_type_gaps_the_position_instead_of_raising(db_session):
    """An unrecognised fifth event_type gaps that position instead of
    crashing or being silently skipped."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-splitunk"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 1),
            event_type="buy", quantity=Decimal("10"), price=Decimal("100.00"), currency="USD",
        )
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 15),
            event_type="split", quantity=Decimal("0"), price=Decimal("0.00"), currency="USD",
        )

        result = recon.reconstructed_investment_by_month(months=1, db=db_session)
        bucket = result[-1]
        pos = bucket["replay_by_position"][f"{ticker}@67"]

        assert pos["value"] is None
        assert pos["gap_reason"] == "unknown_event_type"
    finally:
        db_session.rollback()


def test_synthetic_opening_event_position_is_not_honest(db_session):
    """D-02. Provenance is read from the audit_log source marker, never a
    date heuristic: ETH@64's only event (id 3266) is migration-012 synthetic
    and must gap; BTC@64's only event (id 215), dated the same day, is
    organic and must resolve to a real value. A date heuristic would fail
    this exact pair."""
    from backend import investment_reconstruction as recon

    synthetic_ids = recon._synthetic_event_ids(db_session.connection())
    assert synthetic_ids == set(range(3266, 3277)), synthetic_ids

    result = recon.reconstructed_investment_by_month(months=3, db=db_session)
    bucket = result[-1]
    assert bucket["end_excl"] - timedelta(days=1) >= date(2026, 7, 11)

    eth = bucket["replay_by_position"]["ETH@64"]
    btc = bucket["replay_by_position"]["BTC@64"]
    assert eth["value"] is None
    assert eth["gap_reason"] == "synthetic_opening_only"
    assert btc["value"] is not None


def test_organic_dividend_does_not_clear_synthetic_only_gap(db_session):
    """CR-01. ETH@64's only price-bearing event is migration-012 synthetic.
    Adding an ORGANIC dividend (no organic buy/sell) must not launder that
    fabricated price into a resolved value -- a dividend is income per unit,
    never an instrument mark, so it may not clear the D-02 gap."""
    from backend import investment_reconstruction as recon

    try:
        _make_event(
            db_session, ticker="ETH", platform_id=64, on_date=date(2026, 8, 1),
            event_type="dividend", quantity=Decimal("0"), price=Decimal("5.00"),
            currency="IDR",
        )

        result = recon.reconstructed_investment_by_month(months=3, db=db_session)
        eth = result[-1]["replay_by_position"]["ETH@64"]

        assert eth["value"] is None
        assert eth["gap_reason"] == "synthetic_opening_only"
        assert eth["basis_is_synthetic_only"] is True
    finally:
        db_session.rollback()


def test_cash_sentinel_appears_without_a_holdings_row(db_session):
    """T-21-05 / Pitfall 3. The CASH sentinel (ticker CASH, platform 67) has
    no backing holdings row, and the replay never reads the holdings table,
    so it must still appear with its real quantity."""
    from backend import investment_reconstruction as recon

    result = recon.reconstructed_investment_by_month(months=1, db=db_session)
    bucket = result[-1]
    month_end = bucket["end_excl"] - timedelta(days=1)
    assert month_end >= date(2026, 9, 2)

    cash = bucket["replay_by_position"]["CASH@67"]
    assert cash["quantity"] == Decimal("500000.00000000")

    zero_holdings = db_session.execute(
        text("SELECT count(*) FROM holdings WHERE ticker = 'CASH'")
    ).scalar()
    assert zero_holdings == 0, "a holdings row for CASH would mask a join-based regression"


def _func_line_range(source: str, func_name: str) -> tuple[int, int]:
    """1-indexed inclusive [start, end] line range for a module-level
    function definition, derived via `ast` so callers never hardcode line
    numbers that would rot as the module changes."""
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node.lineno, node.end_lineno
    raise ValueError(f"function {func_name!r} not found in module source")


def test_replay_never_joins_the_holdings_table():
    """T-21-05, narrowed by Phase 22's D-01 fix. The raw-replay functions
    (`_replay_positions`, `reconstructed_investment_by_month`) must still
    never reference the holdings table in a FROM/JOIN clause -- that
    guarantee is unchanged. The scan is now SCOPED to just those two
    functions' line ranges (derived via `ast`, never hardcoded) because D-01
    legitimately adds one holdings read inside `monthly_investment_series`,
    which a whole-module scan would incorrectly flag."""
    import re
    from pathlib import Path

    from backend import investment_reconstruction as recon

    source = Path(recon.__file__).read_text(encoding="utf-8")
    source_lines = source.splitlines()

    def _offending(pattern, lo, hi, flags=0):
        rx = re.compile(pattern, flags)
        return [
            (i + 1, ln)
            for i, ln in enumerate(source_lines)
            if lo <= i + 1 <= hi and rx.search(ln)
        ]

    for func_name in ("_replay_positions", "reconstructed_investment_by_month"):
        lo, hi = _func_line_range(source, func_name)
        offending = _offending(r"(FROM|JOIN)[ \t]+holdings\b", lo, hi, re.IGNORECASE)
        assert not offending, f"holdings table reference(s) in {func_name} ({lo}-{hi}): {offending}"


def test_monthly_investment_series_reads_holdings_exactly_once():
    """Positive half of T-21-05, added by Phase 22's D-01 fix.

    (a) Over the module source with the two raw-replay function ranges
        REMOVED, the `(FROM|JOIN)\\s+holdings` regex matches EXACTLY ONCE --
        that one match is `_HOLDINGS_PRESENCE_SQL`'s own body. A second
        holdings query anywhere else in the module fails this test.
    (b) Inside `monthly_investment_series`' own line range, the identifier
        `_HOLDINGS_PRESENCE_SQL` is referenced EXACTLY ONCE -- the single
        once-per-call build. A per-bucket re-execution fails this test.

    All three line ranges are derived via `ast`, never hardcoded."""
    import re
    from pathlib import Path

    from backend import investment_reconstruction as recon

    source = Path(recon.__file__).read_text(encoding="utf-8")
    source_lines = source.splitlines()

    replay_lo, replay_hi = _func_line_range(source, "_replay_positions")
    raw_month_lo, raw_month_hi = _func_line_range(source, "reconstructed_investment_by_month")
    series_lo, series_hi = _func_line_range(source, "monthly_investment_series")

    def _in_raw_replay_range(line_no: int) -> bool:
        return (replay_lo <= line_no <= replay_hi) or (raw_month_lo <= line_no <= raw_month_hi)

    holdings_rx = re.compile(r"(FROM|JOIN)[ \t]+holdings\b", re.IGNORECASE)
    matches = [
        (i + 1, ln)
        for i, ln in enumerate(source_lines)
        if not _in_raw_replay_range(i + 1) and holdings_rx.search(ln)
    ]
    assert len(matches) == 1, (
        f"expected exactly one holdings query outside the raw-replay ranges: {matches}"
    )

    series_refs = [
        (i + 1, ln)
        for i, ln in enumerate(source_lines)
        if series_lo <= i + 1 <= series_hi and "_HOLDINGS_PRESENCE_SQL" in ln
    ]
    assert len(series_refs) == 1, (
        f"expected exactly one _HOLDINGS_PRESENCE_SQL reference inside "
        f"monthly_investment_series ({series_lo}-{series_hi}): {series_refs}"
    )


def test_no_price_adapter_registry_in_module():
    """21-RESEARCH.md Pitfall 5 / D-01. No PRICE_ADAPTERS-shaped registry and
    no import of backend.prices -- the price is the stored fact on
    portfolio_events.price, never a live/historical fetch."""
    from pathlib import Path

    from backend import investment_reconstruction as recon

    source = Path(recon.__file__).read_text(encoding="utf-8")
    assert "PRICE_ADAPTERS" not in source
    assert "backend.prices" not in source
    assert "backend import prices" not in source


def test_unresolvable_fx_gaps_the_position_and_never_uses_cost_basis(db_session, monkeypatch):
    """RECON-05. An unresolvable FX rate gaps that one position with
    value=None; the cost-basis figure (quantity * price) is never substituted
    for market value anywhere in the bucket, and DD-3 forbids a partial sum."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-fxgap"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2026, 8, 1),
            event_type="buy", quantity=Decimal("10"), price=Decimal("100.00"), currency="USD",
        )
        _fx_spy(monkeypatch, None)

        result = recon.reconstructed_investment_by_month(months=1, db=db_session)
        bucket = result[-1]
        pos = bucket["replay_by_position"][f"{ticker}@67"]

        assert pos["value"] is None
        assert pos["gap_reason"] == "fx_unavailable"
        assert bucket["replay_total"] is None

        cost_basis = Decimal("10") * Decimal("100")
        for p in bucket["replay_by_position"].values():
            assert p["value"] != cost_basis
    finally:
        db_session.rollback()


# ---------------------------------------------------------------------------
# Plan 21-02 -- snapshot regime, honesty gate, monthly_investment_series
# ---------------------------------------------------------------------------

def test_snapshot_regime_uses_the_in_month_snapshot_verbatim(db_session):
    """RECON-04 / D-03 / ROADMAP SC2. A snapshot-regime honest row reuses the
    real portfolio_value_history day verbatim -- no re-derivation. Both
    expectations are derived from live queries, not hardcoded, so this test
    survives new snapshots landing. Non-vacuous: asserts at least 2 honest
    snapshot rows exist first -- if DD-5 ever gaps every snapshot month, this
    test must go red, not silently green."""
    from backend import investment_reconstruction as recon

    result = recon.monthly_investment_series(months=12, db=db_session)
    snapshot_rows = [
        r for r in result["rows"] if r["honest"] and r["valuation_basis"] == "snapshot"
    ]
    assert len(snapshot_rows) >= 2, result["rows"]

    conn = db_session.connection()
    for row in snapshot_rows:
        month_start = date.fromisoformat(f"{row['month']}-01")
        end_excl = _end_excl_for_month(row["month"])
        expected_day = conn.execute(
            text(
                "SELECT MAX(snapshot_date) FROM portfolio_value_history "
                "WHERE snapshot_date >= :s AND snapshot_date < :e"
            ),
            {"s": month_start, "e": end_excl},
        ).scalar()
        expected_total = conn.execute(
            text(
                "SELECT SUM(market_value) FROM portfolio_value_history "
                "WHERE snapshot_date = :d AND currency = 'IDR'"
            ),
            {"d": expected_day},
        ).scalar()
        assert row["as_of_date"] == expected_day, row
        assert row["investment_total"] == expected_total, row


def test_month_without_a_snapshot_gaps_instead_of_inheriting(db_session):
    """D-03. Seeding one PortfolioValueHistory row dated 2026-05-15 moves
    snapshot_floor back into 2026-05 (rollback-scoped). The FOLLOWING month
    (2026-06), which has no snapshot of its own inside its own boundaries,
    must gap with no_snapshot_for_month rather than inheriting May's seeded
    value -- the anti-inherit rule DD-4/D-03 requires."""
    from backend import investment_reconstruction as recon
    from backend.models import PortfolioValueHistory

    ticker = f"{_TEST_PREFIX}-nosnap"
    try:
        db_session.add(
            PortfolioValueHistory(
                snapshot_date=date(2026, 5, 15),
                ticker=ticker,
                quantity=Decimal("1"),
                market_value=Decimal("1000.00"),
                cost_basis=Decimal("1000.00"),
                currency="IDR",
                platform_id=67,
            )
        )
        db_session.flush()

        result = recon.monthly_investment_series(months=12, db=db_session)
        by_month = {r["month"]: r for r in result["rows"]}

        assert by_month["2026-05"]["valuation_basis"] == "snapshot", by_month["2026-05"]
        june = by_month["2026-06"]
        assert june["honest"] is False, june
        assert june["gap_reason"] == "no_snapshot_for_month", june
        assert june["investment_total"] is None, june
    finally:
        db_session.rollback()


def test_position_without_a_holdings_row_is_treated_as_closed(db_session):
    """D-01/D-02 (Phase 22). Flips the pre-fix expectations of what used to
    be `test_snapshot_missing_position_gaps_the_bucket`.

    (a) CASH@67 is still held per the raw replay (unchanged -- proves the
        replay itself was never touched), but it now drops out of the
        narrowed held-set once intersected with live holdings presence --
        it was closed outside the event ledger, not gapped.
    (b) The present-but-zero snapshot row for CASH@67 is unchanged: still
        present at 0.00 on 2026-09-03, still excluded from coverage by the
        zero-value rule D-01 did not touch.

    Then the live current-month bucket must no longer gap for
    `snapshot_missing_position`."""
    from backend import investment_reconstruction as recon

    conn = db_session.connection()
    current_month = date.today().strftime("%Y-%m")
    month_start = date.fromisoformat(f"{current_month}-01")
    end_excl = _end_excl_for_month(current_month)

    snapshot_day = conn.execute(
        text(recon._SNAPSHOT_DAY_SQL), {"start": month_start, "end_excl": end_excl}
    ).scalar()
    assert snapshot_day is not None, "no snapshot in the current month -- test assumption stale"

    events = conn.execute(text(recon._EVENTS_SQL)).fetchall()
    synthetic_ids = recon._synthetic_event_ids(conn)
    held = recon._replay_positions(events, snapshot_day, synthetic_ids, db_session)
    raw_held_keys = set(held.keys())

    holdings_presence_keys = {
        recon._position_key(row[0], row[1])
        for row in conn.execute(text(recon._HOLDINGS_PRESENCE_SQL)).fetchall()
    }
    narrowed_held_keys = raw_held_keys & holdings_presence_keys

    # (a) raw replay is untouched -- CASH@67 still reads as held there.
    assert "CASH@67" in raw_held_keys, raw_held_keys
    # The honesty layer's narrowed set excludes it (D-01/D-02).
    assert "CASH@67" not in narrowed_held_keys, narrowed_held_keys

    # (b) present-but-zero rule is unchanged.
    zero_positions = recon._snapshot_positions(conn, date(2026, 9, 3))
    assert zero_positions["CASH@67"] == Decimal("0.00"), zero_positions
    assert "CASH@67" not in recon._covered_keys(zero_positions), zero_positions

    result = recon.monthly_investment_series(months=1, db=db_session)
    row = result["rows"][-1]
    assert row["month"] == current_month, row
    assert row["gap_reason"] != "snapshot_missing_position", row
    if row["honest"]:
        assert row["investment_total"] is not None, row
        assert row["investment_by_position"] is not None, row
        assert row["valuation_basis"] == "snapshot", row
    else:
        pytest.fail(
            f"current-month bucket gapped for {row['gap_reason']!r} instead of "
            "being honest -- per 22-VALIDATION.md this signals live-data drift, "
            "re-diagnose rather than accept this as a passing test"
        )


def test_null_platform_snapshot_row_keys_apart_and_fails_closed(db_session):
    """WR-01. portfolio_value_history.platform_id is nullable (legacy
    pre-multi-platform rows), portfolio_events.platform_id is NOT NULL. A
    NULL-platform snapshot row therefore keys as `ETH@None` and cannot cover
    the held `ETH@64`. Pins that this asymmetry is accepted and fail-closed:
    it gaps, it never guesses a platform."""
    from backend import investment_reconstruction as recon
    from backend.models import PortfolioValueHistory

    snapshot_day = date(2026, 9, 3)
    ticker = f"{_TEST_PREFIX}-legacy"
    try:
        db_session.add(
            PortfolioValueHistory(
                snapshot_date=snapshot_day,
                ticker=ticker,
                quantity=Decimal("10"),
                market_value=Decimal("999999.00"),
                cost_basis=Decimal("999999.00"),
                currency="IDR",
                platform_id=None,
            )
        )
        db_session.flush()

        positions = recon._snapshot_positions(db_session.connection(), snapshot_day)
        assert f"{ticker}@None" in positions, positions
        covered = recon._covered_keys(positions)
        # A positive-value legacy row is "covered" only under its own
        # None-platform key -- it never covers the event-side key, so DD-5
        # gaps rather than mis-attributing it to a guessed platform.
        assert f"{ticker}@None" in covered, covered
        assert f"{ticker}@64" not in covered, covered
        assert recon._position_key(ticker, None) != recon._position_key(ticker, 64)
    finally:
        db_session.rollback()


def test_series_envelope_mirrors_the_liquid_sibling(db_session):
    """D-05. Envelope keys, row-shape, null-both-fields-when-not-honest, and
    the Phase 22 zip contract -- identical ordered month vocabulary between
    the two series."""
    from backend import investment_reconstruction as recon
    from backend import reconstruction

    result = recon.monthly_investment_series(months=12, db=db_session)
    assert list(result.keys()) == ["tool", "rows", "honest_months", "gap_summary"]

    expected_row_keys = [
        "month",
        "investment_by_position",
        "investment_total",
        "valuation_basis",
        "as_of_date",
        "honest",
        "gap_reason",
    ]
    for row in result["rows"]:
        assert list(row.keys()) == expected_row_keys, row
        if row["honest"]:
            assert row["investment_by_position"] is not None, row
            assert row["investment_total"] is not None, row
            assert row["gap_reason"] is None, row
        else:
            assert row["investment_by_position"] is None, row
            assert row["investment_total"] is None, row
            assert row["gap_reason"] in recon.INVESTMENT_GAP_REASONS, row

    conn = db_session.connection()
    liquid = reconstruction.monthly_liquid_series(months=12, conn=conn)
    assert [r["month"] for r in result["rows"]] == [r["month"] for r in liquid["rows"]]


def test_pre_floor_months_carry_the_investements_deposits_balance(db_session):
    """RECON-05 relaxation (23.1 D-01, D-05 -- user decision 2026-09-24).
    Every ledger-era month before the real snapshot floor no longer gaps: it
    carries the dropped "Investements" Wallet account's running deposits
    balance from `net_worth_corrections`, labelled `valuation_basis =
    "deposits"` (at cost, never a market value -- Phase 23's dashed-line
    caption depends on that label). Months before the Wallet ledger itself
    existed still gap with `no_investment_tracking_before_launch`, because no
    data exists for them at all.

    Every oracle value here is derived independently from the module's own
    SQL (false-pass guard convention) -- never one of the module's private
    SQL-string constants.
    """
    from backend import investment_reconstruction as recon

    conn = db_session.connection()
    snapshot_floor = conn.execute(
        text("SELECT MIN(snapshot_date) FROM portfolio_value_history")
    ).scalar()
    assert snapshot_floor is not None

    ledger_floor = conn.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    assert ledger_floor is not None

    today = date.today()
    months = (today.year - ledger_floor.year) * 12 + (today.month - ledger_floor.month) + 2

    result = recon.monthly_investment_series(months=months, db=db_session)

    pre_ledger_rows = []
    deposits_rows = []

    for row in result["rows"]:
        month_end = _end_excl_for_month(row["month"]) - timedelta(days=1)
        if month_end >= snapshot_floor:
            assert row["valuation_basis"] != "deposits", row
            continue

        if month_end < ledger_floor:
            pre_ledger_rows.append(row)
            assert row["honest"] is False, row
            assert row["gap_reason"] == "no_investment_tracking_before_launch", row
            assert row["investment_total"] is None, row
            assert row["valuation_basis"] is None, row
        else:
            deposits_rows.append(row)
            end_excl = _end_excl_for_month(row["month"])
            expected_total = conn.execute(
                text(
                    "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
                    "WHERE source = :source AND orig_account = :label AND date < :end_excl"
                ),
                {"source": "corrections_260620", "label": "Investements", "end_excl": end_excl},
            ).scalar()
            assert row["honest"] is True, row
            assert row["gap_reason"] is None, row
            assert row["valuation_basis"] == "deposits", row
            assert row["investment_total"] == expected_total, row
            assert row["investment_by_position"] == {"Investements": expected_total}, row
            assert row["as_of_date"] == month_end, row

    assert len(pre_ledger_rows) > 0, "expected at least one pre-ledger gap row"
    # The approved D-05 preview keeps 2021-03..2023-05 at an honest zero:
    # Investements HAS history on this DB, it just starts in 2023-06 (WR-02
    # only gates a zero when the label has no history at all).
    assert any(r["investment_total"] == Decimal("0") for r in deposits_rows), deposits_rows
    assert any(r["investment_total"] > 0 for r in deposits_rows), deposits_rows


def _pre_floor_months(db_session) -> tuple[int, date]:
    conn = db_session.connection()
    snapshot_floor = conn.execute(text("SELECT MIN(snapshot_date) FROM portfolio_value_history")).scalar()
    ledger_floor = conn.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    assert snapshot_floor is not None and ledger_floor is not None
    today = date.today()
    return (today.year - ledger_floor.year) * 12 + (today.month - ledger_floor.month) + 2, snapshot_floor


def test_no_investements_history_never_publishes_a_confident_zero(db_session, monkeypatch):
    """WR-02 / RECON-05. With no recovered rows for the dropped account's
    label at all (fresh install), a pre-floor month has nothing to vouch
    for a zero -- it must gap via the replay path, never publish an honest
    `deposits` 0.00. Simulated by pointing the label at a name with no rows
    (no live writes)."""
    from backend import investment_reconstruction as recon

    monkeypatch.setattr(recon, "_DEPOSITS_LABEL", f"{_TEST_PREFIX}-nolabel")
    months, snapshot_floor = _pre_floor_months(db_session)
    result = recon.monthly_investment_series(months=months, db=db_session)
    pre_floor = [
        r for r in result["rows"]
        if _end_excl_for_month(r["month"]) - timedelta(days=1) < snapshot_floor
    ]
    assert pre_floor
    for row in pre_floor:
        assert row["valuation_basis"] != "deposits", row
        assert not (row["honest"] and row["investment_total"] == Decimal("0")), row


def test_pre_floor_portfolio_event_keeps_the_replay_regime(db_session):
    """WR-02. A real pre-floor portfolio_event (a back-dated funded buy)
    must not be thrown away in favour of the deposits figure: every month
    from the event up to the snapshot floor goes through replay honesty.
    Rollback-scoped seed (db.flush only, never a session-persist call)."""
    from backend import investment_reconstruction as recon

    ticker = f"{_TEST_PREFIX}-prefloor"
    try:
        _make_event(
            db_session, ticker=ticker, platform_id=67, on_date=date(2025, 1, 15),
            event_type="buy", quantity=Decimal("10"), price=Decimal("1000.00"), currency="IDR",
        )
        months, snapshot_floor = _pre_floor_months(db_session)
        result = recon.monthly_investment_series(months=months, db=db_session)
        by_month = {r["month"]: r for r in result["rows"]}

        assert by_month["2024-12"]["valuation_basis"] == "deposits", by_month["2024-12"]
        row = by_month["2025-06"]
        assert row["valuation_basis"] != "deposits", row
        if row["honest"]:
            assert f"{ticker}@67" in row["investment_by_position"], row
        else:
            assert row["gap_reason"] in recon.INVESTMENT_GAP_REASONS, row
    finally:
        db_session.rollback()


# ---------------------------------------------------------------------------
# Plan 21-02 Task 2 -- RECON-06 proofs: static scan, scoped disclosure,
# idempotency, blast radius
# ---------------------------------------------------------------------------

def test_investment_reconstruction_module_has_no_write_imports():
    """RECON-06 / D-04. Static scan of the module's own source, the
    `_offending()` idiom copied from
    backend/tests_live_audit/test_reconstruction.py::test_reconstruction_module_has_no_write_imports.
    No line imports from the write module, the portfolio module or the
    liquid-sibling reconstruction module; no line matches a SQL write
    statement; no line contains a session-commit call; no line imports the
    prices module. Each failure prints the offending line numbers/lines."""
    import re
    from pathlib import Path

    from backend import investment_reconstruction as recon

    source_lines = Path(recon.__file__).read_text(encoding="utf-8").splitlines()

    def _offending(pattern, flags=0):
        rx = re.compile(pattern, flags)
        return [(i + 1, ln) for i, ln in enumerate(source_lines) if rx.search(ln)]

    write_imports = _offending(
        r"^[ \t]*(from|import)[ \t]+backend\.(writes|portfolio|reconstruction)\b"
    )
    assert not write_imports, f"write/portfolio/liquid-sibling import(s): {write_imports}"

    write_stmts = _offending(
        r"(INSERT[ \t]+INTO|UPDATE[ \t]+[a-z_]+[ \t]+SET|DELETE[ \t]+FROM)", re.IGNORECASE
    )
    assert not write_stmts, f"write statement(s): {write_stmts}"

    commit_calls = _offending(r"\.commit\(\)")
    assert not commit_calls, f"session-commit call(s): {commit_calls}"

    prices_imports = _offending(r"^[ \t]*(from|import)[ \t]+backend\.prices\b")
    assert not prices_imports, f"prices-module import(s): {prices_imports}"


def test_read_only_scope_is_disclosed_in_the_docstring():
    """The static scan above would pass a module that quietly triggers a
    write inside ANOTHER module (fx.get_rate's fx_rate_cache append) -- it
    does not entitle a blanket read-only claim. The module docstring must
    name all three protected tables and disclose the fx_rate_cache
    transitive exception rather than let the scan imply a guarantee it does
    not actually make."""
    from backend import investment_reconstruction as recon

    doc = recon.__doc__ or ""
    for table in ("holdings", "portfolio_events", "portfolio_value_history", "fx_rate_cache"):
        assert table in doc, f"{table!r} not disclosed in module docstring"


def test_double_call_is_identical(db_session):
    """RECON-06 idempotency: two calls on one session return fully equal
    output, including row order and Decimal values -- cheap and catches
    accidental non-determinism such as unordered dict/set iteration leaking
    into the output."""
    from backend import investment_reconstruction as recon

    first = recon.monthly_investment_series(months=12, db=db_session)
    second = recon.monthly_investment_series(months=12, db=db_session)
    assert first == second


def test_blast_radius_zero(db_session):
    """RECON-06 / D-04. Count rows in all four candidate tables before and
    after a full monthly_investment_series(months=72) call; all four deltas
    must be exactly zero. The fx_rate_cache assertion is the runtime half of
    the scoped read-only claim (DD-2): it proves the disclosed transitive
    write is never reached with today's all-IDR data."""
    from backend import investment_reconstruction as recon

    tables = ("holdings", "portfolio_events", "portfolio_value_history", "fx_rate_cache")
    conn = db_session.connection()

    def _counts():
        return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}

    before = _counts()
    recon.monthly_investment_series(months=72, db=db_session)
    after = _counts()

    for table in tables:
        delta = after[table] - before[table]
        assert delta == 0, f"{table} changed by {delta} (before={before[table]}, after={after[table]})"
