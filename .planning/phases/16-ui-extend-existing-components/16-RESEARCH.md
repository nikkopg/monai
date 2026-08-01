# Phase 16: UI — Extend Existing Components - Research

**Researched:** 2026-08-01
**Domain:** Frontend (Next.js App Router / React) — extending three existing manual-entry components, no new libraries, no backend changes
**Confidence:** HIGH

## Summary

Phase 16 is a pure internal-pattern-reuse phase: no new package, no new endpoint, no new page. Everything needed already exists in the codebase — the segmented-control pattern in `ui/app/settings/page.tsx` (UIR-07), the 422→`affected_count` reassign flow duplicated identically in `AccountManager.tsx` and `PlatformManager.tsx`, and the four backend endpoints (`POST/PUT /transactions`, `POST /transactions/transfer`, `POST/PUT /accounts`, `POST/PUT /platforms`) already shipped and stable since Phases 12-14. The work is entirely in `ui/app/cashflow/TransactionModal.tsx` (real rework, ~D-01..D-06), `AccountManager.tsx` (one-line payload change, D-07), and `PlatformManager.tsx` (one new input in the edit row, D-08).

The one landmine this research surfaced that CONTEXT.md does not address: **editing an existing transfer-leg transaction**. Today `TransactionModal` is opened in edit mode from the recent-transactions list in `cashflow/page.tsx`, which includes transfer-tinted rows (`is_transfer: true`) alongside plain expense/income rows. The stored `amount` sign on a transfer leg follows leg direction (negative for the debit leg, positive for the credit leg), not expense/income semantics — so a segment inferred purely from `amount < 0` would misclassify a credit leg as "Income". There is also no `PUT /transactions/transfer/{id}` endpoint — the pair endpoint is create-only. REC-05 ("transfer pairs display as one logical unit; editing affects both legs atomically") is explicitly Phase 17 scope. This research recommends the smallest-diff resolution: in edit mode, if `editingTx.is_transfer === true`, lock the segmented control to a disabled "Transfer" state and keep the legacy single-field Account + signed-amount-preserving edit path (`PUT /transactions`, `is_transfer: true` sent explicitly since the checkbox is removed) — never route an edit through the new pair-create endpoint. Flag this as a pitfall for the planner (see `## Common Pitfalls`).

**Primary recommendation:** Extend `TransactionModal.tsx` in place per D-01..D-06, copying the settings-page segmented-control markup verbatim (same tokens, same active/inactive styling). Compute stored `amount` client-side as `segment === "expense" ? -Math.abs(magnitude) : Math.abs(magnitude)` for Expense/Income; branch entirely to `POST /transactions/transfer` for the Transfer segment. Lock the segment to "Transfer" (disabled) when editing an existing transfer leg, keeping that path on the legacy `PUT /transactions` endpoint. `AccountManager.tsx` and `PlatformManager.tsx` need only the two payload/field additions named in D-07/D-08 — no structural changes.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Segmented Expense/Income/Transfer selection | Browser / Client (React state in `TransactionModal.tsx`) | — | Pure UI state; no server round-trip needed to pick a segment |
| Amount sign derivation (unsigned input → signed stored value) | Browser / Client | API / Backend (accepts the already-signed value) | D-02: sign is derived client-side before submit; backend schemas (`TransactionCreate.amount`) still just store whatever signed/unsigned value they're given — validation ownership stays client-side for this phase |
| Transfer atomic pair write | API / Backend (`POST /transactions/transfer` → `apply_add_transfer`) | Browser / Client (form assembly only) | Atomicity (both legs in one DB transaction) is a backend guarantee already shipped in Phase 13; the client only assembles `from_account`/`to_account`/unsigned `amount` |
| Category tree fetch + system-node filtering | Browser / Client (`flattenCategories` in `TransactionModal.tsx`) | API / Backend (`GET /categories` returns the raw tree incl. system nodes) | Filtering system nodes (Transfer, Uncategorized) out of the picker is a presentation concern; the backend already returns `is_system` per node so no new endpoint needed |
| Account/Platform CRUD + reassign-on-delete | API / Backend (`/accounts`, `/platforms` DELETE with `affected_count`) | Browser / Client (`ConfirmDialog` swap on 422) | Reassignment logic (which rows get re-pointed) is a backend transaction; the 422 body only tells the client how many rows are affected |
| "Save & add another" sticky-field reset | Browser / Client | — | Pure client-side form-state semantics — no server involvement |

## Standard Stack

No new libraries. This phase extends existing, already-installed dependencies only.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| next | 14.2.15 (installed) | App Router pages, `/api/*` proxy | Already the project's framework — no change |
| react / react-dom | 18.3.1 (installed) | Component state/rendering | Already the project's UI runtime |
| typescript | 5.6.3 (installed) | Strict typing on all touched files | Existing convention |

