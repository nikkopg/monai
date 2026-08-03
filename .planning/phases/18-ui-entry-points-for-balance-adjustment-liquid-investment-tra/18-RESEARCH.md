# Phase 18: UI Entry Points for Balance Adjustment, Liquid→Investment Transfer, and Funded Buy/Sell - Research

**Researched:** 2026-08-03
**Domain:** Next.js (App Router) UI wiring onto pre-existing, verified FastAPI write endpoints
**Confidence:** HIGH

## Summary

This phase adds three UI entry points to two existing pages — `AccountManager.tsx`
(Cashflow) and the Investments surfaces (`investments/page.tsx`, the new
`investments/[platformId]/page.tsx` action, and `HoldingModal.tsx`) — that call four
REST write endpoints already shipped, tested, and audited in Phase 13/14
(`POST /accounts/{id}/adjust-balance`, `POST /transactions/investment-transfer`,
`POST /portfolio-events/funded-buy`, `POST /portfolio-events/funded-sell`). All four
routes were read directly from `backend/main.py` and `backend/schemas.py` in this
session and their bodies/response shapes are confirmed below — no backend research
was needed beyond confirming shapes; **no new backend code, schema, or migration is
in scope**.

The UI-side work is pure composition of already-established patterns: the
overlay-modal shell (`card` + `ConfirmDialog`'s fixed-inset backdrop, as used by
`HoldingModal.tsx`), the `styles.ts` token set (`input`/`btn`/`label`), the
segmented-control markup already used on the platform detail page's PnL/Buy&Sell
tabs, and the `onChanged()`/`onSaved()` parent-refetch convention every existing
modal already follows. Every read the three new modals need (`GET /accounts`,
`GET /cashflow/summary`) already exists and already returns the needed fields — this
research found **zero missing-field gaps** that would require a backend touch.

The one non-obvious backend behavior worth flagging for the planner: **all three
money-moving endpoints resolve the source/destination account by name via
`_get_or_create_account`, which silently auto-creates a new account if the name
doesn't match an existing one exactly** — never a 404. Because the new UI always
submits an existing account's exact name from a `<select>` populated by
`GET /accounts`, this is safe by construction, but any future free-text account
field on these modals would be a landmine. This is documented under Common
Pitfalls.

**Primary recommendation:** Extend `AccountManager.tsx`, `investments/[platformId]/page.tsx`,
and `HoldingModal.tsx` in place, following the exact modal-shell/token/refetch
patterns already used by `HoldingModal.tsx`/`ConfirmDialog.tsx`/`TransactionModal.tsx`.
No new shared component is needed; a small local overlay (copy-paste the `HoldingModal`
backdrop/card shell) is the right amount of code for the balance-adjust dialog and the
deposit-cash modal, per CONTEXT.md's D-01/D-03 and the Claude's Discretion note.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Balance-adjust form + delta preview | Frontend (Next.js client component) | — | Pure UI; preview is presentation-only, authoritative delta computed server-side in `apply_add_balance_adjustment` |
| Balance-adjust write | API / Backend | — | `POST /accounts/{id}/adjust-balance` already exists (Phase 13); no new endpoint |
| Deposit-cash form (liquid→investment) | Frontend | — | New modal on platform detail page; submits to existing endpoint |
| Investment-transfer write | API / Backend | — | `POST /transactions/investment-transfer` already exists; atomic dual-leg write happens in `writes.py` |
| Funded buy/sell funding selector | Frontend | — | Extends `HoldingModal.tsx`; routes to funded vs. unfunded endpoint based on selector state |
| Funded buy/sell write | API / Backend | — | `POST /portfolio-events/funded-{buy,sell}` already exist |
| Account list / current_balance reads | API / Backend (existing) | Frontend (consumes) | `GET /accounts`, `GET /cashflow/summary` already expose every field these modals need |
| Audit logging of all 4 writes | API / Backend (existing) | — | Every `apply_*` primitive already writes its own `AuditLog` row (Phase 13 D-02); no UI action needed |

## Standard Stack

No new libraries. This phase reuses the existing stack exactly as pinned in
`ui/package.json` — verified live in this session:

