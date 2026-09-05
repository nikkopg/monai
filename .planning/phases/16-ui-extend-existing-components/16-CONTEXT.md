# Phase 16: UI — Extend Existing Components - Context

**Gathered:** 2026-08-01
**Status:** Ready for planning

> **Mode:** `--auto go with all recs`. Every decision below is the **recommended
> option**, auto-selected in a single pass. Any can be vetoed before planning.

<domain>
## Phase Boundary

Extend three **existing** manual-entry UI components so they cover the v1.2
typed-account + record-type model **without being rebuilt**:

- **AccountManager** (`ui/app/cashflow/AccountManager.tsx`) — liquid-account CRUD (ACCT-01)
- **PlatformManager** (`ui/app/investments/PlatformManager.tsx`) — CRUD parity with AccountManager (PLAT-02)
- **TransactionModal** (`ui/app/cashflow/TransactionModal.tsx`) → record modal with an **Expense / Income / Transfer** segmented form (REC-04)

**In scope:** ACCT-01, PLAT-02, REC-04 — the three success criteria in ROADMAP Phase 16.

**Out of scope (own phases):** Records tab, filters, bulk actions (Phase 17 / REC-01..03,05);
platform **detail** view with PnL + buy/sell history tabs (Phase 17 / PLAT-01);
any new backend write mechanics — transfer pair, funding adjustments, shared
mutation layer already shipped in Phases 13/14. Multi-currency FX conversion is backlog.
</domain>

<decisions>
## Implementation Decisions

### Record modal — segmented Expense/Income/Transfer (REC-04)
- **D-01:** Extend `TransactionModal.tsx` **in place** — do not build a new component
  (roadmap: "without being rebuilt"). Add a 3-way **segmented control**
  (Expense / Income / Transfer) at the top of the form, reusing the segmented-control
  pattern already established in `ui/app/settings/page.tsx` (UIR-07). Default segment: **Expense**.
  `[auto] Component strategy — Q: "New record modal or extend TransactionModal?" → Selected: "Extend in place" (recommended default)`
- **D-02:** Amount is entered as an **unsigned positive magnitude**; sign is derived
  from the segment — Expense → stored **negative**, Income → stored **positive**.
  This retires the current "negative = expense" raw-signed input foot-gun.
  `[auto] Amount sign — Q: "Keep signed input or derive sign from type?" → Selected: "Derive from segment" (recommended default)`
- **D-03:** The **Transfer** segment swaps the single Account select for **From-account +
  To-account** selects, **hides** the Category picker and the legacy `is_transfer`
  checkbox, and submits `POST /transactions/transfer` (`TransferCreate`: `from_account`,
  `to_account`, `amount > 0`, `currency`, `date`, `notes`) — the atomic-pair endpoint
  from Phase 13 — **not** `POST /transactions` with `is_transfer: true`. The
  `is_transfer` checkbox is removed from the modal.
  `[auto] Transfer wiring — Q: "is_transfer flag or /transactions/transfer pair endpoint?" → Selected: "Pair endpoint" (recommended default)`
- **D-04:** Expense/Income keep the current `POST /transactions` (create) / `PUT` (edit)
  path and the category picker (system nodes stay filtered out by `flattenCategories`).
  Transfer's category is server-assigned (Transfer system category) — never hand-picked.

### Currency field (REC-04 "amount + currency")
- **D-05:** Expose a **currency field beside amount, defaulting to `IDR`**, wired to the
  `currency` field both endpoints already accept (`TransactionCreate.currency` /
  `TransferCreate.currency`, both default `"IDR"`). Lightweight text/select; **no FX
  conversion** (single-currency IDR assumption holds for spending). Satisfies REC-04
  literally without scope-creeping into multi-currency math.
  `[auto] Currency — Q: "Expose currency field or hardcode IDR?" → Selected: "Expose, default IDR, no FX" (recommended default)`

### "Add another" (REC-04)
- **D-06:** Implement as a second submit button — **"Save & add another"** — beside the
  primary Save. On success it **keeps the modal open**, resets amount / category / note,
  and **preserves the record type, account(s), and date** for fast repeated entry.
  Preferred over a persistent checkbox: one fewer piece of state, matches the existing
  button-row convention.
  `[auto] Add-another — Q: "Persistent checkbox or 'Save & add another' button?" → Selected: "Button" (recommended default)`

