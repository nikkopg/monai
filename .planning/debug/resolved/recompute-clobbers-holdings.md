---
slug: recompute-clobbers-holdings
status: resolved
trigger: "Funded buy/sell on a legacy holding with no backing portfolio_events wipes the prior quantity instead of summing it."
created: 2026-09-03
updated: 2026-09-03
tdd_mode: false
goal: find_and_fix
root_cause: "recompute_holding_from_events rebuilds a position purely from its (ticker, platform_id) event slice; legacy holdings created as direct 'holding add' rows had zero backing events, so the first funded buy overwrote the opening balance."
fix: "Alembic 012 backfills one opening buy event per event-less holding (opening lot from current row → no value change, parity-asserted); writes.apply_add_portfolio_event guard refuses a new event on a non-zero holding with zero events; stray phantom event 216 (BTC/64) deleted per user decision."
verification: "Live: 11 opening events inserted, 0 anomalies, alembic head c2a9f1e6b8d3; 0 non-zero holdings lacking events; all 15 holdings event-backed with unchanged quantities; 20/20 backend/tests/test_portfolio.py pass in rebuilt container."
files_changed: "alembic/versions/012_backfill_opening_events.py, backend/writes.py, backend/tests/test_portfolio.py (commit 57010f5); live data: 11 backfill events + 11 audit rows (migration), event 216 deleted + audit, Danamas Pasti opening event (earlier recovery)."
---

# Debug Session: recompute-clobbers-holdings

## Symptoms

- **Expected:** A funded buy/sell on an existing position adds to the prior quantity — the holding becomes (prior qty + new event qty) with a correct weighted avg cost.
- **Actual:** The holding quantity is REPLACED by only the new event's quantity; the prior units are silently destroyed. No error is surfaced. Violates the milestone's core promise ("never change data without the user's say-so").
- **Error messages:** None — silent data loss. Confirmed on live data: Danamas Pasti (holding 289, platform 67) went 1691.9681 → 140.1614 after a funded buy of 140.1614.
- **Timeline:** Latent since the event-sourcing model was introduced (Phase 5/7 investment subsystem). First *triggered* by Phase 18's funded buy/sell UI (HoldingModal on the platform detail "Buy & Sell" tab). Surfaced in Phase 18 live UAT #3 on 2026-09-03.
- **Reproduction:** Funded buy/sell on any holding that has no backing `portfolio_events`. `recompute_holding_from_events` (backend/portfolio.py:41) rebuilds the position from `qty=0` accumulating ONLY events for (ticker, platform_id), then upserts the holding — so a holding whose quantity was never event-backed gets overwritten by just the new event.

## Root Cause (already established with live evidence — confirm, do not re-derive)

`backend/portfolio.py:recompute_holding_from_events` treats `portfolio_events` as the sole source of truth for a position (D-01/D-02). Legacy holdings (Phase 5/7) were created as direct `holding add` rows (audit_log entity='holding', operation='add') with NO corresponding `buy` events. Live DB has ~5 events for 15 holdings. `apply_add_portfolio_event` (backend/writes.py:449) inserts the new event then calls the recompute, which rebuilds the whole position from the event slice — wiping any prior, non-event-backed quantity.

## Scope (live query, 2026-09-03) — 11 event-less holdings still at risk

| holding_id | platform_id | ticker | quantity | events |
|---|---|---|---|---|
| 263 | 64 | ETH | 0.02643210 | 0 |
| 264 | 64 | TAO | 0.53246700 | 0 |
| 265 | 64 | USDT | 57.48494355 | 0 |
| 266 | 64 | PYTH | 293.81589000 | 0 |
| 267 | 64 | SOL | 0.06514986 | 0 |
| 282 | 65 | PENGU | 4759.45959229 | 0 |
| 286 | 66 | ARB | 1099.80571000 | 0 |
| 288 | 67 | ABF ID | 92.33120000 | 0 |
| 1409 | 65 | BTC | 0.00024563 | 0 |
| 1410 | 65 | ETH | 0.25122275 | 0 |
| 1411 | 66 | GOLD | 0.66258800 | 0 |

Also FLAG for parity investigation: holding 262 (BTC, platform 64, qty 0.00682806) has 2 events (215=0.00682806, 216=0.00024563) whose sum (0.00707369) does NOT equal the holding qty — i.e. even a "2-event" holding is inconsistent. Any backfill must reconcile per-holding, not assume 0-event == the only broken case.

## Already Recovered (proof the fix mechanism works)

Danamas Pasti (holding 289, platform 67) was recovered on 2026-09-03: inserted a synthetic opening `buy` event (1691.9681 @ 5046.3711, date 2026-07-11, IDR, mutual_fund) via `apply_add_portfolio_event` + recompute → restored to 1832.1295 @ 5069.67, now backed by 2 events. Recovery source: `audit_log` id 640 (the original holding-add `after` snapshot).

