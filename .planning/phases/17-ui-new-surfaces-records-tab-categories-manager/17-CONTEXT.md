# Phase 17: UI — New Surfaces (Records Tab, Categories Manager) - Context

**Gathered:** 2026-08-01
**Status:** Ready for planning

> **Mode:** `--auto`. Every decision below is the **recommended option**,
> auto-selected in a single pass. Any can be vetoed before planning.

<domain>
## Phase Boundary

Deliver two **new** purpose-built screens over existing data:

1. **Records tab** — a date-grouped ledger of the full transaction history with
   a daily net per group, filtering, multi-select bulk actions, and transfer
   pairs shown as one logical unit (REC-01, REC-02, REC-03, REC-05).
2. **Platform detail view** — drill into one investment platform with a **PnL**
   tab and a **buy/sell history** tab (PLAT-01).

**Scope correction (important):** the roadmap phase title says "Categories
Manager", but **the category tree manager already shipped in Phase 11**
(`ui/app/settings/CategoryManager.tsx`, a full recursive tree manager) and no
CAT-* requirement is assigned to Phase 17. There is **no new category-manager
build** — the existing one is reused (as the picker for bulk-recategorize). The
title is stale; the real scope is Records + Platform detail.

**In scope:** REC-01, REC-02, REC-03, REC-05, PLAT-01 — plus the **backend reads/
writes these surfaces require** (see D-01..D-05): GET /transactions filters,
`transfer_pair_id` exposure, bulk delete/recategorize, pair-aware delete, and
per-platform PnL/events reads. This is **not a UI-only phase** despite the title.

**Out of scope (own phases / backlog):** new category-manager UI (shipped);
recurring-charge detection, period comparison, streaming (v2 backlog);
liquid→investment funding legs in the records ledger (those are portfolio
events, surfaced in the platform detail view, not the transactions ledger).

**⚠ Size note for planning:** 5 requirements across new backend endpoints + two
new frontend surfaces. The planner should consider a **wave split or a
phase split** (Records surface vs Platform detail are largely independent).
</domain>

<decisions>
## Implementation Decisions

### Backend data plumbing (the Records/Platform surfaces need these)
- **D-01 (filters — REC-01/02):** Extend `GET /transactions` (currently
  `limit`-only, `backend/main.py:641`) with optional, **server-side**
  parameterized query params: `q` (search over merchant/notes), `account_id`,
  `category`, `type` (expense|income|transfer), `amount_min`, `amount_max`,
  `include_transfers` (bool), `date_from`, `date_to`, `limit`, `offset`. Return
  a flat date-desc list. **Date-grouping + daily-net is computed client-side** in
  the Records page (presentation concern). Rationale: filtering = data-scoping
  (server, parameterized SQLAlchemy per the correctness-by-construction rule);
  grouping = presentation (client). Raise/keep a sane cap (e.g. 500) + offset paging.
  `[auto] Filter seam — Q: "Server-side filter params or client-side filter of a bulk fetch?" → Selected: "Server-side params, client-side grouping" (recommended)`
- **D-02 (expose pair id — REC-05):** Add `transfer_pair_id: int | None` to
  `TransactionOut` (`backend/schemas.py`; column already exists on the model,
  `models.py:157`). The ledger needs it to collapse the two legs of a transfer
  into one row. No new query — just surface the existing field.
- **D-03 (bulk actions — REC-03):** Add two **parameterized, audit-logged**
  endpoints, applied in one DB transaction (matches the app's write-safety +
  audit constraint — not a client-side N-call loop): `POST /transactions/bulk-delete`
  (`{ids: int[]}`) and `POST /transactions/bulk-recategorize` (`{ids: int[], category: str}`).
  Web-app-only writes (API-key-gated; NOT added to the MCP read surface). The UI
  gates destructive bulk-delete behind the existing `ConfirmDialog`. Bulk-delete
  handles transfer legs pair-aware (see D-04); bulk-recategorize skips/› no-ops
  transfer legs (transfers are system-categorized).
  `[auto] Bulk seam — Q: "Bulk endpoints or client loops single calls?" → Selected: "Bulk endpoints (atomic + audited)" (recommended)`
- **D-04 (pair-aware delete — REC-05):** Deleting either leg from the ledger
  deletes **both** legs atomically (reuse `apply_delete_transaction(..., allow_paired=True)`
  for both, `writes.py:136`). Single-leg **edit stays blocked in the UI** (matches
  the Phase 13 backend 422 + the Phase 16 modal transfer-leg lock). Applies to the
  single-row delete and to bulk-delete when a selected row is a transfer leg.
- **D-05 (platform detail reads — PLAT-01):** **PnL tab** sourced from
  `portfolio.portfolio_summary(db)`'s existing per-platform group (`platform_id`,
  realized + unrealized + subtotal — already computed, `portfolio.py:174`), exposed
  via a new read (e.g. `GET /platforms/{id}/detail` or filter an added `GET /portfolio`).
  **Buy/sell history tab** from a new read `GET /portfolio-events?platform_id={id}`
  (no such GET exists today — only POST) returning the event ledger (date, ticker,
  side, qty, price). Keep these as REST reads for the UI; **do not** add them to the
  agent/MCP tool surface this phase (scope containment).

### Frontend surfaces
- **D-06 (Records tab — REC-01/02/03):** New top-level nav item **"Records"**
  (`ui/app/components/Nav.tsx`, currently Cashflow/Chat/Investments/Settings) +
  new route `ui/app/records/page.tsx`. Contains: a **date-grouped ledger** (group
  by day, daily-net header per group), a **filter bar** (search, account, category,
  type, amount-range, transfer-visibility toggle → D-01 params), and **multi-select**
  with a **bulk action bar** (delete / recategorize). Reuse verbatim: `TransactionModal`
  (row edit), `ConfirmDialog` (bulk-delete confirm), the category tree/picker from
  CategoryManager (recategorize target), `styles.ts` tokens, the row/error conventions.