| Library | Version (installed) | Purpose | Why Standard (for this repo) |
|---------|---------|---------|--------------|
| next | 16.2.12 `[VERIFIED: npm view]` | App Router, client components | Already the project's framework |
| react | 19.2.8 `[VERIFIED: npm view]` | Component rendering | Already the project's framework |
| @playwright/test | 1.61.1 (from `ui/package.json`) `[CITED: ui/package.json]` | e2e verification | Already the project's only test framework — no unit-test framework in `ui/` |

No installation step is required for this phase — **no `## Package Legitimacy Audit`
table is produced** because no external packages are introduced (Package Legitimacy
Gate is scoped to "phases that install external packages"; this one installs none).

### Alternatives Considered

None — CONTEXT.md's decisions (D-01, D-03, D-05) already selected the exact hosting
components and explicitly rejected alternatives (a global "set balance" surface, a
4th record-modal segment, a new standalone funded-trade modal). Re-litigating those
is out of scope; this research confirms the chosen approach is technically sound.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────┐   ┌──────────────────────────────┐   ┌───────────────────────────────┐
│ AccountManager.tsx           │   │ investments/[platformId]/    │   │ HoldingModal.tsx               │
│ (Cashflow page)               │   │ page.tsx (Platform detail)    │   │ (Investments page + Platform    │
│                                │   │                                │   │  detail "Buy & Sell" trigger)   │
│ "Adjust balance" per row       │   │ "Deposit cash" header action   │   │ + funding-account selector      │
│  -> opens small overlay modal  │   │  -> opens "Deposit cash" modal │   │  (liquid accounts, GET /accounts)│
│  -> reads current_balance      │   │  -> reads liquid accounts      │   │  chosen -> funded-buy/sell path  │
│     from summary.accounts      │   │     (GET /accounts, type filter)│  │  empty  -> unfunded (existing)  │
│  -> shows live delta preview    │   │  -> shows "Moves Rp X from      │   │  -> shows "Debits/credits Rp X"  │
└───────────────┬────────────────┘   │     {account} into {platform}" │   └───────────────┬─────────────────┘
                │ submit                └───────────────┬────────────────┘                 │ submit
                ▼                                        ▼ submit                          ▼
   POST /api/accounts/{id}/adjust-balance   POST /api/transactions/investment-transfer   POST /api/portfolio-events/funded-{buy,sell}
                │                                        │                                 │
                └──────────────┬─────────────────────────┴──────────────┬──────────────────┘
                               ▼                                        ▼
                  Next.js proxy (ui/app/api/[...proxy]/route.ts) injects MONAI_API_KEY server-side
                               │
                               ▼
              FastAPI backend.main — routes at :264 / :1076 / :493 / :526 (all `require_api_key`)
                               │
                               ▼
        backend/writes.py apply_* primitives — ONE DB transaction per write, ONE AuditLog row(s)
                               │
                               ▼
                    PostgreSQL: transactions + portfolio_events (+ audit_log)
                               │
                               ▼
        On 2xx: onChanged()/onSaved() -> parent refetches GET /cashflow/summary,
        GET /net-worth, GET /platforms/{id}/detail, GET /portfolio-events -> UI updates,
        no page reload (Pattern 5, already used by every existing modal)
```

### Recommended Project Structure

No new files/folders — every touch point is an edit to an existing file:

```
ui/app/
├── cashflow/
│   └── AccountManager.tsx        # D-01/D-02: add "Adjust balance" action + inline overlay
├── investments/
│   ├── HoldingModal.tsx          # D-05/D-06: add funding-account selector + funded routing
│   ├── page.tsx                  # unchanged trigger site (already renders HoldingModal)
│   └── [platformId]/
│       └── page.tsx              # D-03/D-04: add "Deposit cash" header action + modal;
│                                  #   also becomes a 2nd HoldingModal trigger site (D-05)
└── e2e/
    ├── cashflow-crud.spec.ts     # extend: "Adjust balance" flow
    └── platform-detail.spec.ts   # extend: "Deposit cash" flow + funded buy/sell trigger
