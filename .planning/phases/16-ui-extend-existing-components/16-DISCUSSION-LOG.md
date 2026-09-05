# Phase 16: UI — Extend Existing Components - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-01
**Phase:** 16-ui-extend-existing-components
**Mode:** `--auto go with all recs` (autonomous single pass — recommended option auto-selected per area)
**Areas discussed:** Record modal strategy, Amount sign, Transfer wiring, Currency field, "Add another", Account manager typing, Platform CRUD parity

---

## Record modal — component strategy (D-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend TransactionModal in place | Add segmented control to the existing modal | ✓ |
| Build a new RecordModal component | Fresh component, retire TransactionModal | |

**User's choice:** Extend in place (recommended) — roadmap says "without being rebuilt".

---

## Amount sign handling (D-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Derive sign from segment | Unsigned magnitude input; Expense→neg, Income→pos | ✓ |
| Keep signed input | Current "negative = expense" raw field | |

**User's choice:** Derive from segment (recommended) — retires the sign foot-gun.

---

## Transfer wiring (D-03)

| Option | Description | Selected |
|--------|-------------|----------|
| `POST /transactions/transfer` pair endpoint | From/To selects, atomic pair (Phase 13) | ✓ |
| `is_transfer: true` on `POST /transactions` | Legacy single-row checkbox | |

**User's choice:** Pair endpoint (recommended) — atomic, matches shipped backend contract.

---

## Currency field (D-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Expose currency, default IDR, no FX | Wire the `currency` field both endpoints accept | ✓ |
| Hardcode IDR | Omit the field entirely | |

**User's choice:** Expose, default IDR (recommended) — satisfies REC-04 literally, no FX scope creep.

---

## "Add another" (D-06)

| Option | Description | Selected |
|--------|-------------|----------|
| "Save & add another" button | Keeps modal open, resets amount/category/note, keeps type+account+date | ✓ |
| Persistent checkbox | Extra state, decides close-behavior on save | |

**User's choice:** Button (recommended) — less state, matches button-row convention.

---

## Account manager — liquid typing (D-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse CRUD as-is, send `type: "liquid"` on create | Liquid-only by definition, no type-picker | ✓ |
| Add a liquid/investment type picker | User switches account type in the manager | |

**User's choice:** Reuse + explicit liquid (recommended) — investment accounts live under platforms/holdings.

---

## Platform manager — CRUD parity (D-08)

| Option | Description | Selected |
|--------|-------------|----------|
| Add `kind` to the inline edit row | Closes the only parity gap (edit was name-only) | ✓ |
| Leave as-is | Already has add/edit/delete-with-reassign | |

**User's choice:** Add `kind` edit (recommended) — reaches true add/edit parity.

---

## Claude's Discretion

- Segmented-control markup/styling (reuse Settings UIR-07 pattern), grid field layout, currency input vs `<select>`.
- Whether "Save & add another" appears in edit mode (recommend create-mode only).

## Deferred Ideas

- Platform detail view (PnL + buy/sell history) → Phase 17 (PLAT-01).
- Records tab (date-grouped ledger, filters, bulk actions, transfer-pair display) → Phase 17.
- Multi-currency FX conversion → backlog.
- Editing account `type` after creation → not needed this phase.
