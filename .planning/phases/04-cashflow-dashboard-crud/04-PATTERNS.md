# Phase 4: Cashflow Dashboard + CRUD - Pattern Map

**Mapped:** 2026-07-04
**Files analyzed:** 18 (7 backend, 11 frontend)
**Analogs found:** 18 / 18

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/writes.py` (NEW) | service | CRUD | `backend/main.py:_execute_proposal_payload` (L197-360) | exact (extraction source) |
| `backend/main.py` — `GET /cashflow/summary` | controller | request-response (aggregation) | `backend/main.py:read_settings` (L118-121) + `backend/tools.py` composers | role-match |
| `backend/main.py` — `PUT/DELETE /transactions/{id}` | controller | CRUD | `backend/main.py:create_transaction` (L95-115) | exact |
| `backend/main.py` — `POST/PUT/DELETE /accounts` | controller | CRUD | `backend/main.py:create_transaction` (L95-115), `write_settings` (L124-150) | role-match |
| `backend/main.py` — `POST /categories/rename`, `/merge` | controller | CRUD (bulk update) | `backend/main.py:write_settings` (L124-150, partial-update + audit pattern) | role-match |
| `backend/tools.py` — `monthly_trend()` | utility (read aggregation) | CRUD (read) | `backend/tools.py:spending_by_category` (L159-175) | exact |
| `backend/tools.py` — `account_balances()` | utility (read aggregation) | CRUD (read) | `backend/tools.py:spending_total`/`net_total` (L107-156) | exact |
| `backend/schemas.py` — new DTOs (`CashflowSummary`, `TransactionUpdate`, `AccountCreate/Update`, `CategoryRenameRequest`/`MergeRequest`) | model (Pydantic DTO) | transform | `backend/schemas.py:TransactionCreate`/`SettingsUpdate` (L24-33, L122-154) | exact |
| `ui/app/cashflow/page.tsx` (grow) | component (page) | request-response + CRUD | `ui/app/cashflow/page.tsx` itself (existing, 247 lines) + `ui/app/settings/page.tsx` (per-card save pattern) | exact |
| `ui/app/cashflow/TransactionModal.tsx` | component (modal form) | CRUD | `ui/app/cashflow/page.tsx` entry form (L110-202) | role-match |
| `ui/app/cashflow/ConfirmDialog.tsx` | component (modal) | event-driven | none in codebase — first modal component | no analog (see below) |
| `ui/app/cashflow/AccountManager.tsx` | component | CRUD | `ui/app/cashflow/page.tsx` (list + inline row pattern from recent-transactions table, L204-244) | role-match |
| `ui/app/cashflow/CategoryManager.tsx` | component | CRUD (bulk) | `ui/app/settings/page.tsx` (per-section save/state pattern, L38-90) | role-match |
| `ui/app/cashflow/CsvUpload.tsx` | component | file-I/O | `backend/main.py:import_csv` (existing, unchanged) — frontend has no prior file-upload UI, thin new wrapper | partial (backend exact, frontend none) |
| `ui/app/cashflow/charts/CategoryDonut.tsx` | component (chart) | transform | Recharts official docs example (`04-RESEARCH.md`) — no in-repo chart precedent | no analog (first Recharts usage) |
| `ui/app/cashflow/charts/IncomeExpenseBar.tsx` | component (chart) | transform | same as above | no analog |
| `ui/app/cashflow/charts/TrendChart.tsx` | component (chart) | transform | same as above | no analog |
| `ui/app/styles.ts` (add `dangerBtn`, `chartColors`) | config (style constants) | transform | `ui/app/styles.ts` itself (existing `btn`, L34-43) | exact |
| `ui/app/api/[...proxy]/route.ts` | middleware (proxy) | request-response | itself — already handles GET/POST/PUT/PATCH/DELETE generically | exact (no changes needed) |

## Pattern Assignments

### `backend/writes.py` (NEW — service, CRUD)

**Analog:** `backend/main.py:_execute_proposal_payload` (L197-360)

**Extraction pattern — per-operation branch to standalone function.** Preserve exact ordering: flush-before-audit for new rows (needed so `tx.id`/`acc.id`/`h.id` populate before the AuditLog row references them), `Decimal(str(x))` wrapping (never `Decimal(x)` on a float), and the caller-owns-commit contract (no `db.commit()` inside any `apply_*` function).

**Add transaction branch to extract** (L215-234):
```python
if operation == "add_transaction":
    account_name = after.get("account", "Unknown")
    currency = after.get("currency", "IDR")
    acc = _get_or_create_account(db, account_name, currency)
    tx = Transaction(
        date=datetime.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc),
        amount=after["amount"],
        currency=currency,
        category=after.get("category"),
        raw_category=after.get("category"),
        merchant=after.get("merchant"),
        notes=after.get("notes"),
        account_id=acc.id,
        is_transfer=after.get("is_transfer", False),
    )
    db.add(tx)
    db.flush()  # LOAD-BEARING: populates tx.id before the AuditLog row below
    db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                    before=None, after=after))
