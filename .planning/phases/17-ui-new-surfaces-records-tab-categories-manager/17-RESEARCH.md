# Phase 17: UI — New Surfaces (Records Tab, Platform Detail) - Research

**Researched:** 2026-08-02
**Domain:** FastAPI query-param filtering + bulk mutation endpoints, SQLAlchemy transfer-pair semantics, Next.js App Router dynamic routes, Playwright route-mocked e2e
**Confidence:** HIGH (all claims verified by direct source read of `backend/main.py`, `backend/writes.py`, `backend/schemas.py`, `backend/models.py`, `backend/portfolio.py`, `backend/tools.py`, `ui/app/components/Nav.tsx`, `ui/app/cashflow/TransactionModal.tsx`, `ui/app/cashflow/ConfirmDialog.tsx`, `ui/app/styles.ts`, `ui/playwright.config.ts`)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (filters — REC-01/02):** Extend `GET /transactions` (currently `limit`-only, `backend/main.py:641`) with optional, **server-side** parameterized query params: `q` (search over merchant/notes), `account_id`, `category`, `type` (expense|income|transfer), `amount_min`, `amount_max`, `include_transfers` (bool), `date_from`, `date_to`, `limit`, `offset`. Return a flat date-desc list. **Date-grouping + daily-net is computed client-side** in the Records page (presentation concern). Rationale: filtering = data-scoping (server, parameterized SQLAlchemy per the correctness-by-construction rule); grouping = presentation (client). Raise/keep a sane cap (e.g. 500) + offset paging.
- **D-02 (expose pair id — REC-05):** Add `transfer_pair_id: int | None` to `TransactionOut` (column already exists on the model, `models.py:157`). The ledger needs it to collapse the two legs of a transfer into one row. No new query — just surface the existing field.
- **D-03 (bulk actions — REC-03):** Add two **parameterized, audit-logged** endpoints, applied in one DB transaction: `POST /transactions/bulk-delete` (`{ids: int[]}`) and `POST /transactions/bulk-recategorize` (`{ids: int[], category: str}`). Web-app-only writes (API-key-gated; NOT added to the MCP read surface). UI gates destructive bulk-delete behind the existing `ConfirmDialog`. Bulk-delete handles transfer legs pair-aware (see D-04); bulk-recategorize skips/no-ops transfer legs (transfers are system-categorized).
- **D-04 (pair-aware delete — REC-05):** Deleting either leg from the ledger deletes **both** legs atomically (reuse `apply_delete_transaction(..., allow_paired=True)` for both, `writes.py:136`). Single-leg **edit stays blocked in the UI** (matches Phase 13 backend 422 + the Phase 16 modal transfer-leg lock). Applies to the single-row delete and to bulk-delete when a selected row is a transfer leg.
- **D-05 (platform detail reads — PLAT-01):** **PnL tab** sourced from `portfolio.portfolio_summary(db)`'s existing per-platform group (`platform_id`, realized + unrealized + subtotal — already computed, `portfolio.py:174`), exposed via a new read (e.g. `GET /platforms/{id}/detail` or filter an added `GET /portfolio`). **Buy/sell history tab** from a new read `GET /portfolio-events?platform_id={id}` (no such GET exists today — only POST) returning the event ledger (date, ticker, side, qty, price). Keep these as REST reads for the UI; **do not** add them to the agent/MCP tool surface this phase (scope containment).
- **D-06 (Records tab — REC-01/02/03):** New top-level nav item **"Records"** (`ui/app/components/Nav.tsx`) + new route `ui/app/records/page.tsx`. Contains: a **date-grouped ledger** (group by day, daily-net header per group), a **filter bar** (search, account, category, type, amount-range, transfer-visibility toggle → D-01 params), and **multi-select** with a **bulk action bar** (delete / recategorize). Reuse verbatim: `TransactionModal` (row edit), `ConfirmDialog` (bulk-delete confirm), the category tree/picker from CategoryManager (recategorize target), `styles.ts` tokens, the row/error conventions.
- **D-07 (transfer pairs in ledger — REC-05):** Rows sharing a `transfer_pair_id` render as **one collapsed row** ("Transfer: From → To", net-zero to spending). Edit opens `TransactionModal` in the Phase-16 transfer-leg-locked mode (segment locked, `PUT /transactions/{id}`). Delete uses the D-04 pair-aware path. No single-leg edit is offered.
- **D-08 (platform detail — PLAT-01):** New route `ui/app/investments/[platformId]/page.tsx`, reached by clicking a platform in the investments platform list/manager. **Two tabs** built from the existing segmented-control pattern: **PnL** (holdings with realized/unrealized/subtotal from D-05) and **Buy/Sell history** (the event ledger table from D-05). Reuse `HoldingModal`, tokens, segmented control.

### Claude's Discretion

- Exact route shape for platform detail (`/investments/[id]` vs `/platforms/[id]`), the precise filter-bar layout, whether bulk-recategorize opens the full category tree or a flat picker, and pagination style (offset vs "load more") — left to planning within the inline-style `styles.ts` convention. **Research recommendation:** keep `/investments/[platformId]` (mounted under the existing Investments nav item, matches the "reached by clicking a platform in the investments platform list" flow in D-08); offset-based "load more" for pagination (see Open Question 2).
- Whether the new backend reads (D-05) return a bespoke DTO or reuse `PortfolioSummary`/`PortfolioEventOut` shapes — planner/researcher's call. **Research recommendation:** reuse both existing shapes directly (see Pattern 4/5 below) — no new DTOs needed.

### Deferred Ideas (OUT OF SCOPE)

- **New category-manager UI** — already shipped in Phase 11; not rebuilt. Reused as the recategorize picker.
- Recurring-charge detection, side-by-side period comparison, token streaming — v2 backlog (QRY-01/02/03).
- Liquid→investment funding legs in the records ledger — surfaced as portfolio events in platform detail, not the transactions ledger.
- Exposing the new platform-detail reads as agent/MCP tools — deferred to keep this phase's tool surface unchanged.

