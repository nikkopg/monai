# Phase 16: UI — Extend Existing Components - Pattern Map

**Mapped:** 2026-08-01
**Files analyzed:** 4 (3 modify + 1 e2e extend/new)
**Analogs found:** 4 / 4 (all in-place edits of files that already exist — "analog" here means the file's own current code plus one cross-file pattern source for the segmented control)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `ui/app/cashflow/TransactionModal.tsx` | component (modal/form) | request-response (CRUD, dual endpoint) | itself (baseline) + `ui/app/settings/page.tsx` for the segmented control | exact (self) / exact (segment control source) |
| `ui/app/cashflow/AccountManager.tsx` | component (CRUD manager) | CRUD | itself (baseline); structural sibling `ui/app/investments/PlatformManager.tsx` | exact (self) |
| `ui/app/investments/PlatformManager.tsx` | component (CRUD manager) | CRUD | itself (baseline); structural sibling `ui/app/cashflow/AccountManager.tsx` (mirror it copied `kind` editing from) | exact (self) |
| `ui/e2e/cashflow-crud.spec.ts` (extend) + `ui/e2e/platform-crud.spec.ts` (new) | test (e2e) | request-response (route-mocked) | `ui/e2e/cashflow-crud.spec.ts` (existing "account reassign-then-delete" test) | exact |

All three production files are **self-analogs** — this is an EXTEND phase, not a new-component phase. The only true cross-file pattern borrow is the segmented control (`settings/page.tsx` → `TransactionModal.tsx`).

## Pattern Assignments

### `ui/app/cashflow/TransactionModal.tsx` (component, request-response)

**Analog for segmented control:** `ui/app/settings/page.tsx` L227-264 (UIR-07 provider selector)

**Import fix required (Pitfall 3):**
```typescript
// BEFORE (current TransactionModal.tsx):
import { card, input, btn, label } from "../styles";
// AFTER — tokens must be added, it is not currently imported:
import { tokens, card, input, btn, label } from "../styles";
```

**Segmented control pattern to copy verbatim (swap `PROVIDERS` → `["expense","income","transfer"] as const`, swap `handleProviderChange` → segment setter):**
```typescript
// Source: ui/app/settings/page.tsx L227-264
<div
  style={{
    display: "inline-flex",
    background: tokens.color.sidebar,
    border: `1px solid ${tokens.color.border2}`,
    borderRadius: 12,
    padding: 4,
    marginBottom: 18,
  }}
>
  {RECORD_TYPES.map((t) => {
    const active = segment === t;
    return (
      <button
        key={t}
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setSegment(t)}
        style={{
          border: "none",
          borderRadius: 9,
          padding: "8px 18px",
          fontSize: 14,
          fontWeight: active ? 600 : 500,
          cursor: disabled ? "default" : "pointer",
          color: active ? tokens.color.ink : tokens.color.muted,
          background: active ? "#fff" : "transparent",
          boxShadow: active ? "0 1px 2px rgba(40,34,24,.12)" : "none",
          opacity: disabled ? 0.5 : 1,
          transition: "all .2s ease",
        }}
      >
        {t[0].toUpperCase() + t.slice(1)}
      </button>
    );
  })}
</div>
```

**Sign-derivation pattern (D-02, new helper, replaces raw `parseFloat(amount)` at current line ~158):**
```typescript
function signedAmount(magnitude: string, segment: "expense" | "income" | "transfer"): number {
  const n = Math.abs(parseFloat(magnitude));
  return segment === "expense" ? -n : n;
}
```

**Edit-mode reverse-mapping (segment + amount initializers):**
```typescript
const [segment, setSegment] = useState<"expense" | "income" | "transfer">(() => {
  if (editingTx?.is_transfer) return "transfer"; // locked/disabled, see below
  if (editingTx) return editingTx.amount < 0 ? "expense" : "income";
  return "expense"; // D-01 default, create mode
});
const [amount, setAmount] = useState(editingTx ? String(Math.abs(editingTx.amount)) : "");
```

**Category-cell visibility guard (D-04) — conditional render, keyed on segment:**
```typescript
{segment !== "transfer" && (
  <div>
    <label style={label}>Category</label>
    <select style={input} value={categorySelection} onChange={(e) => setCategorySelection(e.target.value)}>
      {/* unchanged, flattenCategories()-driven options, system nodes already excluded */}
    </select>
  </div>
)}
```
Edit-mode-transfer-lock exception (UI-SPEC Interaction States #7): when `editingTx?.is_transfer`, category cell IS shown (row may carry pre-phase category data) — this is the one case where the segment !== "transfer" guard does NOT apply.

**From/To account selects (D-03), swap for single Account select:**
```typescript
{segment === "transfer" && !isEdit ? (
  <>
    <div>
      <label style={label}>From account</label>
      <select style={input} value={fromAccountId} onChange={(e) => setFromAccountId(e.target.value)}>
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
    </div>
    <div>
      <label style={label}>To account</label>
      <select style={input} value={toAccountId} onChange={(e) => setToAccountId(e.target.value)}>
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
    </div>
  </>
) : (
  <div>
    <label style={label}>Account</label>
    <select style={input} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
      {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  </div>
)}
```
Client-side guard (cheap, no server check exists): block submit if `fromAccountId === toAccountId` with inline error "From and To accounts must be different." (same error-span styling as existing error text).

**Submit branching (D-03) — build the transfer body from an explicit whitelist, never spread general form state (Pitfall 2):**
```typescript
if (segment === "transfer" && !isEdit) {
  const fromAcc = accounts.find((a) => String(a.id) === fromAccountId);
  const toAcc = accounts.find((a) => String(a.id) === toAccountId);
  const body = {
    from_account: fromAcc?.name ?? "",
    to_account: toAcc?.name ?? "",
    amount: Math.abs(parseFloat(amount)),
    currency,
    date: new Date(date).toISOString(),
    notes: notes || null,
  };
  const r = await fetch("/api/transactions/transfer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // same ok/error handling convention as existing transaction submit
  return;
}
// Expense/Income (create or edit), and edit-mode-transfer-lock (is_transfer:true hardcoded):
// existing POST/PUT /api/transactions path, amount = signedAmount(amount, segment),
// currency added to body, is_transfer explicit boolean (false normally, true when
// editingTx?.is_transfer is true — the checkbox that used to carry this is removed).
```
Never route an edit through `/transactions/transfer` — there is no `PUT /transactions/transfer/{id}` (Pitfall 1 / Anti-Pattern).

**"Save & add another" (D-06) — two submit buttons sharing one handler, distinguished by a small state flag set onClick:**
```typescript
const [addAnother, setAddAnother] = useState(false);
// button row: <button type="submit" onClick={() => setAddAnother(false)}>Add transaction / Add transfer / Save changes</button>
//             {!isEdit && <button type="submit" onClick={() => setAddAnother(true)}>Save & add another</button>}
// in handleSubmit's success branch:
if (addAnother) {
  setAmount("");
  setCategorySelection("");
  setNotes("");
  // segment, accountId/fromAccountId/toAccountId, date, currency all untouched
} else {
  onSaved();
  onClose();
}
onSaved(); // always fires regardless of branch, so parent refetch (Pattern 5) runs even on "add another"
```
Create-mode only — do not render "Save & add another" when `isEdit`.

**Error handling pattern (unchanged convention, apply to transfer branch too):**
```typescript
// "Couldn't save transaction: {detail}. Nothing was changed." (existing)
// "Couldn't save transfer: {detail}. Nothing was changed." (new, same shape, for the transfer branch)
```

**Currency field (D-05) — plain text input, not select, defaulting to "IDR" (no server-side enum on either endpoint):**
```typescript
<div>
  <label style={label}>Currency</label>
  <input style={input} type="text" value={currency} onChange={(e) => setCurrency(e.target.value)} />
</div>
```

**Deleted entirely:** `is_transfer` checkbox cell and its state — removed from UI; field still exists in the schema and must be sent explicitly (`true` only in the edit-mode-transfer-lock branch, `false` otherwise).

---

### `ui/app/cashflow/AccountManager.tsx` (component, CRUD)

**Analog:** itself, current `saveAdd` (baseline ~L44-49)

**The entire diff (D-07) — one field added to the create POST body only:**
```typescript
// BEFORE
const r = await fetch("/api/accounts", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: newName }),
});
// AFTER
const r = await fetch("/api/accounts", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: newName, type: "liquid" }),
});
```
`saveEdit` is NOT touched — stays `{ name: editName }` exactly as today (Pitfall 4: do not add a type picker or make `type` editable, explicitly out of scope / deferred). No other change to this file — table, `ConfirmDialog` 422→reassign flow, `extractDetail()`, and all copy stay byte-identical.

---

### `ui/app/investments/PlatformManager.tsx` (component, CRUD)

**Analog:** itself, current edit-row state/handlers (baseline `editName` state, `saveEdit` L~68-75, edit-row click handler L~211-214, edit-row JSX L~166-171) plus its own Add-form's existing `newKind` input (L~252-257) as the visual/prop template to mirror.

**The diff (D-08) — add `editKind` state, seed it, send it, render it:**
```typescript
// ADD alongside editName:
const [editKind, setEditKind] = useState("");

// Edit-row entry point (the "Edit" span onClick that currently seeds editName) — ADD:
onClick={() => {
  setEditingId(p.id);
  setEditName(p.name);
  setEditKind(p.kind ?? "");   // NEW
}}

// saveEdit body:
// BEFORE:  body: JSON.stringify({ name: editName }),
// AFTER:   body: JSON.stringify({ name: editName, kind: editKind || null }),

// Edit-row JSX — add a second <input>, styled/placeholder identical to the
// Add-form's newKind input:
<input
  style={{ ...input, width: 160 }}
  placeholder="e.g. brokerage, crypto app"
  value={editKind}
  onChange={(e) => setEditKind(e.target.value)}
/>
```
No other change — table structure, delete/reassign flow (`DeleteFlowState`, `extractDetail()`, `ConfirmDialog`), and empty-state copy stay exactly as today.

---

### `ui/e2e/cashflow-crud.spec.ts` (extend) + `ui/e2e/platform-crud.spec.ts` (new)

**Analog:** `ui/e2e/cashflow-crud.spec.ts` existing "account reassign-then-delete" test — route-mocked (`page.route(...)`) Playwright pattern, no live backend.

**Structural copy for the new platform spec:** mirror the account-reassign test's structure (route-mock `/api/platforms`, add → edit (now including `kind`) → delete-with-422-reassign) 1:1, swapping `account`/`accounts` for `platform`/`platforms` and asserting the `kind` field round-trips through edit.

**Extensions needed to `cashflow-crud.spec.ts`** (per RESEARCH.md Wave 0 Gaps — not new patterns, additions to the existing test file using the existing route-mock idiom):
1. segmented-control default-Expense assertion
2. Expense submit posts negative signed amount from unsigned input
3. Income submit posts positive amount
4. Transfer segment hides category picker, posts to `/api/transactions/transfer` with unsigned amount + from/to account names
5. currency field defaults to IDR, included in POST body
6. "Save & add another" keeps modal open, resets amount/category/notes, preserves segment/account/date
7. editing a non-transfer row reverse-maps sign→segment correctly
8. editing a transfer-tinted row locks the segmented control (Pitfall 1 resolution)

No new test framework or config needed — `ui/playwright.config.ts` already covers `e2e/*.spec.ts` globbing.

---

## Shared Patterns

### Inline-style token convention (`ui/app/styles.ts`)
**Source:** `card`, `input`, `btn`, `label`, `tokens` exports (already imported by all three target files except `TransactionModal.tsx`, which needs `tokens` added)
**Apply to:** every new element in all three files — no Tailwind, no CSS Modules, no new styling abstraction (v1.1 locked decision, reaffirmed in CONTEXT.md/RESEARCH.md/UI-SPEC.md).

### 422→`affected_count` reassign flow
**Source:** identical implementation in `AccountManager.tsx` and `PlatformManager.tsx` (`DeleteFlowState`, `extractDetail()`, `ConfirmDialog.tsx`)
**Apply to:** neither file's delete flow is touched this phase — flagged only so the planner does not accidentally re-derive or "fix" it while making the D-07/D-08 edits nearby.

### Error copy convention
**Source:** existing `"Couldn't save {noun}: {detail}. Nothing was changed."` pattern in all three managers/modal
**Apply to:** new transfer-branch error text in `TransactionModal.tsx` — reuse the exact sentence shape, noun = "transfer".

### `onChanged()` / `onSaved()` parent-refetch (Pattern 5, project-wide convention)
**Source:** all three components already call this prop on successful mutation
**Apply to:** must fire in both "Save" and "Save & add another" success paths in `TransactionModal.tsx` (not just the close path) so the parent `cashflow/page.tsx` list refreshes even when the modal stays open for rapid entry.

### `flattenCategories()` / `toLocalDatetimeInputValue()` helpers (already in `TransactionModal.tsx`)
**Source:** `TransactionModal.tsx` L22 (`flattenCategories`) and L68 (`toLocalDatetimeInputValue`)
**Apply to:** both stay unchanged and are reused as-is; do not reimplement or move them.

## No Analog Found

None — this is a pure extend-in-place phase; every touched file already exists with the exact structure needed, and the one cross-file pattern (segmented control) has a direct, verbatim-copyable source.

## Metadata

**Analog search scope:** `ui/app/cashflow/`, `ui/app/investments/`, `ui/app/settings/`, `ui/app/styles.ts`, `ui/e2e/`
**Files scanned:** `TransactionModal.tsx`, `AccountManager.tsx`, `PlatformManager.tsx`, `settings/page.tsx`, `ConfirmDialog.tsx`, `styles.ts`, `cashflow-crud.spec.ts` (via graphify graph query + RESEARCH.md/UI-SPEC.md verbatim excerpts, cross-checked against graphify's dependency graph — no re-reads of already-excerpted ranges)
**Pattern extraction date:** 2026-08-01