```

**Edit transaction branch (partial-update pattern to preserve)** (L236-251):
```python
elif operation == "edit_transaction":
    tx_id = row.get("id")
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if after.get("category") is not None:
        tx.category = after["category"]
    if after.get("amount") is not None:
        from decimal import Decimal as _D
        tx.amount = _D(str(after["amount"]))  # LOAD-BEARING: str() before Decimal() avoids float artifacts
    ...
    db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="edit",
                    before=before, after=after))
```

**Category rename/merge branches (bulk UPDATE, parameterized)** (L294-312):
```python
elif operation == "rename_category":
    old_name = row.get("old_name")
    new_name = row.get("new_name")
    db.execute(
        _text("UPDATE transactions SET category = :new WHERE category = :old"),
        {"new": new_name, "old": old_name},
    )
    db.add(AuditLog(entity="category", entity_id=None, operation="rename",
                    before={"category": old_name}, after={"category": new_name}))
```

**Target shape for `backend/writes.py`** (per-operation function signature convention, matching `_get_or_create_account`'s style in `backend/importer.py`):
```python
def apply_add_transaction(db: Session, after: dict) -> Transaction: ...
def apply_edit_transaction(db: Session, tx_id: int, after: dict, before: dict | None) -> Transaction: ...
def apply_delete_transaction(db: Session, tx_id: int, before: dict | None) -> None: ...
def apply_add_account(db: Session, after: dict) -> Account: ...
def apply_edit_account(db: Session, acc_id: int, after: dict, before: dict | None) -> Account: ...
def apply_delete_account(db: Session, acc_id: int, before: dict | None) -> None: ...
def apply_rename_category(db: Session, old_name: str, new_name: str) -> int:  # returns affected count
def apply_merge_category(db: Session, from_name: str, into_name: str) -> int:
```
`_execute_proposal_payload` becomes a thin dispatcher calling these; new direct endpoints call the same functions.

---

### `backend/main.py` — new direct-write endpoints (controller, CRUD)

**Analog:** `backend/main.py:create_transaction` (L95-115) — auth dependency + write + commit + refresh + `reset_engine()` pattern.

**Imports pattern** (L23-56, existing top-of-file — extend, don't duplicate):
```python
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from backend.auth import require_api_key
from backend.db import get_session
from backend.models import Account, AuditLog, Transaction
```

**Auth + write + cache-invalidate pattern** (L95-115):
```python
@app.post("/transactions", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    acc = _get_or_create_account(db, payload.account, payload.currency)
    tx = Transaction(...)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    from backend.query import reset_engine  # lazy import inside handler — established convention
    reset_engine()
    return tx
```
Apply this exact shape to `PUT/DELETE /transactions/{id}`, `POST/PUT/DELETE /accounts`, `POST /categories/rename|merge` — call the `backend/writes.py` `apply_*` helper instead of inlining ORM mutations, then `db.commit()`, then `reset_engine()`.

**Error handling pattern** — `ValueError` from a helper → 422 (established convention seen in `import_csv`, L157-158):
```python
try:
    parsed, inserted, skipped, currency = import_csv_text(db, text_content)
except ValueError as e:
    raise HTTPException(422, str(e))
```

**Reassign-then-delete 422-with-count pattern (D-06)** — no direct in-repo analog (new behavior); closest structural precedent is `propose_delete_account`'s blocking check (`backend/tools.py` L579-618, count query + conditional). Use `RESEARCH.md` Pattern 3's illustrative code (verified against schema — `Transaction.account_id` FK, `Account` model in `backend/models.py` L43-53).

---

### `backend/main.py` — `GET /cashflow/summary` (controller, request-response aggregation)

**Analog:** compose existing `backend/tools.py` functions the same way an agent tool-call would, but return one Pydantic model instead of individual dicts.

**Existing aggregation call shape to reuse** (`backend/tools.py` L107-175):
```python
def spending_total(period="all_time", start_date=None, end_date=None) -> dict:
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sql = ("SELECT COALESCE(SUM(-amount), 0) FROM transactions "
           "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p))
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "spending_total", "total": total, "period": _period_label(period, s, e)}
```
New `monthly_trend()`/`account_balances()` follow this exact shape: `engine.connect()`, parameterized `text()`, `float()` cast at the Python boundary (READ path convention — do not use `Decimal` here per Pitfall 6), return a `{"tool": ..., "rows": [...]}" dict, same file (`backend/tools.py`), same module-level function style, no class wrapper.

**`resolve_period()` reuse** (`backend/tools.py` L40-75) — do not reinvent date-bounds math; `account_balances(period_start, period_end)` takes the already-resolved `(s, e)` tuple from `resolve_period()`, exactly as `spending_total` does internally.

---

### `backend/schemas.py` — new DTOs (model, transform)

**Analog:** `backend/schemas.py:TransactionCreate` (L24-33) for full-create shape; `SettingsUpdate` (L122-154) for partial-update + `field_validator` pattern.

**MoneyDecimal shared type — reuse verbatim, do not redefine** (L18-21):
```python
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
```
Every new write-path schema field for money (`TransactionUpdate.amount`, `AccountCreate`/`Update` if it ever carries a balance) MUST use `MoneyDecimal`, not `float` or bare `Decimal` — import from `backend.schemas`, don't re-declare.

**Partial-update schema pattern (for `TransactionUpdate`)** — mirrors `SettingsUpdate` (L122-135), all fields `Optional`, `None` means "keep existing":
```python
class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    ...
    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, v: str | None) -> str | None:
        if v and v not in _VALID_PROVIDERS:
            raise ValueError(f"Invalid llm_provider={v!r}. Valid: {sorted(_VALID_PROVIDERS)}")
        return v
```
Apply this shape to `TransactionUpdate` (all fields optional except none — matches `_execute_proposal_payload`'s `after.get(...) is not None` semantics per Open Question 1 in RESEARCH.md).

**`from_attributes` read-model pattern** (`AccountOut`, L50-57) — reuse for any new `*Out` response models built from ORM rows:
```python
class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str | None
    currency: str | None
```

---

### `ui/app/cashflow/page.tsx` (grow) (component, request-response + CRUD)

**Analog:** itself (existing 247-line file) for the transaction-form/list scaffolding to extend; `ui/app/settings/page.tsx` for the per-section save-state (`SaveState`) pattern to reuse in `AccountManager`/`CategoryManager`.

**Imports pattern** (L1-5, unchanged convention):
```tsx
"use client";
import { useEffect, useState } from "react";
import { card, input, btn, label } from "../styles";
```

**Refetch-after-write pattern (existing, extend to also refetch summary)** (L51-57, L82-85):
```tsx
async function loadTxs() {
  const r = await fetch("/api/transactions?limit=10");
  if (r.ok) setTxs(await r.json());
}
useEffect(() => { loadTxs(); }, []);
...
if (r.ok) {
  setForm({ ...form, amount: "", category: "", merchant: "", notes: "" });
  loadTxs();  // extend: Promise.all([loadTxs(), loadSummary()])
}
```

**Error-surfacing pattern (existing, WR-05 fix — reuse verbatim for all new CRUD calls)** (L86-95):
```tsx
} else {
  let detail = `HTTP ${r.status}`;
  try {
    const errBody = await r.json();
    detail = errBody?.detail ?? detail;
  } catch {}
  setError(`Couldn't save transaction: ${detail}`);
}
```

**Per-section independent save-state pattern** (`ui/app/settings/page.tsx` L36, L44, L51, L56):
```tsx
type SaveState = { status: "idle" | "saving" | "success" | "error"; message?: string };
const [providerState, setProviderState] = useState<SaveState>({ status: "idle" });
```
Use this `SaveState` shape (copy into a shared location or redeclare per-component) for `AccountManager` and `CategoryManager` sections, since each is an independently-saveable card matching Settings' three-card precedent.

**Amount formatting / color-by-sign (existing, reuse for chart tooltips and account balances)** (L103-104, L229-238):
```tsx
const fmt = (n: number) => new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);
...
style={{ color: t.amount < 0 ? "#f87171" : "#4ade80", fontVariantNumeric: "tabular-nums" }}
```

**Datetime-local helper (existing, reuse verbatim in `TransactionModal`)** (L28-33):
```tsx
function toLocalDatetimeInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
```

---

### `ui/app/cashflow/TransactionModal.tsx` (component, CRUD)

**Analog:** the existing entry-form JSX block in `ui/app/cashflow/page.tsx` (L110-202) — same field set (date, amount, category, merchant, account, notes, is_transfer), same `input`/`label`/`btn` constants, same grid layout convention (`gridTemplateColumns: "1fr 1fr"`, `gap: 10`). Per D-10, this component is instantiated once and reused for both create and edit modes (a `null` vs populated `editingTx` prop switches title/button label — see UI-SPEC "Layout & Component Notes").

---

### `ui/app/cashflow/AccountManager.tsx` / `CategoryManager.tsx` (component, CRUD)

**Analog:** the recent-transactions `<table>` row-rendering pattern (`ui/app/cashflow/page.tsx` L207-243) for list-row structure; `SettingsPage`'s `putSettings` helper (L85-90+) for the save/PUT/state-update flow to adapt for account edit and category rename/merge submissions.

---

### `ui/app/cashflow/CsvUpload.tsx` (component, file-I/O)

**Analog (backend, unchanged):** `backend/main.py:import_csv` (existing) — already returns exactly the `ImportResponse` shape (`parsed`, `inserted`, `skipped`, `currency`) CASH-08 needs; **zero backend changes**. No frontend file-upload precedent exists in the repo — this is genuinely new UI code, built from the `input`/`btn` constants and the existing fetch/error-surfacing pattern above, posting `multipart/form-data` through `ui/app/api/[...proxy]/route.ts` (which forwards any method + body untouched — no proxy changes needed).

---

### `ui/app/cashflow/charts/*.tsx` (component, transform)

**No in-repo analog** — first Recharts usage in the codebase. Use `04-RESEARCH.md`'s verified Code Example (Recharts official docs pattern) as the base, styled with this project's `chartColors` array and `card`/`label` wrapper conventions:
```tsx
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
const COLORS = ["#3b82f6", "#f87171", "#4ade80", "#fbbf24", "#a78bfa", "#22d3ee"]; // chartColors in styles.ts
function CategoryDonut({ data }: { data: { category: string; total: number }[] }) {
  return (
    <div style={{ width: "100%", height: 280 }}>  {/* 04-UI-SPEC.md: 280px explicit height, Pitfall 3 */}
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="total" nameKey="category" innerRadius={60} outerRadius={100} paddingAngle={2}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={(v: number) => v.toLocaleString()} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```
Income/expense bar and trend chart use `#4ade80` (Success/income) and `#f87171` (Destructive/expense) series colors — matching the existing table's amount-color convention, not `chartColors`' generic palette (per `04-UI-SPEC.md` Color section).