```

### Pattern 1: Overlay modal shell (reuse verbatim)

**What:** Fixed-inset semi-transparent backdrop + centered `card`-styled panel,
`onClick={onClose}` on the backdrop, `onClick={(e) => e.stopPropagation()}` on the
card, Cancel (transparent/muted) + primary (`btn`) actions in a bottom row.
**When to use:** Every one of the three new UI surfaces (balance-adjust dialog,
deposit-cash modal). `HoldingModal.tsx` already extends with a form; its shell is the
exact one to copy for the deposit-cash modal (new component) and to reuse for the
balance-adjust dialog (can also reuse `ConfirmDialog`'s children-slot pattern if the
form is small enough to fit as a single input + preview line).
**Example:**
```typescript
// Source: ui/app/investments/HoldingModal.tsx:102-118 (existing code, verified read)
<div
  style={{
    position: "fixed", inset: 0, background: "rgba(15,17,21,0.72)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
  }}
  onClick={onClose}
>
  <div
    style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
    onClick={(e) => e.stopPropagation()}
  >
    {/* form */}
  </div>
</div>
```

### Pattern 2: Refetch-after-write (Pattern 5, already established)

**What:** Every write handler calls `onSaved()`/`onChanged()` on 2xx, never mutates
local state optimistically. The parent page's `load()`/`refreshAll()` re-fetches the
summary/detail GET(s) that feed the page.
**When to use:** All three new writes. `AccountManager` already takes `onChanged`;
the platform-detail page will need its own `load()` (mirroring
`investments/page.tsx`'s `load` callback) passed as `onSaved` to the new
"Deposit cash" modal, and re-triggered after a funded buy/sell too (since a funded
trade also changes the account balance the Deposit-cash preview would show, if the
platform detail page starts showing account balances — it currently does not, so
this only needs `load()` to refresh holdings/subtotal/events).
**Example:**
```typescript
// Source: ui/app/investments/page.tsx:771-777 (existing code, verified read)
{showEvent && (
  <HoldingModal
    platforms={platformOptions}
    onClose={() => setShowEvent(false)}
    onSaved={load}
  />
)}
```

### Pattern 3: Error-copy convention (verbatim, already established)

**What:** `` `Couldn't save …: ${detail}. Nothing was changed.` `` where `detail` is
extracted via a small helper that prefers `errBody.detail` (string) then
`errBody.detail.message`, falling back to `HTTP {status}`.
**When to use:** All three new submit handlers. `AccountManager.tsx` already has an
`extractDetail()` helper (lines 296-308) that is the canonical version (handles both
the plain-string `detail` from the write endpoints below AND the nested
`{message, affected_count}` shape used by the delete-account 422). All 4 of this
phase's write endpoints return a **plain string** `detail` on 422 (confirmed by
reading every `raise HTTPException(status_code=422, detail=str(e))` call site in
`backend/main.py` for these 4 routes) — so `extractDetail()`'s string branch is what
fires; the nested-object branch is dead code for these specific endpoints but
harmless to reuse verbatim.
**Example:**
```typescript
// Source: ui/app/cashflow/AccountManager.tsx:296-308 (existing code, verified read)
async function extractDetail(r: Response): Promise<string> {
  let detail = `HTTP ${r.status}`;
  try {
    const errBody = await r.json();
    detail =
      typeof errBody?.detail === "string"
        ? errBody.detail
        : errBody?.detail?.message ?? detail;
  } catch {
    // keep the status-based detail
  }
  return detail;
}
```

### Pattern 4: Segmented control (for a funded/unfunded toggle, if made explicit)

**What:** Pill-shaped 2-button group, `tokens.color.sidebar` background,
`border: 1px solid tokens.color.border2`, active button gets white background +
shadow. Already used identically in 3 places (platform detail PnL/Buy&Sell tabs,
investments allocation Asset-type/Platform toggle, cashflow period selector).
**When to use:** Only if the planner chooses a *visible* funded/unfunded toggle for
HoldingModal (CONTEXT.md's Claude's-Discretion recommends implied-by-selection
instead — a `<select>` with a "— none (unfunded) —" option is simpler and matches
existing `<select>` conventions elsewhere in the same modal). Documented here in case
the plan-checker or a future iteration wants the toggle variant.
**Example:**
```typescript
// Source: ui/app/investments/[platformId]/page.tsx:263-297 (existing code, verified read)
<div style={{ display: "inline-flex", background: tokens.color.sidebar,
  border: `1px solid ${tokens.color.border2}`, borderRadius: 12, padding: 4 }}>
  {TABS.map((t) => { /* active ? white bg + shadow : transparent */ })}
</div>
```

