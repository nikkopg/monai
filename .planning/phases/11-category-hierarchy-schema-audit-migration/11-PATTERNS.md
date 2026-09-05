# Phase 11: Category Hierarchy — Schema, Audit, Migration - Pattern Map

**Mapped:** 2026-07-18
**Files analyzed:** 10
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `alembic/versions/009_category_hierarchy.py` | migration | batch (nullable→backfill→NOT NULL + data migration) | `alembic/versions/006_multi_platform_holdings.py` | exact |
| `backend/models.py` (+ `Category` model) | model | CRUD (self-referential) | `backend/models.py` (`Account`, `Platform` classes) | exact |
| `backend/writes.py` (+ `apply_add_category`/`apply_edit_category`/`apply_delete_category`, rework `apply_rename_category`/`apply_merge_category`) | service (audited write layer) | CRUD | `backend/writes.py` `apply_add_account`/`apply_edit_account`/`apply_delete_account` (lines 77-134) | exact |
| `backend/main.py` (+ `POST/PUT/DELETE /categories`) | controller/route | request-response (CRUD) | `backend/main.py` `/accounts` endpoints (lines 202-274) | exact |
| `backend/tools.py` (rewrite `spending_by_category`, `spending_in_category`, `list_categories`; rework `propose_rename_category`/`propose_merge_category`) | service (read/write tool registry) | request-response / CRUD | `backend/tools.py` lines 169-208 (existing category tools) + `TOOLS` registry (lines 493-517) | exact |
| `backend/query.py` (update `FunctionTool` list for rewritten tools) | config/registration | event-driven (tool dispatch) | `backend/query.py` `FunctionTool.from_defaults()` list | exact |
| `data/category_mapping.csv` (or `alembic/data/`) | config (checked-in data) | file-I/O (migration input) | none (net-new artifact type) | no analog |
| `ui/app/settings/CategoryManager.tsx` (moved + extended from `ui/app/cashflow/CategoryManager.tsx`) | component | CRUD (form + delete-guard flow) | `ui/app/cashflow/AccountManager.tsx` (full file, esp. lines 80-140 delete/reassign flow) | exact |
| `ui/app/cashflow/charts/CategoryDonut.tsx` (rewire for rollup + drill-down) | component | transform (aggregation → chart) | `ui/app/cashflow/charts/CategoryDonut.tsx` (self — existing file being modified) | exact (self) |
| `backend/tests/test_category_hierarchy.py` (new) | test | CRUD / batch | `backend/tests/test_category_management.py` (existing) | role-match |

## Pattern Assignments

### `alembic/versions/009_category_hierarchy.py` (migration, batch)

**Analog:** `alembic/versions/006_multi_platform_holdings.py` (read in full, 109 lines)

**Header/docstring pattern** (lines 1-29): every migration opens with a triple-quoted docstring stating what moves, in what strict order, and why (loud failure conditions called out explicitly). Follow this convention exactly for revision 009 — document the 74-string mapping order (create table → seed → add nullable FK → backfill per mapping row → assert parity → NOT NULL → FK + index).

**Nullable → backfill → NOT NULL idiom** (lines 42-83):
```python
def upgrade() -> None:
    op.add_column("portfolio_events", sa.Column("platform_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE portfolio_events e SET platform_id = h.platform_id "
        "FROM holdings h WHERE h.ticker = e.ticker"
    )
    op.alter_column("portfolio_events", "platform_id", nullable=False)
    op.create_foreign_key(
        "fk_portfolio_events_platform", "portfolio_events", "platforms",
        ["platform_id"], ["id"],
    )
    op.create_index("ix_portfolio_events_platform_id", "portfolio_events", ["platform_id"])
```
For 009: replace the single `op.execute(UPDATE...)` with a Python loop over the 74 CSV mapping rows, one bound-parameter `op.execute(text("UPDATE transactions SET category_id = :cid WHERE category = :raw"), {...})` per row (NOT a single opaque UPDATE — see RESEARCH.md Anti-Patterns), so the parity assertion can run per-category and name exactly which string failed. Match exact raw string, no `TRIM()`/`ILIKE` (RESEARCH.md Pitfall 1: whitespace-variant duplicate).

**Downgrade reversal pattern** (lines 86-108): reverse steps in strict opposite order of upgrade — drop index → drop FK → nullable=True → drop column → drop constraints → restore prior state. Mirror this ordering discipline for 009's downgrade.

