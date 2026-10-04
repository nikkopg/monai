"""
Tests for alembic/versions/014_recon_backfill.py — Phase 20 Liquid-Side
Reconstruction (RECON-01, RECON-02, D-02, D-05.2, D-12, D-13).

This is the single test file for the whole phase; later plans (20-02, 20-03)
append to it.

LIVE AUDIT — this file lives in backend/tests_live_audit/, outside
`testpaths` (pyproject.toml) and outside backend/tests/conftest.py's guard,
so a default `pytest` run never collects it and it never inherits the
guarded conftest's monai_test default or its refusal. It is re-run
deliberately against live `monai`:
`DATABASE_URL=postgresql+psycopg://monai:monai@localhost:5434/monai .venv/bin/pytest backend/tests_live_audit/test_reconstruction.py -x -q -p no:cacheprovider`

The rule,
stated in words so it is unambiguous and so the phase-wide acceptance grep for
a session-persist call over this file stays clean: no test in this file may
persist its session on any receiver — not the Session, not a Connection. Every
mutation is undone before the test returns, and the blast-radius test asserts
the live row count is unchanged afterwards.

The migration module lives under alembic/versions/ (not an importable package)
so it is loaded via importlib, exactly as test_category_migration.py /
test_transfer_retro_pairing.py do.
"""

import csv
import importlib.util
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "014_recon_backfill.py"
)
REPO_ROOT = MIGRATION_PATH.parents[2]
FIXTURE_PATH = REPO_ROOT / "alembic" / "data" / "corrections_260620.csv"
_SOURCE = "corrections_260620"

# The fixture is the user's own recovered transactions: personal data,
# gitignored, present only on the machine that derived it.
requires_fixture = pytest.mark.skipif(
    not FIXTURE_PATH.exists(), reason="local-only corrections fixture absent"
)


def _ensure_real_alembic_package() -> None:
    """Bypass this repo's own alembic/ scaffold (see test_category_migration.py
    for the full rationale) so `from alembic import op` resolves to the real
    pip-installed package rather than the local versions/ directory."""
    cached = sys.modules.get("alembic")
    if cached is not None and hasattr(cached, "op"):
        return
    if cached is not None:
        del sys.modules["alembic"]
    shadow_init = (REPO_ROOT / "alembic" / "__init__.py").resolve()
    original_path = list(sys.path)
    try:
        sys.path = [
            p for p in sys.path
            if (Path(p or ".") / "alembic" / "__init__.py").resolve() != shadow_init
        ]
        import alembic  # noqa: F401
    finally:
        sys.path = original_path
    if not hasattr(sys.modules.get("alembic"), "op"):
        raise ImportError(
            "could not resolve the installed alembic package (only found this "
            f"repo's own scaffold at {shadow_init})"
        )