---

### `ui/app/cashflow/ConfirmDialog.tsx` (component, event-driven)

**No in-repo analog** — first modal/dialog component in the codebase (Settings and existing Cashflow use inline cards, no overlay pattern exists yet). Build from `card` (overlay panel) + `btn`/new `dangerBtn` (confirm) + plain muted text button (cancel), per `04-UI-SPEC.md`'s Layout & Component Notes: `maxWidth: 360`, `padding: 24`, backdrop `rgba(15,17,21,0.72)`. Shared across delete-transaction, delete-account (both branches), merge-category confirmations.

---

## Shared Patterns

### Auth-protected write endpoint
**Source:** `backend/main.py:create_transaction` (L95), `write_settings` (L124) — `dependencies=[Depends(require_api_key)]`
**Apply to:** every new `POST`/`PUT`/`DELETE` endpoint in this phase (`/transactions/{id}`, `/accounts`, `/categories/rename`, `/categories/merge`)
```python
@app.put("/transactions/{tx_id}", response_model=TransactionOut, dependencies=[Depends(require_api_key)])
def update_transaction(tx_id: int, payload: TransactionUpdate, db: Session = Depends(get_session)):
    ...
```

### Audit log on every write
**Source:** `backend/main.py:_execute_proposal_payload` (every branch ends with `db.add(AuditLog(...))`)
**Apply to:** every `apply_*` helper in `backend/writes.py` — no exceptions; verification step per RESEARCH.md Pitfall 2: grep the diff for `db.add(AuditLog(` count == count of new write endpoints.