### Anti-Patterns to Avoid

- **Free-text account-name input on any of these 3 modals:** `_get_or_create_account`
  (the shared account-resolution helper all 4 endpoints route through) silently
  creates a new account on any non-matching name — never returns 404/422. Always
  populate the account field from a `<select>` sourced from `GET /accounts`, never a
  free-text `<input>`.
- **Re-deriving the adjust-balance delta client-side and trusting it:** the preview
  in D-02 is presentation-only (`target_balance − current_balance` from
  `GET /cashflow/summary`'s `account_balances()` rows, which is an **all-time
  unfiltered SUM including transfers** — see Pitfall 1 below). The authoritative
  delta is always the one `apply_add_balance_adjustment` computes server-side at
  write time from a fresh query; never submit a pre-computed delta as the API body
  (the schema takes `target_balance`, not a delta, by design).
- **Using the agent-proposal confirm-before-write flow for these writes:** D-07
  explicitly rejects this — these are direct, API-key-gated REST writes with a
  form-level preview, not agent proposals. Do not route through `/query` or
  `ConfirmRequest`/`Proposal`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Delta/preview math | A second copy of `apply_add_balance_adjustment`'s SQL in the frontend | Client-side subtraction of `target_balance − current_balance` from the already-fetched `GET /cashflow/summary` row, clearly labeled "preview" | The backend delta is the source of truth (fresh unfiltered SUM at write time); a client preview only needs to be visually close, not exact-to-the-cent under concurrent writes |
| Liquid-account filtering | A new `GET /accounts?type=liquid` backend query param | Client-side `.filter(a => a.type === "liquid")` over the existing `GET /accounts` response (already includes `type` per `AccountOut`) | Confirmed `AccountOut` (schemas.py:51-57) already returns `type`; no backend change needed, matches D-04's explicit instruction |
| cash_amount defaulting | A backend-side auto-multiply of `quantity * price` | Client-side `setState` default on selector change, kept as an editable controlled input (D-06) | Schema deliberately keeps `cash_amount` independent of `quantity`/`price` to allow fees/rounding — the backend never assumes they're equal |
| Modal overlay/backdrop | A new shared `Modal` component/library | Copy `HoldingModal.tsx`'s inline overlay markup (2 files already do this independently: `HoldingModal.tsx` and `ConfirmDialog.tsx`) | Matches the codebase's established "no shared Modal component, copy the shell" pattern (already 2 independent implementations, not an abstraction problem worth solving in this phase) |

**Key insight:** every "hand-roll risk" in this phase is actually a "don't add a
backend endpoint/param" risk, not a "don't add a library" risk — the backend already
has every read and write this phase needs.

## Common Pitfalls

### Pitfall 1: `current_balance` in `GET /cashflow/summary` is an ALL-TIME, unfiltered sum — not period-scoped

**What goes wrong:** A developer might assume `current_balance` respects the
Cashflow page's selected period (`this_week`/`this_month`/etc.) since it's returned
by the same period-scoped `/cashflow/summary?period=...` call.
**Why it happens:** `account_balances(period_start, period_end)` (tools.py:474-518)
takes the period bounds but only uses them for `period_net`; `current_balance` is a
`COALESCE(SUM(t.amount), 0)` over **ALL** of the account's transactions regardless of
period, transfers included (per the function's own docstring, fixed in the
2026-08-02 Phase 16 UAT#3 patch — `current_balance` used to wrongly exclude transfer
rows before that fix).
**How to avoid:** Use `current_balance` as-is for the balance-adjust preview — it IS
the correct "current balance" the backend will reconcile against (it's the same
unfiltered SUM `apply_add_balance_adjustment` itself computes fresh at write time).
Do not try to "fix" it to be period-scoped.
**Warning signs:** A delta preview that looks right for `this_month` but wrong for
`this_year` — that's actually correct behavior, not a bug.