### Account manager — liquid accounts (ACCT-01)
- **D-07:** Add/edit/remove (with the 422→`affected_count` reassign flow) already exist
  and are reused **unchanged**. Create sends `type: "liquid"` explicitly (backend already
  server-defaults liquid; explicit keeps intent legible on the shared endpoint). This
  manager is **liquid-only by definition** — no type-picker UI, edit stays name-only
  (account `type` is not user-switchable post-create in this phase). Investment accounts
  are managed via platforms/holdings, not here.

### Platform manager — CRUD parity (PLAT-02)
- **D-08:** PlatformManager is already a structural mirror of AccountManager with full
  add / edit / delete-with-reassign — parity is **essentially met**. The one gap: inline
  edit updates only `name`, not `kind`. Close it by adding a **`kind` input to the edit
  row** (`PlatformUpdate` already accepts `kind`) so edit reaches true add/edit parity.
  No other changes.

### Claude's Discretion
- Exact segmented-control markup/styling (reuse settings pattern), grid field layout,
  and whether currency is a text input vs a small `<select>` — left to planning within
  the inline-style `styles.ts` token convention. Whether "Save & add another" is shown
  in edit mode (recommend: create-mode only).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — ACCT-01, PLAT-02, REC-04 (exact acceptance wording)
- `.planning/ROADMAP.md` — Phase 16 goal + success criteria

### Prior-phase decisions this builds on
- `.planning/phases/12-typed-accounts-transfer-funding-schema-foundations/12-CONTEXT.md` — typed accounts (liquid/investment `type` column, migration 010)
- `.planning/phases/13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm/13-CONTEXT.md` — atomic transfer pair semantics behind `POST /transactions/transfer`

### Code (see `<code_context>` for how each is used)
- `ui/app/cashflow/TransactionModal.tsx`, `ui/app/cashflow/AccountManager.tsx`,
  `ui/app/investments/PlatformManager.tsx`, `ui/app/settings/page.tsx` (segmented control),
  `backend/main.py` (endpoints), `backend/schemas.py` (`AccountCreate`/`TransferCreate`/`TransactionCreate`)

No external ADRs — requirements fully captured in the decisions above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`TransactionModal.tsx`** — the modal to extend. Already has `flattenCategories`
  (system-node filtering) and `toLocalDatetimeInputValue` (WR-06 UTC-safe datetime); both stay.
- **`AccountManager.tsx` / `PlatformManager.tsx`** — full CRUD + `ConfirmDialog` 422→reassign
  flow; AccountManager reused as-is (D-07), PlatformManager gains only a `kind` edit input (D-08).
- **`ui/app/settings/page.tsx`** — existing **segmented control** (UIR-07) to copy for the
  Expense/Income/Transfer selector (D-01).
- **`ui/app/cashflow/ConfirmDialog.tsx`**, **`ui/app/styles.ts`** tokens (`card`/`input`/`btn`/`label`).

### Established Patterns
- Inline-style + token-driven `styles.ts` (no Tailwind) — v1.1 decision; stay on it.
- `onChanged()` / `onSaved()` parent-refetch (Pattern 5); Next.js proxy injects `MONAI_API_KEY` server-side.
- Error copy convention: `"Couldn't save …: {detail}. Nothing was changed."`

### Integration Points
- `ui/app/cashflow/page.tsx` mounts `<TransactionModal>` (~L840) and `<AccountManager>` (~L836) — the modal's trigger/entry point stays here for Phase 16 (Records-tab trigger is Phase 17).
- Endpoints: `POST/PUT /transactions` (main.py:749/773), `POST /transactions/transfer` (main.py:826),
  `POST/PUT /accounts` (229/240), `POST/PUT /platforms` (341/352).
</code_context>

<specifics>
## Specific Ideas

- Segmented control should visually match the LLM-provider selector in Settings (UIR-07) — same look, three segments.
- "add another" reads as a fast data-entry affordance (log several expenses in a row) — keep the record type + account sticky between entries.
</specifics>

<deferred>
## Deferred Ideas

- **Platform detail view** (PnL tab + buy/sell history) — Phase 17, PLAT-01.
- **Records tab** (date-grouped ledger, filters, bulk delete/recategorize, transfer-pair display) — Phase 17, REC-01..03/05.
- **Multi-currency FX conversion** for the currency field — backlog (single-currency IDR holds for spending).
- **Editing an account's `type`** (liquid ↔ investment) after creation — not needed this phase.

None of the above were pulled into Phase 16 scope.
</deferred>

---

*Phase: 16-ui-extend-existing-components*
*Context gathered: 2026-08-01*