### Cache invalidation after any write
**Source:** `backend/main.py:create_transaction` (L112-114), `confirm_proposal` (L411-412), `import_csv` (existing)
```python
from backend.query import reset_engine
reset_engine()
```
**Apply to:** every new direct-write endpoint, after `db.commit()`.

### Parameterized SQL only
**Source:** `backend/tools.py` (all aggregations), `_execute_proposal_payload`'s rename/merge branches (L297-310)
**Apply to:** `monthly_trend()`, `account_balances()`, and both category bulk-UPDATE helpers — always `text()` with bound `:param`, never f-string interpolation of user-supplied names/values (category names ARE user input — SQL injection surface flagged in RESEARCH.md Security Domain).

### Refetch-after-write (no optimistic updates)
**Source:** `ui/app/cashflow/page.tsx:loadTxs()` (L51-57) called after `addTx` succeeds (L84)
**Apply to:** every new CRUD action in `TransactionModal`, `AccountManager`, `CategoryManager` — call the relevant `GET` again (and `GET /cashflow/summary` since totals/balances change too) instead of local state patching.

### Inline style constants only — no CSS framework
**Source:** `ui/app/styles.ts` (`card`, `input`, `btn`, `label`)
**Apply to:** all new components; add exactly two new constants (`dangerBtn`, `chartColors`) to `ui/app/styles.ts`, do not redefine `card`/`input`/`btn`/`label` locally in any new file.
```ts
export const dangerBtn: React.CSSProperties = { ...btn, background: "#f87171" };
export const chartColors = ["#3b82f6", "#f87171", "#4ade80", "#fbbf24", "#a78bfa", "#22d3ee"];
```