@pytest.fixture(scope="module")
def migration():
    """Load 014_recon_backfill.py standalone via importlib.

    Fails with FileNotFoundError/ImportError until the migration file exists —
    that is the intended RED-phase failure (module missing, not a bug here).
    """
    _ensure_real_alembic_package()
    spec = importlib.util.spec_from_file_location("migration_014", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration spec from {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# DB fixtures — skip if Postgres not available (matches test_write_tools.py)
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
# Independent transfer-pair matcher (false-pass guard, D-05.2)
#
# Deliberately NOT migration.transfer_pair_closure — the test recomputes pair
# sums from the fixture's raw amount strings via its own csv.DictReader so a
# shared sign-normalisation bug cannot cancel itself out on both sides.
# ---------------------------------------------------------------------------

def _independent_transfer_legs():
    with open(FIXTURE_PATH, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["is_transfer"] == "true"]


def _independent_pairing(legs):
    """Greedy match each leg to a counter-leg on (date, -amount) with a
    different orig_account, consuming each counter-leg once. Returns
    (pairs, unmatched)."""
    remaining = list(legs)
    pairs = []
    unmatched = []
    while remaining:
        leg = remaining.pop(0)
        want = -Decimal(leg["amount"])
        match_idx = None
        for i, cand in enumerate(remaining):
            if (
                cand["date"] == leg["date"]
                and Decimal(cand["amount"]) == want
                and cand["orig_account"] != leg["orig_account"]
            ):
                match_idx = i
                break
        if match_idx is None:
            unmatched.append(leg)
        else:
            pairs.append((leg, remaining.pop(match_idx)))
    return pairs, unmatched


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@requires_fixture
def test_migration_row_count_is_exactly_177(migration, db_session):
    """RECON-01, D-02 — the fixture and the live table both hold exactly 177
    rows with identical per-account counts and sums, and assert_expected_shape
    aborts on any other shape. Expected values are read from the local
    fixture at runtime, never hardcoded (they are personal data)."""
    rows = migration.load_corrections(migration._CSV_PATH)
    assert len(rows) == 177, len(rows)
    expected_sums: dict[str, Decimal] = {}
    for r in rows:
        expected_sums[r["orig_account"]] = expected_sums.get(r["orig_account"], Decimal("0.00")) + r["amount"]

    # The abort is real, not decorative: a truncated row set must raise.
    with pytest.raises(RuntimeError):
        migration.assert_expected_shape(rows[:-1])

    # Live table — read-only, insert nothing.
    live_total = db_session.execute(
        text("SELECT count(*) FROM net_worth_corrections WHERE source = :s"),
        {"s": _SOURCE},
    ).scalar()
    assert live_total == 177, live_total

    live_sums = dict(
        db_session.execute(
            text(
                "SELECT orig_account, sum(amount) FROM net_worth_corrections "
                "WHERE source = :s GROUP BY orig_account"
            ),
            {"s": _SOURCE},
        ).all()
    )
    assert live_sums == expected_sums, (live_sums, expected_sums)
    assert "Investements" in live_sums, live_sums


@requires_fixture
def test_transfer_pair_closure_all_55(migration):
    """RECON-02 / D-05.2 — 110 transfer legs resolve into 55 disjoint pairs,
    each summing to exactly zero, verified independently of the module."""
    rows = migration.load_corrections(migration._CSV_PATH)
    assert migration.transfer_pair_closure(rows) == []

    # Independent verification from the raw fixture strings.
    legs = _independent_transfer_legs()
    assert len(legs) == 110, len(legs)
    pairs, unmatched = _independent_pairing(legs)
    assert unmatched == [], unmatched
    assert len(pairs) == 55, len(pairs)
    for a, b in pairs:
        assert Decimal(a["amount"]) + Decimal(b["amount"]) == Decimal("0.00"), (a, b)


@requires_fixture
def test_migration_blast_radius(migration, db_session):
    """RECON-01 — exercising the real insert path changes ONLY
    net_worth_corrections (+177) and audit_log (+1); transactions/accounts and
    every other table are untouched, and the session is always rolled back."""
    conn = db_session.connection()
    try:
        conn.execute(
            text("DELETE FROM net_worth_corrections WHERE source = :s"),
            {"s": _SOURCE},
        )
        before = migration._table_counts(conn)
        migration.backfill_corrections(conn)
        after = migration._table_counts(conn)

        assert after["net_worth_corrections"] - before["net_worth_corrections"] == 177
        assert after["audit_log"] - before["audit_log"] == 1
        for table in sorted(set(before) | set(after)):
            if table in ("net_worth_corrections", "audit_log"):
                continue
            delta = after.get(table, 0) - before.get(table, 0)
            assert delta == 0, f"{table} changed by {delta}"
        # explicit — the two tables RECON-01 forbids touching
        assert after["transactions"] - before["transactions"] == 0
        assert after["accounts"] - before["accounts"] == 0
    finally:
        db_session.rollback()

    # Prove the test left nothing behind: a fresh connection sees the original 177.
    from backend.db import engine
    with engine.connect() as c:
        residual = c.execute(
            text("SELECT count(*) FROM net_worth_corrections WHERE source = :s"),
            {"s": _SOURCE},
        ).scalar()
    assert residual == 177, residual


def test_no_live_importer_or_write_calls(migration):
    """D-12, T-20-02 — static prohibitions: 014 imports nothing from the app
    package, constructs no ORM row, and issues no write against the live ledger
    or account tables."""
    import re

    source_lines = Path(migration.__file__).read_text(encoding="utf-8").splitlines()

    def _offending(pattern, flags=0):
        rx = re.compile(pattern, flags)
        return [(i + 1, ln) for i, ln in enumerate(source_lines) if rx.search(ln)]

    app_imports = _offending(r"^[ \t]*(from|import)[ \t]+backend")
    assert not app_imports, f"application import(s): {app_imports}"

    orm_ctor = _offending(r"\bTransaction[ \t]*\(")
    assert not orm_ctor, f"ORM row constructor(s): {orm_ctor}"

    live_writes = _offending(
        r"(INSERT[ \t]+INTO|UPDATE|DELETE[ \t]+FROM)[ \t]+(transactions|accounts)\b",
        re.IGNORECASE,
    )
    assert not live_writes, f"live-ledger write(s): {live_writes}"


@requires_fixture
def test_audit_payload_is_json_serializable(migration):
    """D-13, T-20-05 — the audit payload json.dumps cleanly and every money
    value in it is a str, never a raw Decimal."""
    rows = migration.load_corrections(migration._CSV_PATH)
    payload = migration.build_audit_payload(rows)

    json.dumps(payload)  # raises TypeError if a Decimal slipped in

    for account, info in payload["by_account"].items():
        assert isinstance(info["sum"], str), (account, type(info["sum"]))
        assert not isinstance(info["sum"], Decimal), account


# ---------------------------------------------------------------------------
# backend/reconstruction.py — plan 20-02 (RECON-02, RECON-03)
# ---------------------------------------------------------------------------

def test_additive_restoration_invariant(db_session):
    """RECON-02 / D-05.1, asserted in its D-03-gated form. For every bucket
    and every live liquid account:
    reconstructed[name] == live_ledger_sum(name, end_excl) + recovered(name, end_excl)
    where recovered is Decimal("0.00") on/after that account's first
    Adjustment date and otherwise the sum of that label's correction rows
    dated before end_excl. D-05.1 read literally ("for every bucket") and
    D-05.3 (anchor parity) are mutually exclusive at the 2026-09 bucket;
    D-05.3 wins, so the recovered component is gated to zero from each
    account's anchor onward — this test asserts exactly that gated form, not
    the ungated formula (see backend/reconstruction.py's module docstring
    for the full reconciliation).

    False-pass guard: the expected live-ledger sum is computed here with its
    own raw text() statement matching apply_add_balance_adjustment's
    unfiltered form, never via any helper or constant imported from
    backend.reconstruction — a shared filtered-SUM bug would otherwise pass
    on both sides.

    Also includes the repartition guard: for every label in a bucket's
    by_account map (including "Investements", which has no live account),
    the delta from that label's own live ledger sum is EITHER exactly
    Decimal("0.00") OR exactly that same label's own correction sum, never a
    third value and never a different label's sum — proving restoration
    only adds, never repartitions. Guarded against vacuity: the non-zero
    branch must be taken at least once across the 48 buckets.
    """
    from backend.reconstruction import _SOURCE, reconstructed_liquid_by_month

    accounts = dict(
        db_session.execute(
            text("SELECT name, id FROM accounts WHERE type = 'liquid'")
        ).all()
    )
    anchor_dates = dict(
        db_session.execute(
            text(
                "SELECT a.name, MIN(t.date)::date FROM transactions t "
                "JOIN accounts a ON a.id = t.account_id "
                "WHERE a.type = 'liquid' AND t.category = 'Adjustment' "
                "GROUP BY a.name"
            )
        ).all()
    )

    def _live_ledger_sum(account_id, end_excl):
        return Decimal(
            str(
                db_session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
                        "WHERE account_id = :id AND date < :end_excl"
                    ),
                    {"id": account_id, "end_excl": end_excl},
                ).scalar()
            )
        )

    def _correction_sum(label, end_excl):
        return Decimal(
            str(
                db_session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
                        "WHERE source = :source AND orig_account = :label AND date < :end_excl"
                    ),
                    {"source": _SOURCE, "label": label, "end_excl": end_excl},
                ).scalar()
            )
        )

    buckets = reconstructed_liquid_by_month(months=48)
    assert len(buckets) == 48, len(buckets)

    non_zero_branch_taken = False
    for bucket in buckets:
        end_excl = bucket["end_excl"]
        month_end = end_excl - timedelta(days=1)
        reconstructed = bucket["by_account"]

        for name, account_id in accounts.items():
            live_sum = _live_ledger_sum(account_id, end_excl)
            account_anchor = anchor_dates.get(name)
            gate_open = account_anchor is None or month_end < account_anchor
            recovered = _correction_sum(name, end_excl) if gate_open else Decimal("0.00")
            expected = live_sum + recovered
            assert reconstructed[name] == expected, (
                bucket["month"], name, reconstructed[name], expected
            )

        for label, value in reconstructed.items():
            live_sum = _live_ledger_sum(accounts[label], end_excl) if label in accounts else Decimal("0.00")
            delta = value - live_sum
            own_correction = _correction_sum(label, end_excl)
            assert delta in (Decimal("0.00"), own_correction), (
                f"bucket={bucket['month']} label={label} delta={delta} "
                f"permitted=(0.00, {own_correction})"
            )
            if delta != Decimal("0.00"):
                non_zero_branch_taken = True

    assert non_zero_branch_taken, "repartition guard is vacuous — no bucket took the non-zero branch"


