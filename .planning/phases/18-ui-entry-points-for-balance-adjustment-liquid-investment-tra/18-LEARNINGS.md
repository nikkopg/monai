---
phase: 18
phase_name: "ui-entry-points-for-balance-adjustment-liquid-investment-tra"
project: "monai"
generated: "2026-09-05"
counts:
  decisions: 5
  lessons: 5
  patterns: 5
  surprises: 4
missing_artifacts: []
---

# Phase 18 Learnings: UI entry points for balance adjustment, liquid↔investment transfer, funded buy/sell

## Decisions

### Balance adjustment = fresh unfiltered SUM delta, tagged category='Adjustment' + is_transfer=True
The "Adjust balance" UI submits an unsigned target; the backend recomputes the delta from a fresh, dedicated, UNFILTERED `SUM(amount)` (never `account_balances`, which excludes is_transfer rows). The adjustment row is `category='Adjustment'` AND `is_transfer=True` — is_transfer is the only lever that keeps a row out of cashflow totals.

**Rationale:** guarantees the derived balance reconciles exactly to the entered target against live data, not a mocked fixture.
**Source:** 18-01-SUMMARY.md, 18-REVIEW.md

### Funded buy/sell is one atomic commit: cash leg debits the funding account + portfolio event
`apply_add_funded_buy/_sell` writes the liquid cash leg (is_transfer=True, category='Investment') and the buy/sell PortfolioEvent under one commit boundary; the event triggers `recompute_holding_from_events` internally, never a hand-rolled holding update.

**Rationale:** money-movement must be atomic and pass through the shared mutation layer, not ad-hoc SQL.
**Source:** 18-01-SUMMARY.md, 18-PATTERNS.md

### Deposit currency constrained to an IDR `<select>` (CR-03 fix)
The liquid→investment deposit's Currency was a free-text input posted verbatim into both the Transaction and the CASH-sentinel Holding; a typo (`Rp`, `Rupiah`) makes `fx.get_rate` return None and the deposit vanishes from net worth. Changed to a locked IDR dropdown.

**Rationale:** never take free text for a money-classifying field; match the project's single-currency (IDR) constraint by construction.
**Source:** 18-REVIEW.md (CR-03)

### Net-worth line on the trend chart — built, then reverted
A net-worth line was added to the cashflow trend chart (backend `net_worth_trend` + endpoint + frontend line) but reverted (commit bc4c02c) after the historical values proved un-honest (see Lessons). Decision: historical net worth cannot be shown from monai's current data; the correct current figure stays on the hero card; a proper reconstruction is deferred to a new phase.

**Rationale:** "never fabricate a number" — a known-wrong historical line is worse than none.
**Source:** STATE.md quick-task log, this session

### WR-09 name-keyed account resolution left as UI-only; full id-based fix deferred to backend
Deposit/adjust/funded-buy send an account NAME resolved server-side by `_get_or_create_account`; a rename/delete between modal-mount and submit can create a phantom account. Fully closing it needs backend id-based resolution or reject-unknown-name — out of Phase 18's UI-only scope, so `ponytail:` markers were left at the three sites.

**Rationale:** respect the phase's UI-only boundary; don't silently expand into backend changes.
**Source:** 18-REVIEW.md (WR-09)

## Lessons

### recompute_holding_from_events silently clobbers legacy holdings that have no backing events (live data loss)
A funded buy on a legacy holding (created directly, no `portfolio_events`) made `recompute_holding_from_events` rebuild the position from just the one new event — wiping the prior quantity. UAT #3 destroyed 1691.9681 units of Danamas Pasti. Root cause + fix: alembic migration 012 backfills opening buy events for all 11 event-less holdings, plus a write-path guard so a non-zero holding with zero events can never be silently overwritten again.

**Context:** the bug was latent since the Phase 5/7 event-sourcing model; Phase 18's funded-buy UI was the first thing to trigger it. Recovered from `audit_log` holding-add snapshots.
**Source:** 18-HUMAN-UAT.md (test 3), debug session recompute-clobbers-holdings, memory [[recompute-clobbers-eventless-holdings]]

### Historical net worth is not reconstructable from monai's ledger — the Wallet import dropped an entire account
While building the net-worth line, BCA was found ~150M too high for months. Cause: the original Wallet import silently dropped the "Investements" account and its BCA→Investements transfer legs, so money moved to investments still showed as sitting in BCA. The Sep-3 balance adjustments were patching over this. The truth lives in the Wallet CSV export (which has the Investements account + transfers).

**Context:** led directly to a new planned phase (net-worth-history reconstruction from the export). BCA true balance in the export = ~75M (Jun 2026), not 274M.
**Source:** this session's ledger audit + report_2026-06-20 Wallet export, memory [[networth-history-needs-adjustment-anchor]]

