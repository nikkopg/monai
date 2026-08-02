# Phase 17: UI New Surfaces (Records Tab, Platform Detail) - Pattern Map

**Mapped:** 2026-08-02
**Files analyzed:** 10 (5 backend, 5 frontend/e2e)
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/main.py::list_transactions` (extend) | route | CRUD (filtered read) | `backend/tools.py::spending_in_category` + `backend/main.py::cashflow_summary` (param handling) | role-match |
| `backend/main.py::POST /transactions/bulk-delete` (new) | route | CRUD (batch write) | `backend/main.py::delete_transaction` (L802-823) | exact (scaled to batch) |
| `backend/main.py::POST /transactions/bulk-recategorize` (new) | route | CRUD (batch write) | `backend/main.py::update_transaction` (L773-799) | exact (scaled to batch) |
| `backend/main.py::GET /platforms/{id}/detail` (new) | route | CRUD (scoped read) | `backend/main.py::investments_summary` (L575, uses `portfolio_summary`) | role-match |
| `backend/main.py::GET /portfolio-events?platform_id=` (new) | route | CRUD (read) | `backend/main.py::list_transactions` (simple filtered list) | role-match |
| `backend/schemas.py` (TransactionOut + bulk DTOs) | model (DTO) | transform | `backend/schemas.py::TransactionOut`/`TransactionUpdate` (existing) | exact |
| `backend/writes.py` (no new function; reuse) | service | CRUD | `apply_delete_transaction`/`apply_edit_transaction` (L110-148) | exact — do not modify, compose at endpoint layer |
| `ui/app/records/page.tsx` (NEW) | component (page) | request-response + client transform | `ui/app/cashflow/page.tsx` (recent-list, stat cards, modal wiring) | role-match |
| `ui/app/investments/[platformId]/page.tsx` (NEW) | component (page) | request-response | `ui/app/investments/page.tsx` (group rendering) + `TransactionModal.tsx` segmented control | role-match |
| `ui/app/components/Nav.tsx` (modify) | component | config | itself, `NAV_LINKS` array + `Icon()` switch (L17-67) | exact |
| `ui/e2e/records.spec.ts`, `ui/e2e/platform-detail.spec.ts` (NEW) | test | request-response (route-mocked) | `ui/e2e/cashflow-crud.spec.ts`, `ui/e2e/platform-crud.spec.ts` | exact |

## Pattern Assignments

### `backend/main.py` — extend `GET /transactions` (D-01/REC-02)

**Analog:** current `list_transactions` itself (`backend/main.py:641-648`), extended per RESEARCH Pattern 1; hierarchy filter copies `backend/tools.py`'s `_find_category_node`/`_descendant_ids` (used by `spending_in_category`).

**Current code to extend:**
```python
@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(limit: int = 50, db: Session = Depends(get_session)):
    return (
        db.query(Transaction)
        .order_by(desc(Transaction.date))
        .limit(min(limit, 500))
        .all()
    )
```

**Target shape** (add params, one parameterized `.filter()` per param, `offset` before `limit`):
```python
def list_transactions(
    q: str | None = None,
    account_id: int | None = None,
    category: str | None = None,
    type: str | None = None,           # "expense"|"income"|"transfer"
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
        query = query.filter(or_(Transaction.merchant.ilike(f"%{q}%"), Transaction.notes.ilike(f"%{q}%")))
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    if category is not None:
        node = _find_category_node(category)
        query = query.filter(Transaction.category_id.in_(_descendant_ids(node))) if node else query.filter(Transaction.category == category)
    if type == "expense":
        query = query.filter(Transaction.amount < 0, Transaction.transfer_pair_id.is_(None))
    elif type == "income":
        query = query.filter(Transaction.amount > 0, Transaction.transfer_pair_id.is_(None))
    elif type == "transfer":
        query = query.filter(Transaction.transfer_pair_id.isnot(None))  # UI-SPEC locked: pair-id, not is_transfer (Pitfall 5)
    elif not include_transfers:
        query = query.filter(Transaction.is_transfer == False)
    if amount_min is not None:
        query = query.filter(func.abs(Transaction.amount) >= amount_min)
    if amount_max is not None:
        query = query.filter(func.abs(Transaction.amount) <= amount_max)
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date < date_to)
    return query.order_by(desc(Transaction.date)).offset(offset).limit(min(limit, 500)).all()
