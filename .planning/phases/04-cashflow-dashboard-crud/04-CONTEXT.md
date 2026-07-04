# Phase 4: Cashflow Dashboard + CRUD - Context

**Gathered:** 2026-07-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Grow the interim `/cashflow` page (currently a manual-entry form + recent list from
Phase 3) into a real spending/income dashboard with charts, plus full in-UI
management of transactions, accounts, and categories, and a CSV upload with an
import result.

This phase delivers:
- A **dashboard** on `/cashflow`: total income, total expenses, net, per-account
  balances, a spending-by-category donut, an income-vs-expense bar, and a
  month-over-month trend covering ≥6 months — all from real data (CASH-01, CASH-02,
  CASH-03).
- **Transaction CRUD** in the UI: create, edit, delete, reflected immediately without
  a page reload (CASH-04).
- **Account CRUD** in the UI: create, edit, delete — with reassign-then-delete
  semantics (CASH-05).
- **Category management** in the UI: rename (remaps affected transactions) and merge
  one category into another (CASH-06, CASH-07).
- **CSV upload** from the UI showing parsed / inserted / skipped counts (CASH-08).

Out of scope (own phases): holdings / prices / P&L (Phase 5); MCP server (Phase 6);
any styling re-platform (stays inline styles). No new agent/chat capabilities — this
phase exposes and UI-fies existing write logic on a direct path.

**Requirements covered:** CASH-01, CASH-02, CASH-03, CASH-04, CASH-05, CASH-06,
CASH-07, CASH-08.

</domain>

<decisions>
## Implementation Decisions

### UI Write Path (keystone)
- **D-01:** UI create/edit/delete for transactions, accounts, and categories use
  **new direct auth-protected REST endpoints** (`POST`/`PUT`/`DELETE`). The button
  click is the explicit confirmation, so writes apply instantly and reflect without a
  page reload — the Phase-2 propose→confirm token dance is NOT used on the UI path.
- **D-02:** **Refactor the write bodies out of `backend/main.py:_execute_proposal_payload`
  into shared helper functions**, so BOTH the agent's propose→confirm path and the new
  direct UI endpoints write through one implementation. This preserves the `audit_log`
  write (CHAT-06) and `Decimal` handling (FND-03) for every write on either path — one
  source of truth, no divergence.
- **D-03:** A lightweight client-side "are you sure?" confirm on destructive actions
  (delete transaction/account/category, category merge) is Claude's discretion — the
  server write itself stays direct.

### Account Manager
- **D-04:** Per-account display shows **both** an all-time balance (sum of ALL that
  account's transaction amounts — a true current balance, independent of the dashboard
  period) AND the net for the currently-selected dashboard period. The summary payload
  returns `current_balance` (all-time) and `period_net` (scoped) per account.
- **D-05:** Account CRUD gets **direct REST endpoints** — there is no `POST/PUT/DELETE
  /accounts` today, only `GET /accounts`. Build them on the shared write helpers (D-02).
