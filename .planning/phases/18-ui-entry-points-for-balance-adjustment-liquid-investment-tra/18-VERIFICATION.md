---
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
verified: 2026-08-17T16:20:00+07:00
status: human_needed
score: 15/15 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Against the docker-compose stack (real Postgres), open a liquid account row in Cashflow > Accounts, use 'Adjust balance' to set a new target balance, and submit."
    expected: "A new 'Adjustment' transaction record appears (visible in the ledger) and the account's derived balance on the summary reconciles to the entered target — confirming apply_add_balance_adjustment's fresh-SUM delta computation against real data, not just the route-mocked e2e fixture."
    why_human: "Requires a running docker-compose stack with real Postgres; funded/adjust writes are money-moving and the e2e suite is entirely route-mocked (per both 18-01-PLAN.md and 18-02-PLAN.md's <verification> sections) — it can prove the UI sends the right shape but not that the live write path reconciles."
  - test: "Against docker-compose, open a platform detail page, click 'Deposit cash', pick a real liquid account, and submit a deposit."
    expected: "A Deposit portfolio event appears on the platform ledger and the chosen liquid account's balance is debited by the same amount (dual-leg atomic write via apply_add_investment_transfer)."
    why_human: "Same route-mocked-only limitation; XFER-02's live dual-leg write was never exercised against a live backend/DB during this phase's automated verification."
  - test: "Against docker-compose, open the platform detail 'Buy & Sell' tab, use '+ Log event' to submit a funded Buy (with a Funding account chosen) and then a funded Sell."
    expected: "Buy debits the chosen liquid account and records the holding/event in one atomic commit; Sell credits it back. cash_amount matches what was submitted (default or edited)."
    why_human: "Same route-mocked-only limitation for XFER-03's dual-leg atomic write (apply_add_funded_buy/apply_add_funded_sell); not exercised against real Postgres by this phase's own verification loop."
---

# Phase 18: UI entry points for balance adjustment, liquid→investment transfer, and funded buy/sell — Verification Report