```
**IMPORTANT — locked interpretation (17-UI-SPEC.md Component 2):** `type=transfer` maps to `transfer_pair_id IS NOT NULL`, NOT `is_transfer=true`. Adjustment/Investment-funding rows (`is_transfer=true`, `transfer_pair_id=null`) fall under expense/income by sign — do not special-case them.

**No `require_api_key`** — this is an open GET, matching current `list_transactions` and `investments_summary`/`net_worth` conventions (`backend/main.py:733`, `cashflow_summary` docstring at L712).

---

### `backend/main.py` — NEW `POST /transactions/bulk-delete` (D-03/D-04)

**Analog:** `delete_transaction` (`backend/main.py:802-823`) — copy the `before` dict construction VERBATIM (Decimal-JSON gotcha, Pattern 3 in RESEARCH):
```python
@app.delete("/transactions/{tx_id}", dependencies=[Depends(require_api_key)])
def delete_transaction(tx_id: int, db: Session = Depends(get_session)):
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    before = {
        "id": tx.id, "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),  # LOAD-BEARING str() — never pass raw Decimal
        "currency": tx.currency, "category": tx.category, "merchant": tx.merchant,
        "notes": tx.notes, "account_id": tx.account_id, "is_transfer": tx.is_transfer,
    }
    apply_delete_transaction(db, tx_id, before)   # <-- currently NO allow_paired: 422s on any transfer leg today (Pitfall 2)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
```

**Critical correction (RESEARCH Pitfall 1/2):** `apply_delete_transaction(..., allow_paired=True)` only suppresses the pair guard — it does NOT delete the sibling leg. Both this existing single-delete endpoint AND the new bulk-delete endpoint must explicitly look up `Transaction.transfer_pair_id` and delete the sibling too, in the same DB transaction, before the single `db.commit()`. See RESEARCH.md Pattern 2 for the full bulk-delete loop with pair-lookup — copy it verbatim; also retrofit `delete_transaction` (L802-823) with the same pair-lookup-and-delete-both logic (D-04 touches the existing endpoint, not just new ones).

`writes.apply_delete_transaction` (`backend/writes.py:136-148`) is the primitive — do NOT modify it (anti-pattern per RESEARCH: cascading belongs at the endpoint/composition layer, matching how `apply_add_transfer` composes two `apply_add_transaction` calls, `writes.py:150-167`).

Response shape: `{"deleted": [...ids], "skipped": [{"id":.., "reason":..}]}` (Pydantic `BulkActionResponse`) — mirrors the `PATTERNS.md`/RESEARCH Pattern 2 exactly.

---

### `backend/main.py` — NEW `POST /transactions/bulk-recategorize` (D-03)

**Analog:** `update_transaction` (`backend/main.py:773-799`):
```python
@app.put("/transactions/{tx_id}", response_model=TransactionOut, dependencies=[Depends(require_api_key)])
def update_transaction(tx_id: int, payload: TransactionUpdate, db: Session = Depends(get_session)):
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    before = {...same shape as delete_transaction...}
    after = payload.model_dump(mode="json", exclude_none=True)
    try:
        apply_edit_transaction(db, tx_id, after, before)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(tx)
    from backend.query import reset_engine
    reset_engine()
    return tx
