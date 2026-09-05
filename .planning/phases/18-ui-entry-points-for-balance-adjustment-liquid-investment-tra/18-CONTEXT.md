# Phase 18: UI Entry Points for Balance Adjustment, Liquid→Investment Transfer, and Funded Buy/Sell - Context

**Gathered:** 2026-08-03
**Status:** Ready for planning

> **Mode:** `--auto`. Every decision below is the **recommended option**,
> auto-selected in a single pass. Any can be vetoed before planning.

<domain>
## Phase Boundary

Add **UI entry points** for three money-moving operations whose **backend already
shipped in Phase 13** (endpoints + schemas + atomic dual-leg writes + audit logging
all exist and are verified). This phase is **UI-only** — it wires existing REST
endpoints into the existing v1.1-"paper" surfaces; it does **not** build or change
backend write mechanics.

The three operations and their existing endpoints:

- **ACCT-02 — Set account balance** → `POST /accounts/{account_id}/adjust-balance`
  (`BalanceAdjustmentCreate{target_balance}`). Delta is stored as a visible
  "Adjustment" transaction; balances stay derived.
- **XFER-02 — Liquid → investment transfer** → `POST /transactions/investment-transfer`
  (`InvestmentTransferCreate{from_account, platform_id, amount>0, currency, date?, notes?}`).
  Moves cash from a liquid account into an investment platform as a portfolio **deposit** event.
- **XFER-03 — Funded buy/sell** → `POST /portfolio-events/funded-buy` and
  `.../funded-sell` (`FundedBuy/SellCreate{source_account_name, platform_id, ticker,
  quantity>0, price>0, cash_amount>0, cash_currency, event_currency, date?, notes?,
  asset_type?}`). One confirmation writes both the portfolio event and the liquid-account leg.

**In scope:** ACCT-02, XFER-02, XFER-03 — the three requirement IDs named in ROADMAP Phase 18,
surfaced as UI actions on the existing Cashflow and Investments surfaces.

**Out of scope (own phases / already done):** any new backend endpoint, schema, or
migration (all three ops shipped in Phase 13); adding these writes to the agent/MCP
tool surface (they stay web-app-only, API-key-gated, off `READ_TOOL_NAMES` — matches
Phase 17 D-03/D-05); multi-currency FX math (single-currency IDR holds); the record
modal's Expense/Income/Transfer segments (Phase 16, unchanged).
</domain>

<decisions>
## Implementation Decisions

### Balance adjustment entry point (ACCT-02)
- **D-01:** Add a per-account **"Adjust balance"** action to `AccountManager.tsx`
  (`ui/app/cashflow/AccountManager.tsx`) — the component that already owns liquid-account
  rows (edit-name + delete-with-reassign). It opens a small overlay modal (reuse the
  `ConfirmDialog`/modal shell + `styles.ts` tokens) with a single **target-balance** input
  and a **live computed-delta preview** ("Adjustment: +Rp X" / "−Rp X"), then submits
  `POST /accounts/{id}/adjust-balance {target_balance}`. `target_balance` accepts zero/negative
  (no `gt=0`). On success, `onChanged()` refetch (Pattern 5).
  `[auto] Balance-adjust home — Q: "Per-account action in AccountManager vs a global 'Set balance' surface?" → Selected: "Per-account action in AccountManager" (recommended)`
