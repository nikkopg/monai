# Phase 18: UI Entry Points — Pattern Map

**Mapped:** 2026-08-03
**Files analyzed:** 6 (3 modified existing, 1 new modal component recommended, e2e specs extended)
**Analogs found:** 6 / 6 (this is a UI-only phase extending an already-locked design system; every file has a direct in-codebase analog, no gaps)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `ui/app/cashflow/AccountManager.tsx` (MODIFY — add "Adjust balance" action + dialog) | component | request-response (form submit) | itself (existing edit/delete row-action pattern in same file) + `ConfirmDialog.tsx` (children-slot) | exact |
| NEW inline balance-adjust dialog (recommend: new local component `ui/app/cashflow/AdjustBalanceModal.tsx`, or an inline conditional block inside `AccountManager.tsx` — planner's call per CONTEXT Claude's Discretion) | component (modal) | request-response | `ui/app/investments/HoldingModal.tsx` (overlay shell) | exact |
| `ui/app/investments/[platformId]/page.tsx` (MODIFY — add "Deposit cash" header action + modal) | component (page + modal) | request-response | `ui/app/investments/page.tsx` (page hosting `HoldingModal` + `load()` refetch) | exact |
| NEW deposit-cash modal (recommend: `ui/app/investments/DepositCashModal.tsx`) | component (modal) | request-response | `ui/app/investments/HoldingModal.tsx` (whole-file analog: shell, form grid, submit/error handling) | exact |
| `ui/app/investments/HoldingModal.tsx` (MODIFY — add funding-account selector + funded routing) | component (modal) | request-response | itself (extend in place) | exact |
| NEW Playwright specs (extend `ui/e2e/cashflow-crud.spec.ts`, `ui/e2e/platform-detail.spec.ts`) | test | request-response (route-mocked) | same files' existing `test.describe` blocks + `mockPlatformDetail`/`mockPortfolioEvents` helpers (`platform-detail.spec.ts:64-93`) | exact |

## Pattern Assignments

### `ui/app/cashflow/AccountManager.tsx` — add "Adjust balance" (ACCT-02)

**Analog:** itself (existing row-action pattern, lines 196-213) + `ConfirmDialog.tsx` (dialog shell, if reusing children-slot instead of a new modal)

**Imports pattern** (already present, lines 1-6):
```typescript
"use client";
import { useState } from "react";
import { card, input, btn, label } from "../styles";
import ConfirmDialog from "./ConfirmDialog";
```

**Row-action pattern to copy for "Adjust balance" trigger** (lines 196-213 — insert a third `<span role="button">` between Edit and Delete):
```typescript
<span
  role="button"
  onClick={() => {
    setEditingId(a.id);
    setEditName(a.name);
  }}
  style={{ color: "#8b8474", cursor: "pointer", marginRight: 12, fontSize: 12 }}
>
  Edit
</span>
<span
  role="button"
  onClick={() => setDeleteFlow({ stage: "confirm", account: a })}
  style={{ color: "#b5503f", cursor: "pointer", fontSize: 12 }}
>
  Delete
</span>
```
UI-SPEC pins the new "Adjust balance" span at `color: tokens.color.muted3`, 12px, same weight class as Edit (non-destructive) — insert between these two.

