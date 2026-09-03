"""backfill opening-balance buy events for event-less legacy holdings

Revision ID: c2a9f1e6b8d3
Revises: a7c3e9f2b4d1
Create Date: 2026-09-03

Data-only backfill (no schema change). Fixes recompute-clobbers-holdings: a
legacy holding created as a direct `holding add` row (Phase 5/7) has NO backing
`portfolio_events`, so `recompute_holding_from_events` rebuilds its position
from an empty ledger and the FIRST funded buy silently overwrites the opening
balance (live loss: Danamas Pasti 1691.9681 -> 140.1614, Phase 18 UAT #3).

Fix: for every holding whose event ledger does NOT already reproduce its stored
quantity because it has ZERO events, synthesize a single opening `buy` event so
the ledger reproduces the current holding exactly. After that event exists, the
runtime write-path guard (writes.apply_add_portfolio_event) makes a future
funded buy SUM rather than replace.

SOURCE OF THE OPENING LOT (important, verified live 2026-09-03):
The audit_log holding-add snapshot is used for the opening DATE + provenance,
but the opening lot's quantity/price are taken from the CURRENT holding row,
NOT the snapshot. 5 of 11 snapshots are STALE (TAO/USDT-avg/PYTH/SOL/PENGU) —
those holdings were edited via apply_edit_holding after creation. Because these
are zero-event holdings the clobber bug never fired on them, so the current row
is authoritative; using it guarantees the backfill changes no displayed number
and passes parity by construction. A holding with NO snapshot at all is SURFACED
(never fabricated) and skipped.

Scope (IDR-only, single opening buy): parity avg-cost is computed as
SUM(price*qty)/SUM(qty) over buys with FX rate 1 (fx IDR->IDR = 1). Any non-IDR
holding needing backfill is surfaced for manual handling rather than auto-lotted
(none exist today; asserted at run time).

Idempotent: selection predicate is "non-zero quantity AND zero events". After a
run each backfilled position has 1 event, so a second upgrade() selects nothing
and inserts nothing. Every insert is additionally marked in audit_log.after with
source='opening_balance_backfill_012'.

Report-only (never auto-fixed, mirrors 011's flagged-ids idiom): holdings that
HAVE events whose ledger does not reproduce the stored quantity — e.g. holding
262 (BTC/64) carries a phantom event 216 (0.00024563 @ 1956430502.30, values
matching PENGU/BTC-65 test data) making its ledger sum 0.00707369 != stored
0.00682806. That is a human decision (real second buy vs. stray event), so it is
printed and left untouched. PARITY ABORT: if any backfilled position fails to
reproduce its holding after insert, the whole migration raises and rolls back
(env.py runs online migrations in one transaction).

downgrade(): documented no-op (009/010/011 posture — backfilled data values are
left in place; there is no structural schema object to revert).
"""
from decimal import Decimal
from typing import Sequence, Union

import json

import sqlalchemy as sa
from alembic import op

revision: str = "c2a9f1e6b8d3"
down_revision: Union[str, None] = "a7c3e9f2b4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKFILL_SOURCE = "opening_balance_backfill_012"

# Positions with current qty/avg_cost + ledger aggregates. ledger_qty counts
# only buy/sell (a 'deposit'/'dividend' does not establish share quantity here,
# matching recompute_holding_from_events).
_POSITIONS_QUERY = """
    SELECT h.id, h.ticker, h.platform_id, h.quantity, h.avg_cost, h.currency,
           h.purchase_date,
           COALESCE(ev.n, 0) AS n_events,
           COALESCE(ev.buy_qty, 0) - COALESCE(ev.sell_qty, 0) AS ledger_qty
    FROM holdings h
    LEFT JOIN (
        SELECT ticker, platform_id,
               COUNT(*) AS n,
               COALESCE(SUM(quantity) FILTER (WHERE event_type = 'buy'), 0) AS buy_qty,
               COALESCE(SUM(quantity) FILTER (WHERE event_type = 'sell'), 0) AS sell_qty
        FROM portfolio_events
        GROUP BY ticker, platform_id
    ) ev ON ev.ticker = h.ticker AND ev.platform_id = h.platform_id
    ORDER BY h.platform_id, h.ticker
"""

# Original holding-add snapshot for a holding (entity_id is the holding id at
# creation). Latest wins if a holding id was ever re-added.
_SNAPSHOT_BY_HOLDING = """
    SELECT after
    FROM audit_log
    WHERE entity = 'holding' AND operation = 'add' AND entity_id = :hid
    ORDER BY id DESC
    LIMIT 1
"""

_INSERT_EVENT = """
    INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency)
    VALUES (:date, :ticker, 'buy', :qty, :price, :pid, :currency)
    RETURNING id
"""

_INSERT_AUDIT = """
    INSERT INTO audit_log (entity, entity_id, operation, before, after)
    VALUES ('portfolio_event', :evid, 'add', NULL, CAST(:after AS jsonb))
"""

# Ledger-derived qty/avg_cost for a position (IDR / rate=1 assumption).
_PARITY_QUERY = """
    SELECT
        COALESCE(SUM(quantity) FILTER (WHERE event_type = 'buy'), 0)
      - COALESCE(SUM(quantity) FILTER (WHERE event_type = 'sell'), 0) AS dqty,
        CASE WHEN COALESCE(SUM(quantity) FILTER (WHERE event_type = 'buy'), 0) > 0
             THEN SUM(price * quantity) FILTER (WHERE event_type = 'buy')
                  / SUM(quantity) FILTER (WHERE event_type = 'buy')
             ELSE 0 END AS davg
    FROM portfolio_events
    WHERE ticker = :ticker AND platform_id = :pid
"""