- **D-02:** The delta preview reads the account's **current balance** from the data
  AccountManager can already consume (`current_balance` from `GET /cashflow/summary` — the
  component's header comment notes it ignores this field today; this phase uses it). No new
  backend read. Preview is presentation-only; the authoritative delta is computed server-side.
  `[auto] Delta preview — Q: "Show computed adjustment delta before submit or submit raw target?" → Selected: "Show live delta preview" (recommended)`

### Liquid → investment transfer entry point (XFER-02)
- **D-03:** Home the entry point on the **Investments** surface, not the record modal —
  because the result is a portfolio **deposit** event that already surfaces on the platform
  detail "Buy & Sell" ledger (`deposit: "Deposit"` label already exists in
  `ui/app/investments/[platformId]/page.tsx`), and Phase 17 deliberately kept funding legs
  out of the Records ledger. Add a **"Deposit cash"** action on the **platform detail page**
  header (`platform_id` comes from the route) opening a modal: **from-account** (liquid select)
  + amount + currency(default IDR) + date? + notes? → `POST /transactions/investment-transfer`.
  `[auto] Transfer home — Q: "4th segment in the record modal vs a 'Deposit cash' action on the investments surface?" → Selected: "Investments-surface action" (recommended)`
- **D-04:** The modal needs the **liquid-account list**. Fetch it from the existing
  `GET /accounts` (filter `type == "liquid"`); no new backend endpoint. Submit passes
  `from_account` as the account **name** (schema takes a string name, mirroring the funded
  buy/sell precedent).

### Funded buy/sell entry point (XFER-03)
- **D-05:** Extend the existing **`HoldingModal.tsx`** rather than build a new component
  (it already has ticker / quantity / price / event-type fields and mirrors the modal shell).
  Add a **funding-account selector** (liquid accounts from `GET /accounts`). When a source
  account is chosen, the modal routes to `POST /portfolio-events/funded-buy` | `funded-sell`
  (writing the liquid leg atomically); when left **unfunded/none**, it keeps the current
  `POST /portfolio-events` path as the escape hatch. Buy vs Sell selected via the existing
  event-type control. Reachable from its current trigger (investments page) **and** from the
  platform detail "Buy & Sell" tab.
  `[auto] Funded buy/sell home — Q: "New funded-trade modal vs extend HoldingModal with a funding selector?" → Selected: "Extend HoldingModal" (recommended)`
- **D-06:** In funded mode, default **`cash_amount = quantity × price`** but keep it an
  **editable field** (the schema takes `cash_amount` separately from `quantity`/`price` to
  allow fees/rounding). `asset_type` optional (backend defaults). Currencies default IDR.

### Write-safety / confirmation pattern (all three)
- **D-07:** Each modal shows a **form-level preview line** of the money impact before the
  single submit — balance-adjust: the computed delta; investment-transfer: "Moves Rp {amount}
  from {account} into {platform}"; funded buy/sell: "Debits/credits {account} Rp {cash_amount},
  {+/−}{quantity} {ticker}". Submit is **one atomic call** (backend writes both legs in one DB
  transaction) — **do not** use the agent-proposal confirm flow; these are direct API-key-gated
  web-app writes. Keep the standard error copy: `"Couldn't save …: {detail}. Nothing was changed."`
  `[auto] Confirm pattern — Q: "Agent-proposal confirm flow or form-level preview + single atomic submit?" → Selected: "Form-level preview + single submit" (recommended)`

### Claude's Discretion
- Exact modal markup/layout, whether "Adjust balance" is an inline row control vs a small
  dialog, and whether the funding selector is a `<select>` vs segmented control — left to
  planning within the inline-style `styles.ts` token convention.
- Whether to **also** add a convenience "Deposit to investment" shortcut from the Cashflow
  surface (recommend: single home on investments for this phase to avoid duplication).
- Whether HoldingModal's funded/unfunded routing is a visible toggle or implied by the
  presence of a chosen funding account (recommend: implied by selection).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — ACCT-02, XFER-02, XFER-03 (exact acceptance wording; all
  marked Complete/Phase 13 in the traceability table — that reflects **backend** completion)
- `.planning/ROADMAP.md` — Phase 18 goal + success criteria

### Prior-phase decisions this builds on
- `.planning/phases/13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm/13-CONTEXT.md`
  — the atomic dual-leg write semantics behind all three endpoints (funding adjustments, buy/sell pairing)
- `.planning/phases/16-ui-extend-existing-components/16-CONTEXT.md` — record modal + AccountManager
  patterns, currency-field + "Save & add another" conventions, transfer-pair endpoint precedent