### Server-side proxy — no changes needed
**Source:** `ui/app/api/[...proxy]/route.ts` (existing, generic GET/POST/PUT/PATCH/DELETE forwarding with `MONAI_API_KEY` injection)
**Apply to:** all new endpoints ride this unchanged; CSV multipart upload also passes through untouched (body forwarded as raw `ArrayBuffer`, `Content-Type` header preserved via the copied `Headers` object).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `ui/app/cashflow/ConfirmDialog.tsx` | component | event-driven | First modal/overlay component in the codebase — no prior dialog pattern exists; build from `card` + spec in `04-UI-SPEC.md` |
| `ui/app/cashflow/charts/CategoryDonut.tsx`, `IncomeExpenseBar.tsx`, `TrendChart.tsx` | component | transform | First Recharts usage — no charting precedent in-repo; use `04-RESEARCH.md`'s verified official-docs code example as the base pattern |
| `ui/app/cashflow/CsvUpload.tsx` (frontend half only) | component | file-I/O | No prior `<input type="file">` UI in the codebase; backend half (`POST /import`) has a full, unchanged analog |

## Metadata

**Analog search scope:** `backend/main.py`, `backend/tools.py`, `backend/schemas.py`, `backend/models.py`, `backend/importer.py`, `ui/app/cashflow/page.tsx`, `ui/app/settings/page.tsx`, `ui/app/styles.ts`, `ui/app/api/[...proxy]/route.ts`
**Files scanned:** 9 read directly (targeted ranges), plus graphify knowledge-graph queries for orientation (backend write/tools call graph, ui page/styles import graph)
**Pattern extraction date:** 2026-07-04