```
Bulk version loops `ids`, calls `apply_edit_transaction(db, tx_id, {"category": payload.category}, before, allow_paired=False)` per non-transfer row, but **skips (does not error on)** rows where `tx.is_transfer` — add `{"id": tx_id, "reason": "transfer leg — system-categorized"}` to `skipped` instead of raising. One `db.commit()` for the whole batch. `require_api_key`-gated (write route).

---

### `backend/main.py` — NEW `GET /platforms/{id}/detail` (D-05)

**Analog:** `investments_summary` (`backend/main.py:575`, uses `portfolio.portfolio_summary(db)`).
```python
@app.get("/platforms/{platform_id}/detail")
def platform_detail(platform_id: int, db: Session = Depends(get_session)):
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    from backend.prices import refresh_all_prices
    refresh_all_prices(db, force=False)   # same lazy-refresh idiom as investments_summary
    db.commit()
    summary = portfolio_summary(db)
    group = next((g for g in summary["groups"] if g["platform_id"] == platform_id), None)
    return group or {"platform_id": platform_id, "platform_name": platform.name, "kind": platform.kind, "subtotal": 0, "holdings": []}
```
No `require_api_key` (open read, matches `investments_summary`/`net_worth`). Return the raw dict — no new Pydantic response_model needed (reuses `PortfolioSummary.groups[i]`'s existing Decimal-passthrough convention, `schemas.py`).

---

### `backend/main.py` — NEW `GET /portfolio-events?platform_id=` (D-05)

**Analog:** `list_transactions`'s simple filtered-list shape; existing `POST /portfolio-events` (`backend/main.py:427`) for the model/schema import.
```python
@app.get("/portfolio-events", response_model=list[PortfolioEventOut])
def list_portfolio_events(platform_id: int, db: Session = Depends(get_session)):
    return (
        db.query(PortfolioEvent)
        .filter(PortfolioEvent.platform_id == platform_id)
        .order_by(desc(PortfolioEvent.date))
        .all()
    )
```
Reuses `PortfolioEventOut` (`schemas.py`) directly — no new DTO.

---

### `backend/schemas.py` — add `transfer_pair_id` (D-02) + bulk DTOs

**Analog:** existing `TransactionOut`/`TransactionUpdate` field style (Pydantic v2 `BaseModel`, `*Out`/`*Create` naming per CLAUDE.md conventions). Add `transfer_pair_id: int | None = None` to `TransactionOut`. New:
```python
class BulkDeleteRequest(BaseModel):
    ids: list[int]

class BulkRecategorizeRequest(BaseModel):
    ids: list[int]
    category: str

class BulkActionResponse(BaseModel):
    deleted: list[int] = []          # or "recategorized" for the recategorize variant — reuse one shape, rename key per endpoint OR keep generic "affected"
    skipped: list[dict] = []         # [{id, reason}]
