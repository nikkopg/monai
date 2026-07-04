# Phase 4: Cashflow Dashboard + CRUD - Research

**Researched:** 2026-07-04
**Domain:** FastAPI REST CRUD endpoints + Recharts dashboard on Next.js App Router
**Confidence:** HIGH

## Summary

Phase 4 is almost entirely a **surfacing exercise**, not new-capability work. The write
logic for every CRUD operation this phase needs (add/edit/delete transaction, add/edit/delete
account, rename/merge category) already exists and is fully tested inside
`backend/main.py:_execute_proposal_payload` (L197-L360) and the `propose_*` tools in
`backend/tools.py`. The only genuinely new backend work is: (1) refactoring that switch
statement into shared helper functions callable from both the existing propose→confirm path
and new direct-write endpoints, (2) two new SQL queries (per-account balance, month-over-month
trend) that don't exist anywhere today, and (3) one aggregate endpoint that composes existing
+ new queries into a single dashboard payload. On the frontend, this is the project's first
non-React/Next dependency (Recharts 3.9.2, verified legitimate — 286 published versions,
official `recharts/recharts` GitHub repo, ~51.5M weekly downloads, React 18/19-peer-compatible)
plus four new UI surfaces (dashboard widgets, transaction modal, account manager, category
manager) that all reuse the existing inline-style constants and the existing `/api/[...proxy]`
server-side key injection.

The highest-risk area is **not** the CRUD wiring — it's getting the shared-helper refactor
(D-02) right without breaking the agent's existing propose→confirm write path (Phase 2,
fully tested, currently green). The refactor must be surgical: extract per-operation logic
into named functions with the exact same before/after/audit-log semantics, then have
`_execute_proposal_payload` call them AND have new direct endpoints call them. A second
real risk is category rename/merge race conditions — since categories are a free-text
column with no unique constraint or entity table, two concurrent renames to the same
target could silently produce duplicate-looking categories; this is accepted as out of
scope per CONTEXT.md (single-user app) but should be a one-line acknowledgment in the plan,
not silently ignored.

**Primary recommendation:** Refactor `_execute_proposal_payload`'s per-operation branches
into standalone functions (e.g. `apply_add_transaction(db, after) -> Transaction`) in a new
`backend/writes.py` module; both the proposal executor and the new direct REST endpoints
call these. Build `GET /cashflow/summary` as one endpoint composing existing `tools.py`
aggregations plus two new raw-SQL queries (trend, per-account balance) that live in
`tools.py` alongside the others. Add Recharts only; no other new frontend dependency.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dashboard aggregation (totals, category breakdown, trend, balances) | API / Backend | Database | All aggregation is SQL-side (existing pattern); backend composes one JSON payload; DB does the summing |
| Chart rendering (donut, bar, line) | Browser / Client | — | Recharts renders client-side from the JSON the API returns; no SSR needed since page is already `"use client"` |
| Transaction/Account CRUD writes | API / Backend | Database | Direct REST endpoints per D-01; shared write helpers do validation + persistence + audit |
| Category rename/merge | API / Backend | Database | Bulk `UPDATE transactions SET category=...`; no separate category entity/tier |
| CSV upload | API / Backend | — | Reuses existing `POST /import`; UI is a thin wrapper posting `multipart/form-data` through the proxy |
| Audit logging | API / Backend | Database | `AuditLog` row per write, inside the same transaction as the write (existing pattern, must be preserved by shared helpers) |
| API-key auth injection | Frontend Server (SSR proxy) | — | `ui/app/api/[...proxy]/route.ts` already injects `MONAI_API_KEY` server-side; all new endpoints ride this same proxy, no new auth code needed in the UI |
| Immediate UI reflection after write | Browser / Client | — | Simple refetch-after-write (call the GET again) is sufficient; no need for optimistic-update complexity in a single-user app |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Recharts | 3.9.2 (verified via `npm view`, published 2026-07-04) | Donut (PieChart), income-vs-expense bar (BarChart), 6-month trend (BarChart or LineChart) | Declarative React components matching the codebase's React-idiomatic style; zero imperative canvas/SVG code to hand-maintain; peer-compatible with React 18.3.1 already in use |

### Supporting
None. This phase adds exactly one new frontend dependency (per D-07/discussion — Recharts
was explicitly chosen over Chart.js and hand-rolled SVG). No new backend dependency — all
CRUD and aggregation work reuses FastAPI, SQLAlchemy, Pydantic v2 already in `requirements.txt`.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Recharts | react-chartjs-2 (Chart.js) | Canvas-based, less idiomatic in a declarative React tree, harder to theme inline; rejected in discussion |
| Recharts | Hand-rolled SVG | Zero deps but meaningfully more code for donut math, tooltips, responsive sizing; rejected in discussion |
| Direct REST endpoints (D-01) | Reuse propose→confirm for UI writes | Adds a 2-step dance + proposal row per UI edit; rejected — the button click is already the confirmation |

**Installation:**
```bash
cd ui && npm install recharts@^3.9.2
```