def test_anchor_parity_2026_09_03(db_session):
    """RECON-02 / D-05.3, load-bearing. reconstructed_total_liquid(2026-09-03)
    equals the live post-adjustment liquid total exactly — the one point in
    history where ledger and truth are known to coincide.

    False-pass guard (bucket assertion): the live side comes from the
    already-tested, production net_worth(), never a hand-rolled duplicate
    query, so a bug that drops a liquid account from the reconstruction
    surfaces as a disagreement with known-good production code. The bucket
    compared is the LATEST (current-month) one, `[-1]`, whose end_excl is
    always after every recorded transaction — so this check holds on any
    calendar date and survives a back-dated as_of anchor recompute (revised
    decision 1, 2026-09-24), which by construction preserves the all-time sum
    (user decision 3).

    False-pass guard (cutoff-exact assertion): this assertion pins D-05.3 at
    the fixed 2026-09-04 cutoff, independent of the bucket check above and of
    the calendar. It holds as long as every liquid account's FIRST anchor is
    on or before 2026-09-03 — true today, and still true after a D-DEF-04
    anchor, since `_anchor_dates` returns each account's FIRST Adjustment
    date and a new anchor can only move that earlier, never later (user
    decision 3). The reconstructed side here is instead driven through the
    engine's own _LIVE_BY_ACCOUNT_SQL and the real D-03 gate (recovered
    component asserted exactly zero at this cutoff), while the expected side
    is independently re-derived the same way
    test_additive_restoration_invariant does — a per-account `account_id =
    :id` SUM, never reading any constant or helper from
    backend.reconstruction. Routing one side through the engine and the
    other through an independent query is what makes a transfer filter, a
    wrong bound, a dropped/misclassified liquid account, or an ungated
    recovered component surface here; hand-rolling both sides from the same
    formula would degenerate into x == x.
    """
    from backend.reconstruction import (
        _LIVE_BY_ACCOUNT_SQL,
        _RECOVERED_BY_LABEL_SQL,
        _SOURCE,
        _anchor_dates,
        _liquid_anchor,
        reconstructed_liquid_by_month,
    )
    from backend.tools import net_worth

    bucket = reconstructed_liquid_by_month(months=12)[-1]
    reconstructed_total = bucket["total"]

    live_total = net_worth()["liquid_total"]

    q_reconstructed = Decimal(str(reconstructed_total)).quantize(Decimal("1.00"))
    q_live = Decimal(str(live_total)).quantize(Decimal("1.00"))
    assert q_reconstructed == q_live, (
        f"anchor parity mismatch: reconstructed={q_reconstructed} live={q_live} "
        f"diff={q_reconstructed - q_live}"
    )

    # Cutoff-exact assertion, pinned to the anchor date itself rather than
    # the bucket's all-time end_excl.
    anchor_excl = date(2026, 9, 4)
    conn = db_session.connection()

    anchors = _anchor_dates(conn)
    for name, anchor in anchors.items():
        # Floor, not exact equality (user decision 3): revised decision 1
        # lets a D-DEF-04 anchor move an account's FIRST anchor earlier than
        # 2026-09-03, which the gate/cutoff logic below tolerates fine.
        assert anchor is not None and anchor <= date(2026, 9, 3), (name, anchor)
    liquid_anchor = _liquid_anchor(anchors)
    assert liquid_anchor is not None and liquid_anchor <= date(2026, 9, 3), liquid_anchor

    month_end = anchor_excl - timedelta(days=1)
    live_by_account = dict(
        conn.execute(text(_LIVE_BY_ACCOUNT_SQL), {"end_excl": anchor_excl}).all()
    )
    recovered_by_label = dict(
        conn.execute(
            text(_RECOVERED_BY_LABEL_SQL), {"source": _SOURCE, "end_excl": anchor_excl}
        ).all()
    )

    reconstructed_cutoff_total = Decimal("0.00")
    for label, live_value in live_by_account.items():
        account_anchor = anchors.get(label)
        gate_open = account_anchor is None or month_end < account_anchor
        recovered_value = recovered_by_label.get(label, Decimal("0.00")) if gate_open else Decimal("0.00")
        assert recovered_value == Decimal("0.00"), (label, recovered_value)
        reconstructed_cutoff_total += Decimal(str(live_value))
    for label, correction_value in recovered_by_label.items():
        if label in live_by_account:
            continue
        gate_open = liquid_anchor is None or month_end < liquid_anchor
        recovered_value = correction_value if gate_open else Decimal("0.00")
        assert recovered_value == Decimal("0.00"), (label, recovered_value)

    accounts = dict(
        db_session.execute(
            text("SELECT name, id FROM accounts WHERE type = 'liquid'")
        ).all()
    )
    expected_cutoff_total = Decimal("0.00")
    for name, account_id in accounts.items():
        expected_cutoff_total += Decimal(
            str(
                db_session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
                        "WHERE account_id = :id AND date < :anchor_excl"
                    ),
                    {"id": account_id, "anchor_excl": anchor_excl},
                ).scalar()
            )
        )

    q_recon_cutoff = reconstructed_cutoff_total.quantize(Decimal("1.00"))
    q_expected_cutoff = expected_cutoff_total.quantize(Decimal("1.00"))
    assert q_recon_cutoff == q_expected_cutoff, (
        f"anchor-cutoff parity mismatch: reconstructed={q_recon_cutoff} "
        f"expected={q_expected_cutoff} diff={q_recon_cutoff - q_expected_cutoff}"
    )