- **D-06:** **Account delete = reassign-then-delete.** The delete endpoint accepts an
  optional `reassign_to` target account id. If the account has transactions and no
  target is supplied, return **422 with the affected-transaction count** ("N
  transactions use this account — reassign or delete them first"). The UI prompts the
  user to pick a destination account, reassigns, then removes the account.

### Charts
- **D-07:** Use **Recharts** for the donut (spending by category), income-vs-expense
  bar, and 6-month trend (bar or line). This is the first frontend dependency beyond
  React/Next; the cashflow page is already a client component. Declarative React
  components — least custom code vs hand-rolled SVG.

### Dashboard API Shape
- **D-08:** **One aggregate endpoint** `GET /cashflow/summary?period=…` returns every
  dashboard figure in a single payload: totals (income/expense/net) for the selected
  period, per-account `current_balance` + `period_net`, spending-by-category rows, and
  the monthly trend series. The trend series MUST cover **≥6 months** (CASH-02). One
  request per page load / period change. Reuse existing tool queries
  (`spending_total`, `income_total`, `spending_by_category`, etc.) internally where
  they fit; add NEW SQL for the month-over-month trend and per-account balances (neither
  exists today).

### Category Management
- **D-09:** A **dedicated category manager** panel/section lists existing category
  names (from `list_categories`) with **Rename** and **Merge-into** actions. Each
  action shows the **affected-transaction count** before applying. Categories are a
  free-text string column on transactions (no Category table) — rename/merge are bulk
  UPDATEs by string, via the same shared write helpers (already implemented as
  `rename_category` / `merge_category` in `_execute_proposal_payload`).

### Transaction Editing
- **D-10:** Editing a transaction opens a **modal form** with all fields (date, amount,
  category, merchant, account, notes). The **same form component is reused for create**.

### Claude's Discretion
- **CSV upload UX** (CASH-08): reuse the existing `POST /import` endpoint; surface it on
  the cashflow page and display parsed / inserted / skipped from the existing
  `ImportResponse`. Placement and styling are open.
- **Dashboard period selector**: default period and the exact month range shown are
  Claude's discretion (trend must still be ≥6 months).
- Transaction table paging / filtering, exact widget layout, and visual styling within
  the existing inline-styles aesthetic.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 4: Cashflow Dashboard + CRUD" — goal + 6 success
  criteria (dashboard figures, ≥6-month trend, tx/account/category CRUD, CSV import).
- `.planning/REQUIREMENTS.md` — CASH-01…CASH-08 definitions; also the "Out of Scope"
  table (single-currency IDR holds; no budgeting; no bank sync).

### Prior decisions this phase builds on
- `.planning/phases/03-multi-page-ui-shell-settings/03-CONTEXT.md` — nav shell, the
  interim `/cashflow` content to grow, inline-styles convention, shared `ui/app/styles.ts`,
  server-side `/api/[...proxy]` key injection.
- `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `STACK.md` — layering, error
  convention (`ValueError`→422), parameterized-SQL rule, tech baseline.

### Key existing code (verified during scout)
- `backend/main.py:_execute_proposal_payload` (~L197–L360) — existing write logic for
  add/edit/delete transaction + account, and `rename_category` / `merge_category`. This
  is what gets refactored into shared helpers (D-02).
- `backend/tools.py` — read/aggregation tools (`spending_total`, `income_total`,
  `net_total`, `spending_by_category`, `find_transactions`, `list_categories`, …) and
  `resolve_period()` / `PERIODS`; reuse for the summary endpoint.
- `backend/main.py` endpoints — today: `GET /accounts`, `GET/POST /transactions`,
  `POST /import`, `GET/PUT /settings`. NO account/category REST endpoints, NO dashboard
  endpoint, NO `PUT`/`DELETE /transactions`.

No external specs/ADRs beyond the planning docs above — requirements fully captured in
the decisions here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/main.py:_execute_proposal_payload` — all Phase-4 write operations already
  implemented (add/edit/delete transaction + account, rename/merge category). Extract to
  shared helpers; agent path and new direct REST both call them.
- `backend/tools.py` aggregation functions + `resolve_period()` — feed the
  `/cashflow/summary` endpoint; new SQL only needed for trend + per-account balances.
- `ui/app/cashflow/page.tsx` (247 lines) — interim manual-entry form + recent list to
  grow into the dashboard; already `"use client"`.
- `ui/app/styles.ts` — shared inline style constants (`card`, `input`, `btn`, `label`).
- `ui/app/api/[...proxy]/route.ts` — server-side `MONAI_API_KEY` injection for all
  write calls from the UI.
- `require_api_key` dependency + `ImportResponse` schema + `POST /import` (CSV).

### Established Patterns
- Direct REST writes must go through `require_api_key`, raise `ValueError`→422, use
  parameterized SQL / SQLAlchemy ORM only, and store money as `Decimal`.
- Pydantic v2 schemas by role (`*Create`, `*Out`, `*Request`) in `backend/schemas.py`.
- Inline `React.CSSProperties` styling; no CSS framework (Recharts is the one exception,
  a charting lib not a style framework).
- Categories = free-text string on `transactions.category` (no entity table).
- Accounts have no balance column — balance is always derived from transaction sums.

### Integration Points
- `backend/main.py` — new `GET /cashflow/summary`, `PUT`/`DELETE /transactions/{id}`,
  `POST`/`PUT`/`DELETE /accounts`, and category rename/merge endpoints.
- `backend/tools.py` / new query module — trend + balance SQL.
- `ui/app/cashflow/page.tsx` — dashboard widgets, CRUD modals, category manager, CSV
  upload; add Recharts to `ui/package.json`.
- `backend/schemas.py` — request/response DTOs for the new endpoints + summary payload.

</code_context>

<specifics>
## Specific Ideas

- Accounts are real-world buckets like **Cash, Bank A, Bank B** — the account manager is
  a first-class part of this phase, not an afterthought.
- Per-account view must answer both "what's in this account right now" (all-time
  balance) and "what moved this period" (period net) simultaneously.

</specifics>

<deferred>
## Deferred Ideas

- Write tools / CRUD over MCP to external clients — explicitly out of scope (writes stay
  behind the web app; MCP is read-only in Phase 6).
- Stored `opening_balance` column on accounts (considered for balance accuracy;
  rejected for now — derive from transaction sums, no schema change this phase).
- Multi-currency normalization — parked project-wide; single-currency IDR holds.
- Styling re-platform (Tailwind/shadcn) — stays inline styles this cycle.

None of the above belong in Phase 4 — discussion stayed within scope.

</deferred>

---

*Phase: 4-cashflow-dashboard-crud*
*Context gathered: 2026-07-04*