**Version verification:** `npm view recharts version` → `3.9.2`. 286 versions published since
`0.1.0`; official repo `github.com/recharts/recharts`; ~51.5M weekly downloads (npmjs.org
downloads API, week of 2026-06-26 to 2026-07-02); peerDependencies accept React 18.3.1
(project's pinned version) via `^18.0.0`. No `postinstall` script present (verified —
`npm view recharts scripts.postinstall` returns empty).

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|--------------|---------|-------------|
| recharts | npm | ~10 yrs (v0.1.0 predates 2016; 286 versions total) | ~51.5M/week | github.com/recharts/recharts | OK | Approved |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

Recharts is `[VERIFIED: npm registry]` — confirmed via `npm view` AND sourced from an
authoritative signal (official GitHub org `recharts/recharts`, long version history,
mainstream download volume). This is the standard, uncontested charting library for
declarative React charts and was already the user's locked decision (D-07); this audit
confirms it is not a slopsquat/hallucination risk.

## Architecture Patterns

### System Architecture Diagram

```
Browser (ui/app/cashflow/page.tsx, "use client")
  │
  │  1. GET /api/cashflow/summary?period=this_month  (dashboard load / period change)
  │  2. POST/PUT/DELETE /api/transactions/{id}        (transaction CRUD)
  │  3. POST/PUT/DELETE /api/accounts/{id}            (account CRUD, D-05)
  │  4. POST /api/categories/rename | /merge           (category mgmt, D-09)
  │  5. POST /api/import (multipart)                   (CSV upload, CASH-08)
  ▼
Next.js server proxy  ui/app/api/[...proxy]/route.ts
  │  injects MONAI_API_KEY header, forwards to backend, no logic changes needed
  ▼
FastAPI  backend/main.py
  │
  ├─ GET /cashflow/summary  ─────────────► backend/tools.py aggregations
  │                                         (spending_total, income_total, net_total,
  │                                          spending_by_category — existing)
  │                                        + NEW: monthly_trend(), account_balances()
  │                                          (raw SQL, same file/pattern)
  │
  ├─ POST/PUT/DELETE /transactions/{id} ─► backend/writes.py (NEW — extracted from
  ├─ POST/PUT/DELETE /accounts/{id}     ─►   _execute_proposal_payload) shared helpers:
  ├─ POST /categories/rename            ─►   apply_add_transaction / apply_edit_transaction /
  ├─ POST /categories/merge             ─►   apply_delete_transaction / apply_add_account /
  │                                          apply_edit_account / apply_delete_account /
  │                                          apply_rename_category / apply_merge_category
  │                                        each: validate → write → AuditLog row →
  │                                        (caller commits once)
  │
  └─ POST /import (existing, unchanged) ─► backend/importer.py: parse_csv() + insert_rows()
                                            already returns (parsed, inserted, skipped, currency)
  ▼
PostgreSQL  transactions / accounts / audit_log tables
```

Read path (`GET /cashflow/summary`) and write path (direct REST) are architecturally
separate: reads never touch `backend/writes.py`; writes never touch `backend/tools.py`
read aggregations. The propose→confirm path (Phase 2, unchanged) and the new direct
endpoints both call into `backend/writes.py` — this is the one shared seam (D-02).

### Recommended Project Structure
```
backend/
├── writes.py            # NEW — apply_* shared write helpers (D-02 refactor target)
├── main.py               # add: GET /cashflow/summary, PUT/DELETE /transactions/{id},
│                         #      POST/PUT/DELETE /accounts, POST /categories/rename|merge
│                         # _execute_proposal_payload's branches call backend/writes.py
├── tools.py              # add: monthly_trend(), account_balances() read aggregations
├── schemas.py            # add: CashflowSummary, TransactionUpdate, AccountCreate/Update,
│                         #      CategoryRenameRequest, CategoryMergeRequest, + affected-count
│                         #      response shapes
ui/app/cashflow/
├── page.tsx              # grow into dashboard: charts + widgets + section wiring
├── TransactionModal.tsx  # NEW — shared create/edit modal (D-10)
├── AccountManager.tsx    # NEW — account list + CRUD + reassign-then-delete flow (D-05/D-06)
├── CategoryManager.tsx   # NEW — rename/merge panel with affected-count preview (D-09)
├── CsvUpload.tsx         # NEW — thin wrapper around POST /import (CASH-08)
└── charts/
    ├── CategoryDonut.tsx     # Recharts PieChart
    ├── IncomeExpenseBar.tsx  # Recharts BarChart
    └── TrendChart.tsx        # Recharts BarChart or LineChart, >=6 months
```

### Pattern 1: Shared write helper (D-02)
**What:** Extract each `_execute_proposal_payload` branch into a standalone function that
takes a `Session` and the operation's typed args, performs the mutation + `AuditLog` insert,
and returns the affected row(s). Neither the proposal executor nor the new direct endpoint
calls `db.commit()` inside the helper — the caller owns the transaction boundary (preserves
existing "one commit per confirm" and enables "one commit per direct write" without divergence).

**When to use:** Every one of add/edit/delete transaction, add/edit/delete account, rename/merge
category.