## Required Fix

Migration-grade backfill (discipline like migrations 010/011, with row/sum parity assertions): for EVERY holding whose current quantity is not reproduced by its event ledger, synthesize an opening `buy` event from the original `audit_log` holding-add snapshot (qty, avg_cost→price, purchase_date→date, currency), then recompute. After backfill, assert each holding's post-recompute quantity/avg_cost matches its intended (pre-existing + any real subsequent events) value; abort/rollback on any parity mismatch. Where no audit_log holding-add snapshot exists for a holding, surface it explicitly rather than fabricating an opening lot.

Consider a guard in `recompute_holding_from_events` (or `apply_add_portfolio_event`) so a position with zero prior events can never silently overwrite a non-zero existing holding — defense-in-depth against re-introducing this class.

## Current Focus

- **status:** fixing — artifacts written, awaiting live_data_write_approval checkpoint. NO live write executed.
- **reasoning_checkpoint:**
  - hypothesis: recompute_holding_from_events rebuilds a position purely from its (ticker, platform_id) event slice; legacy holdings created as direct `holding add` rows have zero backing events, so the first funded buy makes the ledger = {that one event} and the upsert overwrites the opening balance.
  - confirming_evidence: live DB shows 11 non-zero holdings with 0 events; Danamas Pasti recovery (opening event + recompute → 1832.1295) proved the mechanism; single-IDR-buy recompute reproduces qty/avg_cost exactly (fx IDR→IDR = Decimal("1")).
  - falsification_test: a funded buy on an event-backed position that REPLACED instead of summed would disprove — regression test asserts it SUMS.
  - fix_rationale: backfill inserts a synthetic opening `buy` event per event-less holding so the ledger reproduces the CURRENT holding (no value change); a write-path guard refuses a new event on a non-zero holding with zero events so the class can never silently recur.
  - blind_spots: holding 262 (phantom event 216) and 5 stale audit snapshots — handled by using current-row values + report-only anomaly surfacing, not auto-fix.
- **KEY FINDING (snapshots stale):** audit_log holding-add snapshots for TAO(616), USDT-avg(622), PYTH(625), SOL(627), PENGU(631) do NOT match current holding values — the holdings were edited via apply_edit_holding after creation. Since these are ZERO-event holdings the clobber bug never fired on them, so the CURRENT row is authoritative. Opening lot value therefore sourced from the current holding row (qty + avg_cost), snapshot used only for purchase_date + provenance. This guarantees parity and zero data change.
- **next_action:** Present parity table + files at CHECKPOINT (live_data_write_approval); await user OK before running migration 012 against monai-db.

## Files Written (this session)

- alembic/versions/012_backfill_opening_events.py — idempotent opening-balance backfill (revision c2a9f1e6b8d3, down_revision a7c3e9f2b4d1), parity assert + report-only anomaly surfacing.
- backend/writes.py — guard in apply_add_portfolio_event (refuse new event on non-zero holding with zero events).
- backend/tests/test_portfolio.py — regression tests: funded buy SUMS; guard blocks eventless-nonzero buy.

## Evidence

- timestamp 2026-09-03: Live DB — 5 portfolio_events vs 15 holdings; 11 holdings have 0 events.
- timestamp 2026-09-03: Danamas Pasti holding 289 = 140.1614 (== lone new buy event 3237) before recovery; audit_log 640 held original 1691.9681 @ 5046.3711.
- timestamp 2026-09-03: Recovery via opening event + recompute produced 1832.1295 @ 5069.67 (== 1691.9681 + 140.1614), confirming the fix mechanism.
- timestamp 2026-09-03: Live audit_log holding-add snapshots exist for all 11 event-less holdings; 5 are STALE vs current row (TAO 616, USDT-avg 622, PYTH 625, SOL 627, PENGU 631) — holdings edited post-creation. Current row is authoritative (zero-event holdings never hit the clobber). Opening lot value therefore sourced from current holding row; snapshot supplies date/provenance only.
- timestamp 2026-09-03: Holding 262 (BTC/64) has phantom event 216 (0.00024563 @ 1956430502.30, values matching PENGU/BTC-65 test data); ledger sum 0.00707369 != stored 0.00682806. Report-only anomaly — user decision, not auto-fixed.
- timestamp 2026-09-03: Regression tests PASS in monai-backend container (funded buy SUMS 1000+140=1140; guard raises on eventless non-zero holding; existing recompute test unchanged). Container files RESTORED to baked originals afterward; live DB verified unchanged (15 holdings / 6 events / 0 test rows). NO live financial write executed.

## Eliminated

- (none yet)
