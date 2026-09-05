# Phase 18: UI Entry Points for Balance Adjustment, Liquid→Investment Transfer, and Funded Buy/Sell - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-03
**Phase:** 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
**Mode:** `--auto` (Claude auto-selected the recommended option for every area, single pass)
**Areas discussed:** Balance-adjustment home, Delta preview, Transfer home, Funded buy/sell home, Confirm pattern

---

## Balance adjustment entry point (ACCT-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Per-account action in AccountManager | Add "Adjust balance" per liquid-account row; small modal with target-balance + delta preview | ✓ |
| Global "Set balance" surface | A separate screen/section listing accounts to set balances | |

**Choice:** Per-account action in `AccountManager.tsx` → `POST /accounts/{id}/adjust-balance`.
**Notes:** AccountManager already owns liquid-account rows with edit/delete; smallest, most consistent home.

---

## Delta preview

| Option | Description | Selected |
|--------|-------------|----------|
| Show live delta preview | Compute adjustment (target − current) client-side from existing `current_balance` | ✓ |
| Submit raw target | Just POST target_balance, no preview | |

**Choice:** Live delta preview (presentation-only; server computes authoritative delta).
**Notes:** `current_balance` is available from `GET /cashflow/summary`; no new backend read.

---

## Liquid → investment transfer entry point (XFER-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Investments-surface action | "Deposit cash" on platform detail (platform_id from route) → `investment-transfer` | ✓ |
| 4th segment in record modal | Add "Invest" segment beside Expense/Income/Transfer | |

**Choice:** "Deposit cash" action on the platform detail page.
**Notes:** Deposit surfaces as a portfolio event on the platform "Buy & Sell" ledger; Phase 17 kept funding legs out of Records. Placing entry where the result shows is more coherent.

---

## Funded buy/sell entry point (XFER-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend HoldingModal | Add funding-account selector; chosen account routes to funded-buy/sell, none → existing unfunded path | ✓ |
| New funded-trade modal | Build a separate component for funded buy/sell | |

**Choice:** Extend `HoldingModal.tsx` with a funding selector.
**Notes:** HoldingModal already has ticker/quantity/price/event-type; funded mode adds `source_account_name` + editable `cash_amount` (default qty×price). Reachable from investments page + platform detail Buy/Sell tab.

---

## Write-safety / confirmation pattern (all three)

| Option | Description | Selected |
|--------|-------------|----------|
| Form-level preview + single atomic submit | Preview the cash impact line, then one atomic API call (backend writes both legs) | ✓ |
| Agent-proposal confirm flow | Route through the LLM proposal→confirm mechanism | |

**Choice:** Form-level preview + single atomic submit.
**Notes:** These are direct API-key-gated web-app writes; the agent-proposal flow is for LLM-initiated changes. Standard error copy retained.

---

## Claude's Discretion

- Exact modal markup/layout; inline row control vs dialog for adjust-balance; `<select>` vs segmented control for the funding selector.
- Whether to also add a Cashflow-side "Deposit to investment" shortcut (recommend: single investments home this phase).
- Whether HoldingModal's funded/unfunded routing is a visible toggle or implied by a chosen funding account (recommend: implied).

## Deferred Ideas

- Cashflow-side deposit shortcut; adding these writes to the MCP tool surface; multi-currency FX; the backend `ticker="CASH"` deposit sentinel (already shipped, backend/ops note).