def test_honesty_model_matches_current_adjustment_history(db_session):
    """RECON-03 / D-07 (user decisions 2 and 3, 2026-09-24), relaxed by
    23.1 D-03/D-05 on the user's decision of 2026-09-24: every month from
    the ledger start up to (not including) the liquid anchor is now honest
    on the "ledger_plus_corrections" basis, superseding Phase 20's
    `no_opening_anchor` gate for that stretch. Independently derives the
    expected adjustment/window set from the live category='Adjustment'
    rows, then applies the relaxed rule against those independently-derived
    windows — never a literal honest-month list, an exact adjustment count,
    or a pinned first-anchor date, all of which break the moment a new
    Adjustment (a D-DEF-04 back-dated anchor included) or a new calendar
    month lands. The honest-month list is expected to roll forward with the
    calendar (decision 2); it is compared against a value re-derived from
    live data every run, never hardcoded.

    False-pass guard: the window boundaries themselves — not just a
    hardcoded month count — are asserted against the independently-queried
    adjustment dates, so an off-by-one window boundary cannot "pass" merely
    because the final honest-month count happens to match. No Adjustment
    AMOUNT is asserted anywhere in this test: revised decision 1 rewrites
    Adjustment amounts on a back-dated anchor, so an amount assertion here
    would be a second, unrelated brittleness.
    """
    from backend.reconstruction import _adjustment_windows, monthly_liquid_series

    live_adjustments = db_session.execute(
        text(
            "SELECT a.name, t.date::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id "
            "WHERE a.type = 'liquid' AND t.category = 'Adjustment' "
            "ORDER BY a.name, t.date"
        )
    ).all()

    # Floor, not exact count (decision 3): at least one liquid Adjustment
    # exists, or every window below is vacuously empty. No account name, date
    # or amount is pinned here — those are the user's personal data.
    assert live_adjustments, "no liquid Adjustment rows — window check would be vacuous"

    # Windows, exact and derived independently: account names come from
    # their own query, never backend.reconstruction's own SQL constant.
    liquid_names = [
        r[0] for r in db_session.execute(text("SELECT name FROM accounts WHERE type = 'liquid'")).all()
    ]
    dates_by_account: dict[str, list] = {name: [] for name in liquid_names}
    for name, d in live_adjustments:
        dates_by_account.setdefault(name, []).append(d)
    expected_windows: dict[str, list[tuple]] = {
        name: [(lo, dates[i + 1] if i + 1 < len(dates) else None) for i, lo in enumerate(dates)]
        for name, dates in dates_by_account.items()
    }

    conn = db_session.connection()
    actual_windows = _adjustment_windows(conn)
    assert actual_windows == expected_windows, (actual_windows, expected_windows)

    earliest_liquid_tx = db_session.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    current_month = date.today().strftime("%Y-%m")

    # Data-derived window: exactly one pre-ledger month included, never a
    # literal month count.
    today = date.today()
    months = (today.year - earliest_liquid_tx.year) * 12 + (today.month - earliest_liquid_tx.month) + 2

    # expected_liquid_anchor, independently derived (23.1 D-03, CR-01): MAX
    # over the FIRST adjustment date of every live liquid account that HAS
    # one, or None when no liquid account has ever been adjusted — an
    # unanchored account never extends the relaxed regime forever. Mirrors
    # backend.reconstruction._regime_cutoff without importing it.
    first_dates = [dates_by_account[name][0] for name in liquid_names if dates_by_account.get(name)]
    expected_liquid_anchor: date | None = max(first_dates) if first_dates else None

    def month_end(month_str: str) -> date:
        year, month = (int(p) for p in month_str.split("-"))
        next_month_first = date(year + (month // 12), (month % 12) + 1, 1)
        return next_month_first - timedelta(days=1)

    def expected_honest(month: str) -> tuple[bool, str | None]:
        m_end = month_end(month)
        if earliest_liquid_tx is None or m_end < earliest_liquid_tx:
            return False, None
        if expected_liquid_anchor is not None and m_end <= expected_liquid_anchor:
            return True, "ledger_plus_corrections"
        for account_windows in expected_windows.values():
            if not any(lo < m_end for lo, _hi in account_windows):
                return False, None
        for account_windows in expected_windows.values():
            contained = False
            for lo, hi in account_windows:
                if hi is None:
                    if lo < m_end:
                        contained = contained or (month == current_month)
                else:
                    if lo < m_end <= hi:
                        contained = True
            if not contained:
                return False, None
        return True, None

    result = monthly_liquid_series(months=months)
    expected = {row["month"]: expected_honest(row["month"]) for row in result["rows"]}
    expected_honest_months = [m for m, (h, _basis) in expected.items() if h]
    assert result["honest_months"] == expected_honest_months, (
        result["honest_months"],
        expected_honest_months,
    )
    for row in result["rows"]:
        _exp_honest, exp_basis = expected[row["month"]]
        assert row["valuation_basis"] == exp_basis, (row["month"], row["valuation_basis"], exp_basis)

    # Non-vacuity: at least one "ledger_plus_corrections" row, at least one
    # pre_ledger row, and (unchanged) the current month is honest when every
    # account has an adjustment.
    bases = [row["valuation_basis"] for row in result["rows"] if row["honest"]]
    assert "ledger_plus_corrections" in bases, bases
    gap_reasons = [row["gap_reason"] for row in result["rows"] if not row["honest"]]
    assert "pre_ledger" in gap_reasons, gap_reasons
    if all(dates_by_account[name] for name in liquid_names):
        assert current_month in result["honest_months"], result["honest_months"]


def test_gap_reason_never_fabricated(db_session):
    """RECON-03 / D-09. Every unreconciled month is a real, explicit null —
    never a guess, an interpolation, or a value carried forward from the
    prior month — and every gap_reason is one of the three documented enum
    strings."""
    from backend.reconstruction import GAP_REASONS, monthly_liquid_series

    rows = monthly_liquid_series(months=72)["rows"]
    assert list(rows[0]) == [
        "month",
        "liquid_by_account",
        "liquid_total",
        "valuation_basis",
        "honest",
        "gap_reason",
    ], list(rows[0])

    suspicious_keys = {"estimate", "band", "interpolated", "confidence", "error_margin"}
    prev_non_honest_total = None
    for row in rows:
        assert not (set(row) & suspicious_keys), row

        if row["honest"]:
            assert row["gap_reason"] is None, row
            assert row["liquid_total"] is not None, row
            assert row["liquid_by_account"] is not None, row
            assert row["valuation_basis"] in ("ledger_plus_corrections", None), row
            prev_non_honest_total = None
        else:
            assert row["liquid_total"] is None, row
            assert row["liquid_by_account"] is None, row
            assert row["gap_reason"] in GAP_REASONS, row
            assert row["valuation_basis"] is None, row
            # No carry-forward: two consecutive non-honest rows never share
            # an equal non-None total.
            if row["liquid_total"] is not None and prev_non_honest_total is not None:
                assert row["liquid_total"] != prev_non_honest_total, row
            prev_non_honest_total = row["liquid_total"]


def test_liquid_total_excludes_investements_label(db_session):
    """23.1 D-01/D-05, research Pitfall 1 guard. The raw engine's `total`
    double-books the "Investements" correction label into the liquid side
    (it has no live account, so it joins `by_account` via `recovered_by_label`
    alone). `monthly_liquid_series`'s pre-anchor "ledger_plus_corrections"
    regime must never inherit that raw total: its `liquid_by_account` map
    excludes "Investements" entirely, and its `liquid_total` is the sum of
    that restricted map, not `raw["total"]`.
    """
    from backend.reconstruction import monthly_liquid_series, reconstructed_liquid_by_month

    earliest_liquid_tx = db_session.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    today = date.today()
    months = (today.year - earliest_liquid_tx.year) * 12 + (today.month - earliest_liquid_tx.month) + 2

    conn = db_session.connection()
    raw_rows = reconstructed_liquid_by_month(months=months, conn=conn)
    series_rows = monthly_liquid_series(months=months, conn=conn)["rows"]
    assert len(raw_rows) == len(series_rows), (len(raw_rows), len(series_rows))

    non_zero_investements_seen = False
    for raw, row in zip(raw_rows, series_rows):
        assert raw["month"] == row["month"], (raw["month"], row["month"])
        if row["valuation_basis"] != "ledger_plus_corrections":
            continue
        assert "Investements" not in row["liquid_by_account"], row["liquid_by_account"]
        assert row["liquid_total"] == sum(row["liquid_by_account"].values()), row
        raw_investements = raw["by_account"].get("Investements", Decimal("0.00"))
        assert row["liquid_total"] == raw["total"] - raw_investements, (
            row["month"], row["liquid_total"], raw["total"], raw_investements
        )
        if raw_investements != Decimal("0.00"):
            non_zero_investements_seen = True

    assert non_zero_investements_seen, "guard is vacuous — no ledger_plus_corrections row had a non-zero raw Investements value"


def test_reconstruction_module_has_no_write_imports():
    """D-16 / T-20-03. Static check reading backend/reconstruction.py as
    text: no line imports from backend.writes; no line matches an INSERT,
    UPDATE-SET or DELETE statement; no line contains an is_transfer
    predicate. Each failure message prints the offending line number and
    line."""
    import re

    from backend import reconstruction

    source_lines = Path(reconstruction.__file__).read_text(encoding="utf-8").splitlines()

    def _offending(pattern, flags=0):
        rx = re.compile(pattern, flags)
        return [(i + 1, ln) for i, ln in enumerate(source_lines) if rx.search(ln)]

    write_imports = _offending(r"^[ \t]*(from|import)[ \t]+backend\.writes\b")
    assert not write_imports, f"write-module import(s): {write_imports}"

    write_stmts = _offending(
        r"(INSERT[ \t]+INTO|UPDATE[ \t]+[a-z_]+[ \t]+SET|DELETE[ \t]+FROM)", re.IGNORECASE
    )
    assert not write_stmts, f"write statement(s): {write_stmts}"

    transfer_predicates = _offending(r"is_transfer")
    assert not transfer_predicates, f"is_transfer predicate(s): {transfer_predicates}"


# ---------------------------------------------------------------------------
# as_of back-dated anchor (D-08, plan 20-03)
#
# Seed helpers below use flush(), never a session-persist call, so every row
# they create lives only inside the currently-open transaction. Every
# apply_* function in backend/writes.py leaves that transaction boundary to
# its caller (see that module's own docstring), which is exactly what makes
# a rollback-scoped test like this one safe under D-17: the test's own
# `finally` unwinds the whole transaction, so nothing it creates is ever
# persisted to the live database.
# ---------------------------------------------------------------------------

_ASOF_TEST_PREFIX = "zzReconTest-asof"


def _make_asof_account(db, suffix: str) -> int:
    from backend.models import Account
    acc = Account(name=f"{_ASOF_TEST_PREFIX}-{suffix}", type="liquid", currency="IDR")
    db.add(acc)
    db.flush()
    return acc.id


def _make_asof_transaction(db, account_id: int, on_date: date, amount: Decimal) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime(on_date.year, on_date.month, on_date.day, 12, 0, 0),
        amount=amount,
        currency="IDR",
        account_id=account_id,
        is_transfer=False,
    )
    db.add(tx)
    db.flush()
    return tx.id


def test_as_of_backdated_anchor(db_session):
    """D-08 / T-20-13. `as_of` reconciles against the point-in-time balance
    through the close of `as_of` (same-day inclusive), matches the no-`as_of`
    path exactly when omitted, and never reaches the live database.
    """
    from backend.models import AuditLog
    from backend.writes import apply_add_balance_adjustment

    seed_rows = [
        (date(2026, 1, 15), Decimal("1000.00")),
        (date(2026, 3, 10), Decimal("500.00")),
        (date(2026, 6, 20), Decimal("250.00")),
    ]

    try:
        # Same-day inclusivity: the 2026-03-10 row must count, the
        # 2026-06-20 row must not.
        acc_id = _make_asof_account(db_session, "1")
        for on_date, amount in seed_rows:
            _make_asof_transaction(db_session, acc_id, on_date, amount)

        tx = apply_add_balance_adjustment(
            db_session, acc_id, Decimal("2000.00"), as_of=date(2026, 3, 10)
        )
        db_session.flush()
        assert tx.amount == Decimal("500.00"), tx.amount  # 2000 - (1000 + 500)
        assert tx.date.date() == date(2026, 3, 10), tx.date
        assert tx.category == "Adjustment", tx.category
        assert tx.is_transfer is True, tx.is_transfer

        audit_rows = (
            db_session.query(AuditLog)
            .filter_by(entity="transaction", entity_id=tx.id)
            .all()
        )
        assert len(audit_rows) == 1, audit_rows
        assert isinstance(audit_rows[0].after["amount"], str), audit_rows[0].after

        # Equivalence with the existing (no as_of) path, on a second,
        # identically-seeded throwaway account.
        acc2_id = _make_asof_account(db_session, "2")
        for on_date, amount in seed_rows:
            _make_asof_transaction(db_session, acc2_id, on_date, amount)

        tx2 = apply_add_balance_adjustment(db_session, acc2_id, Decimal("2000.00"))
        db_session.flush()
        all_time_sum = sum((amount for _, amount in seed_rows), Decimal("0"))
        assert tx2.amount == Decimal("2000.00") - all_time_sum, tx2.amount
        assert tx2.date.date() == datetime.now(timezone.utc).date(), tx2.date
        assert tx2.date.date() not in {d for d, _ in seed_rows}, tx2.date

        audit_rows2 = (
            db_session.query(AuditLog)
            .filter_by(entity="transaction", entity_id=tx2.id)
            .all()
        )
        assert len(audit_rows2) == 1, audit_rows2
        assert isinstance(audit_rows2[0].after["amount"], str), audit_rows2[0].after

        with pytest.raises(ValueError, match="as_of must be a datetime.date"):
            apply_add_balance_adjustment(
                db_session, acc_id, Decimal("2000.00"), as_of="2026-03-10"
            )
    finally:
        db_session.rollback()

    remaining = db_session.execute(
        text("SELECT count(*) FROM accounts WHERE name LIKE :pattern"),
        {"pattern": f"{_ASOF_TEST_PREFIX}-%"},
    ).scalar()
    assert remaining == 0, remaining


def test_as_of_backdated_anchor_recomputes_next_adjustment(db_session):
    """D-08 revised decision 1 (2026-09-24, todo 260924-as-of-backdate-guard) —
    supersedes the old "raise when as_of <= latest adjustment" fix. A
    back-dated `as_of` anchor is ALLOWED: it writes X = target - Bal(as_of),
    and if the account has a later Adjustment (the first one dated after
    as_of), that adjustment's amount is reduced by X in the same
    transaction and audit-logged as an 'edit', so the balance at and after
    it — and the all-time sum / net_worth() — never moves. Only the window
    [as_of, next adjustment's date) shifts, which is the intended historical
    correction. `as_of` on the same day as an existing Adjustment is
    rejected before any write, because same-day anchor ordering is
    ambiguous.
    """
    from backend.models import AuditLog
    from backend.writes import apply_add_balance_adjustment

    try:
        acc_id = _make_asof_account(db_session, "recompute-1")

        def bal(d):
            excl = d + timedelta(days=1)
            return Decimal(
                str(
                    db_session.execute(
                        text(
                            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
                            "WHERE account_id = :id AND date < :excl"
                        ),
                        {"id": acc_id, "excl": excl},
                    ).scalar()
                )
            )

        def adjustment_count():
            return db_session.execute(
                text(
                    "SELECT count(*) FROM transactions "
                    "WHERE account_id = :id AND category = 'Adjustment'"
                ),
                {"id": acc_id},
            ).scalar()

        def read_amount(tx_id):
            return Decimal(
                str(
                    db_session.execute(
                        text("SELECT amount FROM transactions WHERE id = :id"),
                        {"id": tx_id},
                    ).scalar()
                )
            )

        _make_asof_transaction(db_session, acc_id, date(2026, 1, 15), Decimal("1000.00"))
        _make_asof_transaction(db_session, acc_id, date(2026, 3, 10), Decimal("500.00"))
        _make_asof_transaction(db_session, acc_id, date(2026, 6, 20), Decimal("250.00"))

        # A_next: no later adjustment exists yet, so this behaves as today.
        a_next = apply_add_balance_adjustment(
            db_session, acc_id, Decimal("3000.00"), as_of=date(2026, 7, 1)
        )
        db_session.flush()
        a_next_id = a_next.id
        assert a_next.amount == Decimal("1250.00"), a_next.amount  # 3000 - 1750

        _make_asof_transaction(db_session, acc_id, date(2026, 8, 5), Decimal("100.00"))

        bal_2026_07_01_before = bal(date(2026, 7, 1))
        bal_2026_08_05_before = bal(date(2026, 8, 5))
        all_time_sum_before = bal(date(2026, 12, 31))

        # Back-date with a later adjustment (A_next) present.
        anchor = apply_add_balance_adjustment(
            db_session, acc_id, Decimal("2000.00"), as_of=date(2026, 3, 10)
        )
        db_session.flush()
        assert anchor.amount == Decimal("500.00"), anchor.amount  # 2000 - 1500
        assert anchor.date.date() == date(2026, 3, 10), anchor.date
        assert anchor.category == "Adjustment", anchor.category
        assert anchor.is_transfer is True, anchor.is_transfer

        # (b) the balance at the anchor date now equals the target.
        assert bal(date(2026, 3, 10)) == Decimal("2000.00"), bal(date(2026, 3, 10))

        # (a) balances at and after A_next, and the all-time sum, don't move.
        assert bal(date(2026, 7, 1)) == bal_2026_07_01_before
        assert bal(date(2026, 8, 5)) == bal_2026_08_05_before
        assert bal(date(2026, 12, 31)) == all_time_sum_before

        # (c) A_next's amount, re-read from the DB, is 750.00 (1250 - 500).
        assert read_amount(a_next_id) == Decimal("750.00"), read_amount(a_next_id)

        # (d) exactly one 'edit' AuditLog row rewrote A_next, str amounts.
        edit_rows = (
            db_session.query(AuditLog)
            .filter_by(entity="transaction", entity_id=a_next_id, operation="edit")
            .all()
        )
        assert len(edit_rows) == 1, edit_rows
        before_amt, after_amt = edit_rows[0].before["amount"], edit_rows[0].after["amount"]
        assert isinstance(before_amt, str) and isinstance(after_amt, str), edit_rows[0]
        assert Decimal(before_amt) == Decimal("1250.00"), before_amt
        assert Decimal(after_amt) == Decimal("750.00"), after_amt

        # Same-day rejection: as_of on A_next's own day is ambiguous.
        adjustment_count_before = adjustment_count()
        with pytest.raises(ValueError, match="same day as an existing adjustment"):
            apply_add_balance_adjustment(
                db_session, acc_id, Decimal("9999.00"), as_of=date(2026, 7, 1)
            )
        assert adjustment_count() == adjustment_count_before
        assert read_amount(a_next_id) == Decimal("750.00")

        # No adjustment after as_of, with earlier ones present: as today.
        current_before = bal(date(2026, 8, 10))
        later = apply_add_balance_adjustment(
            db_session, acc_id, Decimal("5000.00"), as_of=date(2026, 8, 10)
        )
        db_session.flush()
        assert later.amount == Decimal("5000.00") - current_before, later.amount
        assert read_amount(a_next_id) == Decimal("750.00")
        edit_rows_after = (
            db_session.query(AuditLog)
            .filter_by(entity="transaction", entity_id=a_next_id, operation="edit")
            .all()
        )
        assert len(edit_rows_after) == 1, edit_rows_after
    finally:
        db_session.rollback()

    remaining = db_session.execute(
        text("SELECT count(*) FROM accounts WHERE name LIKE :pattern"),
        {"pattern": f"{_ASOF_TEST_PREFIX}-%"},
    ).scalar()
    assert remaining == 0, remaining


def test_as_of_not_exposed_to_agent_tool_surface():
    """D-08 / T-20-01. `as_of` must never reach the LLM or MCP tool schema.

    `propose_add_balance_adjustment` (backend/tools.py, dual-registered into
    backend/query.py's FunctionTool list) is introspected to build both the
    LlamaIndex tool schema and the FastMCP schema, so a single `as_of`
    parameter added to that wrapper would silently hand the model a
    capability to back-date financial records (T-20-01).

    Mirrors, without re-running, backend/tests/test_mcp.py::
    test_new_write_tools_registered_and_excluded, which asserts the same
    absence against a live `tools/list` response over a FastAPI test client.
    """
    import inspect
    import re

    import backend.mcp_server as mcp_server
    import backend.query as query
    import backend.tools as tools
    import backend.writes as writes
    from llama_index.core.tools import FunctionTool

    # 1. as_of IS a parameter of the write-layer function.
    write_params = list(inspect.signature(writes.apply_add_balance_adjustment).parameters)
    assert "as_of" in write_params, write_params

    # 2. as_of is NOT a parameter of the agent-facing wrapper.
    agent_params = list(inspect.signature(tools.propose_add_balance_adjustment).parameters)
    assert agent_params == ["account_id", "target_balance"], agent_params

    # 3. The generated LLM tool schema has no as_of property.
    tool = FunctionTool.from_defaults(fn=tools.propose_add_balance_adjustment)
    schema_props = tool.metadata.get_parameters_dict().get("properties", {})
    assert "as_of" not in schema_props, schema_props

    # 4. Plain-text scan: neither registration module mentions as_of at all.
    for mod_path in (Path(tools.__file__), Path(query.__file__)):
        module_text = mod_path.read_text(encoding="utf-8")
        assert "as_of" not in module_text, (
            f"{mod_path} contains 'as_of' — the propose_*/FunctionTool "
            "registrations in this file are introspected to build both the "
            "LlamaIndex and MCP schemas, so any as_of occurrence here risks "
            "silently granting the model a back-dating capability"
        )

    # 5. The MCP surface, asserted directly rather than by inference:
    # propose_add_balance_adjustment is reachable via TOOLS but structurally
    # excluded from the frozenset build_mcp() iterates.
    assert "propose_add_balance_adjustment" in tools.TOOLS
    assert "propose_add_balance_adjustment" not in tools.READ_TOOL_NAMES

    mcp_source = inspect.getsource(mcp_server.build_mcp)
    assert re.search(r"for\s+\w+\s+in\s+READ_TOOL_NAMES", mcp_source), mcp_source
    assert not re.search(r"for\s+\w+\s+in\s+TOOLS\b", mcp_source), mcp_source


# ---------------------------------------------------------------------------
# liquid_drift_estimate() (D-06, plan 23.1-01)
# ---------------------------------------------------------------------------


def test_liquid_drift_estimate_matches_anchor_day_residual(db_session):
    """23.1 D-06, WR-01. `liquid_drift_estimate()` is an "up to" bound: for
    each anchored liquid account, what the ledger_plus_corrections regime
    would have shown on that account's anchor day minus the statement truth
    recorded that day, summing only the overstated (positive) accounts.

    Independent oracle: the regime value and the truth are each computed
    from whole-ledger SUMs per `account_id` (non-Adjustment ledger plus
    recovered legs vs the full ledger including the Adjustment), never via
    any helper or constant from backend.reconstruction, and never through
    the implementation's corrections-minus-adjustments shortcut.
    """
    from backend.reconstruction import liquid_drift_estimate

    accounts = db_session.execute(
        text(
            "SELECT a.id, a.name, MIN(t.date)::date FROM accounts a "
            "LEFT JOIN transactions t ON t.account_id = a.id AND t.category = 'Adjustment' "
            "WHERE a.type = 'liquid' GROUP BY a.id, a.name"
        )
    ).all()
    anchored = [(acc_id, name, anchor) for acc_id, name, anchor in accounts if anchor is not None]
    if not anchored:
        assert liquid_drift_estimate(conn=db_session.connection()) is None
        return

    def scalar(sql: str, **params) -> Decimal:
        return Decimal(str(db_session.execute(text(sql), params).scalar()))

    expected = Decimal("0.00")
    overstatements = {}
    for acc_id, name, anchor in anchored:
        end_excl = anchor + timedelta(days=1)
        regime_value = scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id "
            "AND category IS DISTINCT FROM 'Adjustment' AND date < :end_excl",
            id=acc_id,
            end_excl=end_excl,
        ) + scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
            "WHERE source = :source AND orig_account = :name AND date < :end_excl",
            source=_SOURCE,
            name=name,
            end_excl=end_excl,
        )
        truth = scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE account_id = :id AND date < :end_excl",
            id=acc_id,
            end_excl=end_excl,
        )
        overstatements[name] = regime_value - truth
        if regime_value > truth:
            expected += regime_value - truth

    actual = liquid_drift_estimate(conn=db_session.connection())
    assert actual is not None
    assert actual == expected.quantize(Decimal("0.01")), (actual, expected, overstatements)
    # A true "up to" bound: never below any single account's overstatement.
    assert all(actual >= v for v in overstatements.values()), (actual, overstatements)