**Example (illustrative — matches existing code shape in `backend/main.py:215-234`):**
```python
# backend/writes.py
def apply_add_transaction(db: Session, after: dict) -> Transaction:
    account_name = after.get("account", "Unknown")
    currency = after.get("currency", "IDR")
    acc = _get_or_create_account(db, account_name, currency)
    tx = Transaction(
        date=datetime.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc),
        amount=Decimal(str(after["amount"])),
        currency=currency,
        category=after.get("category"),
        raw_category=after.get("category"),
        merchant=after.get("merchant"),
        notes=after.get("notes"),
        account_id=acc.id,
        is_transfer=after.get("is_transfer", False),
    )
    db.add(tx)
    db.flush()
    db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add", before=None, after=after))
    return tx

# backend/main.py — proposal executor becomes a thin dispatcher
def _execute_proposal_payload(db: Session, proposal: Proposal) -> None:
    ...
    if operation == "add_transaction":
        apply_add_transaction(db, row["after"])
    elif operation == "edit_transaction":
        apply_edit_transaction(db, row["id"], row["after"], row["before"])
    ...

# backend/main.py — new direct endpoint calls the SAME helper
@app.post("/transactions", ...)  # already exists as create_transaction — can call
                                   # apply_add_transaction directly instead of inlining
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    tx = apply_add_transaction(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(tx)
    reset_engine()
    return tx
```

### Pattern 2: Aggregate dashboard endpoint (D-08)
**What:** One `GET /cashflow/summary?period=...` composing existing `tools.py` functions
plus two new ones. Reuse `resolve_period()` for period math — do not reinvent date bounds.

**Example:**
```python
# backend/tools.py — NEW aggregations, same file/pattern as spending_total etc.

def monthly_trend(months: int = 6) -> dict:
    """Month-over-month income/expense/net for the last N months (CASH-02: months >= 6)."""
    months = max(months, 6)
    sql = """
        SELECT date_trunc('month', date) AS month,
               COALESCE(SUM(amount) FILTER (WHERE amount > 0), 0) AS income,
               COALESCE(SUM(-amount) FILTER (WHERE amount < 0), 0) AS expense
        FROM transactions
        WHERE is_transfer = false
          AND date >= date_trunc('month', CURRENT_DATE) - (:months || ' months')::interval
        GROUP BY 1 ORDER BY 1
    """
    with engine.connect() as c:
        rows = [
            {"month": r[0].date().isoformat()[:7], "income": float(r[1]),
             "expense": float(r[2]), "net": float(r[1]) - float(r[2])}
            for r in c.execute(text(sql), {"months": months}).fetchall()
        ]
    return {"tool": "monthly_trend", "rows": rows}


def account_balances(period_start=None, period_end=None) -> dict:
    """Per-account current_balance (all-time) + period_net (scoped) — D-04."""
    p: dict = {}
    period_clause = _date_clause(period_start, period_end, p)
    sql = f"""
        SELECT a.id, a.name,
               COALESCE(SUM(t.amount), 0) AS current_balance,
               COALESCE(SUM(t.amount) FILTER (WHERE true{period_clause.replace('date', 't.date')}), 0) AS period_net
        FROM accounts a
        LEFT JOIN transactions t ON t.account_id = a.id AND t.is_transfer = false
        GROUP BY a.id, a.name ORDER BY a.name
    """
    with engine.connect() as c:
        rows = [
            {"id": r[0], "name": r[1], "current_balance": float(r[2]), "period_net": float(r[3])}
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "account_balances", "rows": rows}
```

```python
# backend/main.py
@app.get("/cashflow/summary", response_model=CashflowSummary)
def cashflow_summary(period: str = "this_month", start_date: str | None = None,
                      end_date: str | None = None, db: Session = Depends(get_session)):
    s, e = resolve_period(period, start_date, end_date)
    return CashflowSummary(
        totals={"income": income_total(period, start_date, end_date)["total"],
                "expense": spending_total(period, start_date, end_date)["total"],
                "net": net_total(period, start_date, end_date)["net"]},
        by_category=spending_by_category(period, start_date, end_date, limit=10)["rows"],
        accounts=account_balances(s, e)["rows"],
        trend=monthly_trend(6)["rows"],
    )
```

### Pattern 3: Reassign-then-delete for accounts (D-06)
**What:** `DELETE /accounts/{id}?reassign_to={other_id}` — if the account has transactions
and `reassign_to` is absent, return 422 with the count (mirrors the existing
`propose_delete_account` blocking behavior in `tools.py:579-618`, but the direct endpoint
offers reassignment instead of just blocking).

**Example:**
```python
@app.delete("/accounts/{account_id}", dependencies=[Depends(require_api_key)])
def delete_account(account_id: int, reassign_to: int | None = None, db: Session = Depends(get_session)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Account not found")
    tx_count = db.query(Transaction).filter(Transaction.account_id == account_id).count()
    if tx_count > 0:
        if reassign_to is None:
            raise HTTPException(422, detail={
                "message": f"{tx_count} transactions use this account — reassign or delete them first",
                "affected_count": tx_count,
            })
        target = db.get(Account, reassign_to)
        if target is None:
            raise HTTPException(404, "Reassignment target account not found")
        db.query(Transaction).filter(Transaction.account_id == account_id).update(
            {"account_id": reassign_to}
        )
    apply_delete_account(db, account_id)  # shared helper, writes AuditLog
    db.commit()
    reset_engine()
    return {"status": "deleted", "reassigned": tx_count}
```