### Supporting
None — no new supporting packages required.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline-style + `styles.ts` tokens | Tailwind / CSS Modules / styled-components | Explicitly rejected by the v1.1 pre-roadmap decision ("Visual-only re-skin — `ui/app/styles.ts` remains the single token source, no CSS framework migration"); Phase 16 must not introduce one either |
| Hand-rolled 3-way segmented `<button>` group | A generic UI kit / headless-UI radio group | The project has zero UI-kit dependency; the existing settings-page pattern (plain buttons + active-state styling) is the established idiom and is what D-01 explicitly says to reuse |

**Installation:**
```bash
# No installation needed — no new packages this phase.
```

**Version verification:** N/A — no new packages. `package.json` (`ui/package.json`) confirms `next@14.2.15`, `react@18.3.1`, `typescript@5.6.3`, `@playwright/test@1.61.1` already installed; nothing to add or bump for this phase.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new packages (npm or otherwise) — pure extension of existing, already-audited components using already-installed dependencies. No `package.json` change is expected.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ ui/app/cashflow/page.tsx  (mount point — unchanged this phase)       │
│   modalOpen / editingTx state  ──►  <TransactionModal>               │
│   summary.accounts            ──►  <AccountManager>                  │
└─────────────┬──────────────────────────────┬─────────────────────────┘
              │                               │
              ▼                               ▼
   ┌────────────────────────┐      ┌───────────────────────────┐
   │ TransactionModal.tsx    │      │ AccountManager.tsx         │
   │  [NEW] segment state:   │      │  saveAdd(): + type:"liquid"│
   │   "expense"|"income"    │      │  (D-07 — one field added)  │
   │   |"transfer"           │      └──────────┬──────────────────┘
   │                          │                 │
   │  Expense/Income branch:  │                 ▼
   │   amount = sign(segment) │        POST/PUT /api/accounts
   │   * magnitude            │        (proxy → backend/main.py)
   │   ──► POST/PUT           │
   │       /api/transactions  │
   │                          │
   │  Transfer branch:        │      ┌───────────────────────────┐
   │   from/to account selects│      │ PlatformManager.tsx        │
   │   category picker HIDDEN │      │  [NEW] editKind state on   │
   │   ──► POST                       │  the inline edit row       │
   │       /api/transactions/  │      │  (D-08 — kind now editable)│
   │       transfer            │      └──────────┬──────────────────┘
   │                          │                  │
   │  Edit-mode transfer lock:│                  ▼
   │   editingTx.is_transfer  │         POST/PUT /api/platforms
   │   → segment disabled,    │         (proxy → backend/main.py)
   │   stays on legacy         │
   │   PUT /api/transactions   │
   └──────────────────────────┘