**Phase Goal:** Add UI entry points on the existing Cashflow and Investments surfaces for three money-moving operations whose backend already shipped in Phase 13 — set account balance (ACCT-02), liquid→investment transfer (XFER-02), and funded buy/sell (XFER-03). UI-only; no new backend endpoints.
**Verified:** 2026-08-17T16:20:00+07:00
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | "Adjust balance" text action on each liquid account row, between Edit and Delete (D-01) | ✓ VERIFIED | `AccountManager.tsx` L209-215: `<span role="button">` styled `tokens.color.muted3`, positioned between the Edit span (L199-208) and Delete span (L216-222) |
| 2 | Opening it shows a modal with a single "Target balance" input + live signed delta preview from `current_balance` (D-02) | ✓ VERIFIED | `AdjustBalanceModal.tsx` L100-129: single number input pre-filled with `account.current_balance`; `delta = parseFloat(target||"0") - account.current_balance` computed live |
| 3 | Preview reads exact D-07 copy (+Rp green / −Rp U+2212 terracotta / "No change…" muted, submit disabled) | ✓ VERIFIED | `AdjustBalanceModal.tsx` L112-129, L148 (`disabled={saving \|\| delta === 0}`); `balance-adjust.spec.ts` L80-88 asserts the exact rendered strings behaviorally (route-mocked, orchestrator-run GREEN) |
| 4 | Submitting POSTs exactly `{target_balance}` to `/api/accounts/{id}/adjust-balance` and calls `onChanged()` on 2xx | ✓ VERIFIED | `AdjustBalanceModal.tsx` L56-63; `balance-adjust.spec.ts` L91 `expect.poll(() => postedBody).toEqual({ target_balance: 1500000 })`; backend `main.py` L264-279 `adjust_account_balance` / `BalanceAdjustmentCreate` (schemas.py L280-288) accepts exactly `target_balance` — contract match confirmed both directions |
| 5 | 422 renders "Couldn't save adjustment: {detail}. Nothing was changed." and leaves modal open | ✓ VERIFIED | `AdjustBalanceModal.tsx` L64-67 (no `onClose()` call on the error branch) |
| 6 | Platform detail header shows a "Deposit cash" primary action near the `<h1>` (D-03) | ✓ VERIFIED | `[platformId]/page.tsx` L222-274: `btn` (primary green) rendered in the same flex row as the platform `<h1>`, above the stat-card grid |
| 7 | Modal's "From account" is a `<select>` populated from `GET /accounts` filtered `type === 'liquid'` — never free text (D-04) | ✓ VERIFIED | `DepositCashModal.tsx` L68 (`liquidAccounts = accounts.filter(a => a.type === "liquid")`), L167-179 (`<select>`); `investment-transfer.spec.ts` L103 asserts `tagName === "SELECT"` and L104 asserts only liquid names as options |
| 8 | Neutral-ink preview "Moves Rp {amount} from {account} into {platform}." before submit (D-07) | ✓ VERIFIED | `DepositCashModal.tsx` L236-240, `color: tokens.color.text` (neutral ink per UI-SPEC) |
| 9 | Submitting POSTs `{from_account, platform_id, amount, currency}` to `/api/transactions/investment-transfer` and refetches platform detail (`load()`) on 2xx | ✓ VERIFIED | `DepositCashModal.tsx` L103-118; backend `InvestmentTransferCreate` (schemas.py L237-245) accepts exactly these fields; `[platformId]/page.tsx` L558-563 mounts with `onSaved={load}`; `investment-transfer.spec.ts` L119 `toMatchObject` on the captured body |
| 10 | Zero liquid accounts shows terracotta empty-state copy + disables submit; 422 shows standard error copy | ✓ VERIFIED | `DepositCashModal.tsx` L180-184 (empty state), L94-95 (`canSubmit` gates on `liquidAccounts.length > 0`), L119-122 (422 error copy) |
| 11 | `HoldingModal` has a "Funding account" `<select>` — first option "— none (unfunded) —" (value `""`) then liquid accounts from `GET /accounts` (D-05) | ✓ VERIFIED | `HoldingModal.tsx` L324-338 |
| 12 | Choosing a funding account routes submit to `funded-buy`/`funded-sell` by event type; leaving it none keeps the unfunded `/api/portfolio-events` path unchanged (D-05) | ✓ VERIFIED | `HoldingModal.tsx` L127-163 (funded branch) vs L164-192 (unchanged unfunded branch); backend `funded-buy`/`funded-sell`/`portfolio-events` endpoints all present and untouched by this phase (git diff confirms zero backend file changes across all 7 phase-18 commits); `funded-trade.spec.ts` Test D (L236-274) asserts the unfunded escape hatch and that `funded-buy`/`funded-sell` are NOT called |
| 13 | "Cash amount (IDR)" defaults to `quantity × price`, stays independently editable; posted value is the edited value (D-06) | ✓ VERIFIED | `HoldingModal.tsx` L104-113 (resync effect gated on `!cashAmountTouched`), L339-354 (field, sets `cashAmountTouched` on edit); `funded-trade.spec.ts` Test B (L177-202): default asserted as 60,000, then edited to 65,000, posted `cash_amount` asserted `.toBe(65000)` |
| 14 | Preview reads "Debits {account} Rp {cash_amount}, +{qty} {ticker}" (green, funded Buy) / "Credits … −{qty} {ticker}" (terracotta, funded Sell) (D-07) | ✓ VERIFIED | `HoldingModal.tsx` L357-370 |
| 15 | `HoldingModal` reachable from a new "+ Log event" trigger on the platform detail "Buy & Sell" tab, pre-selecting (not locking) via `defaultPlatformId` (D-05) | ✓ VERIFIED | `[platformId]/page.tsx` L341-351 (`btnDark` trigger, only rendered when `tab === "buysell"`), L565-572 (`defaultPlatformId={Number(platformId)}`); `HoldingModal.tsx` L60-66 seeds `platformId` state from the prop but the `<select>` (L258-270) stays fully editable — pre-select, not lock |