### Pattern 4: Category rename/merge as bulk UPDATE (D-09)
**What:** No `Category` table — categories are `transactions.category` free text. Rename
and merge are both `UPDATE transactions SET category = :new WHERE category = :old` (already
implemented at `backend/main.py:294-312` inside `_execute_proposal_payload`). Extract to
`apply_rename_category(db, old_name, new_name)` / `apply_merge_category(db, from_name, into_name)`
returning the affected row count, and expose:

```python
@app.get("/categories/{name}/affected-count")  # OR fold into rename/merge response
def category_affected_count(name: str, db: Session = Depends(get_session)):
    count = db.query(Transaction).filter(Transaction.category == name).count()
    return {"category": name, "affected_count": count}

@app.post("/categories/rename", dependencies=[Depends(require_api_key)])
def rename_category(req: CategoryRenameRequest, db: Session = Depends(get_session)):
    count = apply_rename_category(db, req.old_name, req.new_name)
    db.commit()
    reset_engine()
    return {"old_name": req.old_name, "new_name": req.new_name, "affected_count": count}
```
The UI (`CategoryManager.tsx`) calls the affected-count read BEFORE the user confirms
rename/merge, per D-09 ("show affected-transaction count before applying").

### Pattern 5: Immediate reflection after write (no page reload)
**What:** Simple refetch-after-write. After any successful CRUD call, re-`fetch()` the
relevant GET endpoint(s) and update local state — no optimistic-update library needed. This
matches the existing `loadTxs()` pattern already in `ui/app/cashflow/page.tsx:51-57`
(called after `addTx` succeeds).

**Example:**
```typescript
async function saveTransaction(payload: TxPayload, editingId: number | null) {
  const url = editingId ? `/api/transactions/${editingId}` : "/api/transactions";
  const method = editingId ? "PUT" : "POST";
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (r.ok) {
    await Promise.all([loadTransactions(), loadSummary()]); // re-fetch both — dashboard + list
    closeModal();
  } else {
    setError(await extractErrorDetail(r));
  }
}
```

### Anti-Patterns to Avoid
- **Duplicating write logic between the proposal executor and direct endpoints:** the whole
  point of D-02 is one implementation. If a bug fix or `Decimal` handling change is only
  applied on one path, FND-03 (Decimal end-to-end) and CHAT-06 (audit log) silently diverge
  between the chat-confirm path and the UI path.
- **Building a `categories` table for this phase:** explicitly rejected in CONTEXT.md — categories
  stay free-text; rename/merge are bulk UPDATEs. Don't over-engineer.
- **Client-side chart data transforms that duplicate backend aggregation:** compute totals/
  trend/balances in SQL (as `tools.py` already does), send the final shape to the frontend;
  Recharts should receive `{month, income, expense}[]`-shaped arrays directly, not raw
  transaction rows to sum in the browser.
- **Introducing an optimistic-update/state-management library** (e.g. SWR, React Query) for
  "immediate reflection" — unnecessary for a single-user local app; a refetch after a
  successful write is fast enough and matches the existing codebase pattern exactly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Donut/bar/line chart rendering, tooltips, responsive sizing | Custom SVG/canvas chart code | Recharts `PieChart`/`BarChart`/`LineChart` | Locked decision (D-07); hand-rolled SVG donuts require manual arc-path math, hover-tooltip positioning, and resize observers — all solved by Recharts' `ResponsiveContainer` |
| Month-bucket date grouping | Manual JS date-bucketing of raw transaction rows | SQL `date_trunc('month', date)` GROUP BY | Postgres already does this correctly and fast; matches the existing `resolve_period()` philosophy of doing date logic once, correctly, not per-caller |
| Confirm-before-delete UX for destructive actions | Custom modal state machine per delete button | One shared `ConfirmDialog` component (Claude's discretion per D-03) | Reused across transaction delete, account delete, category merge — avoids N slightly-different confirm implementations |
| CSV parsing for the UI upload | A second Wallet CSV parser in the frontend or a new backend parser | Existing `backend/importer.py:parse_csv()` via existing `POST /import` | Already implemented, tested, and returns the exact `(parsed, inserted, skipped, currency)` tuple CASH-08 needs — this endpoint requires zero changes |

**Key insight:** This phase's biggest risk is re-implementing logic that already exists.
Every write operation's core logic (add/edit/delete tx, add/edit/delete account, rename/merge
category) is already written and tested via the agent's propose tools — the plan's job is to
extract and expose it, not reinvent it.

## Runtime State Inventory

Not applicable — this is a greenfield/additive phase (new endpoints, new UI, two new SQL
queries). No rename/refactor/migration of existing identifiers, no data migration. Schema is
unchanged (no new tables or columns needed — D-06 explicitly rejected adding `opening_balance`
this phase; balances are derived from existing `transactions.amount` sums).

## Common Pitfalls

