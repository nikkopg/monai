---
status: partial
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
source: [18-VERIFICATION.md]
started: 2026-08-17T16:35:00+07:00
updated: 2026-08-17T16:35:00+07:00
---

## Current Test

3. Funded buy/sell live write (XFER-03) — FAILED: critical data-loss bug (see below)

## Prerequisite

The `monai-frontend` container currently on port 3001 was built 2026-08-02 and does NOT
contain any phase-18 code. Rebuild before testing, or every test below will read as failed:

```bash
docker compose up -d --build
```

## Tests

### 1. Balance adjustment live write (ACCT-02)
test: Against docker-compose (real Postgres), open a liquid account row in Cashflow → Accounts, use "Adjust balance" to set a new target balance, and submit.
expected: A new "Adjustment" transaction record appears in the ledger and the account's derived balance on the summary reconciles to the entered target — confirming `apply_add_balance_adjustment`'s fresh-unfiltered-SUM delta computation against real data, not just the route-mocked e2e fixture.
result: PASS (2026-09-03, live against docker-compose on :3000 with rebuilt Phase-18 image; WR-04 liquid-only gating + WR-03 disabled-submit fixes also confirmed)

### 2. Liquid→investment deposit live write (XFER-02)
test: Against docker-compose, open a platform detail page, click "Deposit cash", pick a real liquid account, and submit a deposit.
expected: A Deposit portfolio event appears on the platform ledger AND the chosen liquid account's balance is debited by the same amount — one atomic dual-leg write via `apply_add_investment_transfer`.
result: PASS (2026-09-03, live on :3000; CR-03 IDR dropdown + WR-07 no-blank-refetch also confirmed)

### 3. Funded buy/sell live write (XFER-03)
test: Against docker-compose, open the platform detail "Buy & Sell" tab, use "+ Log event" to submit a funded Buy (with a Funding account chosen), then a funded Sell.
expected: Buy debits the chosen liquid account and records the holding/event in one atomic commit; Sell credits it back. The persisted `cash_amount` matches what was submitted (default qty×price or edited value).
result: FAIL (2026-09-03, live on :3000) — CRITICAL DATA LOSS. A funded buy on an existing position REPLACES the holding quantity instead of summing it.

  Root cause (NOT a Phase-18 UI bug — latent backend data-model bug exposed by the new UI):
  `backend/portfolio.py:recompute_holding_from_events` rebuilds a holding's quantity purely
  from `portfolio_events` (starts qty=0, accumulates only events). But legacy holdings
  (Phase 5/7 era) were created via direct `holding add` with NO backing `buy` events — only
  5 events exist for 10+ holdings. So the first event-based write (Phase 18 funded buy/sell)
  recomputes the position from just the new event and overwrites the prior quantity.

  Confirmed data loss on THIS UAT buy:
  - Danamas Pasti (holding id 289, platform 67): original qty 1691.9681 @ 5046.3711
    (recoverable from audit_log id 640, "holding add", 2026-07-11).
  - UAT funded buy added 140.1614 @ 5350.974 (portfolio_event 3237 / audit_log 6309).
  - Correct result: 1691.9681 + 140.1614 = 1832.1295. Actual stored: 140.16140000 — the
    1691.9681 prior units were wiped.
  - Every legacy holding without backing events is a landmine for funded buy/sell.

  Second finding (feature gap, out of Phase-18 scope): no UI affordance to edit/delete a
  logged buy/sell event from the platform detail page.

  Recovery available: audit_log preserves the original holding state; a backfilled opening
  event + recompute restores the correct summed position.

  RECOVERY APPLIED (2026-09-03, user-approved): inserted synthetic opening buy event
  (1691.9681 @ 5046.3711, 2026-07-11, IDR, mutual_fund) via apply_add_portfolio_event +
  recompute. Danamas Pasti holding 289 restored: qty 140.1614 → 1832.1295, avg_cost
  5350.97 → 5069.67, now backed by 2 events (won't re-clobber). Committed + audit-logged.

  Root-cause fix routed to /gsd-debug: backfill opening buy events for ALL event-less
  legacy holdings, with row/sum parity checks.

  ROOT-CAUSE FIX APPLIED (2026-09-03, debug session recompute-clobbers-holdings, commit
  57010f5): (1) alembic migration 012 backfilled 1 opening buy event for each of 11
  event-less holdings — opening lot sourced from the current holding row so NO displayed
  value changed, parity-asserted with rollback; (2) writes.apply_add_portfolio_event now
  guards against inserting an event on a non-zero holding with zero backing events;
  (3) stray phantom event 216 (BTC/64) deleted per user decision (holding stays 0.00682806,
  now cleanly 1-event backed). Verified live: alembic head c2a9f1e6b8d3, 0 non-zero holdings
  lacking events, all 15 holdings event-backed with unchanged quantities, 20/20
  test_portfolio.py pass. Funded buy/sell on existing positions is now SAFE (sums, not
  replaces). Recommend re-running this UAT test live to confirm end-to-end.

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

## Notes

All three items were flagged open in all three plans' own `<verification>` sections and in
each SUMMARY's coverage block (`human_judgment: true`) — the phase-18 e2e suite is entirely
route-mocked by design, so it proves the UI sends the correct payload shape but never
exercises the live write path. Phase 18 is the last phase of milestone v1.2, so there is no
later phase to defer these to.

Related open item: the live DB currently has zero `type='investment'` accounts
(see `.planning/todos/pending/260817-inv-missing-investments-account.md`). Test 2 and 3
operate on platforms/holdings rather than the investment *account* row, so they are not
blocked by it — but net-worth numbers observed while testing will be skewed until it's resolved.