**Score:** 15/15 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `ui/app/cashflow/AdjustBalanceModal.tsx` | New modal: target-balance input + delta preview | ✓ VERIFIED | Exists, substantive (159 lines, full submit/error/preview logic), wired (imported + mounted in `AccountManager.tsx` L7, L303-309) |
| `ui/app/cashflow/AccountManager.tsx` | Widened `Account` type + row action | ✓ VERIFIED | `Account` type includes `current_balance: number` (L23); row action wired to `setAdjustingAccount` (L211) |
| `ui/e2e/balance-adjust.spec.ts` | RED→GREEN e2e spec | ✓ VERIFIED | Exists, 2 tests, orchestrator-confirmed GREEN (2/2) |
| `ui/app/investments/DepositCashModal.tsx` | New modal: liquid-only select + preview | ✓ VERIFIED | Exists, substantive (270 lines), wired (imported + mounted in `[platformId]/page.tsx` L8, L557-564) |
| `ui/app/investments/[platformId]/page.tsx` | Header action + funded trigger + `load()` refactor | ✓ VERIFIED | Both triggers present and wired; `load()` extracted as a named function reused by both modals' `onSaved` |
| `ui/e2e/investment-transfer.spec.ts` | RED→GREEN e2e spec | ✓ VERIFIED | Exists, 3 tests, orchestrator-confirmed GREEN (3/3) |
| `ui/app/investments/HoldingModal.tsx` | Extended with funding selector | ✓ VERIFIED | Exists, substantive extension (+169/-9 lines), wired (Funding-account `<select>` + routing branch + preview all present and reachable) |
| `ui/e2e/funded-trade.spec.ts` | RED→GREEN e2e spec | ✓ VERIFIED | Exists, 4 tests (A-D), orchestrator-confirmed GREEN (4/4) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `AccountManager.tsx` | `AdjustBalanceModal.tsx` | row's `current_balance` prop, `onChanged` callback | WIRED | `summary.accounts` (from `cashflow/page.tsx:836`) already carries `current_balance`; `onChanged` = `refreshAll`, re-fetches `GET /cashflow/summary` |
| `AdjustBalanceModal.tsx` | `POST /api/accounts/{id}/adjust-balance` | `fetch` in `handleSubmit` | WIRED | Body shape and 422 handling match backend `BalanceAdjustmentCreate` / `adjust_account_balance` exactly |
| `DepositCashModal.tsx` | `GET /api/accounts` | `useEffect` on mount | WIRED | Modal owns its own fetch (platform detail page has no account state); client-filters `type === "liquid"` |
| `DepositCashModal.tsx` | `POST /api/transactions/investment-transfer` | `fetch` in `handleSubmit` | WIRED | Body matches `InvestmentTransferCreate` exactly; `onSaved={load}` refetches platform detail |
| `HoldingModal.tsx` | `POST /api/portfolio-events/funded-buy\|funded-sell` | `fetch` in `handleSubmit`, `isFunded` branch | WIRED | Body matches `FundedBuyCreate`/`FundedSellCreate` exactly (`source_account_name`, `platform_id`, `ticker`, `quantity`, `price`, `cash_amount`, currencies, date, asset_type) |
| `HoldingModal.tsx` (unfunded) | `POST /api/portfolio-events` | `fetch` in `handleSubmit`, else branch | WIRED | Byte-for-byte unchanged from pre-phase-18 behavior; confirmed unaffected by diff (only additive funded branch + new fields inserted) |
| `[platformId]/page.tsx` | `HoldingModal.tsx` | "+ Log event" trigger, `defaultPlatformId` prop | WIRED | Trigger only renders on the Buy & Sell tab; modal mounted with `defaultPlatformId={Number(platformId)}` and `onSaved={load}` |
| `ui/app/api/[...proxy]/route.ts` | FastAPI backend | generic catch-all proxy | WIRED (pre-existing, unmodified) | Confirmed no per-route API files exist under `ui/app/api/` for these 3 writes — all reach the backend via the existing generic proxy that injects `MONAI_API_KEY` server-side; git diff across all 7 phase-18 commits touches zero files under `backend/`, confirming the "UI-only, no new backend endpoint" claim |

### Backend Contract Cross-Check (focus area)

| UI POST | Backend endpoint | Backend schema | Field match |
|---------|-------------------|-----------------|-------------|
| `{ target_balance: number }` | `POST /accounts/{id}/adjust-balance` (`main.py` L264) | `BalanceAdjustmentCreate` (`schemas.py` L280) — `target_balance: MoneyDecimal`, no `gt=0` | Exact match; `MoneyDecimal` accepts a JSON number and serializes back as float (`PlainSerializer`) — same convention already used by `TransactionCreate.amount` elsewhere in the codebase, not a new risk |
| `{ from_account, platform_id, amount, currency, date?, notes? }` | `POST /transactions/investment-transfer` (`main.py` L1076) | `InvestmentTransferCreate` (`schemas.py` L237) | Exact match; `amount: MoneyDecimal, gt=0` — UI never sends non-positive amounts (`canSubmit` requires `parsedAmount > 0`) |
| `{ source_account_name, platform_id, ticker, quantity, price, cash_amount, cash_currency, event_currency, date, asset_type }` | `POST /portfolio-events/funded-buy` / `funded-sell` (`main.py` L493/L526) | `FundedBuyCreate`/`FundedSellCreate` (`schemas.py` L248/L264) — all `gt=0` | Exact match; client-side submit-disable guards `cash_amount > 0` (added as a Rule-2 auto-fix per 18-03-SUMMARY.md, confirmed present at `HoldingModal.tsx` L392-396) |