### Pitfall 1: Refactor regresses the confirmed-write path (Phase 2)
**What goes wrong:** Extracting `_execute_proposal_payload`'s branches into `backend/writes.py`
subtly changes behavior — e.g. dropping the `db.flush()` before building the `AuditLog` row
for `add_transaction` (needed so `tx.id` is populated), or changing `Decimal` construction
(`Decimal(str(x))` vs `Decimal(x)`, which behave differently for floats).
**Why it happens:** The existing code has small but load-bearing details (flush-before-audit
for new-row IDs, `str()`-wrapping before `Decimal()` to avoid float-precision artifacts).
**How to avoid:** Extract each branch as a pure copy-paste-then-rename first (no logic changes),
run the full existing Phase 2 test suite (`test_proposals.py`, `test_write_tools.py`) after
each extraction, THEN wire the new direct endpoints to call the extracted functions.
**Warning signs:** `test_proposals.py` or `test_write_tools.py` failures after refactor;
`AuditLog.entity_id` is `None` for adds (missing flush); `Decimal` rounding differs from
before the refactor.

### Pitfall 2: Direct write endpoints skip the audit log
**What goes wrong:** A new direct REST endpoint (e.g. `PUT /transactions/{id}`) is implemented
inline in `main.py` instead of calling the shared helper, and the developer forgets to add
an `AuditLog` row — breaking CHAT-06 ("every applied write is recorded in an audit log") for
the UI path even though the requirement is project-wide, not agent-only.
**Why it happens:** It's easy to write a "simpler" direct endpoint that just does
`tx.category = payload.category; db.commit()` without realizing the audit contract applies here too.
**How to avoid:** Every new write endpoint MUST call a `backend/writes.py` `apply_*` function,
never inline ORM mutations directly in `main.py`. Add a plan verification step: grep the diff
for `db.add(AuditLog(` calls — count should match the number of write endpoints added.
**Warning signs:** `audit_log` table has no new rows after testing a UI transaction edit.

### Pitfall 3: Recharts `ResponsiveContainer` renders blank inside a flex/grid parent with no explicit height
**What goes wrong:** Recharts charts require the parent DOM node to have a resolvable height;
inside a CSS grid or flex container without an explicit `height` (px or %), `ResponsiveContainer`
computes 0 height and the chart silently doesn't render (no error, blank space).
**Why it happens:** Recharts measures the parent via `ResizeObserver`; percentage heights need
an ancestor chain with a concrete height somewhere.
**How to avoid:** Wrap each chart in a `<div style={{ width: "100%", height: 300 }}>` with an
explicit pixel height before the `<ResponsiveContainer>`. Don't rely on flexbox `flex: 1` alone.
**Warning signs:** Chart section renders as an empty box with correct card padding but no SVG.

### Pitfall 4: Trend query hardcodes "this year" instead of a rolling 6+ month window
**What goes wrong:** CASH-02 requires the trend to cover >=6 months of history. A naive
`WHERE date >= date_trunc('year', CURRENT_DATE)` only returns Jan-to-now, which is fewer than
6 months for most of the year (e.g. 3 months in March).
**Why it happens:** Reusing `resolve_period("this_year")` semantics for the trend query instead
of writing a dedicated rolling window.
**How to avoid:** Use `CURRENT_DATE - INTERVAL 'N months'` (rolling window, not calendar-year
bound) as shown in the `monthly_trend()` example above; test with a fixture where "today" is
early in a calendar year to catch this.
**Warning signs:** Trend chart shows fewer than 6 bars/points when run in Jan-May.

### Pitfall 5: Category rename/merge affected-count race (accepted, not blocking)
**What goes wrong:** The UI shows "12 transactions affected" then the user clicks confirm, but
between the count-fetch and the confirm-click, a chat-agent write changes the category
(unlikely in a single-user app but not impossible if chat + UI are used simultaneously). The
count string shown could be stale.
**Why it happens:** No transactional read-then-write guarantee across the two round-trips
(count fetch, then rename POST).
**How to avoid:** Accept this for a single-user local app (matches CONTEXT.md's Out-of-Scope
list — no concurrency hardening requested). Optionally recompute and re-display the count
inside the rename/merge response itself so the user sees the count that was ACTUALLY applied,
not just the pre-check estimate.
**Warning signs:** Not a functional bug for this cycle; flag only if the plan tries to add
locking/transactions for this — that would be scope creep beyond CONTEXT.md's decisions.

### Pitfall 6: `float` vs `Decimal` in new SQL aggregations
**What goes wrong:** `tools.py`'s existing aggregation functions all cast to `float()` at the
Python boundary (e.g. `float(c.execute(...).scalar())`) — this is consistent with how the chat
answers render numbers, but FND-03 requires "money math uses Decimal end-to-end" for NEW write
paths. The `/cashflow/summary` endpoint is a READ path, so following the existing `tools.py`
`float()` convention is correct and consistent — do NOT introduce `Decimal` here and break the
established pattern, but also do not let this precedent leak into any new WRITE code (which
must stay `Decimal`, matching `TransactionCreate`/`MoneyDecimal` schema conventions).
**Why it happens:** Confusing "FND-03 applies everywhere" with "FND-03 applies to write paths and
new Decimal-sensitive transit" — the existing read tools already made the float choice for
display math and Phase 4 should not silently change that convention for the dashboard.
**How to avoid:** New read aggregations (`monthly_trend`, `account_balances`) follow the
existing `tools.py` `float()` convention. New write endpoints use the existing
`MoneyDecimal`/`Decimal` schema pattern from `TransactionCreate`.
**Warning signs:** Mixed `Decimal`/`float` types in the same response causing a Pydantic
serialization error, or (worse) losing precision in a write path because someone "fixed" it
to match the dashboard's float style.