```

---

### `ui/app/components/Nav.tsx` — add "Records" entry (D-06)

**Current file (full pattern, L17-67):**
```typescript
const NAV_LINKS = [
  { href: "/cashflow", label: "Cashflow", icon: "cashflow" },
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/investments", label: "Investments", icon: "investments" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

type IconName = (typeof NAV_LINKS)[number]["icon"];

function Icon({ name }: { name: IconName }) {
  const common = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "cashflow": return (<svg {...common}><path d="M3 3v18h18" /><path d="M7 14l3-3 3 3 5-6" /></svg>);
    // ...other cases
  }
}
```
**Change:** insert `{ href: "/records", label: "Records", icon: "records" }` directly after the `/cashflow` entry (before `/chat`) — `IconName` auto-widens. Add a `"records"` case to `Icon()`'s switch with a ledger glyph: `<path d="M4 6h16M4 12h10M4 18h13"/>` using the same `common` props object.

---

### `ui/app/records/page.tsx` (NEW) — Records ledger

**Analog:** `ui/app/cashflow/page.tsx` (recent-transactions row markup L742-828, stat-card grid L444-490, `TransactionModal`/`ConfirmDialog` wiring).

**Row markup to copy verbatim, adding a 28px leading checkbox gutter** (L742-828):
```tsx
{txs.map((t) => {
  const isIncome = t.amount >= 0 && !t.is_transfer;
  const tint = t.is_transfer ? tokens.color.tintNeutral : isIncome ? tokens.color.tintGreen : tokens.color.tintWarm;
  return (
    <div key={t.id} style={{ display:"flex", alignItems:"center", gap:14, padding:"12px 0", borderTop:`1px solid ${tokens.color.borderInner}` }}>
      <span style={{ width:38, height:38, borderRadius:11, background:tint, display:"inline-flex",
                      alignItems:"center", justifyContent:"center", fontSize:13, fontWeight:600,
                      color: tokens.color.muted3, flexShrink:0 }}>
        {(t.category || t.merchant || "?").slice(0,1).toUpperCase()}
      </span>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontSize:14, fontWeight:500, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>
          {t.merchant || t.category || "Transaction"}
        </div>
        <div style={{ fontSize:12, color: tokens.color.muted2 }}>
          {(t.category || "Uncategorized") + (t.is_transfer ? " · transfer" : "")} · {t.date.slice(0,10)}
        </div>
      </div>
      <div style={{ fontSize:14, fontWeight:600, fontVariantNumeric:"tabular-nums",
                     color: t.amount < 0 ? tokens.color.terracotta : tokens.color.green, whiteSpace:"nowrap" }}>
        {signed(t.amount)}
      </div>
      <div style={{ display:"flex", gap:12, flexShrink:0 }}>
        <span role="button" onClick={() => { setEditingTx(t); setModalOpen(true); }}
              style={{ color: tokens.color.muted2, cursor:"pointer", fontSize:12 }}>Edit</span>
        <span role="button" onClick={() => setDeletingTx(t)}
              style={{ color: tokens.color.terracotta, cursor:"pointer", fontSize:12 }}>Delete</span>
      </div>
    </div>
  );
})}
```
For Records: prepend a 28px checkbox column; for transfer-pair collapse and day-grouping wrap this same shell per 17-UI-SPEC.md Components 3-6 (client-side `collapseTransferPairs()` — copy the function verbatim from RESEARCH.md's "Code Examples" section, degrade gracefully when `sibling` is undefined per filtered-view edge case).

**Stat/eyebrow header pattern** — copy `cashflow/page.tsx`'s page header (`eyebrow` + `<h1>` layout, `justifyContent:"space-between"`) and its `statLabel`/`statValue` style objects (L876-885) for any stat cards.

**Reuse verbatim (no changes needed):** `TransactionModal` (row edit + transfer-leg-locked mode already built), `ConfirmDialog` (bulk-delete / pair-delete confirm), `CategoryManager.tsx`'s `flattenCategories()` helper (bulk-recategorize picker, filter-bar category select).

---

### `ui/app/investments/[platformId]/page.tsx` (NEW) — Platform detail

**Analog for dynamic route:** Next.js App Router convention — folder name `[platformId]` binds `params.platformId`; `"use client"` component pattern matches every other page in `ui/app/`.

**Analog for segmented control:** `ui/app/cashflow/TransactionModal.tsx` (L75-79, 356-397) — Expense/Income/Transfer segmented control:
```tsx
// Source: ui/app/cashflow/TransactionModal.tsx:75-79, 356-397
type Segment = "expense" | "income" | "transfer";
const SEGMENTS: readonly Segment[] = ["expense", "income", "transfer"];
// ...
<div style={{ background: tokens.color.sidebar, border: `1px solid ${tokens.color.border2}`,
               borderRadius: 12, padding: 4, marginBottom: 18, display:"flex" }}>
  {SEGMENTS.map((s) => (
    <button key={s}
      onClick={locked ? undefined : () => setSegment(s)}
      style={s === segment
        ? { flex:1, background:"#fff", boxShadow:"...", fontWeight:600, fontSize:14, borderRadius:8 }
        : { flex:1, background:"transparent", color: tokens.color.muted, fontWeight:500, fontSize:14 }}
    >{s}</button>
  ))}