### Pitfall 2: `_get_or_create_account` silently creates accounts on name mismatch

**What goes wrong:** covered under Anti-Patterns above — restated here because it's
the single highest-risk landmine in this phase (a typo'd or stale account name in a
`<select>` value would silently fork a duplicate account rather than erroring).
**Why it happens:** `apply_add_transaction` (writes.py:54-76), which every one of
these 4 write paths eventually calls, resolves `after["account"]` /
`after["source_account_name"]` by name via `_get_or_create_account` (imported from
`backend/importer.py`) — a helper built for CSV-import idempotency, not for
strict-existence validation.
**How to avoid:** Populate every account `<select>` directly from a freshly-fetched
`GET /accounts` response (not a stale cached list), and never allow free-text entry.
Because `GET /accounts` is an open (no-auth) read that returns `id`/`name`/`type`, the
modal can always send the exact current name.
**Warning signs:** A new, unexpected row appearing in `AccountManager`'s account list
after a transfer/funded-buy — that's this bug in action, not a UI display glitch.

### Pitfall 3: Platform detail page currently fetches NO account data

**What goes wrong:** Building the "Deposit cash" modal assuming
`investments/[platformId]/page.tsx` already has a liquid-account list in scope.
**Why it happens:** The page currently fetches only `GET /platforms/{id}/detail` and
`GET /portfolio-events?platform_id=`. Confirmed by reading the full file — no
`/api/accounts` fetch exists there today.
**How to avoid:** The new modal must do its own `GET /accounts` fetch (either inside
the modal on mount, or lifted to the page's `useEffect` and passed down as a prop —
either is fine; `HoldingModal` takes `platforms` as a prop from its parent's
already-loaded state, which is the more consistent pattern to mirror for accounts
too, but a modal-owned fetch is also acceptable and matches `CsvUpload`'s
self-contained-fetch precedent elsewhere in the codebase).
**Warning signs:** None yet — this is a net-new fetch, not a regression risk, just a
scope reminder for the planner's task list.

### Pitfall 4: `FundedBuyCreate`/`FundedSellCreate`/`InvestmentTransferCreate` all coerce numeric fields to `float`, never `Decimal`, server-side — but the request body must still be valid JSON numbers

**What goes wrong:** Sending amount/quantity/price/cash_amount as strings (e.g.
`"1000000"`) from a hand-rolled `JSON.stringify` body would still round-trip through
Pydantic's `MoneyDecimal` coercion fine (Pydantic accepts numeric strings), but the
codebase's own convention (see `HoldingModal.tsx`'s existing submit — `quantity:
parseFloat(quantity)`) is to send actual JS numbers, not strings, for these fields.
**Why it happens:** Not a hard bug either way (Pydantic's `MoneyDecimal` handles
both), but consistency with the existing `HoldingModal.tsx` convention matters more
than which one is "more correct."
**How to avoid:** Follow `HoldingModal.tsx`'s existing pattern —
`parseFloat(quantity)`, `parseFloat(price)` — for the new `cash_amount` field too.
**Warning signs:** None functionally; this is a style-consistency note, not a
correctness risk.

### Pitfall 5: `date` field is a plain `YYYY-MM-DD` string on all 4 endpoints, not `datetime-local`

**What goes wrong:** Reusing `HoldingModal.tsx`'s `date` state (which is
`datetime-local`, formatted via `toLocalDatetimeInputValue`) verbatim for the new
funding fields without truncating to a date, given the backend column here is a
`date: str | None` on `InvestmentTransferCreate`/`FundedBuyCreate`/
`BalanceAdjustmentCreate` schemas (confirmed: `date: str | None = None`, distinct
from `PortfolioEventCreate.date: date` used by the existing unfunded path).
**Why it happens:** `HoldingModal.tsx`'s current unfunded submit already does
`.toISOString().slice(0, 10)` before sending — so the existing code already handles
this correctly for the unfunded path; the funded path must do the same truncation
before it hits these new schemas (which accept `str | None`, and the write-layer
composes them into `datetime.fromisoformat(after["date"])` inside
`apply_add_transaction`, which requires a valid ISO date/datetime string, not a bare
`datetime-local` value with no timezone handling beyond what `fromisoformat` accepts).
**How to avoid:** Reuse the exact same `.toISOString().slice(0, 10)` truncation
`HoldingModal.tsx` already does today for its `date` field, applied uniformly to
whichever date input the new/extended forms use.
**Warning signs:** A 422 or a wrong-day date appearing in the transaction/event ledger
if the raw `datetime-local` string (no `Z`/offset) is passed straight through.

