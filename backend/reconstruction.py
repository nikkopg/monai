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
`backend/tests_live_audit/test_reconstruction.py`, never eyeballed.

Each month's liquid point is the plain per-account sum of that month's
records (the raw ledger plus recovered corrections for the LIVE liquid
accounts), on a "ledger_plus_corrections" basis. No adjustment has to exist
for a month to show a number; a month with no records equals the previous
month by the cumulative sum. The "Investements" label is excluded because it
is the investment half's concern, not the liquid half's (D-01) -- see
`liquid_drift_estimate`'s Pitfall-1 guard in the test file. The two remaining
gaps are a month before the first record (`pre_ledger`) and a month whose
needed FX rate is unobtainable (`fx_unavailable`). The known archival residual
the corrections leave on the table is disclosed once via
`liquid_drift_estimate()`, never smoothed into the monthly figures.

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

from backend import fx
from backend.db import engine

_SOURCE = "corrections_260620"
GAP_REASONS = ("pre_ledger", "fx_unavailable")

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

_LIQUID_CURRENCY_SQL = "SELECT name, currency FROM accounts WHERE type = 'liquid'"

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


def _needs_rate(by_account: dict, currency_by_name: dict) -> bool:
    return any(
        currency_by_name.get(name, fx.BASE) != fx.BASE and value != 0
        for name, value in by_account.items()
    )


def _to_idr_by_account(by_account: dict, currency_by_name: dict, rate: Decimal | None) -> dict | None:
    """Per-account values in IDR. IDR (and correction labels, which default to
    IDR) and zero values pass through; a non-zero USD value is converted with
    `fx.at_rate`, or the whole map is None when that needs a rate we lack
    (D-14, D-15). Native amounts are never added across currencies."""
    out: dict = {}
    for name, value in by_account.items():
        if currency_by_name.get(name, fx.BASE) == fx.BASE or value == 0:
            out[name] = value
        elif rate is None:
            return None
        else:
            out[name] = fx.at_rate(value, rate)
    return out


def monthly_liquid_series(months: int = 72, *, conn=None) -> dict:
    """The D-15 output shape: the monthly liquid series, each point the plain
    per-account sum of that month's records. When `honest` is False,
    `liquid_by_account`/`liquid_total` are both None and `gap_reason` is one of
    GAP_REASONS (before the first liquid record, or no FX rate) -- the engine
    refuses to emit an unverified number (D-09).

    A month with no records equals the previous month because each balance is
    a cumulative sum. The map is restricted to LIVE liquid account names in
    every month (never `raw["total"]`, which still carries the "Investements"
    label and would double-count it against the investment half, research
    Pitfall 1). Recovered corrections count only before an account's first
    Adjustment (D-03, applied in `reconstructed_liquid_by_month`). A gap is
    never carried over.

    Figures are IDR (Phase 43): each non-IDR account's native balance is
    converted on its own, past months at that month-end's rate (7-day
    weekend fallback), the newest month at today's rate, and only then
    added. A month whose needed rate is missing is a gap with reason
    `fx_unavailable`.
    """
    owns_conn = conn is None
    conn = conn or engine.connect()
    try:
        raw_rows = reconstructed_liquid_by_month(months=months, conn=conn)
        earliest_liquid_tx = conn.execute(text(_EARLIEST_LIQUID_TX_SQL)).scalar()
        currency_by_name = dict(conn.execute(text(_LIQUID_CURRENCY_SQL)).fetchall())

        # Pass 1: native arithmetic. planned entries are
        # (month, month_end, native by_account or None for a gap, basis, gap_reason).
        planned: list[tuple] = []
        for raw in raw_rows:
            month_end = raw["end_excl"] - timedelta(days=1)
            if earliest_liquid_tx is None or month_end < earliest_liquid_tx:
                planned.append((raw["month"], month_end, None, None, "pre_ledger"))
                continue
            by_account = {n: v for n, v in raw["by_account"].items() if n in currency_by_name}
            planned.append((raw["month"], month_end, by_account, "ledger_plus_corrections", None))

        # Rates (D-14, D-24): past months use the month-end rate (7-day weekend
        # fallback) from fx's cache after at most one range fill; the newest
        # month uses today's rate.
        last = len(planned) - 1
        missing = [
            me for i, (_m, me, ba, _b, _g) in enumerate(planned)
            if ba is not None and i != last and _needs_rate(ba, currency_by_name)
            and fx.cached_rate_within(conn, "USD", me) is None
        ]
        if missing:
            # Fills fx's rate cache on fx's own session; this module still
            # never writes ledger rows.
            start, end = min(missing) - timedelta(days=7), min(max(missing), fx._jakarta_today() - timedelta(days=1))
            if start <= end:
                fx._store_range("USD", fx.BASE, start, end)
        spot_rate = None
        if last >= 0 and planned[last][2] is not None and _needs_rate(planned[last][2], currency_by_name):
            try:
                spot_rate = fx.spot_stale_ok("USD", conn)[0]
            except fx.FxUnavailable:
                pass

        # Pass 2: convert per account, then add (the only cross-account sum, now in IDR).
        rows: list[dict] = []
        gap_counts: dict[str, int] = {}
        honest_months: list[str] = []
        for i, (month, month_end, by_account, basis, gap_reason) in enumerate(planned):
            if by_account is not None:
                rate = None
                if _needs_rate(by_account, currency_by_name):
                    if i == last:
                        rate = spot_rate
                    else:
                        found = fx.cached_rate_within(conn, "USD", month_end)
                        rate = found[0] if found else None
                by_account = _to_idr_by_account(by_account, currency_by_name, rate)
                if by_account is None:
                    gap_reason = "fx_unavailable"
            if by_account is None:
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
            else:
                rows.append(
                    {
                        "month": month,
                        "liquid_by_account": by_account,
                        "liquid_total": sum(by_account.values(), Decimal("0.00")),
                        "valuation_basis": basis,
                        "honest": True,
                        "gap_reason": None,
                    }
                )
                honest_months.append(month)

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
    "ledger_plus_corrections" basis adds on top of the live ledger) minus
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

    Returns None when no live liquid account has an anchor: there is nothing
    to measure against.
    """
    owns_conn = conn is None
    conn = conn or engine.connect()
    try:
        anchors = _anchor_dates(conn)
        if not any(anchors.values()):
            return None
        currency_by_name = dict(conn.execute(text(_LIQUID_CURRENCY_SQL)).fetchall())
        bound = Decimal("0.00")
        for name, anchor in anchors.items():
            # Non-IDR accounts have no archival corrections: subtracting their
            # native adjustment from IDR corrections would mix units (Pitfall 6).
            if anchor is None or currency_by_name.get(name, fx.BASE) != fx.BASE:
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