</div>
```
For platform detail: 2 options `["pnl","buysell"]`, labels "PnL"/"Buy & Sell", default active "pnl" — same container/segment styling, no `locked` prop needed.

**Analog for group/PnL table rendering:** `ui/app/investments/page.tsx`'s per-holding table (column header row style: `fontSize:12, color: tokens.color.muted2, borderBottom`; row uses `badgeColor()`/`fmtQty()`/`pnlColor()` helpers) — reuse these helpers directly, filtered to the one platform's `group.holdings`.

**Investments page link-out (D-08 Component 15):** the existing group-header name span in `investments/page.tsx` becomes `<Link href={`/investments/${g.platform_id}`}>` when `g.platform_id !== null` (Unassigned stays plain text, never a link).

**Reuse verbatim:** `HoldingModal`, `styles.ts` tokens.

---

### `ui/e2e/records.spec.ts`, `ui/e2e/platform-detail.spec.ts` (NEW)

**Analog:** `ui/e2e/cashflow-crud.spec.ts` (route-mock pattern) — `page.route("**/api/...", async (route) => { await route.fulfill({...}) })`, per-test scoped mocks, `test("description", async ({ page }) => {...})`. Also `ui/e2e/platform-crud.spec.ts` for platform-page-specific mocking conventions.
```typescript
// Source: ui/e2e/cashflow-crud.spec.ts:52-95 pattern
await page.route("**/api/transactions?limit=10", async (route) => {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([...]) });
});
test("Add transaction opens the modal and posts to /api/transactions", async ({ page }) => {
  await page.route("**/api/transactions", async (route) => {
    if (route.request().method() === "POST") { await route.fulfill({ status: 201, body: "{...}" }); }
  });
  // ...
});
```
Run with `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test` (Pitfall 6 — bundled Chromium absent in this env).

## Shared Patterns

### API-key write gating
**Source:** `backend/main.py` — every mutating route has `dependencies=[Depends(require_api_key)]`; every GET read (list_transactions, investments_summary, net_worth) has none.
**Apply to:** `POST /transactions/bulk-delete`, `POST /transactions/bulk-recategorize` (gated); `GET /platforms/{id}/detail`, `GET /portfolio-events` (open, matching `investments_summary`/`net_worth` precedent).

### AuditLog Decimal-JSON gotcha
**Source:** `backend/writes.py:100-107` comment + `backend/main.py:782/811` (`"amount": str(tx.amount)`).
**Apply to:** every `before`/`after` dict built inline in the new bulk endpoints — never pass a raw `Decimal` (`tx.amount`) into an AuditLog dict; always `str()` first.

### Pair-lookup-and-delete-both belongs at the endpoint layer, not the primitive
**Source:** `backend/writes.py:136-148` (`apply_delete_transaction`, `allow_paired` only suppresses a guard) + `backend/writes.py:150-167` (`apply_add_transfer` composes two `apply_add_transaction` calls at the composition layer).
**Apply to:** `DELETE /transactions/{tx_id}` (existing, needs retrofit per Pitfall 2) and the new bulk-delete endpoint — both look up `Transaction.transfer_pair_id`, find the sibling (`transfer_pair_id == X AND id != tx_id`), delete both inside one `db.commit()`.

### `styles.ts` tokens + inline `React.CSSProperties`
**Source:** `ui/app/styles.ts` (`tokens.color.*`, `tokens.space.*`, `card`/`input`/`btn`/`label` exports).
**Apply to:** all new frontend files — no Tailwind, no CSS modules, hand-rolled inline styles only (project-wide convention, reaffirmed in 17-UI-SPEC.md).

### `onChanged`/`onSaved` refetch after mutation
**Source:** `ui/app/cashflow/page.tsx` (`TransactionModal onSaved={load}` pattern).
**Apply to:** Records bulk actions and single-row edit/delete — refetch the current filtered page after any mutation succeeds.

## No Analog Found

None — every file in scope has a strong (exact or role-match) analog already in this repo. This phase is composition-only per RESEARCH.md's summary.

## Metadata

**Analog search scope:** `backend/main.py`, `backend/writes.py`, `backend/schemas.py`, `backend/portfolio.py`, `backend/tools.py`, `ui/app/cashflow/*`, `ui/app/investments/*`, `ui/app/components/Nav.tsx`, `ui/e2e/*`
**Files scanned:** ~12 (direct reads) + graphify traversal (94 nodes) for line-number confirmation
**Pattern extraction date:** 2026-08-02
