"""Read-only investment-side history reconstruction (RECON-04, RECON-05, RECON-06).

This module never mutates a table: no row in `holdings`, `portfolio_events`
or `portfolio_value_history` is created, modified, or removed by anything in
this file, and it imports nothing from `backend.writes` or `backend.portfolio`
(both contain write paths -- even a read-only call site there would be a
smell). It never persists its session.

Scope of that guarantee (DD-2): the promise above is specific, not a blanket
read-only claim. `fx.get_rate` (backend/fx.py, reused as-is, never
reimplemented here) may append one immutable row to `fx_rate_cache` on a
cache miss. That transitive effect lives entirely inside backend/fx.py, is
append-only, and is unreachable with today's data -- every `portfolio_events`
row on the live database carries `currency = 'IDR'`, so `get_rate` returns
its identity result before touching the cache at all.

D-01 -- why no price adapter is called: RECON-04 asks for the LAST
TRANSACTED price, which is the value already stored on
`portfolio_events.price`. A live or historical market-price fetch here would
be mark-to-market, a different and unrequested number. No price-adapter
registry exists in this module (21-RESEARCH.md Pitfall 5).

D-02 -- a position whose every supporting event on or before a bucket's
month-end was written by Alembic migration 012 resolves to a gap
(`synthetic_opening_only`) instead of a fabricated valuation. Provenance is
read from the `audit_log` `source` marker migration 012 itself wrote
(`opening_balance_backfill_012`), never inferred from the 2026-07-11 date:
three organic events (ids 136, 215, 3238) are also dated 2026-07-11, and a
date heuristic would misclassify them. Mixed-lot caveat: a position with at
least one organic event on or before the bucket's month-end is treated as
honest for that bucket even when an earlier synthetic opening lot is still
folded into its running quantity.

DD-1 -- the public entry point takes `db: Session | None = None`, not a bare
Connection, because `fx.get_rate(base, quote, as_of, db)` requires a
`Session` -- carrying both a `Session` and a `Connection` would let one call
see two transactions' worth of database state. Raw SQL in this module runs
on `db.connection()`.

D-01 (Phase 22) -- `monthly_investment_series` now reads the live `holdings`
table exactly once per call, to narrow its snapshot-regime held-set to
positions that still have a holdings row (D-02). This is still a read: no
INSERT, UPDATE, DELETE or commit is added anywhere in this module. The raw
replay functions below (`_replay_positions`, `reconstructed_investment_by_month`)
are untouched and still never read `holdings` at all.

RECON-06 -- idempotent by construction: this module is a pure function of
(`portfolio_events`, `portfolio_value_history`, `audit_log`) contents with no
internal cache or side table.

Deliberately NOT honesty-gated and NOT snapshot-aware -- this is the raw
replay arithmetic; plan 21-02 gates it against real `portfolio_value_history`
snapshots and composes the public series envelope.

D-01 (Phase 23.1) -- the user's decision relaxes RECON-05 for
every ledger-era month strictly before the real snapshot floor: instead of
gapping, that month carries the dropped "Investements" Wallet account's
running deposits balance, read straight from `net_worth_corrections`. This
is money deposited AT COST, never a market value -- every such row is
labelled `valuation_basis = "deposits"` so no consumer can mistake it for a
valuation. The flat carry from the last Investements row up to
the snapshot floor is the account's real cumulative balance, because the
underlying SUM is cumulative, not an interpolation. Months before the Wallet
ledger itself existed -- before `MIN(date)` over liquid `transactions` --
still gap with `no_investment_tracking_before_launch`, because no data
exists for them at all; this is the one gap reason this module never stops
using. The module now also reads `net_worth_corrections` (to compute the
deposits total) and `MIN(date)` of liquid `transactions` (the ledger floor),
both strictly as reads.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import fx
from backend.db import SessionLocal

# All money/quantity arithmetic below uses Decimal, never float -- matching
# the Numeric(28,8) quantity / Numeric(18,2) money column precision.

# Do NOT call a live/historical price API here (CoinGecko/yfinance). RECON-04
# specifies last-transacted price (portfolio_events.price), not
# mark-to-market. A registry dict of adapters in this module is a design
# error (21-RESEARCH.md Pitfall 5).

_SYNTHETIC_SOURCE = "opening_balance_backfill_012"

# Phase 23's caption contract -- a UI renders one of these fixed strings, and
# free prose is never emitted in its place. The last two are consumed by
# plan 21-02 (snapshot-side honesty gating), not by this module.
INVESTMENT_GAP_REASONS = (
    "no_investment_tracking_before_launch",
    "synthetic_opening_only",
    "fx_unavailable",
    "unknown_event_type",
    "negative_running_quantity",
    "no_snapshot_for_month",
    "snapshot_missing_position",
)

# Copied byte-identical from backend/reconstruction.py -- a pure date-range
# generator, no reason to fork it.
_MONTH_SQL = (
    "SELECT to_char(m, 'YYYY-MM') AS month, "
    "(m + interval '1 month')::date AS end_excl "
    "FROM generate_series("
    "date_trunc('month', CURRENT_DATE) - ((:months - 1) || ' months')::interval, "
    "date_trunc('month', CURRENT_DATE), interval '1 month') AS m "
    "ORDER BY m"
)

_SYNTHETIC_EVENT_IDS_SQL = (
    "SELECT entity_id FROM audit_log "
    "WHERE entity = 'portfolio_event' AND operation = 'add' "
    "AND after->>'source' = :source"
)

_EVENTS_SQL = (
    "SELECT id, date, ticker, event_type, quantity, price, platform_id, currency "
    "FROM portfolio_events ORDER BY date, id"
)


def _synthetic_event_ids(conn) -> set[int]:
    """Event ids whose audit_log add-row carries migration 012's own source
    marker (D-02). No date heuristic -- see module docstring."""
    rows = conn.execute(text(_SYNTHETIC_EVENT_IDS_SQL), {"source": _SYNTHETIC_SOURCE}).fetchall()
    return {row[0] for row in rows}


def _position_key(ticker: str, platform_id: int | None) -> str:
    """Correlates an event-side position (portfolio_events.platform_id is NOT
    NULL) with a snapshot-side one (portfolio_value_history.platform_id is
    nullable for pre-multi-platform rows).

    A legacy NULL-platform snapshot row therefore keys as `TICKER@None` and can
    never match its event-side `TICKER@<id>` key. That asymmetry is ACCEPTED and
    fail-closed (WR-01): the position reads as uncovered and the bucket gaps
    with `snapshot_missing_position` rather than being silently attributed to a
    guessed platform. Gapping over guessing is this module's whole point.
    Pinned by `test_null_platform_snapshot_row_keys_apart_and_fails_closed`."""
    return f"{ticker}@{platform_id}"


def _replay_positions(events, at_date: date, synthetic_ids: set[int], db: Session) -> dict[str, dict]:
    """Fold every event dated on or before `at_date` into per-position
    running state, then resolve each held position's value.

    Resolution order (deterministic, DD-3): unknown event type seen, then
    negative running quantity, then every supporting event synthetic
    (D-02 -- synthetic_opening_only), then FX unresolved (fx_unavailable),
    then resolved.
    """
    positions: dict[str, dict] = {}
    for ev in events:
        if ev.date > at_date:
            continue
        key = _position_key(ev.ticker, ev.platform_id)
        pos = positions.setdefault(
            key,
            {
                "quantity": Decimal("0"),
                "basis_event": None,
                "unknown_event_type": False,
                "all_synthetic": True,
            },
        )
        if ev.event_type in ("buy", "deposit"):
            pos["quantity"] += ev.quantity
            pos["basis_event"] = ev
        elif ev.event_type == "sell":
            pos["quantity"] -= ev.quantity
            pos["basis_event"] = ev
        elif ev.event_type == "dividend":
            # Income per unit, not an instrument mark -- changes neither
            # quantity nor the price basis used for valuation.
            pass
        else:
            # An unrecognised fifth event_type never raises or is silently
            # skipped -- it sets a sticky flag that gaps this one position.
            pos["unknown_event_type"] = True
        if pos["basis_event"] is ev:
            # ONLY the event that supplies the price basis may clear this
            # flag. A non-price-bearing organic event (dividend, or any
            # future income-shaped type) must never launder a still-synthetic
            # price basis into a resolved, "honest" value (D-02 / CR-01).
            pos["all_synthetic"] = pos["all_synthetic"] and (ev.id in synthetic_ids)

    result: dict[str, dict] = {}
    for key, pos in positions.items():
        if pos["quantity"] == 0:
            # Closed (or never opened) -- excluded entirely, never reported
            # with a zero value.
            continue

        ev = pos["basis_event"]
        entry = {
            "quantity": pos["quantity"],
            "value": None,
            "gap_reason": None,
            "basis_date": ev.date if ev is not None else None,
            "basis_is_synthetic_only": pos["all_synthetic"],
        }

        if pos["unknown_event_type"]:
            entry["gap_reason"] = "unknown_event_type"
        elif pos["quantity"] < 0:
            # A ledger inconsistency, not a short position.
            entry["gap_reason"] = "negative_running_quantity"
        elif pos["all_synthetic"]:
            entry["gap_reason"] = "synthetic_opening_only"
        else:
            # The CASH sentinel needs no branch of its own: its stored price
            # is 1.00, so quantity * price * rate is exactly its value. It
            # cannot be dropped by a join because this function never reads
            # the holdings table at all (T-21-05 / Pitfall 3).
            basis_currency = ev.currency or "IDR"
            rate = fx.get_rate(basis_currency, "IDR", ev.date, db)
            if rate is None:
                # Vendor outage/gap -- propagate None, never fabricate
                # rate=1.0 and never fall back to cost basis (RECON-05).
                entry["gap_reason"] = "fx_unavailable"
            else:
                entry["value"] = pos["quantity"] * ev.price * rate

        result[key] = entry
    return result


def reconstructed_investment_by_month(months: int = 72, *, db: Session | None = None) -> list[dict]:
    """Raw per-month replay arithmetic for every held position.

    `replay_total` is the sum of every held position's value when ALL of
    them resolved, and `None` the moment any held position carries a
    `gap_reason` (DD-3: no partial sums -- an understated total wearing an
    honest label is the exact failure this project exists to avoid). A
    bucket with no held positions at all gets an empty `replay_by_position`
    and `replay_total = None`. Never commits and never rolls back a
    caller-supplied session -- the transaction boundary belongs to the
    caller (mirrors backend/writes.py's stated convention).
    """
    owns_db = db is None
    db = db or SessionLocal()
    try:
        conn = db.connection()
        buckets = [
            {"month": r[0], "end_excl": r[1]}
            for r in conn.execute(text(_MONTH_SQL), {"months": months}).fetchall()
        ]
        events = conn.execute(text(_EVENTS_SQL)).fetchall()
        synthetic_ids = _synthetic_event_ids(conn)

        results: list[dict] = []
        for bucket in buckets:
            end_excl = bucket["end_excl"]
            month_end = end_excl - timedelta(days=1)
            by_position = _replay_positions(events, month_end, synthetic_ids, db)

            if by_position and all(p["gap_reason"] is None for p in by_position.values()):
                total = sum((p["value"] for p in by_position.values()), Decimal("0"))
            else:
                total = None

            results.append(
                {
                    "month": bucket["month"],
                    "end_excl": end_excl,
                    "replay_by_position": by_position,
                    "replay_total": total,
                }
            )
        return results
    finally:
        if owns_db:
            db.close()


_SNAPSHOT_FLOOR_SQL = "SELECT MIN(snapshot_date) FROM portfolio_value_history"

# Copied byte-identical from backend/reconstruction.py's `_SOURCE` -- this
# module's static import scan forbids importing that module, so the shared
# literal is redeclared here (same convention as `_MONTH_SQL` above).
_SOURCE = "corrections_260620"

# The dropped Wallet account's label, spelled exactly as stored in
# `net_worth_corrections.orig_account`.
_DEPOSITS_LABEL = "Investements"

# 23.1 D-01: the deposits-regime running balance -- a plain point-in-time SUM
# over the dropped account's recovered legs, same half-open `date < :end_excl`
# convention as every other bucket boundary in this file and its liquid
# sibling. Source and label are bound parameters, never interpolated.
_DEPOSITS_SQL = (
    "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
    "WHERE source = :source AND orig_account = :label AND date < :end_excl"
)

# WR-02: the deposits regime only exists when the dropped account left ANY
# recovered history. Without it (fresh install, another user's data) a
# deposits "0.00" would be an unverified confident zero, so those months fall
# through to the replay path and gap as before 23.1.
_DEPOSITS_HISTORY_SQL = (
    "SELECT EXISTS (SELECT 1 FROM net_worth_corrections "
    "WHERE source = :source AND orig_account = :label)"
)

# Copied byte-identical from backend/reconstruction.py's
# `_EARLIEST_LIQUID_TX_SQL` -- same import-scan restriction as `_SOURCE`
# above.
_LEDGER_FLOOR_SQL = (
    "SELECT MIN(t.date)::date FROM transactions t "
    "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
)

_SNAPSHOT_DAY_SQL = (
    "SELECT MAX(snapshot_date) FROM portfolio_value_history "
    "WHERE snapshot_date >= :start AND snapshot_date < :end_excl"
)

# Every one of the live rows is IDR (verified 2026-09-20), and restricting to
# IDR here means a future non-IDR row is treated as an UNCOVERED position by
# the DD-5 coverage check below rather than being summed across currencies.
# That statement is accurate only because the DD-5 coverage set is the FULL
# held set -- under a narrower set a non-IDR row for an excluded position
# would slip through, which is exactly why the set is not narrowed.
_SNAPSHOT_ROWS_SQL = (
    "SELECT ticker, platform_id, market_value FROM portfolio_value_history "
    "WHERE snapshot_date = :snapshot_date AND currency = 'IDR'"
)

# `holdings` carries no temporal column (verified: its columns are id,
# ticker, quantity, avg_cost, purchase_date, currency, asset_type,
# platform_id, coingecko_id only), so this presence test is necessarily
# as-of-now for every bucket including past ones. A position both omitted
# from an old snapshot and since sold would understate that past month --
# accepted under D-02 (22-CONTEXT.md).
_HOLDINGS_PRESENCE_SQL = "SELECT ticker, platform_id FROM holdings"


def _snapshot_positions(conn, snapshot_date: date) -> dict[str, Decimal]:
    """Real `portfolio_value_history` market_value keyed by position,
    reused VERBATIM -- no re-derivation, no rounding, no conversion (D-03)."""
    rows = conn.execute(text(_SNAPSHOT_ROWS_SQL), {"snapshot_date": snapshot_date}).fetchall()
    return {_position_key(row[0], row[1]): row[2] for row in rows}


def _covered_keys(snapshot_positions: dict[str, Decimal]) -> set[str]:
    """A position is COVERED only when it is present AND its market_value is
    strictly greater than zero (DD-5). Presence alone is not enough: the live
    CASH@67 row on 2026-09-03 carries market_value=0.00 and must not count as
    coverage for a 500,000 IDR position."""
    return {key for key, value in snapshot_positions.items() if value > 0}


def _honesty(
    month: str,
    month_end: date,
    snapshot_floor: date | None,
    snapshot_day: date | None,
    covered_keys: set[str],
    held_keys: set[str],
    replay_bucket: dict,
) -> tuple[bool, str | None, str | None]:
    """Decide, per month bucket, whether the replay or a real snapshot is
    the honest basis -- or whether neither can be published. Returns
    `(honest, gap_reason, valuation_basis)`; `gap_reason` is always a member
    of `INVESTMENT_GAP_REASONS`, never free prose.

    Replay regime -- taken when `snapshot_floor` is None or `month_end`
    precedes it:
      1. No held position at all -> not honest, `no_investment_tracking_before_launch`.
      2. Otherwise, if any held position carries a `gap_reason`, the bucket
         is not honest and the bucket's reason is that position's reason,
         resolved in the deterministic order `unknown_event_type`,
         `negative_running_quantity`, `synthetic_opening_only`,
         `fx_unavailable` -- first present wins.
      3. Otherwise honest, basis `"replay"`.

    Snapshot regime -- taken when `month_end >= snapshot_floor`:
      4. No snapshot day inside this bucket's OWN month -> not honest,
         `no_snapshot_for_month`. Never falls back to the replay here and
         never reaches into an adjacent month (DD-4, D-03) -- enforced by
         `_SNAPSHOT_DAY_SQL`'s own month-scoped WHERE clause, not by this
         function.
      5. Otherwise, if `held_keys` is not a subset of `covered_keys` -> not
         honest, `snapshot_missing_position` (DD-5).
      6. Otherwise honest, basis `"snapshot"`.

    `held_keys` must be the FULL held set `_replay_positions` reports at the
    chosen snapshot day -- synthetic-backed positions INCLUDED, per DD-5.
    Narrowing it to organically-backed positions only would let a partial
    snapshot day pass coverage and publish an understated total as honest.
    """
    in_replay_regime = snapshot_floor is None or month_end < snapshot_floor

    if in_replay_regime:
        by_position = replay_bucket["replay_by_position"]
        if not by_position:
            return False, "no_investment_tracking_before_launch", None

        for reason in (
            "unknown_event_type",
            "negative_running_quantity",
            "synthetic_opening_only",
            "fx_unavailable",
        ):
            if any(pos["gap_reason"] == reason for pos in by_position.values()):
                return False, reason, None

        return True, None, "replay"

    if snapshot_day is None:
        return False, "no_snapshot_for_month", None

    if not held_keys <= covered_keys:
        return False, "snapshot_missing_position", None

    return True, None, "snapshot"


def monthly_investment_series(months: int = 72, *, db: Session | None = None) -> dict:
    """The Phase 20-shaped envelope for the investment side (D-05): the same
    four keys (`tool`, `rows`, `honest_months`, `gap_summary`) as
    `monthly_liquid_series`, `rows` keyed by the same `month` strings so
    Phase 22 can zip the two series.

    Real `portfolio_value_history` snapshots are reused VERBATIM for every
    month that has one inside its own boundaries -- no re-derivation, no
    smoothing, no interpolation (D-03). Snapshots are sparse, so a month
    with no snapshot of its own GAPS rather than inheriting a neighbouring
    month's value (DD-4). A snapshot day that omits -- or carries at a zero
    market_value -- any position the replay says is held GAPS the bucket
    with `snapshot_missing_position` rather than publishing an understated
    total (DD-5). Every ledger-era bucket whose month-end precedes the first
    real snapshot carries the dropped "Investements" account's running
    deposits balance instead of gapping, labelled `valuation_basis =
    "deposits"` -- at cost, never a market value (23.1 D-01, relaxing
    RECON-05 on the user's 2026-09-24 decision). Only buckets whose month-end
    precedes the Wallet ledger's own start still gap, with
    `no_investment_tracking_before_launch`, because no data exists for them
    at all. The deposits basis is skipped (WR-02) when the "Investements"
    label has no recovered rows at all -- those months keep the replay
    path's gap -- and for any month whose replay bucket is non-empty, so a
    real pre-floor portfolio_event is never hidden behind deposits. Each row carries `valuation_basis` and `as_of_date` so a consumer
    never has to guess which basis or which exact day produced the number.
    Never commits and never rolls back a caller-supplied session -- same
    convention as `reconstructed_investment_by_month`.
    """
    owns_db = db is None
    db = db or SessionLocal()
    try:
        conn = db.connection()
        raw_rows = reconstructed_investment_by_month(months=months, db=db)
        snapshot_floor = conn.execute(text(_SNAPSHOT_FLOOR_SQL)).scalar()
        ledger_floor = conn.execute(text(_LEDGER_FLOOR_SQL)).scalar()
        has_deposits_history = conn.execute(
            text(_DEPOSITS_HISTORY_SQL), {"source": _SOURCE, "label": _DEPOSITS_LABEL}
        ).scalar()
        events = conn.execute(text(_EVENTS_SQL)).fetchall()
        synthetic_ids = _synthetic_event_ids(conn)
        holdings_presence_keys = {
            _position_key(row[0], row[1])
            for row in conn.execute(text(_HOLDINGS_PRESENCE_SQL)).fetchall()
        }

        rows: list[dict] = []
        gap_counts: dict[str, int] = {}
        honest_months: list[str] = []

        for raw in raw_rows:
            month = raw["month"]
            end_excl = raw["end_excl"]
            month_end = end_excl - timedelta(days=1)
            month_start = date.fromisoformat(f"{month}-01")

            # 23.1 D-01: a ledger-era, pre-snapshot-floor month carries the
            # dropped Investements account's deposits balance instead of
            # going through replay/snapshot honesty. WR-02: only when that
            # account left any history at all, and only when the replay
            # bucket is empty -- a real pre-floor portfolio_event (e.g. a
            # back-dated funded buy) keeps the replay regime, including its
            # gap reasons, rather than being overwritten by deposits.
            if (
                has_deposits_history
                and not raw["replay_by_position"]
                and ledger_floor is not None
                and snapshot_floor is not None
                and ledger_floor <= month_end < snapshot_floor
            ):
                deposits_total = Decimal(
                    str(
                        conn.execute(
                            text(_DEPOSITS_SQL),
                            {"source": _SOURCE, "label": _DEPOSITS_LABEL, "end_excl": end_excl},
                        ).scalar()
                    )
                )
                rows.append(
                    {
                        "month": month,
                        "investment_by_position": {_DEPOSITS_LABEL: deposits_total},
                        "investment_total": deposits_total,
                        "valuation_basis": "deposits",
                        "as_of_date": month_end,
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)
                continue

            in_snapshot_regime = snapshot_floor is not None and month_end >= snapshot_floor

            snapshot_day: date | None = None
            snapshot_positions: dict[str, Decimal] = {}
            covered_keys: set[str] = set()
            held_keys: set[str] = set()

            if in_snapshot_regime:
                snapshot_day = conn.execute(
                    text(_SNAPSHOT_DAY_SQL),
                    {"start": month_start, "end_excl": end_excl},
                ).scalar()
                if snapshot_day is not None:
                    snapshot_positions = _snapshot_positions(conn, snapshot_day)
                    covered_keys = _covered_keys(snapshot_positions)
                    held_positions = _replay_positions(events, snapshot_day, synthetic_ids, db)
                    # D-01/D-02: a position the replay still shows as held but
                    # with no `holdings` row was closed outside the event
                    # ledger (the CASH@67 case -- drawn to zero, holding row
                    # deleted per audit_log #6342), so a snapshot omitting it
                    # is expected, not a gap.
                    held_keys = set(held_positions.keys()) & holdings_presence_keys

            honest, gap_reason, basis = _honesty(
                month, month_end, snapshot_floor, snapshot_day, covered_keys, held_keys, raw
            )

            if honest and basis == "snapshot":
                rows.append(
                    {
                        "month": month,
                        "investment_by_position": snapshot_positions,
                        "investment_total": sum(snapshot_positions.values(), Decimal("0")),
                        "valuation_basis": "snapshot",
                        "as_of_date": snapshot_day,
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)
            elif honest and basis == "replay":
                by_position = raw["replay_by_position"]
                rows.append(
                    {
                        "month": month,
                        "investment_by_position": {
                            key: pos["value"] for key, pos in by_position.items()
                        },
                        "investment_total": raw["replay_total"],
                        "valuation_basis": "replay",
                        "as_of_date": month_end,
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)
            else:
                rows.append(
                    {
                        "month": month,
                        "investment_by_position": None,
                        "investment_total": None,
                        "valuation_basis": None,
                        "as_of_date": None,
                        "honest": False,
                        "gap_reason": gap_reason,
                    }
                )
                gap_counts[gap_reason] = gap_counts.get(gap_reason, 0) + 1

        return {
            "tool": "reconstructed_investment_series",
            "rows": rows,
            "honest_months": honest_months,
            "gap_summary": gap_counts,
        }
    finally:
        if owns_db:
            db.close()


# This module exposes no FastAPI route, is not registered in
# backend/tools.py's TOOLS dict, and is not registered as a LlamaIndex
# FunctionTool in backend/query.py -- same posture as backend/reconstruction.py
# (D-14). Plan 21-02 composes the honesty-gated public series; Phase 22
# composes it with the liquid side; Phase 23 renders it.