**Revision header boilerplate** (lines 30-39):
```python
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "<new-uuid>"
down_revision: Union[str, None] = "<008's revision id>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

---

### `backend/models.py` (+ `Category` model) (model, CRUD)

**Analog:** `backend/models.py` — `Account` (lines 44-54) and `Transaction` (lines 74-94)

**Imports pattern** (lines 21-37): SQLAlchemy 2.0 `Mapped`/`mapped_column` style, `DeclarativeBase`, explicit column type imports (`Boolean`, `String`, `ForeignKey`, `UniqueConstraint`, etc.) — no new imports needed beyond what's already imported except possibly nothing (all needed types are already imported).

**Self-referential model pattern** (mirrors `Account` shape at lines 44-54):
```python
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
```
`Category` follows this exact shape plus a self-referential `parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)` and a `UniqueConstraint("name", "parent_id", ...)` (per RESEARCH.md Pattern 1). `Transaction.category`/`raw_category` (lines 83-84) stay as-is (`raw_category` untouched per D-08); add `category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False, index=True)` alongside them, matching `account_id`'s FK shape (line 87-89).

**Docstring convention:** every table has a short doc comment above it (e.g. `Platform` at lines 58-63, `AuditLog` at line 98) explaining what it stores and any load-bearing decisions — add same for `Category` (self-referential, depth cap enforced in app code not DDL, `is_system` for Transfer/Uncategorized).

---

### `backend/writes.py` (+ `apply_add_category`/`apply_edit_category`/`apply_delete_category`; rework rename/merge) (service, CRUD)

**Analog:** `backend/writes.py` — `apply_add_account` (77-88), `apply_edit_account` (91-104), `apply_delete_account` (107-134)

**Module contract** (lines 1-14, docstring): every `apply_*` function performs exactly one entity mutation, writes exactly one `AuditLog` row, and never commits — caller owns the transaction boundary. Follow this contract exactly for the new category write helpers.

**Add pattern** (lines 77-88):
```python
def apply_add_account(db: Session, after: dict) -> Account:
    """Insert a new account."""
    acc = Account(name=after["name"], type=after.get("type"), currency=after.get("currency"))
    db.add(acc)
    db.flush()  # LOAD-BEARING: populates acc.id before the AuditLog row below
    db.add(AuditLog(entity="account", entity_id=acc.id, operation="add", before=None, after=after))
    return acc
```
`apply_add_category` mirrors this, plus a depth-cap guard (walk `parent_id` chain, raise `ValueError` if depth would exceed 3 — RESEARCH.md Pattern 1/Anti-Patterns: no CHECK constraint, enforce here).

**Edit pattern** (lines 91-104): partial-update, only non-None fields in `after` change; single `AuditLog` row with `before`/`after`.

**Delete-with-reassign pattern** (lines 107-134) — the exact shape for `apply_delete_category`, extended per RESEARCH.md Pitfall 3 (categories have child categories, accounts don't — guard must check both direct transaction count AND child-category count):
```python
def apply_delete_account(db: Session, acc_id: int, before: dict | None, reassign_to: int | None = None) -> int:
    reassigned_count = 0
    audit_after: dict | None = None
    if reassign_to is not None:
        result = db.execute(
            text("UPDATE transactions SET account_id = :reassign_to WHERE account_id = :acc_id"),
            {"reassign_to": reassign_to, "acc_id": acc_id},
        )
        reassigned_count = result.rowcount
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}
    acc = db.get(Account, acc_id)
    if acc is not None:
        db.delete(acc)
    db.add(AuditLog(entity="account", entity_id=acc_id, operation="delete", before=before, after=audit_after))
    return reassigned_count