## Code Examples

### Existing per-account query shape to extend (verified against schema)
```python
# Source: backend/models.py L43-53 (Account), L56-77 (Transaction)
# accounts has no balance column — always derive via SUM(transactions.amount)
# WHERE account_id = a.id AND is_transfer = false (existing sign convention:
# income > 0, expense < 0 — see tools.py module docstring L9-12)
```

### Existing CSV import response shape (reuse verbatim for CASH-08)
```python
# Source: backend/schemas.py L68-72
class ImportResponse(BaseModel):
    parsed: int
    inserted: int
    skipped: int
    currency: str
```
The UI's CSV upload component (`CsvUpload.tsx`) needs no new backend schema — `POST /import`
already returns exactly the shape CASH-08 asks for ("parsed / inserted / skipped counts").
Only new frontend code is needed: a `<input type="file">` + `FormData` POST through the
existing proxy.

### Recharts donut example (from official docs pattern)
```tsx
// Source: Recharts official docs (PieChart examples) — https://recharts.org/en-US/api/PieChart
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

const COLORS = ["#3b82f6", "#f87171", "#4ade80", "#fbbf24", "#a78bfa", "#22d3ee"];

function CategoryDonut({ data }: { data: { category: string; total: number }[] }) {
  return (
    <div style={{ width: "100%", height: 300 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="total"
            nameKey="category"
            innerRadius={60}
            outerRadius={100}
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number) => v.toLocaleString()} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Manual entry form + recent list only (Phase 3 interim state) | Full dashboard + CRUD + category manager + CSV upload UI | This phase (Phase 4) | `ui/app/cashflow/page.tsx` grows from 247 lines to a composed page importing several new components |
| Agent-only writes via propose→confirm | Direct REST writes for UI, propose→confirm still used by chat | This phase (D-01/D-02) | Two write entry points sharing one implementation; UI writes no longer require a 15-min-TTL token round trip |
| No account REST endpoints (`GET /accounts` only) | Full account CRUD REST endpoints | This phase (D-05) | Closes a gap noted in STATE.md's Pending Todos ("no read tool exposes account id" for the agent path is a *different*, still-open gap — not fixed by this phase, only the direct-REST gap is closed) |

**Deprecated/outdated:** None — no library or pattern in this phase replaces a previously
deprecated approach; this is additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recharts `BarChart`/`LineChart`/`PieChart` API shapes shown in Code Examples match the exact v3.9.2 API (not verified against live v3 docs in this session, based on stable long-standing Recharts API surface) | Code Examples, Architecture Patterns | Minor — Recharts' core chart API (Pie/Bar/Line + ResponsiveContainer) has been stable across major versions for years; if a prop name changed in v3, the planner/executor will hit a TypeScript error immediately and can consult live docs, low blast radius |
| A2 | `date_trunc('month', ...)` + `INTERVAL` SQL syntax shown for `monthly_trend()` is valid Postgres 16 syntax (not executed against the live DB in this research session) | Code Examples, Pattern 2 | Low — this is standard, widely-used Postgres syntax; if a syntax detail is off, it fails fast at query-execution time during plan execution, not silently |

**A1 and A2 are LOW risk, MEDIUM-confidence assumptions** — both are based on stable,
long-established API/syntax surfaces rather than exotic or recently-changed behavior. No
user confirmation is required before planning; the executor should verify by running the
actual query/component during implementation (standard practice regardless).

## Open Questions

1. **Should the direct-write endpoints require the SAME request/response shape as the
   existing `propose_*` tool payloads, or new dedicated Pydantic schemas?**
   - What we know: `propose_edit_transaction` accepts `category`, `merchant`, `amount`, `notes`
     (all optional) — a PATCH-like partial update. `TransactionCreate` (existing, for POST) is
     a full-required-fields create schema.
   - What's unclear: Whether `PUT /transactions/{id}` should mirror `TransactionCreate`'s shape
     (full replace) or the `propose_edit_transaction` partial-field shape (only provided fields change).
   - Recommendation: Use a partial-update schema (`TransactionUpdate`, all fields `Optional`) to
     match `propose_edit_transaction`'s existing semantics and the shared-helper's `after.get(...)
     is not None` pattern already established in `_execute_proposal_payload` — this is the path
     of least resistance for D-02's shared-helper reuse and matches the modal-form UX (D-10)
     where only touched fields need submitting.

2. **Where does `apply_delete_account`'s reassign-then-delete transaction-reassignment logic
   live — inside `backend/writes.py`'s `apply_delete_account`, or in the `main.py` endpoint
   before calling the (simpler) existing delete helper?**
   - What we know: The existing `propose_delete_account` (tools.py:579-618) BLOCKS delete if the
     account has transactions (no reassignment option) — it's a read-then-error pattern, not a
     mutation. D-06 wants a NEW reassign-then-delete behavior that doesn't exist in either the
     agent path or `_execute_proposal_payload` today.
   - What's unclear: Whether the agent's `propose_delete_account` tool should ALSO gain
     `reassign_to` support (for consistency) or stay block-only, with reassign-then-delete being
     a UI-only capability this phase.
   - Recommendation: Per CONTEXT.md scope ("Write tools / CRUD over MCP... explicitly out of
     scope" refers to MCP, not the agent chat — but D-06's reassign-then-delete is framed as a UI
     behavior in the decision text). Keep `apply_delete_account`'s reassignment logic in the
     `main.py` DELETE endpoint (bulk `UPDATE transactions SET account_id = reassign_to` then call
     the simple delete helper) and leave `propose_delete_account`'s agent-facing block-only
     behavior untouched — this is the minimal-surface-area interpretation consistent with
     "no new agent/chat capabilities" stated in CONTEXT.md's Phase Boundary section.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Frontend dev/build | Yes (assumed from Phase 3 completion) | 20+ (per STACK.md) | — |
| npm | Installing recharts | Yes (assumed from Phase 3 completion) | — | — |
| PostgreSQL | New SQL aggregations, all CRUD | Yes (assumed from Phase 1-3 completion; project has a running `monai_pgdata` volume) | 16-alpine | — |
| recharts (npm registry) | Charting | Yes — verified via `npm view recharts version` = 3.9.2 | 3.9.2 | — |

No missing dependencies — this phase builds entirely on infrastructure already verified
working in Phases 1-3 (Postgres, FastAPI, Next.js dev server, Playwright for e2e per
`ui/e2e/smoke.spec.ts` + `settings.spec.ts` precedent).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest >=8.0.0, existing `backend/tests/` suite (9 files incl. `test_write_tools.py`, `test_proposals.py`, `test_tools.py`) |
| Framework (frontend e2e) | Playwright 1.61.1, `ui/e2e/` (`smoke.spec.ts`, `settings.spec.ts` precedent from Phase 3) |
| Config file | `ui/playwright.config.ts` (existing); no dedicated pytest.ini — uses `backend/tests/conftest.py` |
| Quick run command | `cd backend && python -m pytest tests/test_write_tools.py -x` (per-module) |
| Full suite command | `cd backend && python -m pytest tests/ -x` and `cd ui && npm run e2e` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|--------------------|--------------|
| CASH-01 | `/cashflow/summary` returns totals/category/account data from real rows | unit + integration | `pytest tests/test_cashflow_summary.py -x` | Wave 0 (new) |
| CASH-02 | Trend covers >=6 months, rolling window not calendar-year-bound | unit | `pytest tests/test_cashflow_summary.py::test_trend_covers_six_months -x` | Wave 0 (new) |
| CASH-03 | Per-account `current_balance` (all-time) + `period_net` (scoped) both correct | unit | `pytest tests/test_cashflow_summary.py::test_account_balances -x` | Wave 0 (new) |
| CASH-04 | Transaction create/edit/delete via direct REST, audit row written | unit + integration | `pytest tests/test_transaction_crud.py -x` | Wave 0 (new) |
| CASH-04 | UI reflects change without reload | e2e | `npm run e2e -- cashflow-crud.spec.ts` | Wave 0 (new) |
| CASH-05 | Account create/edit/delete via direct REST; reassign-then-delete (D-06) | unit + integration | `pytest tests/test_account_crud.py -x` | Wave 0 (new) |
| CASH-06 | Rename category remaps all matching transactions | unit | `pytest tests/test_category_management.py::test_rename -x` | Wave 0 (new) |
| CASH-07 | Merge category moves all `from_name` rows to `into_name` | unit | `pytest tests/test_category_management.py::test_merge -x` | Wave 0 (new) |
| CASH-08 | CSV upload from UI shows parsed/inserted/skipped | e2e (backend already covered by existing importer tests) | `npm run e2e -- csv-upload.spec.ts` | Wave 0 (new e2e only — backend logic already tested) |
| (regression) | Existing propose→confirm path still works after D-02 refactor | integration | `pytest tests/test_proposals.py tests/test_write_tools.py -x` | Exists — must stay green |

### Sampling Rate
- **Per task commit:** relevant single test file (e.g. `pytest tests/test_transaction_crud.py -x`)
- **Per wave merge:** `pytest tests/ -x` (full backend suite) + `npm run e2e` (full Playwright suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`, INCLUDING `test_proposals.py` +
  `test_write_tools.py` (regression check on the D-02 refactor)