## Code Examples

### Extracting the 422 error `detail` (all 4 endpoints return a plain string)

```python
# Source: backend/main.py (verified read, lines 271-274, 514-517, 537-540, 1094-1097)
try:
    tx = apply_add_balance_adjustment(db, account_id, payload.target_balance)
except ValueError as e:
    raise HTTPException(status_code=422, detail=str(e))
# -> response body: {"detail": "<plain string message>"}
```

### Success response shapes (confirmed by reading each route in `backend/main.py`)

```typescript
// POST /accounts/{id}/adjust-balance -> 201
// { transaction_id: number, amount: string }   // amount is the computed delta, as a string

// POST /transactions/investment-transfer -> 201
// { transaction_id: number, portfolio_event_id: number }
// NOTE: field name is transaction_id here too — verified at main.py:1099-1101
//   (return { "transaction_id": tx.id, "portfolio_event_id": ev.id })

// POST /portfolio-events/funded-buy -> 201
// { transaction_id: number, portfolio_event_id: number }

// POST /portfolio-events/funded-sell -> 201
// { transaction_id: number, portfolio_event_id: number }
```

### Filtering `GET /accounts` to liquid on the client (D-04)

```typescript
// GET /api/accounts already returns AccountOut[] = { id, name, type, currency }[]
const liquidAccounts = accounts.filter((a) => a.type === "liquid");
```

## State of the Art

Not applicable — this is a UI-only phase against a stable, already-shipped backend
contract from the same milestone (Phase 13/14, 2026-07-3x). No external
library/ecosystem drift to track.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The platform detail page's account fetch (for "Deposit cash") should be modal-owned or page-level `useEffect`-lifted — either is acceptable, no strong precedent forces one over the other | Pitfall 3 / Recommended Structure | Low — either implementation satisfies D-04; only affects where the `fetch("/api/accounts")` call lives, not behavior |
| A2 | `HoldingModal`'s funded/unfunded routing being "implied by selection" (a `<select>` with a none/blank option) rather than a visible toggle is the right call | Pattern 4 | Low — CONTEXT.md already recommends this in Claude's Discretion; flagged only because it's a UI judgment call, not a locked decision |

**If this table is empty:** N/A — see above; both items are low-risk implementation
choices already steered by CONTEXT.md's Claude's-Discretion section, not
unverified factual claims.

## Open Questions

1. **Does the platform-detail "Deposit cash" modal need its own account-balance
   display, or just the account name in the picker?**
   - What we know: D-03's preview copy is "Moves Rp {amount} from {account} into
     {platform}" — no balance display required.
   - What's unclear: Nothing blocking — this is confirmed sufficient by D-03's own
     copy spec.
   - Recommendation: No balance display needed on this modal; keep it to
     name + amount + currency + date + notes as D-04 specifies.

2. **Should a funded buy/sell triggered from the platform-detail "Buy & Sell" tab
   pre-select that platform in `HoldingModal`?**
   - What we know: D-05 says the modal is "reachable from its current trigger
     (investments page) and from the platform detail 'Buy & Sell' tab."
   - What's unclear: CONTEXT.md doesn't explicitly say whether the platform_id
     should be pre-selected/locked when opened from the detail page (vs. defaulting
     to "first platform" as `HoldingModal` does today).
   - Recommendation: Pre-select (and reasonably lock or just default-select) the
     current platform when opened from `investments/[platformId]/page.tsx` — matches
     the principle that a page-scoped action shouldn't force the user to re-pick
     what's already implied by where they clicked. Low-risk UX call for the planner
     to make explicitly in the plan rather than leaving implicit.

## Environment Availability