- `.planning/phases/17-ui-new-surfaces-records-tab-categories-manager/17-CONTEXT.md` — platform detail
  page (PnL + Buy/Sell tabs), the "funding legs surface as portfolio events, not in Records" decision,
  and the web-app-only-writes-stay-off-MCP rule

### Code (see `<code_context>` for how each is used)
- `backend/schemas.py:237-288` — `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`,
  `BalanceAdjustmentCreate` (exact field names/types)
- `backend/main.py` — routes: `/accounts/{id}/adjust-balance:264`, `/portfolio-events/funded-buy:493`,
  `/portfolio-events/funded-sell:526`, `/transactions/investment-transfer:1076`
- `ui/app/cashflow/AccountManager.tsx`, `ui/app/cashflow/ConfirmDialog.tsx`,
  `ui/app/investments/HoldingModal.tsx`, `ui/app/investments/[platformId]/page.tsx`,
  `ui/app/investments/page.tsx`, `ui/app/styles.ts`

No external ADRs — decisions captured above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`AccountManager.tsx`** — liquid-account rows with inline edit + `ConfirmDialog` delete/reassign
  flow; the host for D-01's "Adjust balance" action. Already able to consume `current_balance`.
- **`HoldingModal.tsx`** — overlay modal with ticker/quantity/price/event-type; POSTs
  `/api/portfolio-events` (unfunded). D-05 extends it with a funding selector → funded endpoints.
- **`investments/[platformId]/page.tsx`** — platform detail with PnL + "Buy & Sell" tabs, segmented
  control, event ledger already rendering `deposit` events; host for D-03 "Deposit cash" + the D-05
  buy/sell trigger.
- **`ConfirmDialog.tsx`**, **`styles.ts`** tokens (`card`/`input`/`btn`/`label`) — modal shells + styling.

### Established Patterns
- Inline-style + token `styles.ts` (no Tailwind); `onChanged()`/`onSaved()` parent-refetch (Pattern 5);
  Next.js proxy injects `MONAI_API_KEY` server-side (UI calls `/api/...`).
- Error-copy convention: `"Couldn't save …: {detail}. Nothing was changed."`
- Writes are API-key-gated and **web-app-only** — NOT added to the MCP read surface (`READ_TOOL_NAMES`
  stays 15). All three Phase 18 endpoints already exist as direct REST writes.
- e2e verification is Playwright (route-mocked) under `ui/e2e/`; no unit-test framework in `ui/`.

### Integration Points
- `ui/app/cashflow/page.tsx` mounts `<AccountManager>`; `ui/app/investments/page.tsx` mounts
  `<HoldingModal>` + platform list linking to the detail route.
- The modals need the **liquid-account list** (`GET /accounts`, filter `type=="liquid"`) and, for the
  adjust-balance preview, `current_balance` (`GET /cashflow/summary`) — both existing reads.
</code_context>

<specifics>
## Specific Ideas

- These are money-moving surfaces — every one shows a plain-language preview of the cash impact
  before the single confirm, so the user never guesses what a submit will do.
- Group investment funding (XFER-02 deposit + XFER-03 funded trade) on the investments surface so
  "fund / trade this platform" reads as one coherent place; keep balance-adjust with the accounts it
  edits (cashflow). Balance-adjust deltas appear as visible "Adjustment" records — no hidden balance field.
</specifics>

<deferred>
## Deferred Ideas

- A convenience "Deposit to investment" shortcut from the Cashflow surface (single investments home
  chosen for this phase).
- Adding these three writes to the agent/MCP tool surface — intentionally kept web-app-only.
- Multi-currency FX conversion for the currency fields — backlog (single-currency IDR holds).
- The Phase-14 `ticker="CASH"` deposit sentinel is a **backend** decision already shipped; the UI
  just calls `investment-transfer`. (See [[cash-deposit-sentinel-decision]] — flagged for a one-line
  user OK before first production use, but that is a backend/ops note, not a Phase 18 UI decision.)

None of the above were pulled into Phase 18 scope.
</deferred>

---

*Phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra*
*Context gathered: 2026-08-03*