def test_liquid_drift_estimate_is_none_without_any_anchor(monkeypatch, db_session):
    """23.1 D-06, CR-01. Only when NO live liquid account has ever been
    adjusted does `liquid_drift_estimate` return None — there is nothing to
    measure against. One unanchored account alone must not hide the
    caption (see the series test below)."""
    import backend.reconstruction as reconstruction

    def fake_anchor_dates(conn):
        return {"Account A": None, "Account B": None}

    monkeypatch.setattr(reconstruction, "_anchor_dates", fake_anchor_dates)
    assert reconstruction.liquid_drift_estimate(conn=db_session.connection()) is None


def _month_end_of(month_str: str) -> date:
    year, month = (int(p) for p in month_str.split("-"))
    return date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)


def test_unanchored_liquid_account_keeps_d07_after_regime_cutoff(monkeypatch, db_session):
    """CR-01. A new liquid account with no Adjustment row (agent "add
    account", or the importer's get-or-create) must not move the whole
    series onto the relaxed basis. Months before the cutoff (MAX over the
    anchors that exist) stay "ledger_plus_corrections"; every month on or
    after it stays on D-07 and gaps with `no_opening_anchor` because the
    newcomer has no window. Stubs the anchor/window queries instead of
    inserting an account, so the live DB is never written."""
    import backend.reconstruction as reconstruction

    conn = db_session.connection()
    real_anchors = reconstruction._anchor_dates(conn)
    real_windows = reconstruction._adjustment_windows(conn)
    known = [d for d in real_anchors.values() if d is not None]
    assert known, real_anchors
    cutoff = max(known)

    newcomer = "__cr01_unanchored_newcomer__"
    monkeypatch.setattr(reconstruction, "_anchor_dates", lambda c: {**real_anchors, newcomer: None})
    monkeypatch.setattr(
        reconstruction, "_adjustment_windows", lambda c: {**real_windows, newcomer: []}
    )

    earliest = conn.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    today = date.today()
    months = (today.year - earliest.year) * 12 + (today.month - earliest.month) + 2

    result = reconstruction.monthly_liquid_series(months=months, conn=conn)
    pre, post = [], []
    for row in result["rows"]:
        m_end = _month_end_of(row["month"])
        if m_end < earliest:
            assert row["gap_reason"] == "pre_ledger", row
        elif m_end <= cutoff:
            assert row["honest"] and row["valuation_basis"] == "ledger_plus_corrections", row
            pre.append(row["month"])
        else:
            assert not row["honest"] and row["gap_reason"] == "no_opening_anchor", row
            post.append(row["month"])
    assert pre and post, (pre, post)

    # The drift caption survives: the anchored accounts still measure it.
    assert reconstruction.liquid_drift_estimate(conn=conn) is not None

    # No anchor anywhere: no relaxed regime at all, never "honest forever".
    monkeypatch.setattr(reconstruction, "_anchor_dates", lambda c: dict.fromkeys(real_anchors))
    monkeypatch.setattr(reconstruction, "_adjustment_windows", lambda c: {n: [] for n in real_anchors})
    result = reconstruction.monthly_liquid_series(months=months, conn=conn)
    assert not any(r["valuation_basis"] == "ledger_plus_corrections" for r in result["rows"])
    assert not result["honest_months"], result["honest_months"]