Skipped — this phase has no new external dependencies (Docker, DB, Ollama, etc.);
it only touches already-running Next.js/FastAPI services already verified working
in prior phases (16, 17).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Playwright `@playwright/test` 1.61.1 (route-mocked, no live backend) |
| Config file | `ui/playwright.config.ts` (existing, unchanged) |
| Quick run command | `npx playwright test e2e/cashflow-crud.spec.ts e2e/platform-detail.spec.ts` |
| Full suite command | `npm run e2e` (from `ui/`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ACCT-02 | "Adjust balance" action opens a dialog, shows a live delta preview, POSTs `{target_balance}` to `/api/accounts/{id}/adjust-balance`, refetches summary on success | e2e (route-mocked) | `npx playwright test e2e/cashflow-crud.spec.ts -g "adjust balance"` | ❌ Wave 0 — add new `test.describe` block to `cashflow-crud.spec.ts` |
| ACCT-02 | 422 error shows `"Couldn't save …: {detail}. Nothing was changed."` and does not close the dialog | e2e (route-mocked) | same file, same describe block, second test | ❌ Wave 0 |
| XFER-02 | "Deposit cash" action on platform detail opens a modal, lists liquid accounts (`GET /accounts` mocked, `type=liquid` filtered client-side), POSTs to `/api/transactions/investment-transfer`, refetches platform detail on success | e2e (route-mocked) | `npx playwright test e2e/platform-detail.spec.ts -g "Deposit cash"` | ❌ Wave 0 — add new `test.describe` block to `platform-detail.spec.ts` |
| XFER-03 | `HoldingModal` funding selector: choosing a liquid account routes submit to `/api/portfolio-events/funded-buy` (or `funded-sell` when Sell is selected); leaving it blank/none keeps the existing `/api/portfolio-events` unfunded path | e2e (route-mocked) | `npx playwright test e2e/platform-detail.spec.ts -g "funded"` (or a new `holding-modal.spec.ts` if the planner prefers isolating HoldingModal tests) | ❌ Wave 0 |
| XFER-03 | `cash_amount` defaults to `quantity × price` but is independently editable before submit | e2e (route-mocked) | same describe block, dedicated test asserting the posted body's `cash_amount` after manual edit | ❌ Wave 0 |
| D-07 (all 3) | Form-level preview line renders the correct plain-language money-impact string before submit is enabled/clicked | e2e (route-mocked), can be folded into each endpoint's own test above via a `getByText(...)` assertion before clicking submit | same commands as above | ❌ Wave 0 (covered inline, not a separate file) |

### Sampling Rate
- **Per task commit:** `npx playwright test <changed-spec-file>`
- **Per wave merge:** `npm run e2e` (from `ui/`) — full suite, catches regressions
  in the 4 pre-existing out-of-scope e2e failures already logged in
  `.planning/phases/16-ui-extend-existing-components/deferred-items.md` (do not
  attempt to fix those in this phase; they're documented as pre-existing).
- **Phase gate:** Full suite green (modulo the already-documented pre-existing
  failures) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `ui/e2e/cashflow-crud.spec.ts` — add `test.describe("balance adjustment (ACCT-02)")`
      block, route-mocking `POST /api/accounts/*/adjust-balance` (success + 422 cases),
      reusing the existing `mockCashflowSummary`-style fixture helper already in this
      file so `current_balance` is present on the account row the dialog reads.
- [ ] `ui/e2e/platform-detail.spec.ts` — add `test.describe("Deposit cash (XFER-02)")`
      and `test.describe("funded buy/sell (XFER-03)")` blocks, mocking
      `GET /api/accounts`, `POST /api/transactions/investment-transfer`, and
      `POST /api/portfolio-events/funded-{buy,sell}` following this file's existing
      `mockPlatformDetail`/`mockPortfolioEvents` helper-function convention (see
      `platform-detail.spec.ts:64-93`, verified read).
- [ ] No new fixtures/conftest needed — Playwright route-mocking is fully
      self-contained per-file, matching the existing convention (no shared fixture
      file exists in `ui/e2e/` today, and none is needed here).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Single-user, no auth system in this app (unchanged by this phase) |
| V3 Session Management | No | N/A |
| V4 Access Control | Yes | All 4 write routes already gate on `require_api_key` (`Depends(require_api_key)`, confirmed present on every route this phase calls) — the UI must call them ONLY through the existing `/api/...` Next.js proxy, which injects `MONAI_API_KEY` server-side and never exposes it to the browser bundle (confirmed: `ui/app/api/[...proxy]/route.ts` reads `process.env.MONAI_API_KEY`, not a `NEXT_PUBLIC_` var). Never hardcode or client-fetch the key. |
| V5 Input Validation | Yes | Pydantic schemas (`BalanceAdjustmentCreate`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`) already enforce `gt=0` on every unsigned-magnitude field server-side; the UI's `required`/`type="number"` HTML attributes are a UX nicety only, never the security boundary — already the established pattern (`HoldingModal.tsx`'s existing fields work the same way). |
| V6 Cryptography | No | No crypto operations introduced by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent duplicate-account creation via account-name typo (Pitfall 2) | Tampering (data-integrity, not classic security) | Populate account `<select>` fields exclusively from a fresh `GET /accounts` fetch, never free text — already the mitigation this research recommends structurally |
| API key exposure via a `NEXT_PUBLIC_`-prefixed env var or a client-side fetch bypassing the proxy | Information Disclosure | Always call `/api/...` (the proxy), never `MONAI_API` (the raw backend base URL) directly from a client component — already enforced by every existing modal/page in this codebase; this phase must not deviate |
| Amount/quantity/price manipulation via devtools before submit | Tampering | Server-side `gt=0` Pydantic validation is authoritative (already in place); client validation is defense-in-depth only |

## Sources

### Primary (HIGH confidence)
- `backend/schemas.py` (lines 51-57, 190-288) — verified by direct read this session:
  `AccountOut`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`,
  `BalanceAdjustmentCreate` exact field names/types
- `backend/main.py` (lines 220-320, 420-550, 828-857, 1050-1101) — verified by
  direct read this session: all 4 route handlers, their response shapes, error
  mapping, and `GET /cashflow/summary`/`GET /accounts` reads
- `backend/writes.py` (lines 1-338) — verified by direct read this session: every
  `apply_add_*` primitive this phase's endpoints call, including the
  `_get_or_create_account` auto-create behavior (Pitfall 2) and the unfiltered-SUM
  delta computation (Pitfall 1)
- `backend/tools.py` (lines 474-518) — verified by direct read this session:
  `account_balances()`'s exact SQL and the 2026-08-02 all-time-SUM fix
- `backend/tests/test_write_endpoints.py` (lines 153-403) — verified by direct read
  this session: exact request bodies + assertions for all 4 endpoints, including the
  422 nonexistent-platform and zero-cash-amount cases
- `ui/app/cashflow/AccountManager.tsx`, `ui/app/investments/HoldingModal.tsx`,
  `ui/app/cashflow/ConfirmDialog.tsx`, `ui/app/investments/[platformId]/page.tsx`,
  `ui/app/investments/page.tsx`, `ui/app/cashflow/page.tsx`, `ui/app/styles.ts`,
  `ui/app/api/[...proxy]/route.ts` — all read in full this session
- `ui/e2e/platform-detail.spec.ts`, `ui/e2e/cashflow-crud.spec.ts` — read this
  session for the route-mocking / fixture-helper conventions
- `npm view next version` / `npm view react version` — run this session, confirms
  16.2.12 / 19.2.8 installed (CLAUDE.md's documented 14.2.15/18.3.1 versions are
  stale relative to the live `node_modules`; the installed versions are what
  matters for this phase, not CLAUDE.md's possibly-outdated doc)

### Secondary (MEDIUM confidence)
- None used — every claim in this document traces to a direct file read or a live
  registry check in this session (no WebSearch was needed; this is a pure
  same-codebase composition phase).

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all versions confirmed live via `npm view`
- Architecture: HIGH — every pattern and file cited was read directly this session, not inferred
- Pitfalls: HIGH — all 5 pitfalls trace to specific, quoted lines of existing backend code read this session (not speculative)

**Research date:** 2026-08-03
**Valid until:** Stable until the next backend touch to `writes.py`/`schemas.py`/`main.py` for these 4 routes (no expiry driven by external ecosystem drift — internal-only phase)