### Code review's critical findings sat on the exact paths live UAT would exercise
The 3 CRITICALs (stale-response race rendering the wrong platform's money; funded buy booked one day early before 07:00 WIB; unvalidated currency zeroing a deposit) were on the deposit/funded-buy paths UAT walks. Fixing review findings BEFORE live UAT avoided testing known-broken code.

**Context:** all 9 phase-18 e2e specs were GREEN yet three criticals shipped — green e2e ≠ contract-correct.
**Source:** 18-REVIEW.md, 18-VERIFICATION.md

### Mocked e2e can pass while the real write is broken
All 9 phase-18 Playwright specs passed (route-mocked), but the clobber bug only surfaced against real Postgres in live UAT. Route mocks validate the request shape, not the backend's effect on real data.

**Context:** the phase's own evidence (9/9 GREEN) did not catch a data-loss bug.
**Source:** 18-HUMAN-UAT.md vs 18-VERIFICATION.md

### `datetime-local` → toISOString() books early-morning trades a day early
`new Date(date).toISOString().slice(0,10)` converts a local wall-clock to UTC; in WIB (UTC+7) any time before 07:00 slices to the previous calendar day, mis-bucketing both the cash leg and the portfolio event.

**Context:** the file already had `toLocalDatetimeInputValue` warning about this exact hazard, but the submit path didn't use its inverse.
**Source:** 18-REVIEW.md (CR-02)

## Patterns

### Recover clobbered/lost financial data from audit_log
`audit_log` (entity='holding'/'account', operation='add') preserves the original `after` snapshot. A wiped holding was restored by backfilling a synthetic opening buy event from audit_log id 640; the same source can recover other lost state.

**When to use:** any time a derived value was overwritten/lost and you need the pre-mutation truth. Note `audit_log` is singular; recompute's own upsert writes NO audit row.
**Source:** debug session recompute-clobbers-holdings

### Migration-grade backfill with per-row parity assertions + rollback
Migration 012 synthesizes opening events sourced from the CURRENT holding row (so no displayed value changes), then asserts each position's post-recompute qty/avg_cost matches, aborting the whole migration on any mismatch. Idempotent via a "non-zero AND zero-events" predicate.

**When to use:** any data-backfill over real financial data — parity-assert and fail-closed, matching migrations 010/011 discipline.
**Source:** debug session, alembic/versions/012

### Live UAT against real Postgres, gated on a fresh build
The stale docker container (built before the phase) made every UAT test read as failed until rebuilt. Confirm the running image's build time predates vs postdates the code before trusting UAT results.

**When to use:** every human/live UAT — verify deploy first. monai frontend serves on :3001 (a different app squats on :3000).
**Source:** 18-HUMAN-UAT.md prerequisite, memory [[deploy-requires-rebuild]]

### One shared api helper module (extractDetail/fmtPlain) instead of copy-paste
`extractDetail` was copy-pasted 4× and had diverged exactly where it broke (WR-02: Pydantic 422 array rendered as `[object Object]`). Consolidated into `ui/app/lib/api.ts`.

**When to use:** when the same parse/format helper appears in 3+ components — the divergence IS the bug surface.
**Source:** 18-REVIEW.md (WR-12)

### Defense-in-depth guard at the shared mutation function, not per-caller
The clobber fix added ONE guard in `apply_add_portfolio_event` (refuse a new event on a non-zero, event-less holding), covering every caller (REST, agent, MCP) at once rather than patching each entry point.

**When to use:** root-cause fixes for a class of bug — guard where all callers route through.
**Source:** debug session, backend/writes.py

## Surprises

### A phase can trigger a years-old latent bug
The recompute-clobber bug had existed since the Phase 5/7 event-sourcing model but never fired until Phase 18's funded-buy UI became the first event-based write against legacy holdings. New UI surfaced old data-model debt as live data loss.

**Impact:** UAT #3 destroyed real holdings; required a full debug session + migration mid-close.
**Source:** debug session recompute-clobbers-holdings

### monai's investment history is only ~2 months deep
`portfolio_value_history` snapshots only began 2026-07-11, and there are no historical prices — so even the investment half of net worth has no multi-year history. This, plus the liquid-ledger drift, is why net worth over the years isn't derivable from monai's current data.

**Impact:** killed the net-worth line as first built; spawned a new reconstruction phase sourced from the Wallet export.
**Source:** this session's investigation

### The frontend serves on :3001; :3000 is a different app
Live UAT initially hit `http://localhost:3000`, which is an unrelated "Old Legs" app; monai is on :3001. The earlier WR-08 "stale :3001" note had inverted after the rebuild.

**Impact:** brief mis-direction during UAT setup; corrected once image build times were checked.
**Source:** 18-HUMAN-UAT.md

### The clobber recovery mechanism doubled as the fix
Backfilling an opening event to RECOVER Danamas Pasti was the same operation that, generalized to all event-less holdings (migration 012), PREVENTS recurrence. Recovery and root-cause fix were one mechanism.

**Impact:** one design (opening-event backfill) solved both the immediate data loss and the systemic class.
**Source:** debug session, alembic/versions/012