def test_month_end_anchor_leaves_no_gap_between_regimes(monkeypatch, db_session):
    """WR-04. An anchor dated on the last day of a month must not strand
    that month between the two regimes: `month_end < anchor` is False there
    and D-07's half-open `lo < month_end` is False too, so a strict test
    would gap a fully anchored month with a misleading `no_opening_anchor`.
    Stubs every account's anchor to 2026-08-31 (no live writes)."""
    import backend.reconstruction as reconstruction

    conn = db_session.connection()
    names = list(reconstruction._anchor_dates(conn))
    anchor = date(2026, 8, 31)
    monkeypatch.setattr(reconstruction, "_anchor_dates", lambda c: dict.fromkeys(names, anchor))
    monkeypatch.setattr(
        reconstruction, "_adjustment_windows", lambda c: {n: [(anchor, None)] for n in names}
    )

    earliest = conn.execute(
        text(
            "SELECT MIN(t.date)::date FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
        )
    ).scalar()
    today = date.today()
    months = (today.year - earliest.year) * 12 + (today.month - earliest.month) + 2

    rows = {r["month"]: r for r in reconstruction.monthly_liquid_series(months=months, conn=conn)["rows"]}
    aug = rows["2026-08"]
    assert aug["honest"] and aug["valuation_basis"] == "ledger_plus_corrections", aug
    assert not any(r["gap_reason"] == "no_opening_anchor" for r in rows.values()), rows
