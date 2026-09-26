"""Read-only liquid-side net-worth reconstruction (RECON-02, RECON-03).

This module is strictly READ-ONLY history reconstruction. It issues no
INSERT, UPDATE or DELETE, and imports nothing from `backend.writes` (D-16).
It reads only `transactions`, `accounts`, and `net_worth_corrections`
(populated by migration `014`, plan 20-01).

WHY RECON-02's literal formula is NOT implemented:
`reconstructed_bank(t) + reconstructed_Investements(t) == raw_bank_ledger_sum(t)`
is a *partition* identity — it only holds if the recovered Investements rows
sit inside the bank account's ledger. A row-by-row reconciliation proved they are all
absent from the live database. Implementing that formula would subtract
money out of the bank ledger that was never there (D-04). The three replacement
invariants (D-05) — additive restoration, transfer-pair closure, and anchor
parity — are the real substance of this phase and are enforced by test in
`backend/tests/test_reconstruction.py`, never eyeballed.

D-05 (Phase 23.1): the user relaxed Phase 20's conservative
`no_opening_anchor` gate for every month strictly before the single liquid
anchor date — the raw ledger plus recovered corrections for the LIVE liquid
accounts is honest enough to show, on a "ledger_plus_corrections" basis. The
"Investements" label is excluded from that regime because it is now the
investment half's concern, not the liquid half's (D-01) — see
`liquid_drift_estimate`'s Pitfall-1 guard in the test file. The known
archival residual this regime leaves on the table is disclosed once via
`liquid_drift_estimate()`, never smoothed into the monthly figures. The
regime keys off the single `_regime_cutoff` date; a later back-dated anchor
round (D-DEF-04) could create an intermediate window this rule does not
describe — re-derive it before relying on multi-round anchors (research
Pitfall 4).

RECONCILING D-05.1 AGAINST THE D-03 GATE (read this before touching the
recovered-component logic below):

D-05.1 holds for every bucket strictly BEFORE an account's anchor; on and
after that anchor the recovered component is exactly zero by D-03, because
the anchoring adjustment already absorbed the missing legs, so applying both
would subtract the same money twice. D-05.1 read literally ("for every
bucket") and D-05.3 (anchor parity) are mutually exclusive at the 2026-09
bucket — D-05.1-literal would demand `live_sum + recovered_legs` there while
D-05.3 demands `live_sum` alone. D-05.3 wins; D-05.1 is therefore implemented
in its anchor-gated form, and `test_additive_restoration_invariant` asserts
that gated form deliberately, not by accident.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from backend.db import engine

_SOURCE = "corrections_260620"
GAP_REASONS = ("pre_ledger", "no_opening_anchor", "no_closing_anchor")

_MONTH_SQL = (
    "SELECT to_char(m, 'YYYY-MM') AS month, "
    "(m + interval '1 month')::date AS end_excl "
    "FROM generate_series("
    "date_trunc('month', CURRENT_DATE) - ((:months - 1) || ' months')::interval, "
    "date_trunc('month', CURRENT_DATE), interval '1 month') AS m "
    "ORDER BY m"
)

# Unfiltered, half-open point-in-time balance SUM (D-06) — matches
# apply_add_balance_adjustment's reconciliation convention exactly. There is
# deliberately no transfer-exclusion predicate here: a transfer moves real
# money between accounts and a balance must reflect it. This is NOT the
# cashflow-scoped FILTER account_balances() uses for its period total — that
# convention belongs to a cashflow metric, not a balance, and must not be
# copied here.
_LIVE_BY_ACCOUNT_SQL = (
    "SELECT a.name, COALESCE(SUM(t.amount), 0) FROM transactions t "
    "JOIN accounts a ON a.id = t.account_id "
    "WHERE a.type = 'liquid' AND t.date < :end_excl GROUP BY a.name"
)

_RECOVERED_BY_LABEL_SQL = (
    "SELECT orig_account, COALESCE(SUM(amount), 0) FROM net_worth_corrections "
    "WHERE source = :source AND date < :end_excl GROUP BY orig_account"
)

_ADJUSTMENT_DATES_SQL = (
    "SELECT a.name, t.date::date FROM transactions t "
    "JOIN accounts a ON a.id = t.account_id "
    "WHERE a.type = 'liquid' AND t.category = 'Adjustment' "
    "ORDER BY a.name, t.date"
)

_LIQUID_ACCOUNT_NAMES_SQL = "SELECT name FROM accounts WHERE type = 'liquid' ORDER BY name"

_EARLIEST_LIQUID_TX_SQL = (
    "SELECT MIN(t.date)::date FROM transactions t "
    "JOIN accounts a ON a.id = t.account_id WHERE a.type = 'liquid'"
)

# D-06 residual inputs, per live liquid account, both bounded at THAT
# account's own anchor day (end_excl = anchor + 1 day) -- the same per-account
# gate `reconstructed_liquid_by_month` applies to its recovered legs. Later
# adjustments are unrelated to the archival residual and must not move this
# figure.
_ACCOUNT_CORRECTIONS_SQL = (
    "SELECT COALESCE(SUM(amount), 0) FROM net_worth_corrections "
    "WHERE source = :source AND orig_account = :name AND date < :end_excl"
)

_ACCOUNT_ADJUSTMENT_TOTAL_SQL = (
    "SELECT COALESCE(SUM(t.amount), 0) FROM transactions t "
    "JOIN accounts a ON a.id = t.account_id "
    "WHERE a.type = 'liquid' AND a.name = :name AND t.category = 'Adjustment' "
    "AND t.date < :end_excl"
)


def _anchor_dates(conn) -> dict[str, date | None]:
    """Every live liquid account name -> its FIRST Adjustment date, or None
    when never adjusted. The first anchor is the right one: once a real
    statement balance has been recorded for an account, the live ledger from
    that point forward is authoritative (D-03)."""
    names = [r[0] for r in conn.execute(text(_LIQUID_ACCOUNT_NAMES_SQL)).fetchall()]
    anchors: dict[str, date | None] = {name: None for name in names}
    for name, adj_date in conn.execute(text(_ADJUSTMENT_DATES_SQL)).fetchall():
        if anchors.get(name) is None:
            anchors[name] = adj_date
    return anchors


def _liquid_anchor(anchors: dict[str, date | None]) -> date | None:
    """MAX over all live liquid accounts' anchors, or None if any liquid
    account has no anchor at all — the point at which the entire liquid side
    is reconciled to statement truth. Used for correction labels with no
    live account (e.g. "Investements")."""
    values = list(anchors.values())
    if not values or any(v is None for v in values):
        return None
    return max(values)


def _regime_cutoff(anchors: dict[str, date | None]) -> date | None:
    """Upper bound of the 23.1 "ledger_plus_corrections" regime: MAX over
    the anchors that EXIST, or None when no liquid account has ever been
    adjusted. Unlike `_liquid_anchor`, one unanchored newcomer (e.g. an
    account created by `apply_add_account` or the importer) never turns
    "no anchor" into "relaxed forever" -- that newcomer stays on the D-07
    path and gaps with `no_opening_anchor`, exactly as before 23.1 (CR-01)."""
    known = [d for d in anchors.values() if d is not None]
    return max(known) if known else None


def reconstructed_liquid_by_month(months: int = 72, *, conn=None) -> list[dict]:
    """Corrected per-account, per-month liquid balances.

    For each month bucket, live ledger balance plus recovered legs, gated by
    D-03: a label's recovered legs contribute only strictly before that
    label's anchor date; on and after it, the correction contributes exactly
    Decimal("0.00") because the anchoring adjustment already absorbed every
    missing leg. `by_account` keys are account NAMES (D-15); every live
    liquid account name and every distinct correction label appear, even
    when their contribution is zero. Deliberately NOT honesty-gated — this
    is the raw arithmetic the additive-restoration invariant is asserted
    against.
    """
    owns_conn = conn is None
    conn = conn or engine.connect()
    try:
        buckets = [
            {"month": r[0], "end_excl": r[1]}
            for r in conn.execute(text(_MONTH_SQL), {"months": months}).fetchall()
        ]
        anchors = _anchor_dates(conn)
        liquid_anchor = _liquid_anchor(anchors)
        live_names = set(anchors.keys())

        results: list[dict] = []
        for bucket in buckets:
            end_excl = bucket["end_excl"]
            month_end = end_excl - timedelta(days=1)

            live_by_account = {
                name: Decimal(str(total))
                for name, total in conn.execute(
                    text(_LIVE_BY_ACCOUNT_SQL), {"end_excl": end_excl}
                ).fetchall()
            }
            recovered_by_label = {
                label: Decimal(str(total))
                for label, total in conn.execute(
                    text(_RECOVERED_BY_LABEL_SQL), {"source": _SOURCE, "end_excl": end_excl}
                ).fetchall()
            }

            # Every live liquid account name appears even with zero rows in
            # this bucket (e.g. an account opened after end_excl), and every
            # distinct correction label appears even with zero recovered
            # legs in this bucket (D-15) — the GROUP BY result alone omits
            # both cases.
            labels = live_names | set(live_by_account) | set(recovered_by_label)
            by_account: dict[str, Decimal] = {}
            for label in labels:
                live_value = live_by_account.get(label, Decimal("0.00"))
                if label in live_names:
                    account_anchor = anchors.get(label)
                    gate_open = account_anchor is None or month_end < account_anchor
                else:
                    gate_open = liquid_anchor is None or month_end < liquid_anchor
                recovered_value = (
                    recovered_by_label.get(label, Decimal("0.00")) if gate_open else Decimal("0.00")
                )
                by_account[label] = (live_value + recovered_value).quantize(Decimal("0.01"))

            results.append(
                {
                    "month": bucket["month"],
                    "end_excl": end_excl,
                    "by_account": by_account,
                    "total": sum(by_account.values(), Decimal("0.00")),
                }
            )
        return results
    finally:
        if owns_conn:
            conn.close()


# This module exposes no FastAPI route, is not registered in
# backend/tools.py's TOOLS dict, and is not registered as a LlamaIndex
# FunctionTool in backend/query.py (D-14). Phase 22 composes it; Phase 23
# renders it.


def _adjustment_windows(conn) -> dict[str, list[tuple[date, date | None]]]:
    """For each live liquid account name, the ordered Adjustment dates
    a1..an become windows (a1, a2), (a2, a3), ..., (an, None) — the final
    entry with a None upper bound is the still-open window. An account with
    no adjustments maps to an empty list."""
    names = [r[0] for r in conn.execute(text(_LIQUID_ACCOUNT_NAMES_SQL)).fetchall()]
    dates_by_account: dict[str, list[date]] = {name: [] for name in names}
    for name, adj_date in conn.execute(text(_ADJUSTMENT_DATES_SQL)).fetchall():
        dates_by_account.setdefault(name, []).append(adj_date)

    windows: dict[str, list[tuple[date, date | None]]] = {}
    for name, dates in dates_by_account.items():
        account_windows: list[tuple[date, date | None]] = []
        for i, lo in enumerate(dates):
            hi = dates[i + 1] if i + 1 < len(dates) else None
            account_windows.append((lo, hi))
        windows[name] = account_windows
    return windows


def _honesty(
    month: str,
    month_end: date,
    windows: dict[str, list[tuple[date, date | None]]],
    current_month: str,
    earliest_liquid_tx: date | None,
) -> tuple[bool, str | None]:
    """D-07's per-adjustment-window honesty model, exactly as specified.

    A window (lo, hi) contains month_end when lo < month_end <= hi for a
    closed window, or lo < month_end for the open final window. The boundary
    is deliberately half-open on the left: an adjustment dated exactly on
    the month-end does not itself make that month honest.

    Precedence is exactly pre_ledger, then no_opening_anchor, then
    no_closing_anchor. Never emit free prose — the returned string is always
    a member of GAP_REASONS; Phase 23 captions the gap from this enum.

    Explicitly rejects the reverted single-anchor model: honesty is never
    "the month is after the earliest adjustment anywhere on the liquid
    side" — every liquid account's own window must independently contain
    month_end.
    """
    if earliest_liquid_tx is None or month_end < earliest_liquid_tx:
        return False, "pre_ledger"

    for account_windows in windows.values():
        opened = any(lo < month_end for lo, _hi in account_windows)
        if not opened:
            return False, "no_opening_anchor"

    for account_windows in windows.values():
        contained = False
        for lo, hi in account_windows:
            if hi is None:
                if lo < month_end:
                    contained = contained or (month == current_month)
            else:
                if lo < month_end <= hi:
                    contained = True
        if not contained:
            return False, "no_closing_anchor"

    return True, None


def monthly_liquid_series(months: int = 72, *, conn=None) -> dict:
    """The D-15 output shape: corrected monthly liquid series with per-month
    honesty. When `honest` is False, `liquid_by_account`/`liquid_total` are
    both None and `gap_reason` is one of GAP_REASONS — the engine refuses to
    emit an unverified number (D-09). No interpolation, no carry-forward, no
    confidence band; the residual is reported once in prose in the phase
    summary and the months it covers stay gaps.

    D-05 (Phase 23.1): every month on or after the ledger start whose
    month-end is on or before the `_regime_cutoff` date (MAX over the
    anchors that exist) is honest on a
    "ledger_plus_corrections" basis — the raw `by_account` map restricted to
    LIVE liquid account names (never `raw["total"]`, which still carries the
    "Investements" label and would double-count it against the investment
    half, research Pitfall 1). Months on or after the anchor keep today's
    D-07 window rule unchanged; with no anchor anywhere there is no relaxed
    regime at all. `valuation_basis` is None for both the
    pre-ledger gap and the D-07 path; it is only ever
    "ledger_plus_corrections" for the new pre-anchor regime.
    """
    owns_conn = conn is None
    conn = conn or engine.connect()
    try:
        raw_rows = reconstructed_liquid_by_month(months=months, conn=conn)
        windows = _adjustment_windows(conn)
        earliest_liquid_tx = conn.execute(text(_EARLIEST_LIQUID_TX_SQL)).scalar()
        current_month = date.today().strftime("%Y-%m")
        anchors = _anchor_dates(conn)
        regime_cutoff = _regime_cutoff(anchors)
        live_names = set(anchors.keys())

        rows: list[dict] = []
        gap_counts: dict[str, int] = {}
        honest_months: list[str] = []
        for raw in raw_rows:
            month = raw["month"]
            month_end = raw["end_excl"] - timedelta(days=1)

            is_pre_ledger = earliest_liquid_tx is None or month_end < earliest_liquid_tx
            # `<=`, not `<` (WR-04): a cutoff dated exactly on a month-end
            # would otherwise fall to D-07, whose half-open `lo < month_end`
            # rule gaps it as `no_opening_anchor` even though the D-03 gate
            # has already closed and the balance is fully anchored.
            pre_anchor = (
                not is_pre_ledger and regime_cutoff is not None and month_end <= regime_cutoff
            )

            if pre_anchor:
                liquid_by_account = {
                    name: value for name, value in raw["by_account"].items() if name in live_names
                }
                rows.append(
                    {
                        "month": month,
                        "liquid_by_account": liquid_by_account,
                        "liquid_total": sum(liquid_by_account.values(), Decimal("0.00")),
                        "valuation_basis": "ledger_plus_corrections",
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)
                continue

            honest, gap_reason = _honesty(month, month_end, windows, current_month, earliest_liquid_tx)
            if honest:
                rows.append(
                    {
                        "month": month,
                        "liquid_by_account": raw["by_account"],
                        "liquid_total": raw["total"],
                        "valuation_basis": None,
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)
            else:
                rows.append(
                    {
                        "month": month,
                        "liquid_by_account": None,
                        "liquid_total": None,
                        "valuation_basis": None,
                        "honest": False,
                        "gap_reason": gap_reason,
                    }
                )
                gap_counts[gap_reason] = gap_counts.get(gap_reason, 0) + 1

        return {
            "tool": "reconstructed_liquid_series",
            "rows": rows,
            "honest_months": honest_months,
            "gap_summary": gap_counts,
        }
    finally:
        if owns_conn:
            conn.close()


def liquid_drift_estimate(*, conn=None) -> Decimal | None:
    """D-06's computed anchor-day residual, never hard-coded -- an UPPER
    bound on how far pre-anchor liquid balances may be overstated.

    Per anchored live liquid account: the recovered corrections for that
    account dated up to its own anchor day (what the
    "ledger_plus_corrections" regime adds on top of the live ledger) minus
    the Adjustment-category transactions on that account up to the same day
    (the statement truth that replaced them). A positive residual means that
    account's pre-anchor months are overstated. Only the POSITIVE residuals
    are summed (WR-01): netting an understated account against an overstated
    one would publish an "up to" figure smaller than a single account's own
    overstatement (one overstated account can exceed the net figure).

    Each account is bounded at its own anchor day (`end_excl = anchor + 1
    day`): later adjustments are unrelated to the archival residual and must
    never move this figure. Unanchored accounts contribute nothing -- there
    is no statement truth to measure them against. The result is the D-06
    caption input -- recomputed on every call, never persisted, and reported
    once as a single headline figure, never spread across months (Phase 20's
    residual rule).

    Returns None when `_regime_cutoff` returns None: with no anchor on any
    live liquid account there is nothing to measure against.
    """
    owns_conn = conn is None
    conn = conn or engine.connect()
    try:
        anchors = _anchor_dates(conn)
        if _regime_cutoff(anchors) is None:
            return None
        bound = Decimal("0.00")
        for name, anchor in anchors.items():
            if anchor is None:
                continue
            params = {"source": _SOURCE, "name": name, "end_excl": anchor + timedelta(days=1)}
            corrections = Decimal(str(conn.execute(text(_ACCOUNT_CORRECTIONS_SQL), params).scalar()))
            adjustments = Decimal(
                str(conn.execute(text(_ACCOUNT_ADJUSTMENT_TOTAL_SQL), params).scalar())
            )
            bound += max(corrections - adjustments, Decimal("0.00"))
        return bound.quantize(Decimal("0.01"))
    finally:
        if owns_conn:
            conn.close()