### Wave 0 Gaps
- [ ] `backend/tests/test_cashflow_summary.py` — covers CASH-01, CASH-02, CASH-03
- [ ] `backend/tests/test_transaction_crud.py` — covers CASH-04 (backend)
- [ ] `backend/tests/test_account_crud.py` — covers CASH-05 (backend, incl. reassign-then-delete)
- [ ] `backend/tests/test_category_management.py` — covers CASH-06, CASH-07 (backend)
- [ ] `ui/e2e/cashflow-crud.spec.ts` — covers CASH-04 UI reflection, CASH-05 UI, CASH-06/07 UI
- [ ] `ui/e2e/csv-upload.spec.ts` — covers CASH-08 UI flow
- [ ] No new fixtures needed beyond the existing `db_available`/`db_session` pattern in
      `test_write_tools.py` — reuse directly

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Single-user local app; `MONAI_API_KEY` (Phase 1) already covers this, unchanged this phase |
| V3 Session Management | No | No session concept in this app |
| V4 Access Control | Yes | Every new write endpoint (`POST/PUT/DELETE /transactions`, `/accounts`, `/categories/*`) MUST carry `dependencies=[Depends(require_api_key)]` — same pattern as existing `POST /transactions`, `POST /import`, `PUT /settings` |
| V5 Input Validation | Yes | Pydantic v2 schemas (`TransactionUpdate`, `AccountCreate`/`Update`, `CategoryRenameRequest`/`MergeRequest`) validate all new endpoint inputs; `field_validator` pattern already established in `schemas.py` (`SettingsUpdate._validate_llm_provider`) for enum-like fields |
| V6 Cryptography | No | No new crypto surface — `hmac.compare_digest` pattern for API key already exists and is unchanged |