**Error-copy helper — reuse verbatim, do not duplicate** (lines 296-308, already in this file):
```typescript
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
Call site pattern to copy for the new submit handler (mirrors `saveEdit`, lines 67-89):
```typescript
async function saveAdjustment(accountId: number, targetBalance: number) {
  setError(null);
  try {
    const r = await fetch(`/api/accounts/${accountId}/adjust-balance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_balance: targetBalance }),
    });
    if (r.ok) {
      onChanged();
    } else {
      const detail = await extractDetail(r);
      setError(`Couldn't save adjustment: ${detail}. Nothing was changed.`);
    }
  } catch (e) {
    setError(`Couldn't save adjustment: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
  }
}
```

**Data needed:** `Account` type in this file only has `{id, name}` — the delta preview needs `current_balance`, which the file's own comment (line 18-20) confirms is available if the parent passes the richer `GET /cashflow/summary` per-account rows instead of `GET /accounts`. Planner must either (a) widen the `Account` type / `Props.accounts` shape to optionally carry `current_balance`, or (b) have the new dialog do its own tiny lookup from a `summary` prop passed down from `cashflow/page.tsx`. RESEARCH.md D-02 confirms no new backend read is needed — `current_balance` already flows through `GET /cashflow/summary`.

---

### NEW balance-adjust dialog (ACCT-02)

**Analog:** `ui/app/investments/HoldingModal.tsx` overlay shell (lines 102-121) — copy the backdrop/card/heading structure verbatim, replace the form body with a single `target_balance` input + delta-preview line.

**Shell to copy (verbatim, lines 102-121):**
```typescript
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
    <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>
      {/* "Adjust balance — {account name}" per UI-SPEC */}
    </h2>
    <form onSubmit={handleSubmit}>{/* single target_balance input */}</form>
  </div>
</div>
```

**Cancel/Submit button row to copy (lines 224-247)** — same transparent-Cancel + `btn`-primary-Submit + inline error span pattern; swap `disabled={saving || platforms.length === 0}` for `disabled={saving || delta === 0}` per UI-SPEC's "submit disabled when delta===0" rule.

**Delta-preview logic (new, per UI-SPEC copy contract):**
```typescript
const delta = parseFloat(targetBalance || "0") - currentBalance;
// delta > 0 -> `Adjustment: +Rp ${fmtPlain(delta)}` in tokens.color.green
// delta < 0 -> `Adjustment: −Rp ${fmtPlain(Math.abs(delta))}` in tokens.color.terracotta (U+2212 minus, not hyphen)
// delta === 0 -> "No change — target equals current balance." in tokens.color.muted, submit disabled
```
`fmtPlain`/`Intl.NumberFormat("en-US")` grouping helper: copy the local definition already used in `investments/[platformId]/page.tsx` / `investments/page.tsx` (not exported — redefine locally, matches existing per-file convention, no shared util module in this codebase).

**Submit body:** `{ target_balance: parseFloat(targetBalance) }` — no `min`/`gt=0`, accepts zero/negative (`BalanceAdjustmentCreate` has no such constraint). No `date` field (schema has none).

---

### `ui/app/investments/[platformId]/page.tsx` — "Deposit cash" (XFER-02)

**Analog:** `ui/app/investments/page.tsx` lines 771-777 for the modal-mount + `onSaved={load}` refetch pattern:
```typescript
{showEvent && (
  <HoldingModal
    platforms={platformOptions}
    onClose={() => setShowEvent(false)}
    onSaved={load}
  />
)}
```
Mirror this exactly for the new `DepositCashModal`: `{showDeposit && <DepositCashModal platformId={...} platformName={...} onClose={...} onSaved={load} />}`.

**Header trigger placement:** per UI-SPEC, near the `<h1>` platform name, above the stat-card grid; style = `btn` (primary green), copy = `Deposit cash`.

**Pitfall (RESEARCH Pitfall 3):** this page currently fetches only `GET /platforms/{id}/detail` and `GET /portfolio-events?platform_id=` — no account fetch exists. The new modal must own its own `GET /accounts` fetch on mount (matches `HoldingModal`'s prop-in convention is NOT available here since the page has no accounts state yet; a modal-owned `useEffect` fetch, mirroring `CsvUpload`'s self-contained-fetch precedent, is the simplest option — ladder rung: one `useEffect` + `fetch`, no new shared hook).

---

### NEW `DepositCashModal` (XFER-02)

**Analog:** `HoldingModal.tsx` — copy the whole shell/skeleton (imports, overlay, card, heading, form grid, button row, error handling), swap the field set to: `From account` (`<select>`, liquid-filtered), `Amount`, `Currency` (default `IDR`), `Date` (`<input type="date">`, NOT `datetime-local` — RESEARCH Pitfall 5 / UI-SPEC date-field table says `InvestmentTransferCreate.date` is `str | None`, send the `YYYY-MM-DD` value as-is, no `.toISOString()` truncation needed since native `<input type="date">` already yields that format), `Notes` (optional text).

**Submit:**
```typescript
const body = {
  from_account: fromAccountName,       // exact name string from the <select>, never free text
  platform_id: platformId,             // number, from route
  amount: parseFloat(amount),
  currency: currency || "IDR",
  date: date || undefined,             // already YYYY-MM-DD from <input type="date">
  notes: notes || undefined,
};
const r = await fetch("/api/transactions/investment-transfer", { method: "POST", headers: {...}, body: JSON.stringify(body) });
```
Error copy: `Couldn't deposit cash: ${detail}. Nothing was changed.` (same `extractDetail`-style helper as `AccountManager.tsx`/`HoldingModal.tsx`).

**Empty-state pattern to copy verbatim (`HoldingModal.tsx` lines 169-173):**
```typescript
{platforms.length === 0 && (
  <p style={{ ...label, fontSize: 11, marginTop: 4, color: "#b5503f" }}>
    Add a platform first
  </p>
)}
```
Reuse for: `No liquid accounts yet — add one in Cashflow before depositing cash.` — same style, disable submit while true.

**Preview line (new, per UI-SPEC):** `Moves Rp {fmtPlain(amount)} from {account name} into {platform name}.` in neutral ink (`tokens.color.text`), not green/terracotta.

---

### `ui/app/investments/HoldingModal.tsx` — funding selector (XFER-03)

**Analog:** itself — extend in place, following its own existing `<select>` field pattern (Platform field, lines 155-174) for the new "Funding account" field.

**New field to add (mirrors the Platform `<select>` block above, lines 155-174):**
```typescript
<div>
  <label style={label}>Funding account</label>
  <select
    style={input}
    value={fundingAccount}
    onChange={(e) => setFundingAccount(e.target.value)}
  >
    <option value="">— none (unfunded) —</option>
    {liquidAccounts.map((a) => (
      <option key={a.id} value={a.name}>{a.name}</option>
    ))}
  </select>
</div>
```

**cash_amount default-then-editable field (new, conditionally rendered when `fundingAccount !== ""`):**
```typescript
const [cashAmount, setCashAmount] = useState("");
const [cashAmountTouched, setCashAmountTouched] = useState(false);
// re-sync only when quantity/price change AND the user hasn't manually edited cash_amount
useEffect(() => {
  if (!cashAmountTouched && quantity && price) {
    setCashAmount(String(parseFloat(quantity) * parseFloat(price)));
  }
}, [quantity, price]);
```

**Routing logic in `handleSubmit` (extends the existing single-path submit, lines 58-100):**
```typescript
if (fundingAccount) {
  const endpoint = eventType === "sell" ? "/api/portfolio-events/funded-sell" : "/api/portfolio-events/funded-buy";
  const body = {
    source_account_name: fundingAccount,
    platform_id: parseInt(platformId, 10),
    ticker: ticker.trim(),
    quantity: parseFloat(quantity),
    price: parseFloat(price),
    cash_amount: parseFloat(cashAmount),
    cash_currency: "IDR",
    event_currency: "IDR",
    date: new Date(date).toISOString().slice(0, 10),   // unchanged truncation, both paths
    notes: notes || undefined,
    asset_type: assetType,
  };
  // fetch(endpoint, ...), error copy: `Couldn't log funded ${eventType}: ${detail}. Nothing was changed.`
} else {
  // existing unfunded /api/portfolio-events path, unchanged (lines 64-96)
}
```
Note: `eventType === "dividend"` has no funded path — schema only has funded-buy/funded-sell; keep funding selector irrelevant/hidden or ignored when `eventType === "dividend"` (planner should clarify submit-button label logic accordingly, per UI-SPEC's "Log funded Buy/Sell" vs "Log event" CTA table).

**Preview line (new, per UI-SPEC, only shown when `fundingAccount` set):**
```typescript
eventType === "sell"
  ? `Credits ${fundingAccount} Rp ${fmtPlain(cashAmount)}, −${quantity} ${ticker}`   // terracotta
  : `Debits ${fundingAccount} Rp ${fmtPlain(cashAmount)}, +${quantity} ${ticker}`     // green
```

**Liquid-account fetch:** modal-owned `useEffect` + `fetch("/api/accounts")`, client-filter `.filter(a => a.type === "liquid")` — same as `DepositCashModal`'s fetch (RESEARCH D-04, "Don't Hand-Roll" table).

**`defaultPlatformId` prop (per UI-SPEC's platform-detail trigger site):**
```typescript
type Props = {
  platforms: PlatformOption[];
  onClose: () => void;
  onSaved: () => void;
  defaultPlatformId?: number;   // NEW — pre-select, not lock
};
// const [platformId, setPlatformId] = useState<string>(
//   defaultPlatformId ? String(defaultPlatformId) : (platforms.length > 0 ? String(platforms[0].id) : "")
// );
```

---

### NEW Playwright specs (extend existing files)

**Analog:** `ui/e2e/platform-detail.spec.ts` lines 64-93 (`mockPlatformDetail`/`mockPortfolioEvents` helper-function convention) and the existing `test.describe` blocks in both `cashflow-crud.spec.ts` and `platform-detail.spec.ts`.

**Pattern to copy:** route-mock via `page.route("**/api/...", ...)`, one `test.describe` block per new flow (per RESEARCH's Wave 0 Gaps): `"balance adjustment (ACCT-02)"` in `cashflow-crud.spec.ts`; `"Deposit cash (XFER-02)"` and `"funded buy/sell (XFER-03)"` in `platform-detail.spec.ts`. No new fixture file — self-contained per-file mocking is the established convention (no shared fixtures directory exists today).

---

## Shared Patterns

### Modal overlay shell
**Source:** `ui/app/investments/HoldingModal.tsx:102-121`
**Apply to:** balance-adjust dialog, deposit-cash modal (both new), and the HoldingModal extension (already has it).
Fixed-inset `rgba(15,17,21,0.72)` backdrop, `zIndex: 100`, `onClick={onClose}` on backdrop / `stopPropagation` on card, `{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }` card override, `<h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>` heading.

### Cancel/Submit button row
**Source:** `ui/app/investments/HoldingModal.tsx:224-247`
**Apply to:** all 3 surfaces.
Transparent muted Cancel button + `btn`-styled primary submit showing `"Saving…"` while `saving`, inline `<span style={{ color: "#b5503f", fontSize: 12 }}>{error}</span>` next to the buttons — never a separate error block above the form.

### Error-copy convention + `extractDetail` helper
**Source:** `ui/app/cashflow/AccountManager.tsx:296-308`
**Apply to:** all 3 new/modified submit handlers.
`` `Couldn't {verb}: ${detail}. Nothing was changed.` `` — verb varies per surface ("save adjustment", "deposit cash", "log funded buy/sell"). Reuse the exact `extractDetail(r: Response)` function body verbatim (string-or-nested-message branch), do not write a second copy of it per file — copy-paste is the established per-file convention here (no shared utils module exists), but keep the function body byte-identical.

### Refetch-after-write (Pattern 5)
**Source:** `ui/app/investments/page.tsx:771-777`
**Apply to:** all 3 writes — never optimistic local mutation. `AccountManager` takes `onChanged`; new investments modals take `onSaved`, wired to the hosting page's `load()`.

### Account `<select>`-only rule (money-safety, not a style choice)
**Source:** RESEARCH.md Pitfall 2 / UI-SPEC "Hard rule" section
**Apply to:** every account-selection field on all 3 surfaces — always populate from a fresh `GET /accounts` fetch, filter `type === "liquid"` client-side, submit the exact `name` string. Never a free-text `<input>` — `_get_or_create_account` silently creates a duplicate account on any mismatch.

### Date-field handling (per-endpoint, do not conflate)
**Source:** UI-SPEC "Date field types" table / RESEARCH Pitfall 5
- Balance adjustment: no date field at all.
- Deposit cash: `<input type="date">`, send value as-is (already `YYYY-MM-DD`).
- Funded buy/sell (extends `HoldingModal`'s existing field): keep the existing `datetime-local` input + `.toISOString().slice(0, 10)` truncation (lines 213-220, 69) — do not add a second date-input variant, applies to both funded and unfunded submit paths.

### Numeric coercion
**Source:** `ui/app/investments/HoldingModal.tsx:67-71` (`parseFloat(quantity)`, `parseFloat(price)`)
**Apply to:** every numeric field across all 3 surfaces (`target_balance`, `amount`, `cash_amount`, `quantity`, `price`) — always `parseFloat(...)` before sending, never a string.

### Money formatting
**Source:** local `fmtPlain`/`fmtSigned`-style `Intl.NumberFormat("en-US")` helpers already defined per-file in `investments/[platformId]/page.tsx` and `investments/page.tsx` (no shared module — redefine locally in each new file, per existing convention).
**Apply to:** all money-preview lines. Prefix literal `"Rp "`; use `signDisplay: "always"` with U+2212 minus (not hyphen) for negative deltas.

## No Analog Found

None. Every file in scope has a direct, exact-match analog already in the codebase (RESEARCH.md confirmed zero missing-field/missing-pattern gaps for this phase).

## Metadata

**Analog search scope:** `ui/app/cashflow/`, `ui/app/investments/`, `ui/app/styles.ts`, `ui/e2e/`
**Files scanned:** `AccountManager.tsx`, `ConfirmDialog.tsx`, `HoldingModal.tsx`, `investments/page.tsx`, `investments/[platformId]/page.tsx`, `styles.ts` (all read in full this session or in RESEARCH.md's prior verified session read)
**Pattern extraction date:** 2026-08-03