def _resolve_date(snapshot: dict | None, holding_purchase_date, fallback_iso: str) -> str:
    """Opening date: snapshot.purchase_date -> holding.purchase_date -> fallback."""
    if snapshot and snapshot.get("purchase_date"):
        return snapshot["purchase_date"]
    if holding_purchase_date is not None:
        return holding_purchase_date.isoformat()
    return fallback_iso


def backfill_opening_events(conn) -> dict:
    """Insert one opening `buy` event per non-zero, event-less holding so the
    ledger reproduces the current holding. Accepts a raw Connection
    (op.get_bind()) or a Session (tests). Idempotent. Aborts (raises) on any
    parity mismatch. Returns a report dict.
    """
    rows = list(conn.execute(sa.text(_POSITIONS_QUERY)))

    backfilled: list[dict] = []
    skipped_no_snapshot: list[dict] = []
    anomalies: list[dict] = []

    for r in rows:
        qty = Decimal(str(r.quantity))
        ledger_qty = Decimal(str(r.ledger_qty))

        # Report-only: a position that HAS events but whose ledger does not
        # reproduce the stored qty (e.g. holding 262 phantom event). Never
        # auto-fixed — a human decides. Rounded to holdings' 8-dp precision.
        if r.n_events > 0 and ledger_qty.quantize(Decimal("1.00000000")) != qty.quantize(Decimal("1.00000000")):
            anomalies.append({
                "holding_id": r.id, "ticker": r.ticker, "platform_id": r.platform_id,
                "stored_qty": str(qty), "ledger_qty": str(ledger_qty),
            })
            continue

        # Only event-less, non-zero holdings need an opening lot.
        if r.n_events > 0 or qty == 0:
            continue

        if (r.currency or "IDR") != "IDR":
            # Parity math below assumes rate=1; surface non-IDR rather than
            # auto-lot with a possibly-wrong cost basis.
            skipped_no_snapshot.append({
                "holding_id": r.id, "ticker": r.ticker, "platform_id": r.platform_id,
                "reason": f"non-IDR currency {r.currency} — manual backfill required",
            })
            continue

        snap_row = conn.execute(sa.text(_SNAPSHOT_BY_HOLDING), {"hid": r.id}).first()
        snapshot = snap_row[0] if snap_row is not None else None
        if snapshot is None:
            # No provenance — surface, never fabricate a lot.
            skipped_no_snapshot.append({
                "holding_id": r.id, "ticker": r.ticker, "platform_id": r.platform_id,
                "reason": "no audit_log holding-add snapshot",
            })
            continue

        opening_date = _resolve_date(snapshot, r.purchase_date, "2026-07-11")
        price = Decimal(str(r.avg_cost))  # current row is authoritative (see docstring)

        evid = conn.execute(sa.text(_INSERT_EVENT), {
            "date": opening_date, "ticker": r.ticker, "qty": qty, "price": price,
            "pid": r.platform_id, "currency": "IDR",
        }).scalar()
        conn.execute(sa.text(_INSERT_AUDIT), {
            "evid": evid,
            "after": json.dumps({
                "date": opening_date, "ticker": r.ticker, "event_type": "buy",
                "quantity": str(qty), "price": str(price), "platform_id": r.platform_id,
                "currency": "IDR", "source": _BACKFILL_SOURCE,
            }),
        })
        backfilled.append({
            "holding_id": r.id, "ticker": r.ticker, "platform_id": r.platform_id,
            "event_id": evid, "qty": str(qty), "price": str(price), "date": opening_date,
        })

    # PARITY: every backfilled position's ledger must now reproduce its holding.
    for b in backfilled:
        p = conn.execute(sa.text(_PARITY_QUERY), {"ticker": b["ticker"], "pid": b["platform_id"]}).first()
        dqty = Decimal(str(p.dqty)).quantize(Decimal("1.00000000"))
        davg = Decimal(str(p.davg)).quantize(Decimal("1.00"))
        want_qty = Decimal(b["qty"]).quantize(Decimal("1.00000000"))
        want_avg = Decimal(b["price"]).quantize(Decimal("1.00"))
        if dqty != want_qty or davg != want_avg:
            raise RuntimeError(
                "Opening-balance backfill PARITY ABORT for holding "
                f"{b['holding_id']} ({b['ticker']}/{b['platform_id']}): ledger "
                f"derived qty={dqty} avg={davg} but holding wants qty={want_qty} "
                f"avg={want_avg}. Rolling back."
            )

    print(
        f"Opening-balance backfill 012: {len(backfilled)} opening events inserted; "
        f"{len(skipped_no_snapshot)} surfaced (no snapshot / non-IDR); "
        f"{len(anomalies)} ledger anomalies flagged (report-only, never auto-fixed)."
    )
    if skipped_no_snapshot:
        print(f"  SURFACED (manual): {skipped_no_snapshot}")
    if anomalies:
        print(f"  ANOMALIES (manual decision, e.g. phantom event): {anomalies}")

    return {
        "backfilled": backfilled,
        "skipped_no_snapshot": skipped_no_snapshot,
        "anomalies": anomalies,
    }


def upgrade() -> None:
    backfill_opening_events(op.get_bind())


def downgrade() -> None:
    # No-op by design — see module docstring (009/010/011 downgrade posture).
    # Synthesized opening events are data, not schema; they are left in place.
    pass