**Scope correction (from CONTEXT.md):** the roadmap phase title says "Categories Manager" but the category tree manager already shipped in Phase 11 (`ui/app/settings/CategoryManager.tsx`). No CAT-* requirement is assigned to Phase 17 — there is no new category-manager build. The real scope is Records + Platform detail plus the backend plumbing both need.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| REC-01 | User can browse all records in a date-grouped ledger with a daily net per group | D-01 extended `GET /transactions` (server filters + offset paging, Pattern 1) feeds a client-side day-group/daily-net computation (Pitfall 4 covers the 500-row-cap paging requirement) |
| REC-02 | User can filter records by search, account, category, record type, amount range, and transfer visibility | Pattern 1 gives the exact parameterized-filter implementation for every one of these params, including hierarchy-aware category matching (Pitfall 3) and the `type=transfer` semantics question (Open Question 1) |
| REC-03 | User can select multiple records and bulk delete or bulk recategorize | Pattern 2 gives the full bulk-endpoint design (atomic transaction, partial-failure response shape, AuditLog-per-entity) plus the Decimal-JSON gotcha (Pattern 3) and transfer-leg skip behavior for recategorize |
| REC-05 | Transfer pairs display as one logical unit; editing or deleting affects both legs atomically (single-leg edits blocked) | D-02's `transfer_pair_id` exposure + Pitfalls 1-2 (the critical correction that `allow_paired=True` does NOT cascade — the endpoint must explicitly look up and delete the sibling leg, for both the existing single-delete endpoint and the new bulk-delete) + the collapse-to-one-row client logic (Code Examples) |
| PLAT-01 | User can open a platform detail view with a PnL tab and a buy/sell history tab | Pattern 4 (reuse `portfolio_summary()`'s per-platform group for `GET /platforms/{id}/detail`) + Pattern 5 (new `GET /portfolio-events?platform_id=` reusing `PortfolioEventOut`) + the dynamic-route/segmented-control frontend pattern (Code Examples) |
</phase_requirements>

## Summary

Phase 17 is backend-plumbing-heavy despite the "UI" title: 5 requirements need new query params on `GET /transactions`, two new bulk endpoints, one new field on `TransactionOut`, and two new platform-detail reads — before either frontend surface (Records ledger, Platform detail) can be built. All the primitives the backend work needs already exist and are correctly shaped: `apply_delete_transaction(..., allow_paired=True)` is already pair-aware, `portfolio_summary()` already returns per-platform PnL groups, and `resolve_period`/`_find_category_node`/`_descendant_ids` already give a hierarchy-aware category-filter pattern to copy. No new external packages are needed — this is 100% internal code composition.

The two frontend surfaces (Records ledger, Platform detail) are genuinely independent after the backend lands: Records only needs `GET /transactions` + bulk endpoints + `TransactionModal`/`ConfirmDialog`/`CategoryManager` reuse; Platform detail only needs the two new platform reads + the segmented-control pattern already used in `TransactionModal.tsx` and `settings/page.tsx`. Recommend a 3-wave plan: **Wave 1 = backend** (filters, bulk endpoints, transfer_pair_id, platform reads — all in `main.py`/`schemas.py`/`writes.py`), **Wave 2a = Records surface**, **Wave 2b = Platform detail surface** (2a/2b can run in parallel, both depend only on Wave 1).

**Primary recommendation:** One backend plan (Wave 1) exposing 4 new/extended endpoints, followed by two parallel frontend plans (Records, Platform detail) that only consume those endpoints — do not interleave backend and frontend work within a single plan given the size (5 requirements, 2 new surfaces, 4 endpoint changes).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Transaction filtering (search/account/category/type/amount/date/transfers) | API / Backend | — | Data-scoping = correctness-by-construction (parameterized SQLAlchemy); never client-side over an unbounded fetch |
| Day-grouping + daily-net | Browser / Client | — | Pure presentation of an already-filtered flat list; no new data need |
| Bulk delete / recategorize | API / Backend | Database | Atomic multi-row mutation + audit log — must be one DB transaction, not N client calls |
| Transfer-pair collapse (ledger row) | Browser / Client | API / Backend | API surfaces `transfer_pair_id` (data); client groups two legs into one visual row (presentation) |
| Transfer-pair-aware delete | API / Backend | Database | Both legs must vanish atomically — reuses existing `apply_delete_transaction(allow_paired=True)` |
| Platform PnL (realized/unrealized) | API / Backend | Database | Already computed server-side by `portfolio.portfolio_summary()` — no new calculation logic, just a scoped read |
| Buy/sell event history | API / Backend | Database | New read over `portfolio_events` table, platform-scoped |
| Nav entry + route mounting | Browser / Client (Next.js) | — | Static nav config + App Router file-based routing |

## Standard Stack

No new external packages. This phase composes existing dependencies only:

| Library | Version | Purpose | Why Standard (already in use) |
|---------|---------|---------|-------------------------------|
| FastAPI | >=0.110.0 (installed) | New query params + 2 POST endpoints | Already the only API framework in the repo |
| SQLAlchemy | >=2.0.0 (installed) | Parameterized filter query, bulk delete/update in one transaction | Already the only DB access layer; `db.query(Transaction).filter(...)` composes cleanly |
| Next.js App Router | 14.2.15 (installed) | `records/page.tsx`, `investments/[platformId]/page.tsx` dynamic segment | Already the routing mechanism (`ui/app/*/page.tsx` convention) |
| Playwright | installed (see `ui/playwright.config.ts`) | New route-mocked specs for Records + platform detail | Already the only e2e framework, no unit-test framework in `ui/` |

**Alternatives Considered**

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Server-side filter params (D-01, locked) | Client-side filter over a bulk fetch | Rejected in CONTEXT — violates correctness-by-construction and doesn't scale past the 500-row cap |
| Bulk endpoints (D-03, locked) | N sequential client DELETE/PUT calls | Rejected in CONTEXT — not atomic, N audit rows instead of 1, no partial-failure story |
| Reuse `PortfolioSummary`/`PortfolioEventOut` shapes for platform-detail reads | Bespoke platform-detail DTOs | Reuse recommended below (Claude's Discretion item) — avoids duplicate serialization logic for the same underlying data |

**Installation:** None required — no `pip install` / `npm install` needed for this phase.

## Package Legitimacy Audit

**Not applicable.** This phase adds zero external packages (backend: pure SQLAlchemy/FastAPI composition; frontend: pure React/Next.js composition of existing patterns). No `Package Legitimacy Audit` table is produced — the gate is scoped to phases that install new dependencies.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────┐
                    │  ui/app/records/page.tsx     │
                    │  (NEW — Records surface)     │
                    │                               │
   filter bar ──────┼──▶ fetch /api/transactions   │
   (q, account,     │      ?q=&account_id=&category=│
   category, type,  │      &type=&amount_min/max=   │
   amount range,    │      &include_transfers=      │
   xfer toggle)     │      &date_from/to=&limit=&   │
                    │      offset=                  │
                    │           │                    │
                    │           ▼                    │
                    │  client-side: group by day,    │
                    │  compute daily net,            │
                    │  collapse transfer_pair_id     │
                    │  rows into 1 ledger row         │
                    │           │                    │
   multi-select ────┼──▶ bulk action bar             │
   checkboxes       │      │         │                │
                    │      ▼         ▼                │
                    │  POST /api/  POST /api/          │
                    │  transactions/  transactions/    │
                    │  bulk-delete    bulk-recategorize│
                    └───────┼─────────┼────────────────┘
                            │         │
                            ▼         ▼
              ┌───────────────────────────────────┐
              │  Next.js proxy route.ts             │
              │  (injects MONAI_API_KEY server-side)│
              └───────────────┬─────────────────────┘
                               ▼
              ┌───────────────────────────────────┐
              │  backend/main.py                    │
              │  GET  /transactions  (extended)     │
              │  POST /transactions/bulk-delete NEW │
              │  POST /transactions/bulk-recategorize│
              │                                      │
              │  each row op calls writes.py:        │
              │  apply_delete_transaction(           │
              │    allow_paired=True)  [pair-aware]  │
              │  apply_edit_transaction(              │
              │    allow_paired=True)  [recategorize] │
              │                                      │
              │  ONE db.commit() for the whole batch  │
              │  N AuditLog rows, one per entity      │
              └───────────────┬─────────────────────┘
                               ▼
                    PostgreSQL: transactions, audit_log


                    ┌──────────────────────────────────────┐
                    │ ui/app/investments/[platformId]/      │
                    │ page.tsx (NEW — Platform detail)      │
                    │                                        │
   segmented ───────┼──▶ tab: PnL          tab: Buy/Sell     │
   control          │       │                   │            │
   (reuse pattern)  │       ▼                   ▼            │
                    │  fetch /api/         fetch /api/        │
                    │  platforms/{id}/     portfolio-events    │
                    │  detail (NEW)        ?platform_id={id}  │
                    │                       (NEW GET)          │
                    └───────┼───────────────────┼──────────────┘
                            ▼                   ▼
              ┌───────────────────────────────────────────┐
              │  backend/main.py                            │
              │  GET /platforms/{id}/detail  NEW            │
              │    -> filters portfolio.portfolio_summary()  │
              │       groups to platform_id == {id}          │
              │  GET /portfolio-events?platform_id=  NEW     │
              │    -> db.query(PortfolioEvent)                │
              │       .filter(platform_id==id)                │
              │       .order_by(desc(date))                   │
              └───────────────┬─────────────────────────────┘
                               ▼
                    PostgreSQL: holdings, portfolio_events,
                    price_cache, platforms

              NOTE: neither new platform-detail read is added to
              backend/tools.py TOOLS / READ_TOOL_NAMES — the phase
              deliberately keeps the agent/MCP tool surface unchanged.
```

### Recommended Project Structure

```
backend/
├── main.py              # extend list_transactions(); add bulk-delete,
│                         # bulk-recategorize, /platforms/{id}/detail,
│                         # GET /portfolio-events endpoints
├── schemas.py            # add transfer_pair_id to TransactionOut;
│                         # add BulkDeleteRequest/BulkRecategorizeRequest/
│                         # BulkActionResponse; add PlatformDetailOut (or
│                         # reuse PortfolioSummary's group shape)
├── writes.py              # NO changes needed — apply_delete_transaction
│                         # and apply_edit_transaction already accept
│                         # allow_paired; bulk endpoints just loop+call them
└── tests/
    ├── test_write_endpoints.py   # extend: bulk-delete, bulk-recategorize,
    │                             # transaction-filter param tests
    └── test_portfolio.py         # extend: platform-detail read tests

ui/app/
├── components/Nav.tsx     # add {href:"/records", label:"Records", icon:"records"}
├── records/
│   └── page.tsx           # NEW — date-grouped ledger, filter bar, bulk bar
├── investments/
│   ├── page.tsx           # existing — add Link to /investments/[platformId]
│   └── [platformId]/
│       └── page.tsx       # NEW — PnL + Buy/Sell segmented tabs
└── e2e/
    ├── records-crud.spec.ts       # NEW
    └── platform-detail.spec.ts    # NEW
```

### Pattern 1: Server-side parameterized transaction filter (D-01)

**What:** Extend `list_transactions` with optional query params, each adding one parameterized `.filter()`/SQL clause — never string-concatenated SQL.
**When to use:** Records ledger's filter bar (REC-02).
**Example — current code to extend (`backend/main.py:641-648`):**
```python
# Source: backend/main.py:641 (current, LIMIT-only)
@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(limit: int = 50, db: Session = Depends(get_session)):
    return (
        db.query(Transaction)
        .order_by(desc(Transaction.date))
        .limit(min(limit, 500))
        .all()
    )
```
**Recommended extension** (SQLAlchemy ORM `.filter()` chain — matches the ORM style already used for single-row CRUD in this file; the raw `text()` style in `tools.py` is used only for the read-only aggregation layer, not for CRUD-adjacent endpoints):
```python
@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    q: str | None = None,
    account_id: int | None = None,
    category: str | None = None,
    type: str | None = None,        # "expense" | "income" | "transfer"
    amount_min: float | None = None,
    amount_max: float | None = None,
    include_transfers: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    query = db.query(Transaction)
    if q:
        query = query.filter(
            or_(Transaction.merchant.ilike(f"%{q}%"), Transaction.notes.ilike(f"%{q}%"))
        )
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    if category is not None:
        node = _find_category_node(category)          # reuse tools.py helper
        if node is not None:
            query = query.filter(Transaction.category_id.in_(_descendant_ids(node)))
        else:
            query = query.filter(Transaction.category == category)  # fallback exact match
    if type == "expense":
        query = query.filter(Transaction.amount < 0, Transaction.is_transfer == False)
    elif type == "income":
        query = query.filter(Transaction.amount > 0, Transaction.is_transfer == False)
    elif type == "transfer":
        query = query.filter(Transaction.is_transfer == True)
    elif not include_transfers:
        query = query.filter(Transaction.is_transfer == False)
    if amount_min is not None:
        query = query.filter(func.abs(Transaction.amount) >= amount_min)
    if amount_max is not None:
        query = query.filter(func.abs(Transaction.amount) <= amount_max)
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date < date_to)  # caller passes exclusive bound, or +1 day like resolve_period
    return (
        query.order_by(desc(Transaction.date))
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )
```
Note: `_find_category_node`/`_descendant_ids` live in `backend/tools.py` (module-private helpers, no leading-underscore-import convention broken since `main.py` already imports plain functions from `tools.py` elsewhere) — import them, or lift the two small tree-walk helpers into `main.py`/a shared module if cross-module private-function imports feel wrong for this codebase's convention. **[ASSUMED: exact import mechanics — verify during planning whether `tools.py`'s underscore-prefixed helpers are already imported cross-module anywhere else in `main.py`; if not, this may warrant a small shared-helpers extraction rather than importing a private name.]**

### Pattern 2: Bulk endpoint atomicity + audit (D-03)

**What:** One request body with `ids: int[]`, one `db.commit()` for the whole batch, one `AuditLog` row per entity (not one per batch) — matching the existing single-op `apply_*` contract exactly.
**When to use:** `POST /transactions/bulk-delete`, `POST /transactions/bulk-recategorize`.
**Example, modeled on the existing single-delete endpoint (`backend/main.py:802-823`):**
```python
# Source: pattern derived from backend/main.py:802 delete_transaction +
# backend/writes.py:136 apply_delete_transaction (allow_paired already exists)
class BulkDeleteRequest(BaseModel):
    ids: list[int]

class BulkActionResponse(BaseModel):
    deleted: list[int] = []      # or "recategorized"
    skipped: list[dict] = []     # [{id, reason}] — partial-failure surfaced, not silently dropped

@app.post("/transactions/bulk-delete", response_model=BulkActionResponse,
          dependencies=[Depends(require_api_key)])
def bulk_delete_transactions(payload: BulkDeleteRequest, db: Session = Depends(get_session)):
    deleted, skipped = [], []
    for tx_id in payload.ids:
        tx = db.get(Transaction, tx_id)
        if tx is None:
            skipped.append({"id": tx_id, "reason": "not found"})
            continue
        before = {  # same before-shape as delete_transaction (main.py:808-818)
            "id": tx.id, "date": tx.date.isoformat() if tx.date else None,
            "amount": str(tx.amount), "currency": tx.currency, "category": tx.category,
            "merchant": tx.merchant, "notes": tx.notes, "account_id": tx.account_id,
            "is_transfer": tx.is_transfer,
        }
        apply_delete_transaction(db, tx_id, before, allow_paired=True)  # D-04: pair-aware
        deleted.append(tx_id)
        if tx.transfer_pair_id is not None:
            # the paired leg was NOT in `ids` but must also vanish (D-04) —
            # apply_delete_transaction only deletes the ONE row passed to it;
            # the caller must explicitly also delete the sibling leg.
            sibling_id = (
                db.query(Transaction.id)
                .filter(Transaction.transfer_pair_id == tx.transfer_pair_id, Transaction.id != tx_id)
                .scalar()
            )
            if sibling_id is not None and sibling_id not in deleted:
                sibling_before = {...}  # same shape, fetched before delete
                apply_delete_transaction(db, sibling_id, sibling_before, allow_paired=True)
                deleted.append(sibling_id)
    db.commit()  # ONE transaction boundary for the whole batch (D-03 "atomic")
    from backend.query import reset_engine
    reset_engine()
    return BulkActionResponse(deleted=deleted, skipped=skipped)
```
**Critical correction to CONTEXT D-04's wording:** `apply_delete_transaction(..., allow_paired=True)` only removes the ONE transaction id passed to it — it does not cascade to the sibling leg itself (confirmed from `writes.py:136-147`: `allow_paired=True` just **bypasses the guard that blocks deleting a paired leg**, it doesn't fetch or delete the pair). The endpoint (single-delete AND bulk-delete) must **explicitly look up and delete both legs** when either is a transfer row, as shown above. This applies equally to the single `DELETE /transactions/{tx_id}` endpoint (currently at `main.py:802`, calls `apply_delete_transaction(db, tx_id, before)` with no `allow_paired` at all today — it will 422 on any transfer leg until this phase adds pair-lookup logic there too, per D-04).

`bulk-recategorize` mirrors this shape but calls `apply_edit_transaction(db, tx_id, {"category": payload.category}, before, allow_paired=False)` and **skips (does not error on) transfer legs** — per D-03: "bulk-recategorize skips/no-ops transfer legs (transfers are system-categorized)". Detect via `tx.is_transfer` before calling `apply_edit_transaction`, add skipped id with `reason: "transfer leg — system-categorized"` to the response, do not raise.

### Pattern 3: AuditLog Decimal-JSON gotcha (memory: `auditlog-decimal-json-gotcha.md`)

**What:** `AuditLog.after`/`before` are JSONB columns. `apply_add_transaction`/`apply_edit_transaction`/`apply_delete_transaction` all already convert `Decimal` to `str()` before putting it in `after`/`before` dicts (see `writes.py:62`, `writes.py:103`, `writes.py:128`). **Never build a bulk-endpoint `before`/`after` dict that stuffs a raw `Transaction.amount` (a `Decimal`) directly** — always `str(tx.amount)` as the existing single-row endpoints do (`main.py:782`, `main.py:811`).
**Why it matters here:** the bulk-delete/bulk-recategorize loop above builds `before` dicts per-row inline — a naive refactor that reuses `tx.amount` without `str()` reintroduces the exact bug this project already hit once (see Memory: `auditlog-decimal-json-gotcha.md`).
**How to avoid:** Copy the `before` dict construction verbatim from `delete_transaction`/`update_transaction` (main.py:779-789, 808-818) — both already do `"amount": str(tx.amount)`.

### Pattern 4: Platform-detail reads reuse `portfolio_summary()` (D-05)

**What:** `portfolio.portfolio_summary(db)` (`backend/portfolio.py:174`) already computes and groups everything the PnL tab needs — `{platform_id, platform_name, kind, subtotal, holdings: [{ticker, quantity, avg_cost, current_price, current_value, unrealized_pnl, realized_pnl, is_stale, ...}]}` per platform.
**When to use:** `GET /platforms/{id}/detail`.
**Example:**
```python
# Source: backend/portfolio.py:174 portfolio_summary(), backend/main.py:575 investments_summary()
@app.get("/platforms/{platform_id}/detail")
def platform_detail(platform_id: int, db: Session = Depends(get_session)):
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    from backend.prices import refresh_all_prices
    refresh_all_prices(db, force=False)  # same lazy-refresh idiom as investments_summary (D-09)
    db.commit()
    summary = portfolio_summary(db)
    group = next((g for g in summary["groups"] if g["platform_id"] == platform_id), None)
    return group or {"platform_id": platform_id, "platform_name": platform.name,
                      "kind": platform.kind, "subtotal": 0, "holdings": []}
```
**Discretion resolved:** reuse the existing `groups[i]` shape (a plain dict, same as `PortfolioSummary.groups: list`) rather than inventing a bespoke DTO — it already contains every PnL field PLAT-01 needs (realized_pnl, unrealized_pnl, current_value per holding, subtotal). No new Pydantic response_model needed; return the dict directly (matches `PortfolioSummary`'s own "money fields inside `groups` are already Decimal; dict passthrough" convention, `schemas.py:307-320`).

### Pattern 5: Buy/sell history read — new `GET /portfolio-events`

**What:** No such GET exists today (`backend/main.py` only has `POST /portfolio-events` at line 427). `PortfolioEventOut` (`schemas.py:184`) already has the exact fields PLAT-01's history tab needs (`id, date, ticker, event_type, quantity, price`) — reuse it directly, filtered by `platform_id`.
```python
# Source: backend/models.py:249 PortfolioEvent, backend/schemas.py:184 PortfolioEventOut
@app.get("/portfolio-events", response_model=list[PortfolioEventOut])
def list_portfolio_events(platform_id: int, db: Session = Depends(get_session)):
    return (
        db.query(PortfolioEvent)
        .filter(PortfolioEvent.platform_id == platform_id)
        .order_by(desc(PortfolioEvent.date))
        .all()
    )
```
**Note:** `PortfolioEventOut` omits `platform_id`/`source_account_id` — fine per D-05's scope (buy/sell history is date/ticker/side/qty/price only). If the UI wants a "funded from account X" column later, that's a schema extension outside this phase's scope.

### Anti-Patterns to Avoid

- **Cascading delete inside `apply_delete_transaction` itself:** do NOT modify `writes.py:apply_delete_transaction` to auto-delete the sibling leg — it is a shared primitive also called by the single-row `DELETE /transactions/{tx_id}` endpoint and the agent propose/confirm path; changing its cascade behavior there is a wider blast radius than needed. Keep the pair-lookup-and-delete-both logic in the **endpoint** (both single and bulk), which already has DB access to look up the sibling — matches how `apply_add_transfer` composes two `apply_add_transaction` calls at the *endpoint/composition* layer, not inside the primitive.
- **Client-side N-call loops for bulk actions:** explicitly rejected by D-03 — a `for (const id of selected) await fetch(...)` loop from the Records page is not atomic and produces N audit rows instead of one batch.
- **Adding platform-detail reads to `backend/tools.py` TOOLS dict:** D-05 explicitly keeps these off the agent/MCP surface. Do not add `platform_detail`/`list_portfolio_events`-equivalent functions to `tools.py`'s `TOOLS` registry — they're pure REST-endpoint-local logic in `main.py`, never wrapped as an agent tool this phase.
- **Filtering `GET /transactions` against the `cashflow_transactions` VIEW:** that view excludes investment-typed-account rows (`NOT EXISTS ... type='investment'`) — appropriate for spending aggregates but WRONG for a full transaction ledger, which must show every row. Keep querying the base `transactions` table (as the current unmodified `list_transactions` already does) — do not switch to `cashflow_transactions` when adding filters.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Category hierarchy matching for the `category` filter param | A new fuzzy/substring category matcher | `tools.py:_find_category_node` + `_descendant_ids` (already handles case-insensitive exact/substring + subtree expansion) | Exact same semantics as `spending_in_category`'s filter — consistency across dashboard and ledger |
| Transfer-pair sibling lookup | A new "find my transfer partner" helper module | `Transaction.transfer_pair_id` self-join: `db.query(Transaction).filter(transfer_pair_id == X, id != tx_id)` (2-3 lines) | The column + shared-group-id convention (`writes.py:165-166`, "both legs' transfer_pair_id set to leg A's own id") already fully defines pair lookup — no new abstraction needed |
| Recategorize target picker | A new flat category `<select>` | `CategoryManager.tsx`'s existing tree UI (Phase 11) or `TransactionModal.tsx`'s `flattenCategories()` helper (already excludes system nodes) | Both already exist and are exercised in production; a third category-picker implementation is pure duplication |
| Segmented control (PnL / Buy-Sell tabs) | A tabs library | Copy the inline-style segmented-control markup from `TransactionModal.tsx:360-397` (or `settings/page.tsx` UIR-07 origin) | Third use of the same ~35-line pattern in this codebase — it's already the established idiom, no dependency justified |
| Partial-failure bulk response shape | A generic "batch result" library/class | Plain `{deleted: [...], skipped: [{id, reason}]}` dict, mirrored on the Pydantic response model shown above | The problem is small and fully bounded (max 500 ids per the existing cap) — a library adds indirection for no benefit |

**Key insight:** Every non-trivial piece of logic this phase needs (pair lookup, hierarchy filtering, PnL computation, segmented control, category picker) is a 2026-08-01-or-earlier commit already sitting in this repo. This phase is almost entirely **composition**, not new algorithm design — treat any research finding that proposes a genuinely new abstraction with suspicion.

## Common Pitfalls

### Pitfall 1: `allow_paired=True` does not cascade-delete the sibling

**What goes wrong:** Assuming `apply_delete_transaction(db, tx_id, before, allow_paired=True)` deletes both legs of a transfer because "pair-aware" sounds like it handles the pair.
**Why it happens:** The parameter name and CONTEXT.md's D-04 prose ("deleting either leg... deletes both legs atomically") read as if the primitive does the cascading. It does not — `allow_paired=True` only **suppresses the guard** that otherwise raises `ValueError` when deleting a paired leg (`writes.py:140-144`). The actual deletion of a single row (`db.delete(tx)`) is unconditional and scoped to the one `tx_id` passed in.
**How to avoid:** The endpoint layer (both `DELETE /transactions/{tx_id}` and the new bulk-delete) must look up `Transaction.transfer_pair_id`, find the sibling row (`transfer_pair_id == X AND id != tx_id`), and call `apply_delete_transaction` on it too, inside the same DB transaction, before the single `db.commit()`.
**Warning signs:** A test that deletes one leg and finds the sibling still present in the DB after commit.

### Pitfall 2: The existing single `DELETE /transactions/{tx_id}` will 422 on any transfer leg today

**What goes wrong:** Assuming REC-05 ("editing or deleting affects both legs atomically") is purely new frontend behavior layered on unchanged backend.
**Why it happens:** `main.py:802-823`'s `delete_transaction` calls `apply_delete_transaction(db, tx_id, before)` with **no `allow_paired` argument at all** — it defaults to `False`. Deleting a transfer leg through the existing single-delete endpoint today raises `ValueError` (→422) via the guard at `writes.py:140-144`.
**How to avoid:** This phase must also touch the *existing* single-delete endpoint, not just add new bulk endpoints — add the same pair-lookup-and-delete-both logic there. REC-05 is a backend change to an existing endpoint, not purely additive.
**Warning signs:** A Records-ledger single-row delete on a transfer row returns 422 in manual testing even after the bulk endpoint works.

### Pitfall 3: Category filter param needs hierarchy expansion, or "Food" silently misses "Food & Drinks > Coffee" rows

**What goes wrong:** A naive `Transaction.category == category` filter only matches exact-string rows, missing every subcategory — inconsistent with how `spending_in_category`/`CAT-04`'s dashboard rollups already treat a parent category name as "this node + all descendants."
**Why it happens:** `Transaction.category` (legacy string column) still exists alongside `Transaction.category_id` (FK, D-08 dual-write) — it's easy to filter on the flat string column and get exact-match-only behavior that silently diverges from every other category-aware read in the app.
**How to avoid:** Resolve `category` via `_find_category_node` + `_descendant_ids` → `category_id.in_(ids)`, exactly like `spending_in_category` (`tools.py:294-300`). Reserve string-exact fallback only for the case `_find_category_node` returns `None`.
**Warning signs:** Filtering by a parent/group category (e.g. "Food & Drinks") in the Records ledger returns fewer rows than the dashboard's category-rollup total for the same period.

### Pitfall 4: The 500-row cap silently truncates a full-history ledger

**What goes wrong:** `list_transactions`'s `.limit(min(limit, 500))` caps every response at 500 rows regardless of the requested `limit`. A user with >500 total transactions (this project's live DB has 5608+ rows per CLAUDE.md's currency-check note) will never see their full history without `offset` paging — and a Records page built assuming "one fetch = the whole ledger" will silently show only the newest 500.
**Why it happens:** The cap exists for good reason (open, unauthenticated-by-default GET, no `require_api_key` — must bound response size) but the Records surface's entire purpose is browsing the *full* history.
**How to avoid:** The `offset` param (D-01, already locked) is mandatory, not optional — the Records page must implement either "load more" (increment offset) or numbered pages; do not ship a first cut that only calls the endpoint once with a large `limit` and calls it done. Confirm the cap value (keep 500, or raise per the CONTEXT note "keep a sane cap (e.g. 500) + offset paging" — 500 is explicitly sanctioned, don't need to raise it).
**Warning signs:** A live-data QA pass ("browse to page 2") reveals older transactions never appear no matter how the filter bar is set.

### Pitfall 5: `is_transfer` alone does not distinguish transfers from Adjustment/Investment-funding rows

**What goes wrong:** The `type` filter param (D-01: expense|income|transfer) and the `include_transfers` toggle both key off `is_transfer`. But `is_transfer=True` is *also* set on balance-adjustment rows (`writes.py:105`, category='Adjustment') and funded-buy/sell cash legs (`writes.py:218`, category='Investment') — per the project's own decision log ("is_transfer is the only existing lever that excludes a row from cashflow totals," Phase 13). A `type=transfer` filter meant to show liquid↔liquid transfer pairs will also surface Adjustment and Investment-funding rows, which are NOT `transfer_pair_id`-paired and would break the "collapse into one row" ledger logic (D-07) if treated as pairs.
**Why it happens:** `is_transfer` was designed as a single "exclude from spending totals" lever (D-08, Phase 13), not as a discriminator between transfer-pair rows, adjustment rows, and funding rows.
**How to avoid:** For D-07's pair-collapse logic specifically, key off `transfer_pair_id IS NOT NULL` (only true liquid↔liquid transfer legs have this set — `writes.py:165-166`), not `is_transfer`. For the `type=transfer` filter param, decide explicitly whether it means "is_transfer=true" (includes Adjustment/Investment rows) or "transfer_pair_id IS NOT NULL" (only true pairs) — **recommend the latter for ledger display purity**, and let Adjustment/Investment rows surface under `type=expense`/`income` naturally (an Adjustment row has a sign like income/expense; Investment-funding legs are debits). **[ASSUMED — flag for CONTEXT confirmation]:** whether "Adjustment" and "Investment"-category is_transfer rows should appear in the Records ledger at all, and under which `type` filter bucket — CONTEXT.md doesn't explicitly resolve this edge case.
**Warning signs:** The Records ledger shows an "Adjustment" or "Investment" row rendered as a broken/unpaired "Transfer:" collapsed row (no sibling to pair with).

### Pitfall 6: PLAYWRIGHT_CHROMIUM_PATH — sandboxed CI/dev env has no bundled Chromium

**What goes wrong:** `npx playwright test` fails to launch because the default bundled-browser path (`/opt/pw-browsers` or similar) doesn't exist in this environment.
**Why it happens:** `ui/playwright.config.ts:6-33` already has a documented fallback: `process.env.PLAYWRIGHT_CHROMIUM_PATH || <default>`, with `executablePath: fallbackChromiumPath` wired in.
**How to avoid:** Run e2e specs with `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test` (confirmed working value from prior phases per phase brief). Any new spec file added this phase inherits the same config automatically — no per-spec change needed, just remember the env var when invoking the runner.
**Warning signs:** `browserType.launch: Executable doesn't exist at ...` on a fresh shell.

## Code Examples

### Nav.tsx — adding the Records entry (D-06)

```typescript
// Source: ui/app/components/Nav.tsx:17-22 (current NAV_LINKS array)
const NAV_LINKS = [
  { href: "/cashflow", label: "Cashflow", icon: "cashflow" },
  { href: "/records", label: "Records", icon: "records" },      // NEW — insert here
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/investments", label: "Investments", icon: "investments" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;
```
`IconName` type auto-widens from `(typeof NAV_LINKS)[number]["icon"]` — add a `"records"` case to the `Icon()` switch (`Nav.tsx:27-67`) with a new inline SVG path (a simple list/ledger glyph is consistent with the existing stroke-icon style: `width:20 height:20 viewBox:"0 0 24 24" stroke:"currentColor" strokeWidth:1.7`).

### Next.js dynamic route for platform detail (D-08)

```
ui/app/investments/[platformId]/page.tsx
```
Standard App Router convention (already used implicitly nowhere else in this repo yet, but is the canonical Next.js 14 pattern — `[platformId]` folder name binds `params.platformId: string` in the page component). `"use client"` component (matches every other page in `ui/app/`), reads `useParams()` or the `params` prop, fetches `/api/platforms/${platformId}/detail` and `/api/portfolio-events?platform_id=${platformId}` on mount, renders the segmented-control pattern copied from `TransactionModal.tsx:360-397`.

### Transfer-pair collapse — client-side grouping (D-07)

```typescript
// Client-side grouping logic for records/page.tsx — groups rows sharing
// transfer_pair_id into one display row. Runs AFTER the server-filtered
// fetch (D-01: grouping is a presentation concern per locked decision).
function collapseTransferPairs(rows: Tx[]): LedgerRow[] {
  const seen = new Set<number>();
  const result: LedgerRow[] = [];
  for (const tx of rows) {
    if (tx.transfer_pair_id == null) {
      result.push({ kind: "single", tx });
      continue;
    }
    if (seen.has(tx.transfer_pair_id)) continue;   // already emitted this pair
    seen.add(tx.transfer_pair_id);
    const sibling = rows.find(
      (r) => r.transfer_pair_id === tx.transfer_pair_id && r.id !== tx.id
    );
    result.push({ kind: "transfer-pair", legA: tx, legB: sibling ?? null });
  }
  return result;
}
```
Note: if the server-side filter (e.g. `account_id`) matches only ONE leg of a pair (the two legs are on different accounts by definition), `sibling` may be `undefined` in a filtered view — the UI must degrade gracefully (render the single visible leg, not crash) rather than assume both legs are always co-present in a filtered result set. **[ASSUMED]** — flag this UX edge case for planning: filtering "Records by account=Checking" will show the outgoing leg of a transfer to Savings, with no sibling in the same filtered set. This is expected/correct (that's what "account-scoped filtering" means) but the collapse function must not throw on a missing sibling.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `GET /transactions?limit=` only, no filters | Server-side filter params + offset paging (this phase) | Phase 17 | Records tab becomes viable; dashboard's `/cashflow/summary` stays untouched (separate endpoint) |
| `TransactionOut` without `transfer_pair_id` | Exposed field (this phase) | Phase 17 | Frontend can finally detect and collapse transfer pairs — previously invisible over the API despite existing in the DB since migration 010 |
| Single-row-only write endpoints | Bulk endpoints (this phase) | Phase 17 | First bulk-mutation surface in the app; sets precedent for future "select multiple, act once" UI patterns |

**Deprecated/outdated:** None — this phase only adds capability, it doesn't retire anything. The legacy `Transaction.category` string column stays alongside `category_id` (dual-write, per Phase 11 D-08) — not touched this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Cross-module import of `tools.py`'s underscore-prefixed `_find_category_node`/`_descendant_ids` into `main.py` is acceptable, vs. extracting them to a shared module | Pattern 1 | Low — cosmetic; planner can choose either without changing behavior |
| A2 | Whether "Adjustment"/"Investment"-category `is_transfer=True` rows should appear in the Records ledger, and under which `type` filter bucket | Pitfall 5 | Medium — wrong bucketing could make the ledger's per-day net or transfer-visibility toggle behave unexpectedly for these edge-case rows; recommend explicit confirmation during planning or a follow-up CONTEXT question |
| A3 | Filtered views (e.g. account-scoped) may show one leg of a transfer pair without its sibling present in the same result set — UI must degrade gracefully | Code Examples (collapse function) | Low-Medium — an unhandled case here could crash the Records page render, not just look wrong |

**If this table is empty:** N/A — see above.

## Open Questions

1. **Should `type=transfer` filter mean `is_transfer=true` or `transfer_pair_id IS NOT NULL`?**
   - What we know: `is_transfer=true` is a broader flag also covering Adjustment and Investment-funding rows (Pitfall 5); `transfer_pair_id IS NOT NULL` is the narrower, precise "this is one leg of a liquid↔liquid transfer pair" signal.
   - What's unclear: CONTEXT.md's D-01 lists `type` as one of `expense|income|transfer` without disambiguating which underlying column/condition backs "transfer."
   - Recommendation: use `transfer_pair_id IS NOT NULL` for `type=transfer` (matches D-07's pair-collapse semantics exactly, and keeps Adjustment/Investment rows correctly bucketed under expense/income by their sign) — surface this as a locked decision during planning rather than leaving it implicit in code.

2. **Exact cap-raise vs. keep-500 for `GET /transactions` given a full-ledger use case.**
   - What we know: CONTEXT explicitly sanctions keeping ~500 as "a sane cap... + offset paging."
   - What's unclear: Whether 500 is comfortable for a single "page" of the Records ledger UX (that's a lot of rows to day-group and render at once) or whether the frontend should default to a smaller `limit` (e.g. 100) per fetch with the 500 as a hard ceiling only.
   - Recommendation: default frontend fetch `limit=100`, `offset` increments for "load more" — well under the 500 ceiling, keeps the client-side day-grouping/rendering fast. Backend cap stays 500 as the hard maximum.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | All backend reads/writes | ✓ (per project CLAUDE.md, port 5434) | 16-alpine | — |
| Playwright + Chromium | New e2e specs | ✓ with `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome` (config already handles fallback) | installed, see `ui/playwright.config.ts` | Bundled path `/opt/pw-browsers` absent — env var fallback confirmed working in this environment (Pitfall 6) |
| Node.js / npm | Frontend build + e2e | ✓ | 20-alpine (Docker) / 22.x (host) | — |
| Python / uv | Backend | ✓ | 3.12-slim (Docker) / 3.14 (host) | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** Playwright's bundled Chromium — always launch with `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome` set.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Backend framework | pytest >=8.0.0, live-Postgres integration style (no mocking, matches `test_write_tools.py`/`test_write_endpoints.py` idiom — direct DB introspection, explicit rollback of probe inserts) |
| Backend config | none dedicated — `backend/tests/` convention, run via `pytest backend/tests/` |
| Frontend framework | Playwright, route-mocked (`ui/e2e/*.spec.ts`) — no unit-test framework in `ui/` |
| Frontend config | `ui/playwright.config.ts` (Chromium executablePath fallback wired) |
| Quick run command | `pytest backend/tests/test_write_endpoints.py -k bulk -x` (backend); `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test e2e/records-crud.spec.ts` (frontend) |
| Full suite command | `pytest backend/tests/` (backend); `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test` (frontend, from `ui/`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REC-01 | Date-grouped ledger with daily net renders full history via paged fetch | e2e (route-mocked) | `npx playwright test e2e/records-crud.spec.ts -g "date-grouped"` | ❌ Wave 0 |
| REC-01 | `GET /transactions` respects `offset`/`limit` paging | backend integration | `pytest backend/tests/test_write_endpoints.py -k transaction_paging -x` | ❌ Wave 0 |
| REC-02 | Each filter param (q, account_id, category, type, amount range, include_transfers, date range) narrows results correctly | backend integration | `pytest backend/tests/test_write_endpoints.py -k transaction_filter -x` | ❌ Wave 0 |
| REC-02 | Category filter includes subcategory rows (hierarchy) | backend integration | `pytest backend/tests/test_write_endpoints.py -k category_filter_hierarchy -x` | ❌ Wave 0 |
| REC-03 | Bulk-delete removes all selected ids atomically, one AuditLog per entity | backend integration | `pytest backend/tests/test_write_endpoints.py -k bulk_delete -x` | ❌ Wave 0 |
| REC-03 | Bulk-recategorize applies to all non-transfer ids, skips transfer legs | backend integration | `pytest backend/tests/test_write_endpoints.py -k bulk_recategorize -x` | ❌ Wave 0 |
| REC-03 | Bulk-delete/recategorize UI multi-select + bulk bar + ConfirmDialog | e2e (route-mocked) | `npx playwright test e2e/records-crud.spec.ts -g "bulk"` | ❌ Wave 0 |
| REC-05 | `transfer_pair_id` present in `TransactionOut` JSON | backend integration | `pytest backend/tests/test_write_endpoints.py -k transfer_pair_id_exposed -x` | ❌ Wave 0 |
| REC-05 | Deleting one leg (single or bulk) deletes both legs | backend integration | `pytest backend/tests/test_write_tools.py -k pair_aware_delete -x` (extend existing `test_paired_leg_delete_blocked` file) | ❌ Wave 0 (extend existing file) |
| REC-05 | Transfer pair renders as one collapsed row; edit opens transfer-locked modal | e2e (route-mocked) | `npx playwright test e2e/records-crud.spec.ts -g "transfer pair"` | ❌ Wave 0 |
| PLAT-01 | `GET /platforms/{id}/detail` returns correct PnL group scoped to that platform | backend integration | `pytest backend/tests/test_portfolio.py -k platform_detail -x` | ❌ Wave 0 |
| PLAT-01 | `GET /portfolio-events?platform_id=` returns only that platform's events, date-desc | backend integration | `pytest backend/tests/test_portfolio.py -k portfolio_events_by_platform -x` | ❌ Wave 0 |
| PLAT-01 | Platform detail page renders PnL tab + Buy/Sell tab via segmented control | e2e (route-mocked) | `npx playwright test e2e/platform-detail.spec.ts` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** relevant quick-run command for the touched surface (backend test file or targeted e2e spec)
- **Per wave merge:** full backend `pytest backend/tests/` + full `npx playwright test` (from `ui/`, with `PLAYWRIGHT_CHROMIUM_PATH` set)
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_write_endpoints.py` — add filter-param tests, bulk-delete/bulk-recategorize tests, transfer_pair_id exposure test
- [ ] `backend/tests/test_write_tools.py` — extend pair-aware delete coverage to the bulk path (existing `test_paired_leg_delete_blocked` at line 1618 covers the single-row guard already)
- [ ] `backend/tests/test_portfolio.py` — add platform-detail and portfolio-events-by-platform read tests
- [ ] `ui/e2e/records-crud.spec.ts` — new spec file (date-grouping, filter bar, bulk select/delete/recategorize, transfer-pair collapse+edit+delete)
- [ ] `ui/e2e/platform-detail.spec.ts` — new spec file (route to `/investments/[id]`, PnL tab, Buy/Sell tab)
- [ ] No new test-framework install needed — pytest and Playwright are both already configured

## Security Domain

`security_enforcement` not set to `false` in `.planning/config.json` → treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Single-user, no auth layer in this app (documented architecture) |
| V3 Session Management | No | N/A — no sessions |
| V4 Access Control | Yes | `dependencies=[Depends(require_api_key)]` on both new bulk endpoints and both new platform-detail POST-adjacent writes; GET reads (`/platforms/{id}/detail`, `/portfolio-events`) stay open reads matching the existing `/investments/summary`/`GET /transactions` precedent (no `require_api_key`) — consistent with "every write route requires the API key... GET /investments/summary is an open read" convention already documented at `main.py:422` |
| V5 Input Validation | Yes | Pydantic `BulkDeleteRequest`/`BulkRecategorizeRequest` (typed `ids: list[int]`); FastAPI query-param type coercion on all new `GET /transactions` params (int/float/bool/str) rejects malformed input with 422 automatically |
| V6 Cryptography | No | N/A — no new secrets/crypto this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SQL injection via `q` search param | Tampering | Parameterized `.ilike()` through SQLAlchemy ORM `.filter()` — never raw string concatenation into `text()`. The `q` param is bound as a query parameter, not interpolated into SQL text. |
| IDOR — bulk-delete/recategorize accepting arbitrary ids not scoped to any owner | Tampering / Information Disclosure | Not applicable at the threat-model level (single-user app, no cross-tenant boundary exists) — but still validate each id exists (`db.get(Transaction, tx_id) is None` → skip/report, never raise a raw 500) to avoid `IntegrityError`/`AttributeError` leaks, mirroring the `apply-fk-integrityerror-not-422` memory (validate refs explicitly, convert to `ValueError`→422 rather than letting a DB constraint violation surface as a 500) |
| Mass-deletion blast radius (bulk-delete with no cap) | Denial of Service (self-inflicted data loss) | The UI gates bulk-delete behind `ConfirmDialog` (D-03, already decided) showing the count; consider a sane `ids` length cap (e.g. reject/422 above 500, matching the existing per-request row cap) at the schema/endpoint level — **[ASSUMED]**, not explicitly locked in CONTEXT, flag for planner discretion |
| Agent/MCP tool-surface creep | Elevation of Privilege | New platform-detail reads and bulk endpoints must NOT be added to `backend/tools.py`'s `TOOLS` dict / `READ_TOOL_NAMES` frozenset — explicitly scoped out by D-05's "do not add to agent/MCP tool surface" and D-03's "web-app-only writes... NOT added to the MCP read surface." Verify via `grep -n "TOOLS\[" backend/tools.py` after implementation shows no new entries. |

## Sources

### Primary (HIGH confidence — direct source read, this session)
- `backend/main.py` (lines 575-928) — `GET /transactions`, `DELETE /transactions/{id}`, `PUT /transactions/{id}`, `POST /transactions/transfer`, `GET /investments/summary`, all `require_api_key`-gated write route dependency wiring
- `backend/writes.py` (lines 1-220) — `apply_delete_transaction`, `apply_edit_transaction`, `apply_add_transfer`, `apply_add_investment_transfer`, `resolve_category_id`
- `backend/schemas.py` (full file) — `TransactionOut`, `TransactionUpdate`, `PortfolioSummary`, `PortfolioEventOut`, `TransferCreate`, money-Decimal serialization convention
- `backend/models.py` (lines 120-280) — `Transaction.transfer_pair_id` (plain Integer, no FK, indexed), `PortfolioEvent`, `AuditLog` (JSONB before/after)
- `backend/portfolio.py` (lines 140-320) — `portfolio_summary()` group-building logic, per-holding realized/unrealized PnL shape
- `backend/tools.py` (lines 1-90, 200-330, 594-625) — `resolve_period`, `PERIODS`, `_find_category_node`, `_descendant_ids`, `spending_in_category` (hierarchy-filter reference pattern), `find_transactions` (existing filter-clause-building pattern), `READ_TOOL_NAMES` frozenset location
- `ui/app/components/Nav.tsx` (full file) — `NAV_LINKS` array + `Icon()` switch pattern
- `ui/app/cashflow/TransactionModal.tsx` (full file) — segmented control markup, transfer-leg lock (`locked`/`showFromTo`), category flatten helper
- `ui/app/cashflow/ConfirmDialog.tsx` (partial) — reusable destructive-confirm modal shape
- `ui/app/styles.ts` (lines 1-140) — `tokens`, `card`, `input`, `btn`, `label` design-token exports
- `ui/playwright.config.ts` — `PLAYWRIGHT_CHROMIUM_PATH` fallback mechanism (confirmed via grep, lines 6-33)
- `.planning/phases/17-ui-new-surfaces-records-tab-categories-manager/17-CONTEXT.md` — D-01..D-08 locked decisions
- `.planning/phases/16-ui-extend-existing-components/16-CONTEXT.md` — record-modal + transfer-leg-lock decisions this phase reuses
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — requirement wording, prior-phase decision log, memory of `auditlog-decimal-json-gotcha` and `apply-fk-integrityerror-not-422`
- graphify knowledge graph queries (`GET /transactions endpoint filters`, `transfer_pair_id apply_delete_transaction bulk delete audit log`, `portfolio_summary portfolio_events platform detail PnL`, `Nav.tsx cashflow page recent list rendering`) — used to orient before each raw-file read per project mandate

### Secondary (MEDIUM confidence)
- None — no external web sources were needed; this phase is 100% internal composition of existing, already-verified-in-repo code.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all composition of already-installed/verified libraries
- Architecture: HIGH — every pattern cited is a direct read of existing, working code in this repo, not inferred
- Pitfalls: HIGH for Pitfalls 1-2 (verified by reading `writes.py`'s actual guard logic, not assumed from CONTEXT prose) and Pitfall 6 (confirmed via `playwright.config.ts`); MEDIUM for Pitfalls 3-5 (correct per existing patterns but the exact edge-case handling is a planning-time decision, flagged in Assumptions Log)

**Research date:** 2026-08-02
**Valid until:** No hard expiry — this is internal-code research, not third-party API/library research subject to drift. Re-verify only if `backend/writes.py`, `backend/portfolio.py`, or `backend/schemas.py` change materially before planning executes.

## RESEARCH COMPLETE