```

**Rename/merge rework (D-11):** replace `apply_rename_category`'s current `UPDATE transactions SET category = :new WHERE category = :old` bulk pattern (RESEARCH.md Anti-Patterns) with a single-row `UPDATE categories SET name = :new WHERE id = :id` — records follow via FK, zero transaction rows touched.

---

### `backend/main.py` (+ `/categories` CRUD) (controller, request-response)

**Analog:** `backend/main.py` — `create_account` (207-215), `update_account` (218-233), `delete_account` (236-274)

**Create pattern** (207-215):
```python
@app.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_account(payload: AccountCreate, db: Session = Depends(get_session)):
    acc = apply_add_account(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc
```
`require_api_key` dependency + `reset_engine()` call after commit is MANDATORY on every new mutating category endpoint (RESEARCH.md Pitfall 5 — LLM query engine caches a module-level singleton).

**Update pattern** (218-233): fetch-or-404, build `before` dict, call `apply_edit_*`, catch `ValueError` → 422, commit, refresh, reset_engine.

**Delete-with-reassign 3-way branch** (236-274):
```python
@app.delete("/accounts/{account_id}", dependencies=[Depends(require_api_key)])
def delete_account(account_id: int, reassign_to: int | None = None, db: Session = Depends(get_session)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    before = {"id": acc.id, "name": acc.name, "type": acc.type, "currency": acc.currency}
    tx_count = int(db.execute(
        text("SELECT COUNT(*) FROM transactions WHERE account_id = :aid"), {"aid": account_id}
    ).scalar() or 0)
    if tx_count > 0:
        if reassign_to is None:
            raise HTTPException(status_code=422, detail={
                "message": f"{tx_count} transactions use this account — reassign or delete them first",
                "affected_count": tx_count,
            })
        # ... apply_delete_account(db, account_id, before, reassign_to)
```
`DELETE /categories/{id}` mirrors this exactly, plus (Pitfall 3) an additional child-category count check whose 422 payload distinguishes `"affected_count"` (transactions) from a `"child_count"`/`"subcategory_count"` key so the UI can present the right reassignment picker (category target, not transaction target).

---

### `backend/tools.py` (rewrite category tools + registry) (service, request-response)

**Analog:** `backend/tools.py` lines 169-208 (`spending_by_category`, `spending_in_category`) + registry lines 493-517

**Current string-matching pattern to replace** (169-185):
```python
def spending_by_category(period="all_time", start_date=None, end_date=None, limit=5) -> dict:
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"lim": max(1, min(int(limit), 50))}
    sql = (
        "SELECT category, SUM(-amount) AS total FROM transactions "
        "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p) +
        " GROUP BY category ORDER BY total DESC LIMIT :lim"
    )
    with engine.connect() as c:
        rows = [(r[0], float(r[1])) for r in c.execute(text(sql), p).fetchall()]
    return {"tool": "spending_by_category", "rows": rows, "period": _period_label(period, s, e)}
```
Rewrite per RESEARCH.md Pattern 4 — join `categories`, roll up to top-level via `COALESCE(c.parent_id, c.id)`, exclude `is_system` (Transfer):
```python
sql = (
    "SELECT COALESCE(c.parent_id, c.id) AS top_id, "
    "       COALESCE(p.name, c.name) AS top_name, "
    "       SUM(-t.amount) AS total "
    "FROM transactions t JOIN categories c ON c.id = t.category_id "
    "LEFT JOIN categories p ON p.id = c.parent_id "
    "WHERE t.amount < 0 AND t.is_transfer = false AND NOT c.is_system"
    + _date_clause(s, e, p) +
    " GROUP BY 1, 2 ORDER BY total DESC LIMIT :lim"
)
```
Keep the exact `{"tool": ..., "rows": ..., "period": ...}` structured-dict return convention — every tool in this file returns that shape; don't deviate.

**Registry pattern** (493-517):
```python
TOOLS = {
    "spending_total": spending_total,
    ...
    "list_categories": list_categories,
    ...
}
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)
```
CRITICAL (dual-registration gotcha, RESEARCH.md + repo memory): rewritten `spending_by_category`/`spending_in_category`/`list_categories` are already read-tool registry entries — no new registration needed there, but `backend/query.py`'s `FunctionTool.from_defaults()` list must ALSO be updated to match the new signatures/behavior, or the agent silently keeps serving stale pre-hierarchy behavior. `propose_rename_category`/`propose_merge_category` are write tools added via `TOOLS.update({...})` AFTER line 517's `READ_TOOL_NAMES` snapshot — never move them above that line.

---

### `ui/app/settings/CategoryManager.tsx` (moved + extended) (component, CRUD)

**Analog:** `ui/app/cashflow/AccountManager.tsx` (delete/reassign flow, lines 91-140+)

**Delete + 422-reassign flow pattern** (91-123):
```typescript
async function confirmDelete(account: Account) {
  setError(null);
  try {
    const r = await fetch(`/api/accounts/${account.id}`, { method: "DELETE" });
    if (r.ok) {
      setDeleteFlow({ stage: "idle" });
      onChanged();
      return;
    }
    if (r.status === 422) {
      const errBody = await r.json().catch(() => ({}));
      const affectedCount = errBody?.detail?.affected_count ?? 0;
      const otherAccounts = accounts.filter((a) => a.id !== account.id);
      setDeleteFlow({
        stage: "reassign",
        account,
        affectedCount,
        targetId: otherAccounts[0] ? String(otherAccounts[0].id) : "",
      });
      return;
    }
    const detail = await extractDetail(r);
    setError(`Couldn't save account: ${detail}. Nothing was changed.`);
    setDeleteFlow({ stage: "idle" });
  } catch (e) { /* ...network error handling... */ }
}