No sign-convention or Decimal/float boundary defect found: all three writes go through the same `MoneyDecimal` JSON-number convention already established for every other write endpoint in this codebase (`TransactionCreate`, etc.) — Phase 18 introduces no new serialization risk.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ACCT-02 | 18-01 | User can set an account's balance; delta stored as visible Adjustment record | ✓ SATISFIED (UI layer) | AdjustBalanceModal + row action; backend write path was already marked Complete under Phase 13 in REQUIREMENTS.md traceability — Phase 18 supplies the missing user-facing entry point |
| XFER-02 | 18-02 | User can transfer liquid → investment platform | ✓ SATISFIED (UI layer) | DepositCashModal + header action |
| XFER-03 | 18-03 | Buy/sell requires choosing a liquid source/destination account | ✓ SATISFIED (UI layer) | HoldingModal funding selector + Buy & Sell tab trigger |

**Note (informational, not a gap):** `.planning/REQUIREMENTS.md`'s traceability table already listed ACCT-02/XFER-02/XFER-03 as `[x]` complete, attributed to "Phase 13", before Phase 18 ran — Phase 13 shipped only the backend write primitives, not a reachable UI. This is a pre-existing documentation quirk (predates this phase, not introduced or worsened by it) and does not affect Phase 18's own goal achievement — all 3 IDs are present in REQUIREMENTS.md and none are orphaned. Not actionable as a Phase 18 gap; flagged for awareness only.

### Anti-Patterns Found

None. Grepped all 8 phase-18-modified/created files for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` and stub patterns (`return null`, hardcoded empty props, console.log-only handlers) — zero matches. No `ConfirmDialog` wrapper was added to any of the 3 surfaces (D-07 compliance confirmed). No `NEXT_PUBLIC_`/raw-backend-URL reference introduced (all 3 modals call `/api/...` exclusively). Git status confirms no stray temp Playwright config files were left behind from the documented local port-conflict workarounds.

### Behavioral Spot-Checks

Full e2e suite already run by the orchestrator on a freshly built server (55/59 passed; the 3 phase-18 specs are 9/9 GREEN — 2 balance-adjust + 3 investment-transfer + 4 funded-trade). Re-verification of this run was explicitly out of scope per the task's `<already_established_do_not_redo>` block; this report instead traced each spec's assertions against the actual component/backend source to confirm the GREEN result reflects real contract-correct behavior, not weak/tautological assertions (see Observable Truths table — each cites the specific assertion line).

### Probe Execution

Not applicable — no `scripts/*/tests/probe-*.sh` convention found in this repo; PLAN/SUMMARY do not reference probes.

### Human Verification Required

1. **Balance adjustment live write (ACCT-02)**
   **Test:** Against docker-compose (real Postgres), submit an "Adjust balance" change on a real liquid account.
   **Expected:** A visible "Adjustment" transaction record appears and the derived balance reconciles to the entered target.
   **Why human:** e2e coverage is entirely route-mocked; the live dual-write path (fresh unfiltered SUM delta computation) was never exercised against real data during this phase.

2. **Liquid→investment deposit live write (XFER-02)**
   **Test:** Against docker-compose, submit a "Deposit cash" transfer from a real liquid account into a real platform.
   **Expected:** A Deposit portfolio event appears on the platform ledger; the liquid account is debited by the same amount (one atomic write).
   **Why human:** Same route-mocked-only limitation for the dual-leg atomic write.

3. **Funded buy/sell live write (XFER-03)**
   **Test:** Against docker-compose, log a funded Buy then a funded Sell via "+ Log event" with a Funding account chosen.
   **Expected:** Buy debits the account and records the holding/event atomically; Sell credits it back.
   **Why human:** Same route-mocked-only limitation for the dual-leg atomic write; also confirms `cash_amount` (default or edited) is what's actually persisted.

These three items were explicitly flagged as open in all three plans' own `<verification>` sections and both 18-01/18-02/18-03-SUMMARY.md coverage blocks (`human_judgment: true`) — this phase is the last phase in the v1.2 milestone (no later phase to defer to), so they cannot be deferred and are carried forward here as the phase's outstanding human-verification gate.

### Gaps Summary

No gaps. All 15 must-have truths across the three plans are verified against actual source (not SUMMARY claims): components exist, are substantive, are wired to each other and to the correct pre-existing backend endpoints with matching field shapes, and no new backend endpoint/schema/read was introduced (confirmed via `git show --stat` on every phase-18 commit). The only open item is the three live-database UAT checks the plans themselves scoped out of automated verification — these route to human sign-off, not to a code fix.

---

*Verified: 2026-08-17T16:20:00+07:00*
*Verifier: Claude (gsd-verifier)*