- **D-07 (transfer pairs in ledger — REC-05):** Rows sharing a `transfer_pair_id`
  render as **one collapsed row** ("Transfer: From → To", net-zero to spending).
  Edit opens `TransactionModal` in the Phase-16 transfer-leg-locked mode (segment
  locked, `PUT /transactions/{id}`). Delete uses the D-04 pair-aware path. No
  single-leg edit is offered.
- **D-08 (platform detail — PLAT-01):** New route `ui/app/investments/[platformId]/page.tsx`,
  reached by clicking a platform in the investments platform list/manager. **Two
  tabs** built from the existing segmented-control pattern (Settings UIR-07 / the
  Phase-16 record modal): **PnL** (holdings with realized/unrealized/subtotal from
  D-05) and **Buy/Sell history** (the event ledger table from D-05). Reuse
  `HoldingModal`, tokens, segmented control.

### Claude's Discretion
- Exact route shape for platform detail (`/investments/[id]` vs `/platforms/[id]`),
  the precise filter-bar layout, whether bulk-recategorize opens the full category
  tree or a flat picker, and pagination style (offset vs "load more") — left to
  planning within the inline-style `styles.ts` convention.
- Whether the new backend reads (D-05) return a bespoke DTO or reuse
  `PortfolioSummary`/`PortfolioEventOut` shapes — planner/researcher's call.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — REC-01, REC-02, REC-03, REC-05, PLAT-01 (exact wording)
- `.planning/ROADMAP.md` — Phase 17 goal + 5 success criteria (note: title's "Categories Manager" is stale)

### Prior-phase decisions this builds on
- `.planning/phases/16-ui-extend-existing-components/16-CONTEXT.md` — the record modal + transfer-leg-lock the Records ledger reuses (D-03/§7)
- `.planning/phases/15-net-worth-aggregation-dashboard/15-CONTEXT.md` — dashboard-consistent aggregation the Records/platform data must not contradict
- `.planning/phases/13-*/13-CONTEXT.md` — atomic transfer-pair semantics (`transfer_pair_id`, pair-aware writes)

### Code (see `<code_context>` for how each is used)
- `backend/main.py` (endpoints: GET /transactions:641, DELETE /transactions:802, POST /transactions/transfer:826)
- `backend/schemas.py` (`TransactionOut` — add `transfer_pair_id`), `backend/writes.py` (`apply_delete_transaction` allow_paired:136), `backend/portfolio.py` (`portfolio_summary`:174), `backend/models.py` (`transfer_pair_id`:157, `PortfolioEvent`:249)
- `ui/app/components/Nav.tsx`, `ui/app/cashflow/page.tsx` (recent-list ledger analog), `ui/app/investments/page.tsx`, `ui/app/settings/CategoryManager.tsx` (tree/picker reuse), `ui/app/cashflow/TransactionModal.tsx` + `ConfirmDialog.tsx`

No external ADRs — decisions captured above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`portfolio.portfolio_summary(db)`** — already returns per-platform groups with
  realized/unrealized/subtotal; PLAT-01's PnL tab is mostly a filter+display of it.
- **`writes.apply_delete_transaction(..., allow_paired)`** — pair-aware delete primitive already exists.
- **`TransactionModal` / `ConfirmDialog`** (Phase 16) — row edit (incl. transfer-leg lock) + destructive confirm.
- **`CategoryManager.tsx`** — recursive category tree; its picker feeds bulk-recategorize.
- **Segmented control** (Settings UIR-07 / Phase-16 modal) — reuse for the platform detail PnL/History tabs.
- **`styles.ts` tokens**, the cashflow recent-list row markup, the 422→reassign + error-copy conventions.

### Established Patterns
- Parameterized SQLAlchemy `text()`/query only (no client SQL); writes audit-logged; web-app-only writes stay off the MCP read surface (`READ_TOOL_NAMES`).
- Inline-style + token `styles.ts` (no Tailwind); `onChanged/onSaved` refetch (Pattern 5); Next.js proxy injects `MONAI_API_KEY`.
- e2e verification is Playwright (route-mocked) under `ui/e2e/`; no unit-test framework in `ui/`.

### Integration Points
- New nav route(s): `ui/app/records/page.tsx`, `ui/app/investments/[platformId]/page.tsx`; new `Nav.tsx` entry for Records.
- New backend params/endpoints on `backend/main.py` + `TransactionOut` field + new portfolio reads; no migration needed (`transfer_pair_id` column already exists).
</code_context>

<specifics>
## Specific Ideas

- Records ledger should feel like the cashflow recent-list grown up — same row styling, but grouped by day with a per-day net header and a filter bar on top.
- Platform detail tabs mirror the record modal's segmented control visually (one design language across the app).
- Transfer pairs must read as a single line so the ledger never looks like double-counting.
</specifics>

<deferred>
## Deferred Ideas

- **New category-manager UI** — already shipped in Phase 11; not rebuilt. Reused as the recategorize picker.
- Recurring-charge detection, side-by-side period comparison, token streaming — v2 backlog (QRY-01/02/03).
- Liquid→investment funding legs in the records ledger — surfaced as portfolio events in platform detail, not the transactions ledger.
- Exposing the new platform-detail reads as agent/MCP tools — deferred to keep this phase's tool surface unchanged.

None of the above were pulled into Phase 17 scope.
</deferred>

---

*Phase: 17-ui-new-surfaces-records-tab-categories-manager*
*Context gathered: 2026-08-01*