async function confirmReassignDelete() {
  if (deleteFlow.stage !== "reassign") return;
  const { account, targetId } = deleteFlow;
  const r = await fetch(`/api/accounts/${account.id}?reassign_to=${targetId}`, { method: "DELETE" });
  // ... same ok/422/error handling
}
```
`CategoryManager.tsx`'s delete flow copies this exactly, extended for the two-kind 422 payload (Pitfall 3: transactions vs. subcategories) — `setDeleteFlow` state needs a discriminator so the reassignment target picker offers transaction-targets vs. category-targets appropriately. Use `ui/app/styles.ts` tokens (`card`, `btn`, `input`, `label` — already imported in `AccountManager.tsx`) for styling; no new CSS approach.

---

### `ui/app/cashflow/charts/CategoryDonut.tsx` (rewire for rollup + drill-down) (component, transform)

**Analog:** itself (existing file, read in full per RESEARCH.md Sources) — modify in place to consume the new `spending_by_category` top-group rollup shape and add drill-down interaction (click top-group → show its subcategory breakdown). No new charting library; reuse whatever charting primitive the file already uses.

---

### `backend/tests/test_category_hierarchy.py` (new) (test, CRUD/batch)

**Analog:** `backend/tests/test_category_management.py` (existing rename/merge/list/affected-count tests against the free-string column)

Mirror its `db_available` fixture pattern and assertion style; existing file's assertions (`tx.category == new`) become `tx.category_id == new_id` once rewritten onto the hierarchy — per RESEARCH.md, treat `test_category_management.py` as "modify," not "delete and forget." New `test_category_hierarchy.py` covers CAT-01 (depth cap) and CAT-02 (block-or-reassign incl. child-category case per Pitfall 3).

---

## Shared Patterns

### Audited write helper contract
**Source:** `backend/writes.py` lines 1-14 (module docstring)
**Apply to:** every new `apply_add_category`/`apply_edit_category`/`apply_delete_category` and reworked `apply_rename_category`/`apply_merge_category`
```
Every apply_* function:
  - performs exactly one entity mutation (add/edit/delete/rename/merge)
  - writes exactly one AuditLog row recording before/after state
  - never commits the session itself — the caller owns the transaction boundary
```

### require_api_key + reset_engine() on every mutating endpoint
**Source:** `backend/main.py` lines 207-215
**Apply to:** all new `/categories` POST/PUT/DELETE endpoints
```python
@app.post("/accounts", ..., dependencies=[Depends(require_api_key)])
def create_account(payload: AccountCreate, db: Session = Depends(get_session)):
    acc = apply_add_account(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc
```

### Dual tool registration (read tools + FunctionTool list + READ_TOOL_NAMES ordering)
**Source:** `backend/tools.py` lines 493-517; `backend/query.py` FunctionTool list
**Apply to:** every rewritten/added category tool (`spending_by_category`, `spending_in_category`, `list_categories`, `propose_rename_category`, `propose_merge_category`)
```python
TOOLS = { ... "list_categories": list_categories, ... }
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)  # captured BEFORE write-tool TOOLS.update()
```
Checklist: (1) function in `tools.py` `TOOLS` dict (read) or `TOOLS.update()` block (write); (2) matching `FunctionTool.from_defaults(fn=...)` entry in `query.py`; (3) write tools never appear above the `READ_TOOL_NAMES` snapshot line.

### Nullable → backfill → NOT NULL migration idiom
**Source:** `alembic/versions/006_multi_platform_holdings.py` lines 42-83
**Apply to:** `alembic/versions/009_category_hierarchy.py`'s `transactions.category_id` column
```python
op.add_column("transactions", sa.Column("category_id", sa.Integer(), nullable=True))
# backfill via per-mapping-row bound UPDATE, not one opaque UPDATE (parity-checkable)
op.alter_column("transactions", "category_id", nullable=False)
op.create_foreign_key("fk_transactions_category", "transactions", "categories", ["category_id"], ["id"])
op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
```

### Block-or-reassign delete guard (3-way branch: 404 / 422+affected_count / 200)
**Source:** `backend/main.py` lines 236-274; `ui/app/cashflow/AccountManager.tsx` lines 91-140
**Apply to:** `DELETE /categories/{id}`, `CategoryManager.tsx` delete flow — extended per Pitfall 3 for child-category counts alongside transaction counts.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `data/category_mapping.csv` (or `alembic/data/category_mapping.csv`) | config | file-I/O | No prior checked-in migration-data artifact exists in this repo; RESEARCH.md recommends co-locating under `alembic/` since no convention exists. Format: stdlib `csv`, columns `raw_category,group,subcategory,emoji,color` |

## Metadata

**Analog search scope:** `backend/models.py`, `backend/writes.py`, `backend/main.py`, `backend/tools.py`, `backend/query.py`, `alembic/versions/006_multi_platform_holdings.py`, `ui/app/cashflow/AccountManager.tsx`, `ui/app/cashflow/CategoryManager.tsx`, `ui/app/cashflow/charts/CategoryDonut.tsx`, `backend/tests/test_category_management.py`
**Files scanned:** 10 (all read in full or targeted-range by this agent or by RESEARCH.md's prior verified reads)
**Pattern extraction date:** 2026-07-18
