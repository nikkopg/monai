# Phase 4: Cashflow Dashboard + CRUD - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-04
**Phase:** 4-cashflow-dashboard-crud
**Areas discussed:** UI write path, Account manager, Charting library, Dashboard API shape, CRUD edge cases (accounts/categories/transactions)

---

## UI Write Path

| Option | Description | Selected |
|--------|-------------|----------|
| Direct REST | New auth-protected POST/PUT/DELETE; click = confirmation, instant write; refactor write logic out of `_execute_proposal_payload` into shared helpers so agent + UI share one audited/Decimal-safe path | ✓ |
| Reuse propose→confirm | UI forms create a proposal then confirm it; single write path but 2-step dance + a proposals row per edit | |
| Direct, but confirm deletes | Direct for create/edit, explicit confirm dialog for destructive deletes | |

**User's choice:** Direct REST
**Notes:** Server writes stay direct; a client-side "are you sure?" on deletes is Claude's discretion.

---

## Account Manager — Balance display

| Option | Description | Selected |
|--------|-------------|----------|
| Sum of all transactions | All-time sum = true current balance, independent of dashboard period | ✓ (both) |
| Sum within selected period | Balance scoped to selected period (a delta, not a real balance) | ✓ (both) |
| Stored opening balance + sum | Add `opening_balance` column via migration | |

**User's choice:** "sum of all transaction, but i also want to be able to show sum within selected period"
**Notes:** Show BOTH — all-time `current_balance` as headline + `period_net` for the selected period.

---

## Account Manager — Delete semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Block with count | Refuse delete, report N transactions using the account | |
| Reassign then delete | Move this account's transactions to another account, then delete | ✓ |
| Cascade delete | Delete account and all its transactions | |

**User's choice:** Reassign then delete
**Notes:** Delete endpoint takes optional `reassign_to`; 422 with affected count if account has transactions and no target given.

---

## Charting Library

| Option | Description | Selected |
|--------|-------------|----------|
| Recharts | Declarative React charts for donut/bar/line; ~1 dep; most idiomatic Next.js choice | ✓ |
| Hand-rolled SVG | Zero deps, matches no-framework convention, more code to maintain | |
| Chart.js (react-chartjs-2) | Canvas-based, feature-rich, less idiomatic in a React tree | |

**User's choice:** Recharts
**Notes:** First frontend dependency beyond React/Next; cashflow page already a client component.

---

## Dashboard API Shape

| Option | Description | Selected |
|--------|-------------|----------|
| One /cashflow/summary endpoint | Single GET returning all dashboard figures for a period; new SQL for trend + balances behind it | ✓ |
| Granular endpoints | Separate endpoint per widget; more flexible but 4-5 requests + more surface | |
| Reuse tool functions via /query | Drive dashboard through the agent query path; doesn't cover trend/balances, couples UI to agent | |

**User's choice:** One /cashflow/summary endpoint
**Notes:** Trend series must cover ≥6 months (CASH-02); reuse existing tool queries where they fit.

---

## CRUD edge cases — Category management surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated category manager | List of category names with Rename + Merge-into actions, showing affected-row counts | ✓ |
| Inline from transactions table | Rename/merge from category cells; bulk semantics easy to miss | |
| Reuse chat/agent for categories | Leave to the agent propose flow; fails "from the UI" intent | |

**User's choice:** Dedicated category manager
**Notes:** Categories are free-text strings; rename/merge = bulk UPDATE via existing shared write logic; show affected count before applying.

---

## CRUD edge cases — Transaction edit UX

| Option | Description | Selected |
|--------|-------------|----------|
| Modal form | Click row → modal with all fields; same form reused for create | ✓ |
| Inline row editing | Edit fields directly in the table row; cramped for 6-7 fields | |
| Side drawer/panel | Slide-in panel with the edit form | |

**User's choice:** Modal form
**Notes:** Reuse the same form component for both create and edit.

---

## Clarification raised during discussion

- User asked whether an account manager already exists. Answer: the write LOGIC exists
  (add/edit/delete account in `_execute_proposal_payload` + `propose_*_account` tools,
  agent path only), and `GET /accounts` exists — but there are NO direct account REST
  endpoints and NO account-manager UI. Phase 4 adds both, reusing the shared write
  helpers plus the new reassign-then-delete behavior.

## Claude's Discretion

- CSV upload UX (CASH-08) — reuse existing `POST /import`, show parsed/inserted/skipped
  from `ImportResponse`; placement/styling open.
- Dashboard period selector — default period and month range (trend still ≥6 months).
- Transaction table paging/filtering, widget layout, visual styling within inline-styles
  aesthetic.

## Deferred Ideas

- Write/CRUD over MCP to external clients (out of scope; MCP read-only in Phase 6).
- Stored `opening_balance` column on accounts (rejected this phase; derive from sums).
- Multi-currency normalization (parked project-wide; single-currency IDR).
- Styling re-platform (Tailwind/shadcn) — stays inline styles.