### Known Threat Patterns for FastAPI + SQLAlchemy + parameterized SQL

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SQL injection via category rename/merge names | Tampering | Already mitigated — `_execute_proposal_payload`'s existing rename/merge SQL uses `text()` with bound `:new`/`:old` params (main.py:294-312); the extraction into `backend/writes.py` MUST preserve parameterization, never string-format category names into SQL |
| Unauthenticated write via a forgotten `Depends(require_api_key)` | Elevation of Privilege | Every new mutating endpoint declared with the dependency, same as existing write endpoints; add a plan verification step that greps all new `@app.post`/`put`/`delete` route decorators for the dependency |
| Orphaned transactions after account delete (data integrity, not classic STRIDE but a correctness/DoS-adjacent risk) | Tampering / Repudiation | D-06's reassign-then-delete pattern prevents orphaned `account_id` foreign keys; the 422-with-count response prevents silent data loss |
| CSV upload path traversal / arbitrary file read | Information Disclosure | Not a new risk — `POST /import` already reads only the uploaded `UploadFile` bytes via `await file.read()`, never touches the filesystem by path; no change needed |

## Sources

### Primary (HIGH confidence)
- `backend/main.py` (read directly) — existing endpoint list, `_execute_proposal_payload` full implementation, auth dependency pattern
- `backend/tools.py` (read directly) — all `propose_*` write tools, all read aggregation tools, `resolve_period()`
- `backend/models.py` (read directly) — `Account`/`Transaction`/`AuditLog` schema, confirms no `Category` table, no `opening_balance` column
- `backend/schemas.py` (read directly) — `MoneyDecimal` pattern, existing DTO shapes (`ImportResponse`, `TransactionCreate`, `SettingsUpdate` validator pattern)
- `backend/importer.py` (read directly) — confirms `import_csv_text()` returns exactly `(parsed, inserted, skipped, currency)`
- `ui/app/cashflow/page.tsx` (read directly) — existing interim page structure, `loadTxs()` refetch pattern to extend
- `ui/app/styles.ts`, `ui/app/api/[...proxy]/route.ts`, `ui/package.json` (read directly) — inline style constants, proxy auth injection (no changes needed), current dependency set
- `backend/auth.py` (read directly) — `require_api_key` dependency contract
- `backend/tests/test_write_tools.py` (read directly) — existing test fixture pattern (`db_available`, `db_session`) to reuse for new CRUD tests
- npm registry (`npm view recharts version/versions/repository.url/peerDependencies/scripts.postinstall`, executed this session) — Recharts 3.9.2, 286 versions, official repo, React 18/19 peer-compatible, no postinstall script
- npmjs.org downloads API (executed this session) — ~51.5M weekly downloads for recharts

### Secondary (MEDIUM confidence)
- Recharts PieChart/BarChart/LineChart API shape in Code Examples — based on long-stable,
  well-known Recharts component API (not independently re-verified against live v3.9.2 docs
  in this session; flagged as Assumption A1)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Recharts verified via live npm registry query this session; zero
  ambiguity on the choice (already locked in CONTEXT.md D-07)
- Architecture: HIGH — every pattern (shared write helper, aggregate endpoint, reassign-delete,
  category bulk-update, refetch-after-write) is either already implemented in the codebase
  (read directly) or a direct, low-risk extension of an existing pattern
- Pitfalls: HIGH — pitfalls 1, 2, 4, 6 are grounded in specific lines of existing code read
  this session; pitfall 3 (Recharts container height) is a well-known, widely-documented
  Recharts gotcha; pitfall 5 is explicitly scoped as accepted-risk per CONTEXT.md

**Research date:** 2026-07-04
**Valid until:** 2026-08-03 (30 days — stable stack, no fast-moving dependencies; Recharts
major-version cadence is slow and this phase pins `^3.9.2`)