```

Data flow for a new record: user opens modal (create mode, default segment = Expense) → fills unsigned amount + currency + category + account + date/note → submit → client derives sign → `fetch("/api/transactions", { method: "POST", body })` → Next.js `/api/*` proxy injects `MONAI_API_KEY` → `backend/main.py:create_transaction` → `onSaved()` triggers parent `refreshAll()` (Pattern 5) → modal either closes (Save) or resets and stays open (Save & add another, D-06).

### Recommended Project Structure
No new files. All three target files stay in place:
```
ui/app/cashflow/
├── TransactionModal.tsx   # extend in place (D-01) — segmented control, sign derivation, transfer branch, currency field, "add another"
├── AccountManager.tsx     # one-line payload change (D-07)
└── PlatformManager.tsx    # (mirrored under ui/app/investments/) one input in edit row (D-08)
```

### Pattern 1: Segmented control (copy from settings/page.tsx, UIR-07)
**What:** A row of plain `<button type="button">`s inside a pill container, active button gets white background + shadow + bold text, inactive buttons are transparent.
**When to use:** Any 2-4 option exclusive-choice control where a `<select>` would be visually heavier than the design calls for.
**Example (verbatim source, adapt option array + click handler):**
```typescript
// Source: ui/app/settings/page.tsx L227-264 (UIR-07 provider selector)
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
  {PROVIDERS.map((p) => {
    const active = provider === p;
    return (
      <button
        key={p}
        type="button"
        onClick={() => handleProviderChange(p)}
        style={{
          border: "none",
          borderRadius: 9,
          padding: "8px 18px",
          fontSize: 14,
          fontWeight: active ? 600 : 500,
          cursor: "pointer",
          color: active ? tokens.color.ink : tokens.color.muted,
          background: active ? "#fff" : "transparent",
          boxShadow: active ? "0 1px 2px rgba(40,34,24,.12)" : "none",
          transition: "all .2s ease",
        }}
      >
        {p}
      </button>
    );
  })}
</div>
```
For the record-type segment, replace `PROVIDERS` with `["expense", "income", "transfer"] as const` (or `RECORD_TYPES`), and note **`TransactionModal.tsx` does not currently import `tokens`** — its import line is `import { card, input, btn, label } from "../styles";`. It must be changed to `import { tokens, card, input, btn, label } from "../styles";` to reuse this pattern verbatim.

Add a `disabled` prop wired to `isEdit && editingTx.is_transfer` (see Pitfall below) so the segment can be locked in edit mode when the underlying record is a transfer leg — set `cursor: disabled ? "default" : "pointer"`, `opacity: disabled ? 0.5 : 1`, and skip the `onClick` handler.

### Pattern 2: Unsigned magnitude → signed stored amount (D-02)
**What:** Amount input is `type="number"` with **no negative sign entry** (`min="0"` or just document the contract); sign is derived from the segment at submit time.
**When to use:** Expense/Income branch only — Transfer already takes an unsigned `amount` server-side (`TransferCreate.amount: Field(..., gt=0)`).
**Example:**
```typescript
// New helper inside TransactionModal.tsx, replaces the raw `parseFloat(amount)`
// in the current handleSubmit (line 158).
function signedAmount(magnitude: string, segment: "expense" | "income" | "transfer"): number {
  const n = Math.abs(parseFloat(magnitude));
  return segment === "expense" ? -n : n; // income and transfer both positive; transfer's sign split happens per-leg server-side
}
```

### Pattern 3: Reverse-mapping a stored signed amount into segment + magnitude (edit mode)
**What:** When `editingTx` is a plain (non-transfer) row, infer the initial segment from the stored sign.
**When to use:** `useState` initializers for `segment` and `amount` in edit mode.
**Example:**
```typescript
const [segment, setSegment] = useState<"expense" | "income" | "transfer">(() => {
  if (editingTx?.is_transfer) return "transfer"; // locked/disabled per Pitfall below
  if (editingTx) return editingTx.amount < 0 ? "expense" : "income";
  return "expense"; // D-01 default for create mode
});
const [amount, setAmount] = useState(
  editingTx ? String(Math.abs(editingTx.amount)) : ""
);
```
Note `editingTx.amount === 0` falls into the `income` branch (`< 0` is false) — harmless, zero-amount rows are an edge case with no sign to preserve either way.

### Pattern 4: Category picker visibility per segment (D-03/D-04)
**What:** Expense/Income render the existing category `<select>` (fed by `flattenCategories`, system nodes already excluded); Transfer renders nothing in that grid cell (or omits the cell entirely) since the server assigns the Transfer system category.
**When to use:** Conditional render keyed on `segment !== "transfer"`.
**Example:**
```typescript
{segment !== "transfer" && (
  <div>
    <label style={label}>Category</label>
    <select style={input} value={categorySelection} onChange={...}>
      {/* unchanged flattenCategories-driven options */}
    </select>
  </div>
)}
```

### Pattern 5: Transfer's From/To account selects (D-03)
**What:** Swap the single `Account` `<select>` for two `<select>`s (`fromAccountId`, `toAccountId`) when `segment === "transfer"`, both sourced from the same `accounts` prop.
**Example:**
```typescript
{segment === "transfer" ? (
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
Client-side guard worth adding (not in any backend schema, but cheap and prevents a silently-wrong pair): if `fromAccountId === toAccountId`, block submit with an inline error before the fetch — `TransferCreate` has no same-account check server-side (`apply_add_transfer` will happily create a self-pair).

### Pattern 6: Submit branching (D-03)
**What:** `handleSubmit` branches entirely on `segment` for URL/method/body — the Transfer branch never touches the existing `is_transfer` field or checkbox (removed).
**Example:**
```typescript
// Source: adapts backend/schemas.py TransferCreate / TransactionCreate contracts
async function handleSubmit(e: React.FormEvent) {
  e.preventDefault();
  setSaving(true);
  setError(null);
  try {
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
      // ... same ok/error handling as today, then onSaved()/onClose() or reset (D-06)
      return;
    }
    // Expense/Income (create or edit) — existing POST/PUT /api/transactions path,
    // amount now = signedAmount(amount, segment), currency added to body,
    // is_transfer explicitly false (or true+locked, see Pitfall) since the
    // checkbox is gone.
  } finally {
    setSaving(false);
  }
}
```

### Pattern 7: "Save & add another" (D-06)
**What:** A second `<button type="submit">` (or a shared handler distinguishing which button was clicked via a data attribute / `formTarget`-style state) that, on success, resets `amount`/`categorySelection`/`notes` to blank but preserves `segment`, `accountId`/`fromAccountId`/`toAccountId`, and `date`, and does **not** call `onClose()`.
**Recommended implementation:** two submit buttons sharing one `handleSubmit`, distinguished by which one was clicked — use a small `pendingAction` ref/state set in each button's `onClick` (buttons still `type="submit"` so Enter-key submit still works and defaults to "Save").
```typescript
const [addAnother, setAddAnother] = useState(false);
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
```
Per CONTEXT.md Claude's Discretion (recommended): **create-mode only** — do not render the "Save & add another" button when `isEdit` is true (editing one record and wanting to "add another" is a confusing combination; the existing single "Save changes" button suffices).

### Anti-Patterns to Avoid
- **Re-signing the amount twice:** Do not let `is_transfer`'s old sign-of-input convention leak into the new Expense/Income magnitude field — the `placeholder="-25000"` and "(negative = expense)" label text must be removed/replaced (`placeholder="25000"`, label `"Amount"`).
- **Routing an edit through the pair-create endpoint:** There is no `PUT /transactions/transfer/{id}`. Never construct a submit path that POSTs a new pair while `isEdit` is true.
- **Building a currency `<select>` with a hardcoded enum:** Both `TransactionCreate.currency` and `TransferCreate.currency` are free-text `str = "IDR"` fields server-side — no enum validation exists. A plain text input defaulting to `"IDR"` (per D-05, "text/select left to planning discretion") is the lower-risk choice; a `<select>` would need to enumerate currencies the backend doesn't actually constrain.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Segmented/tabbed choice control | A custom radio-group component or a new shared `<SegmentedControl>` abstraction | Copy the inline pattern from `settings/page.tsx` verbatim | One other call site exists in the whole codebase; a shared component for two call sites is premature abstraction the project's own conventions don't otherwise use (no shared UI-kit exists) |
| 422→reassign delete flow | A new confirm/reassign pattern for accounts or platforms | Already implemented identically in both managers — D-07/D-08 touch **only** the add/edit payload shape, never this flow | It's already correct and tested (`cashflow-crud.spec.ts` "account reassign-then-delete") |
| Transfer atomicity | Client-side "POST leg A, then POST leg B" with manual rollback-on-failure | `POST /transactions/transfer` (already atomic, one DB transaction, Phase 13) | Re-deriving atomicity client-side would reintroduce exactly the half-written-transfer bug class Phase 13 was built to prevent |
| UTC-safe datetime-local formatting | A new date-formatting helper, or `toISOString()` on the raw value | `toLocalDatetimeInputValue()` — already in `TransactionModal.tsx` (WR-06 fix), reuse unchanged | `toISOString()` shifts by the local UTC offset; this was a fixed bug (WR-06), don't reintroduce it |

**Key insight:** Every "hard part" of this phase (atomicity, system-category exclusion, UTC-safe dates, 422 reassign) already has a battle-tested, in-repo solution. The actual net-new code is: one enum-like state variable (`segment`), one derived-sign helper, one conditional render swap (category cell / account cell), one new fetch branch, and two field additions in the two managers.

## Common Pitfalls

### Pitfall 1: Editing an existing transfer leg through the new segmented UI
**What goes wrong:** `editingTx.is_transfer === true` rows are reachable from the same "Edit" action as plain rows (recent-transactions list in `cashflow/page.tsx` renders all rows, transfer-tinted or not, with an "Edit" span). If the segmented control freely lets the user pick "Transfer" in edit mode and submit routes to `POST /transactions/transfer`, it silently **creates a brand-new pair** instead of editing the existing leg — the old leg is untouched, a new orphan pair is created, and the user sees two unrelated transactions where they expected one edit.
**Why it happens:** D-03 wires the Transfer segment to the create-only pair endpoint; nothing in CONTEXT.md's decisions accounts for edit mode intersecting with a transfer-tinted row, because full transfer-pair-aware editing is explicitly Phase 17 (REC-05: "editing or deleting affects both legs atomically — single-leg edits blocked").
**How to avoid:** In edit mode, if `editingTx.is_transfer`, initialize `segment = "transfer"` for display purposes but render the segmented control `disabled` (no `onClick`) and keep the account field as the single legacy `Account` select (not From/To) and the submit path as `PUT /transactions` with `is_transfer: true` sent explicitly in the body (the checkbox that used to carry this is removed, so the field must be preserved some other way — hardcode `true` when locked). This means the *existing* single-leg edit behavior (amount/category/notes/account editable, sign not derived-from-segment for this one case) is preserved exactly as it works today, just without the checkbox UI. Full atomic-pair edit remains Phase 17 scope.
**Warning signs:** A Playwright test or manual UAT that edits a transfer-tinted row and later finds an extra `transfer_pair_id` in the DB, or the edited leg's amount sign flipping unexpectedly.

### Pitfall 2: `flattenCategories` and system-node assumptions don't change, but the render guard must
**What goes wrong:** Forgetting to wrap the category `<select>` in `{segment !== "transfer" && ...}` — since the underlying fetch/flatten logic is untouched, the field will render fine even for Transfer, silently letting the user pick a category that's then either ignored (dead input) or, worse, accidentally included in the transfer POST body if the body-assembly code is copy-pasted carelessly.
**Why it happens:** The category state (`categorySelection`) still exists in the component regardless of segment; only the render is conditional. A careless `handleSubmit` refactor could still read `categorySelection` into the transfer body.
**How to avoid:** Build the transfer POST body from an explicit whitelist of fields (`from_account`, `to_account`, `amount`, `currency`, `date`, `notes`) — never spread a general "form state" object into it.
**Warning signs:** `TransferCreate` schema has no `category` field — sending one is silently ignored by FastAPI/Pydantic (extra fields are dropped by default), so this bug is easy to miss without an explicit test asserting the POST body shape.

### Pitfall 3: `TransactionModal.tsx` doesn't currently import `tokens`
**What goes wrong:** Copying the settings-page segmented-control JSX verbatim will fail to compile (`tokens is not defined`) because `TransactionModal.tsx`'s current import is `import { card, input, btn, label } from "../styles";` — no `tokens`.
**Why it happens:** The two files evolved independently; `settings/page.tsx` already imports `tokens` for other reasons (typography), `TransactionModal.tsx` never needed it before.
**How to avoid:** Add `tokens` to the import line as the first line of the diff.
**Warning signs:** TypeScript build failure immediately on `npm run build` / `tsc` — fast, cheap to catch, just don't forget it.

### Pitfall 4: `AccountManager.tsx`'s `saveEdit` never sent `type`, and D-07 doesn't ask it to
**What goes wrong:** A planner over-reading D-07 might try to make account `type` editable inline (matching the PlatformManager `kind` pattern from D-08) — this is explicitly **out of scope** ("edit stays name-only (account `type` is not user-switchable post-create in this phase)" and Deferred Ideas: "Editing an account's `type` … not needed this phase").
**Why it happens:** The two managers look symmetric (D-08 adds a `kind` edit input to PlatformManager), so it's tempting to mirror that into AccountManager's `type`.
**How to avoid:** D-07's only change is in `saveAdd`'s POST body (`{ name: newName, type: "liquid" }`); `saveEdit` stays `{ name: editName }` exactly as today.
**Warning signs:** A PLAN.md task that touches `AccountManager.tsx`'s edit row / `saveEdit` beyond what's already there is over-scoped for this phase.

### Pitfall 5: Currency field omission breaks the "amount + currency" literal requirement text
**What goes wrong:** REC-04's acceptance text is explicit: "amount + currency, account, category picker, date-time, note". Skipping the currency field (defaulting silently to `"IDR"` server-side without exposing it in the UI) technically satisfies the backend contract but fails the literal UI requirement and D-05's explicit instruction to "Expose a currency field beside amount".
**How to avoid:** Render a currency input/select next to amount in both the Expense/Income and Transfer branches (Transfer's `TransferCreate.currency` also defaults `"IDR"` and needs the same field), defaulting to `"IDR"`, with no FX conversion logic behind it.

## Code Examples

### Full current `TransactionModal.tsx` amount/category grid cell (baseline before diff)
```typescript
// Source: ui/app/cashflow/TransactionModal.tsx L244-270 (current, pre-Phase-16)
<div>
  <label style={label}>Amount (negative = expense)</label>
  <input
    style={input}
    type="number"
    step="any"
    required
    value={amount}
    placeholder="-25000"
    onChange={(e) => setAmount(e.target.value)}
  />
</div>
<div>
  <label style={label}>Category</label>
  <select style={input} value={categorySelection} onChange={(e) => setCategorySelection(e.target.value)}>
    <option value="">(no category)</option>
    {categoryOptions.map((o) => (
      <option key={o.name} value={o.name}>
        {`${"  ".repeat(o.depth)}${o.name}`}
      </option>
    ))}
  </select>
</div>
```

### AccountManager.tsx saveAdd — the one-line D-07 diff
```typescript
// Source: ui/app/cashflow/AccountManager.tsx L44-49 (current)
const r = await fetch("/api/accounts", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: newName }),   // BEFORE
  // body: JSON.stringify({ name: newName, type: "liquid" }),  // AFTER (D-07)
});
```

### PlatformManager.tsx saveEdit — the D-08 diff (add editKind state + input)
```typescript
// Source: ui/app/investments/PlatformManager.tsx L34-35 (current state) and L68-75 (current saveEdit)
// ADD alongside editName:
const [editKind, setEditKind] = useState("");

// saveEdit body BEFORE:
body: JSON.stringify({ name: editName }),
// AFTER (D-08) — PlatformUpdate already accepts kind, mirrors AddForm's newKind input:
body: JSON.stringify({ name: editName, kind: editKind || null }),

// Edit-row entry point (setEditingId/setEditName click handler, L211-214) must
// also seed editKind:
onClick={() => {
  setEditingId(p.id);
  setEditName(p.name);
  setEditKind(p.kind ?? "");   // NEW
}}

// Edit-row JSX (L166-171) needs a second <input> beside the name input, mirroring
// the add-form's kind input (L252-257: placeholder="e.g. brokerage, crypto app").
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Signed amount input, "negative = expense" convention + separate `is_transfer` checkbox | Unsigned magnitude + segmented Expense/Income/Transfer control, sign derived client-side | This phase (D-01/D-02/D-03) | Removes the sign-entry foot-gun (REC-04 motivation); transfer creation moves off the shared `POST /transactions` + flag path onto the dedicated atomic-pair endpoint that's existed since Phase 13 but was never wired into this modal |

**Deprecated/outdated:**
- The `isTransfer` checkbox and its `is_transfer` body field in the create/edit POST/PUT body: removed from the UI per D-03, but the underlying `TransactionCreate.is_transfer` / `TransactionUpdate.is_transfer` schema fields are NOT removed server-side — they're just no longer user-toggleable through this modal (edit-mode-transfer-lock still needs to send `is_transfer: true` explicitly per Pitfall 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "Save & add another" is implemented as two submit buttons distinguished by a small state flag set in each button's onClick (rather than `document.activeElement` / `nativeEvent.submitter` sniffing) | Pattern 7 | Low — this is an implementation-detail recommendation only; CONTEXT.md's Claude's Discretion explicitly leaves the exact mechanism open. An alternative (checking `e.nativeEvent.submitter`) is equally valid and slightly less state |
| A2 | Currency field renders as a plain text input, not a `<select>` | Pitfall 5 / D-05 | Low — CONTEXT.md explicitly defers this to planning discretion; a `<select>` with a short hardcoded list (IDR/USD) would also satisfy D-05 since the backend doesn't validate currency values either way |
| A3 | Edit-mode transfer-leg lock (Pitfall 1) is the correct minimal-diff resolution, not "hide the Edit action entirely for transfer rows" | Common Pitfalls #1 | Medium — an alternative resolution (disable the Edit action on transfer-tinted rows in `cashflow/page.tsx` until Phase 17) is equally valid and arguably simpler; this was not a locked decision in 16-CONTEXT.md and should be confirmed with the user or decided explicitly by the planner, since it touches `page.tsx` row-rendering, not just the modal |

**If this table is empty:** N/A — see above.

## Open Questions

1. **Edit-mode behavior when the record being edited is a transfer leg (Pitfall 1 / A3)**
   - What we know: `TransactionModal` is opened in edit mode from rows that may have `is_transfer: true`; there is no pair-aware edit endpoint; REC-05 (transfer-pair-aware edit) is Phase 17.
   - What's unclear: Whether the planner should (a) lock the segment control and keep legacy single-leg PUT editing for transfer rows (this research's recommendation), or (b) disable/hide the "Edit" action entirely for transfer-tinted rows in `cashflow/page.tsx` until Phase 17 ships proper pair-aware editing.
   - Recommendation: Option (a) is the smaller diff and matches "extend without rebuilding"; note it explicitly as a task in PLAN.md so it isn't silently skipped. Surface this to the user via discuss-phase follow-up or plan-checker if ambiguity remains a concern.

2. **Does `investments/page.tsx` need any TransactionModal-adjacent wiring for the currency field?**
   - What we know: `investments/page.tsx` mounts only `<PlatformManager>` (confirmed via grep — no `TransactionModal` import there); `TransactionModal` is exclusively mounted from `cashflow/page.tsx`.
   - What's unclear: Nothing — this confirms D-01's scope boundary is already structurally enforced; no cross-page wiring needed this phase.
   - Recommendation: None needed — informational only, included to save the planner a duplicate check.

## Environment Availability

Skipped — no external tool/service dependencies beyond the existing dev stack (Node.js, npm, already-running backend). No Docker/DB/service probing needed for a pure frontend-component-extension phase.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Playwright `@playwright/test` 1.61.1 (already installed, `ui/playwright.config.ts`) |
| Config file | `ui/playwright.config.ts` |
| Quick run command | `cd ui && npx playwright test e2e/cashflow-crud.spec.ts` |
| Full suite command | `cd ui && npm run e2e` |

No unit-test framework exists in `ui/` (no Jest/Vitest, no `*.test.tsx` files) — component-level tests are not this project's convention. All UI verification is Playwright e2e with route-mocked (`page.route(...)`) backend responses, per the existing pattern in `e2e/cashflow-crud.spec.ts`, `e2e/cashflow-dashboard.spec.ts`, `e2e/settings.spec.ts`, `e2e/smoke.spec.ts`. `[VERIFIED: repo file listing]`

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ACCT-01 | Add/edit/remove liquid accounts in account manager | e2e | `npx playwright test e2e/cashflow-crud.spec.ts -g "account"` | ✅ existing reassign-delete test covers delete; add/edit-with-type coverage → Wave 0 gap |
| PLAT-02 | Platform manager reaches CRUD parity (kind now editable) | e2e | `npx playwright test e2e/platform-crud.spec.ts` (new file) | ❌ Wave 0 — no existing platform-focused spec file; only `PlatformManager` is exercised indirectly, if at all |
| REC-04 | Add a record via Expense/Income/Transfer segmented modal | e2e | `npx playwright test e2e/cashflow-crud.spec.ts -g "transaction"` | ✅ existing create/edit/delete tests need extending for segment + transfer branch — Wave 0 gap |

### Sampling Rate
- **Per task commit:** targeted spec file (`npx playwright test e2e/cashflow-crud.spec.ts` or the new platform spec)
- **Per wave merge:** `cd ui && npm run e2e` (full Playwright suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `ui/e2e/cashflow-crud.spec.ts` — extend with: (1) segmented-control default-Expense assertion, (2) Expense submit posts a negative signed amount from an unsigned input, (3) Income submit posts a positive amount, (4) Transfer segment hides category picker and posts to `/api/transactions/transfer` with unsigned amount + from/to account names, (5) currency field defaults to IDR and is included in the POST body, (6) "Save & add another" keeps the modal open and resets amount/category/notes while preserving segment/account/date, (7) editing a non-transfer row correctly reverse-maps sign→segment, (8) editing a transfer-tinted row locks the segment control (Pitfall 1 resolution)
- [ ] `ui/e2e/platform-crud.spec.ts` (new file, mirroring `cashflow-crud.spec.ts`'s account-reassign test) — covers PLAT-02: add platform with kind, inline edit now updates both name and kind, delete with 422→reassign flow (structural copy of the existing account-reassign test)
- [ ] `AccountManager` add-with-type coverage — extend an existing or new test asserting `POST /api/accounts` body includes `type: "liquid"` (D-07)
- Framework install: none — Playwright is already installed and configured

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Single-user, no auth UI touched this phase |
| V3 Session Management | No | Not touched |
| V4 Access Control | No | Not touched |
| V5 Input Validation | Yes | Client-side: `required` + `type="number"` on amount inputs (existing pattern, kept); server-side validation is unchanged (`TransactionCreate`/`TransferCreate`/`AccountCreate`/`PlatformCreate` Pydantic schemas already enforce types — `TransferCreate.amount` already has `gt=0`). No new validation surface is introduced beyond the client-side same-account transfer guard recommended in Pattern 5 |
| V6 Cryptography | No | Not touched |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Client sends a category/extra field into the Transfer POST body that the schema doesn't expect | Tampering (low severity — self-hosted single-user app) | FastAPI/Pydantic drops unrecognized fields by default (no `extra="forbid"` on `TransferCreate`) — not a security boundary per se in this single-user app, but a correctness one; see Pitfall 2 |
| Same-account transfer (`from_account === to_account`) | Tampering / data integrity | No server-side guard exists today (`apply_add_transfer` has no self-pair check) — recommend a client-side guard (Pattern 5) as a UX safeguard; a full server-side fix is out of this phase's scope (would be a backend/schemas.py change, not a UI extension) |

This phase makes no changes to `require_api_key`, the `MONAI_API_KEY` proxy injection, or any authentication/session code — all existing writes already route through the same protected endpoints this phase reuses unchanged.

## Sources

### Primary (HIGH confidence)
- `ui/app/cashflow/TransactionModal.tsx` (full read) — current state/handlers/JSX baseline for the D-01..D-06 diff
- `ui/app/settings/page.tsx` (full read) — segmented-control markup (UIR-07) to copy verbatim
- `ui/app/cashflow/AccountManager.tsx` (full read) — D-07 diff target
- `ui/app/investments/PlatformManager.tsx` (full read) — D-08 diff target
- `ui/app/cashflow/page.tsx` (relevant sections) — modal/manager mount points, recent-transactions list rendering (source of Pitfall 1), confirmed no `TransactionModal` mount elsewhere
- `ui/app/investments/page.tsx` (grep) — confirmed no `TransactionModal` import (only `PlatformManager`)
- `backend/schemas.py` (full read) — exact request-body contracts for `TransactionCreate`, `TransactionUpdate`, `TransferCreate`, `AccountCreate`, `AccountUpdate`, `PlatformCreate`, `PlatformUpdate`
- `backend/main.py` L229-390, L749-880 (read) — `create_transaction`/`update_transaction`/`create_transfer`/account/platform CRUD endpoint bodies, confirmed no `PUT /transactions/transfer/{id}` exists
- `ui/e2e/cashflow-crud.spec.ts` (full read) — existing Playwright test patterns, route-mocking conventions, no unit-test framework present
- `ui/package.json` (read) — confirmed installed dependency versions, no test framework besides Playwright
- `.planning/config.json` (grep) — confirmed `nyquist_validation: true`

### Secondary (MEDIUM confidence)
None — no web/docs sources were needed; this phase's research-plan seam returned no external search providers configured (`brave_search: false, firecrawl: false, exa_search: false` from `init.phase-op`), and none were needed given the phase introduces zero new libraries.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions confirmed directly from `ui/package.json`
- Architecture: HIGH — every pattern cited is read verbatim from the actual files being extended, not inferred
- Pitfalls: HIGH for Pitfalls 2-5 (directly observable from code); MEDIUM for Pitfall 1 (a real gap in CONTEXT.md's decision coverage, flagged as Open Question A3 rather than asserted as the only valid resolution)

**Research date:** 2026-08-01
**Valid until:** 2026-09-01 (30 days — stable internal codebase, no fast-moving external dependency)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Record modal — segmented Expense/Income/Transfer (REC-04)**
- **D-01:** Extend `TransactionModal.tsx` **in place** — do not build a new component (roadmap: "without being rebuilt"). Add a 3-way **segmented control** (Expense / Income / Transfer) at the top of the form, reusing the segmented-control pattern already established in `ui/app/settings/page.tsx` (UIR-07). Default segment: **Expense**.
- **D-02:** Amount is entered as an **unsigned positive magnitude**; sign is derived from the segment — Expense → stored **negative**, Income → stored **positive**. This retires the current "negative = expense" raw-signed input foot-gun.
- **D-03:** The **Transfer** segment swaps the single Account select for **From-account + To-account** selects, **hides** the Category picker and the legacy `is_transfer` checkbox, and submits `POST /transactions/transfer` (`TransferCreate`: `from_account`, `to_account`, `amount > 0`, `currency`, `date`, `notes`) — the atomic-pair endpoint from Phase 13 — **not** `POST /transactions` with `is_transfer: true`. The `is_transfer` checkbox is removed from the modal.
- **D-04:** Expense/Income keep the current `POST /transactions` (create) / `PUT` (edit) path and the category picker (system nodes stay filtered out by `flattenCategories`). Transfer's category is server-assigned (Transfer system category) — never hand-picked.

**Currency field (REC-04 "amount + currency")**
- **D-05:** Expose a **currency field beside amount, defaulting to `IDR`**, wired to the `currency` field both endpoints already accept (`TransactionCreate.currency` / `TransferCreate.currency`, both default `"IDR"`). Lightweight text/select; **no FX conversion** (single-currency IDR assumption holds for spending). Satisfies REC-04 literally without scope-creeping into multi-currency math.

**"Add another" (REC-04)**
- **D-06:** Implement as a second submit button — **"Save & add another"** — beside the primary Save. On success it **keeps the modal open**, resets amount / category / note, and **preserves the record type, account(s), and date** for fast repeated entry. Preferred over a persistent checkbox: one fewer piece of state, matches the existing button-row convention.

**Account manager — liquid accounts (ACCT-01)**
- **D-07:** Add/edit/remove (with the 422→`affected_count` reassign flow) already exist and are reused **unchanged**. Create sends `type: "liquid"` explicitly (backend already server-defaults liquid; explicit keeps intent legible on the shared endpoint). This manager is **liquid-only by definition** — no type-picker UI, edit stays name-only (account `type` is not user-switchable post-create in this phase). Investment accounts are managed via platforms/holdings, not here.

**Platform manager — CRUD parity (PLAT-02)**
- **D-08:** PlatformManager is already a structural mirror of AccountManager with full add / edit / delete-with-reassign — parity is **essentially met**. The one gap: inline edit updates only `name`, not `kind`. Close it by adding a **`kind` input to the edit row** (`PlatformUpdate` already accepts `kind`) so edit reaches true add/edit parity. No other changes.

### Claude's Discretion
- Exact segmented-control markup/styling (reuse settings pattern), grid field layout, and whether currency is a text input vs a small `<select>` — left to planning within the inline-style `styles.ts` token convention. Whether "Save & add another" is shown in edit mode (recommend: create-mode only).

### Deferred Ideas (OUT OF SCOPE)
- **Platform detail view** (PnL tab + buy/sell history) — Phase 17, PLAT-01.
- **Records tab** (date-grouped ledger, filters, bulk delete/recategorize, transfer-pair display) — Phase 17, REC-01..03/05.
- **Multi-currency FX conversion** for the currency field — backlog (single-currency IDR holds for spending).
- **Editing an account's `type`** (liquid ↔ investment) after creation — not needed this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ACCT-01 | User can add, edit, and remove liquid accounts in a dedicated account manager | `AccountManager.tsx` already has full add/edit/remove + 422 reassign (read in full, unchanged flow confirmed); only gap is the D-07 `type: "liquid"` payload addition on create — see Code Examples and Pitfall 4 |
| PLAT-02 | Platform manager reaches CRUD parity with the account manager | `PlatformManager.tsx` already has full add/edit/remove + 422 reassign, structurally mirrors AccountManager (read in full); only gap is the D-08 `kind` edit-row input — see Code Examples |
| REC-04 | User can add a record via a modal with Expense/Income/Transfer segmented form (amount + currency, account, category picker, date-time, note; "add another") | `TransactionModal.tsx` full baseline read; settings-page segmented-control pattern read for reuse; backend `TransactionCreate`/`TransferCreate` contracts confirmed; sign-derivation, category-visibility, from/to-account, and add-another patterns all documented above with code examples; edit-mode-transfer landmine flagged as Pitfall 1 / Open Question 1 |
</phase_requirements>

## RESEARCH COMPLETE
