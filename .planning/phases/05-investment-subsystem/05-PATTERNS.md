# Phase 5: Investment Subsystem - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 16 (new + modified)
**Analogs found:** 14 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/prices.py` (new) | service | request-response (external HTTP) | `backend/tools.py` `TOOLS` registry | role-match (registry shape) |
| `backend/portfolio.py` (new) | service | transform (event→position) | `backend/tools.py` `resolve_period` + aggregations | role-match |
| `backend/scheduler.py` (new) | service | batch / event-driven | `backend/main.py` app init (no lifespan yet) | no-analog (new capability) |
| `backend/writes.py` (modified) | service | CRUD | existing `apply_add_account`/`apply_delete_account` in same file | exact |
| `backend/schemas.py` (modified) | model (DTO) | request-response | `AccountCreate`/`AccountUpdate`/`AccountOut`/`TransactionCreate` | exact |
| `backend/main.py` (modified — CRUD routes) | route/controller | CRUD | `create_account`/`update_account`/`delete_account` (L121-201) | exact |
| `backend/main.py` (modified — lifespan) | config | event-driven | `app = FastAPI(...)` (L96, unadorned) | no-analog (new capability) |
| `backend/main.py` (modified — price-refresh route) | route/controller | request-response | `cashflow_summary` composed-read endpoint (L214) | role-match |
| `backend/models.py` (modified — `Platform`) | model | — | `Account` model (L43-53) | exact |
| `backend/models.py` (modified — `PortfolioValueHistory`) | model | — | `PriceCache` (L176) / `Transaction` (L56) | role-match |
| `backend/models.py` (modified — `holdings.platform_id`) | model | — | `Transaction.account_id` FK (L69) | exact |
| `backend/tools.py` (modified — correlation tool) | utility (read tool) | request-response | `spending_in_category` (L188) + `resolve_period` (L41) | exact |
| `alembic/versions/004_*.py` (new) | migration | — | `alembic/versions/002_new_tables.py`, `003_app_settings.py` | exact |
| `ui/app/investments/PlatformManager.tsx` (new) | component | CRUD | `ui/app/cashflow/AccountManager.tsx` | exact (direct mirror, D-12) |
| `ui/app/investments/HoldingModal.tsx` / `HoldingOverrideModal.tsx` / `PriceOverrideDialog.tsx` (new) | component | CRUD | `ui/app/cashflow/TransactionModal.tsx` + `ConfirmDialog.tsx` | exact |
| `ui/app/investments/StalenessBadge.tsx` (new) | component | render | (no component precedent — inline badge styles from Phase 4) | partial (style-token reuse only) |
| `ui/app/investments/page.tsx` (modified) | page | request-response | `ui/app/cashflow/page.tsx` (`"use client"` tracker) | role-match |

## Pattern Assignments

### `backend/writes.py` — `apply_add_holding` / `apply_add_portfolio_event` / `apply_add_platform` / `apply_edit_platform` / `apply_delete_platform` (service, CRUD)

**Analog:** `backend/writes.py` (extend in-place — same module, same conventions)

**Module contract** (`backend/writes.py` lines 10-14): every `apply_*` function performs exactly one mutation, writes exactly one `AuditLog` row (before/after), and **never commits** — the caller owns the transaction boundary. New holding/event/platform writes MUST follow this verbatim (D-16).

**Add pattern** (`apply_add_account`, lines 76-87):
```python
def apply_add_account(db: Session, after: dict) -> Account:
    acc = Account(name=after["name"], type=after.get("type"), currency=after.get("currency"))
    db.add(acc)
    db.flush()  # LOAD-BEARING: populates acc.id before the AuditLog row below
    db.add(AuditLog(entity="account", entity_id=acc.id, operation="add", before=None, after=after))
    return acc
```
- `apply_add_platform` copies this exactly (`entity="platform"`).
- `apply_add_portfolio_event` follows the same shape (`entity="portfolio_event"`), then calls `recompute_holding_from_events(db, ticker)` from `backend/portfolio.py` before returning so the position falls out of the ledger (D-01).

**Money-as-Decimal invariant** (`apply_add_transaction`, line 33):
```python
amount=Decimal(str(after["amount"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
```
Apply to `quantity`, `price`, `avg_cost` in every event/holding write (FND-03; crypto qty is `Numeric(28,8)`, money is `Numeric(18,2)`).

**Reassign-then-delete pattern** (`apply_delete_account`, lines 106-133) — the direct template for `apply_delete_platform` (D-12). The reassignment UPDATE + count is recorded in the single AuditLog row (`after={"reassign_to": ..., "reassigned_count": ...}`); the deletion decision lives in the endpoint, the write lives here:
```python
if reassign_to is not None:
    result = db.execute(
        text("UPDATE holdings SET platform_id = :reassign_to WHERE platform_id = :pid"),
        {"reassign_to": reassign_to, "pid": platform_id},
    )
    reassigned_count = result.rowcount
    audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}
```

---

### `backend/main.py` — holdings/events/platforms CRUD + price-refresh endpoints (route, CRUD)

**Analog:** `create_account` / `update_account` / `delete_account` (lines 121-201)

**Auth + create pattern** (lines 121-129):
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
- `require_api_key` (imported `backend/main.py:44`) guards every WRITE route; GET reads are open (see `cashflow_summary`).
- Endpoint calls the `apply_*` helper, THEN `db.commit()` (helper never commits), THEN `reset_engine()`.
- `require_api_key` is imported from `backend.auth` — reuse, do not re-implement.

**Edit pattern with before-snapshot + ValueError→422** (lines 132-147):
```python
before = {"id": acc.id, "name": acc.name, "type": acc.type, "currency": acc.currency}
try:
    apply_edit_account(db, account_id, payload.model_dump(mode="json", exclude_none=True), before)
except ValueError as e:
    raise HTTPException(status_code=422, detail=str(e))
```
The endpoint builds the `before` dict from the live ORM row; `exclude_none=True` gives partial-update semantics.

**Delete-with-422-detail-shape** (lines 182-196) — the exact `detail` shape the `PlatformManager.tsx` UI copy consumes:
```python
if tx_count > 0:
    if reassign_to is None:
        raise HTTPException(status_code=422, detail={
            "message": f"{tx_count} transactions use this account — reassign or delete them first",
            "affected_count": tx_count,
        })
```
Platform delete uses `affected_count` = holdings count; mirror this dict shape exactly (frontend reads `detail.affected_count`).

**Composed-read endpoint** (`cashflow_summary`, lines 214-243) — analog for `GET /investments/summary`: open read (no `require_api_key`), resolves period once, composes `tools.py` aggregations into a single Pydantic payload. `GET /investments/summary` composes holdings + `price_cache` current-price + P&L calculators from `backend/portfolio.py`, and does the lazy price refresh (D-09) for stale tickers inline.

---

### `backend/schemas.py` — `HoldingCreate`/`Out`, `PortfolioEventCreate`/`Out`, `PlatformCreate`/`Update`/`Out`, `PortfolioSummary` (model/DTO)

**Analog:** `AccountCreate`/`AccountUpdate`/`AccountOut`/`TransactionCreate` (lines 24-96)

**Create DTO with MoneyDecimal** (`TransactionCreate`, lines 24-32):
```python
class TransactionCreate(BaseModel):
    date: datetime
    amount: MoneyDecimal = Field(..., description="Signed: negative = expense, positive = income")
    currency: str = "IDR"
    ...
```
Use the shared `MoneyDecimal` type for `price`/`avg_cost`/`quantity` monetary fields.

**Out DTO (ORM read)** (`AccountOut`, lines 50-56):
```python
class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str | None
    currency: str | None
```

**Update DTO (all-optional partial)** (`AccountUpdate`, lines 90-95):
```python
class AccountUpdate(BaseModel):
    """Partial-update body — all fields Optional."""
    name: str | None = None
    ...
```
`PlatformUpdate` adds `kind: str | None = None`. `PortfolioSummary` follows the `CashflowSummary` composed-payload style (line 59) — nested dicts/lists for platform groups, per-holding rows, totals, and "as of" timestamp.

---

### `backend/models.py` — `Platform`, `PortfolioValueHistory`, `holdings.platform_id` (model)

**Analog:** `Account` (lines 43-53), `PriceCache` (lines 176-195), `Transaction.account_id` FK (line 69)

**Simple managed entity** (`Account`, lines 43-49) — template for `Platform` (add `kind: Mapped[str | None] = mapped_column(String(32), nullable=True)`):
```python
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
```

**FK column** (`Transaction.account_id`, lines 69-71) — template for `holdings.platform_id` (nullable so existing rows + "unassigned" state are valid):
```python
account_id: Mapped[int | None] = mapped_column(
    ForeignKey("accounts.id"), nullable=True, index=True
)
```

**Money/currency column conventions** (`PriceCache`, lines 186-195) — template for `PortfolioValueHistory` money columns: `Numeric(18,2)` for market_value/cost_basis, `Numeric(28,8)` for quantity, `String(8) server_default="IDR"` for currency, `DateTime(timezone=True) server_default="now()"` for timestamps.

**Note:** `Holding`, `PortfolioEvent`, `PriceCache` already exist (lines 126-195) and are reused as-is (D-17). `PortfolioEvent.event_type` (`String(16)`) already carries `buy|sell|dividend`.

---

### `backend/tools.py` — correlation read tool `spending_before_after_purchase` (utility, read tool)

**Analog:** `spending_in_category` (line 188) + `resolve_period` (line 41)

**Registry + structured-dict return** (module docstring, lines 1-18): tools never emit raw SQL, use parameterized `text()`, return a structured dict keyed by `"tool"`. Register the new tool in the `TOOLS` dict (D-15).

**Parameterized-SQL read pattern** (`_currency`, lines 99-102) — the connection + bound-param shape for the pivot-date lookup:
```python
with engine.connect() as c:
    row = c.execute(text("SELECT ... WHERE ticker = :ticker AND event_type = 'buy'"), {"ticker": ticker}).scalar()
```

**Period-window reuse** — the correlation tool resolves the pivot date (earliest buy event), computes equal-length before/after windows, and calls `spending_in_category(category, period="custom", start_date=..., end_date=...)` — reusing the existing `custom` period contract (`resolve_period`, lines 52-58; note end_date is made exclusive there). Full skeleton in `05-RESEARCH.md` § Code Examples (lines 584-648).

---

### `backend/prices.py` (new — price-adapter registry, service)

**Analog:** `TOOLS` dict registry pattern in `backend/tools.py`

**Registry shape:** `PRICE_ADAPTERS: dict[str, Callable[[str], tuple[Decimal, str] | None]]` keyed by `asset_type` — mirrors the `TOOLS = {name: callable}` dict (D-08). Each adapter returns `(Decimal, source) | None`; failure returns `None` (broad `except`, matching the intentional broad-exception convention in `ask()`/`/query`), never raises — caller falls back to the latest `price_cache` row + stale flag (INV-03). Full skeleton in `05-RESEARCH.md` Pattern 1 (lines 241-306). Money uses `Decimal(str(price))` per the `writes.py` line-33 invariant.

---

### `backend/portfolio.py` (new — recompute + P&L, service/transform)

**Analog:** `resolve_period` (pure derivation function) + `backend/tools.py` aggregation style

`recompute_holding_from_events(db, ticker)` scans ordered `portfolio_events`, derives `quantity`/`avg_cost` (average-cost, `avg_cost` unchanged by a sell), returns realized P&L as a byproduct, and writes the `holdings` row. Called from every event write in `writes.py` and idempotently from the scheduler. Full algorithm in `05-RESEARCH.md` Pattern 2 (lines 308-370). All math in `Decimal`.

---

### `backend/scheduler.py` + `backend/main.py` lifespan (new — no analog)

**No analog:** the app is currently `app = FastAPI(title="monai", version="0.1.0")` (line 96, unadorned — no lifespan, first always-on background component). Use `@asynccontextmanager lifespan(app)` + `AsyncIOScheduler(timezone="Asia/Jakarta")` with `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`. Reuse the existing `get_session_sync()` (`backend/db.py:30`) inside the job — do NOT create a second session path. Full pattern in `05-RESEARCH.md` Pattern 3 (lines 378-421). Planner uses RESEARCH.md here, not a codebase analog.

---

### `alembic/versions/004_investment_platforms.py` (new — migration)

**Analog:** `alembic/versions/002_new_tables.py` (revision `7b4e9f1a6c52`), `003_app_settings.py` (revision `9c1a4f7d2b8e`, current head)

`down_revision = "9c1a4f7d2b8e"` (chains onto 003). Creates `platforms`, `portfolio_value_history`, adds `holdings.platform_id` FK (nullable). `entrypoint.sh` already runs `alembic upgrade head` — no wiring needed. Full skeleton in `05-RESEARCH.md` § Code Examples (lines 651-703).

---

### `ui/app/investments/PlatformManager.tsx` (new — component, CRUD)

**Analog:** `ui/app/cashflow/AccountManager.tsx` (direct mirror, D-12)

**Imports + state pattern** (lines 1-39):
```tsx
"use client";
import { useState } from "react";
import { card, input, btn, label } from "../styles";
import ConfirmDialog from "../cashflow/ConfirmDialog";  // reuse verbatim — generic, not cashflow-specific

const [editingId, setEditingId] = useState<number | null>(null);
const [editName, setEditName] = useState("");
const [deleteFlow, setDeleteFlow] = useState<DeleteFlowState>({ stage: "idle" });
```
`DeleteFlowState` is the discriminated union `{stage: "idle"} | {stage: "confirm"; ...} | {stage: "reassign"; affectedCount; targetId}` (lines 28-31).

**Reassign-on-422 delete flow** (`confirmDelete`, lines 91-123):
```tsx
const r = await fetch(`/api/platforms/${platform.id}`, { method: "DELETE" });
if (r.status === 422) {
  const errBody = await r.json().catch(() => ({}));
  const affectedCount = errBody?.detail?.affected_count ?? 0;
  setDeleteFlow({ stage: "reassign", platform, affectedCount, targetId: ... });
}
```
Then re-issue with `?reassign_to=${targetId}` (`confirmReassignDelete`, lines 125-150).

**Inline-edit table row + Edit/Delete text-links** (lines 155-217) and the `ConfirmDialog` with a `<select>` in its `children` slot (lines 268-291) — copy structurally. `PlatformManager` adds a second optional `kind` input next to `name` in the add/edit rows (per UI-SPEC). `extractDetail(r)` helper (lines 296-308) — copy verbatim.

---

### `ui/app/investments/HoldingModal.tsx` / `HoldingOverrideModal.tsx` / `PriceOverrideDialog.tsx` (new — component, CRUD)

**Analog:** `ui/app/cashflow/TransactionModal.tsx` (dual-mode create/edit) + `ConfirmDialog.tsx`

**Dual-mode create/edit contract** (`TransactionModal`, lines 51-57): `editingTx == null` → create; populated → edit. Same `editingHolding == null` switch drives `HoldingModal`/`HoldingOverrideModal`.

**Overlay + card panel shell** (lines 183-202):
```tsx
<div style={{ position: "fixed", inset: 0, background: "rgba(15,17,21,0.72)", display: "flex",
  alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={onClose}>
  <div style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
    onClick={(e) => e.stopPropagation()}>
```
`PriceOverrideDialog` uses `maxWidth: 360, padding: 24` (ConfirmDialog dimensions) per UI-SPEC.

**datetime-local helper** (`toLocalDatetimeInputValue`, lines 44-49) — copy verbatim for the event Date field (avoids UTC shift).

**Submit + error-copy pattern** (`handleSubmit`, lines 118-181): `saving` state → "Saving…" disabled button, POST/PUT through `/api/...` proxy, `onSaved()` + `onClose()` on success, `"Couldn't save ...: ${detail}. Nothing was changed."` on failure (exact copy in `05-UI-SPEC.md` § Copywriting). Event-type `<select>` (Buy/Sell/Dividend, lowercase values), platform `<select>` with "(unassigned)" option per UI-SPEC.

---

### `ui/app/investments/page.tsx` (modified — page)

**Analog:** `ui/app/cashflow/page.tsx` (`"use client"` tracker with modals + refetch)

Convert the Phase-3 server-component skeleton to `"use client"` (RESEARCH Pitfall 5). Fetch `GET /api/investments/summary`, render portfolio-total banner + P&L summary row + platform-grouped holding cards + `PlatformManager`. Use the `fmt()` `Intl.NumberFormat({signDisplay:"always"})` pattern from `cashflow/page.tsx` for signed/colored P&L (UI-SPEC § Color). "Refresh prices" button → `POST /api/prices/refresh` → refetch.

---

### `ui/app/investments/StalenessBadge.tsx` (new — partial analog)

**No component precedent** — built fresh per `05-UI-SPEC.md` § Color (staleness spec) and § Layout notes (lines 207-210). Props: `fetchedAt`, `source`, `isStale` (server-computed flag — frontend never does TTL math). Reuses the category-manager pill visual (`background:"#2a2e37"`, `borderRadius:999`, `padding:"2px 8px"`) and style tokens from `ui/app/styles.ts`. A ~15-line relative-time helper, no npm dep.

## Shared Patterns

### Write path (audit + Decimal + single transaction boundary)
**Source:** `backend/writes.py` (module docstring lines 10-14; `apply_add_account` lines 76-87)
**Apply to:** all backend holding/event/platform writes (D-16)
Every `apply_*`: one mutation, one `AuditLog` row (before/after), `db.flush()` before the audit row to populate the id, NEVER commit (caller owns commit). Money via `Decimal(str(x))`.

### API auth + error mapping
**Source:** `backend/main.py:44` (`from backend.auth import require_api_key`); `create_account` L121-129; ValueError→422 at L141-142
**Apply to:** all new WRITE routes (holdings/events/platforms/price-refresh). Pattern: `dependencies=[Depends(require_api_key)]`, call `apply_*`, `db.commit()`, `db.refresh()`, `reset_engine()`. `ValueError → HTTPException(422)`; missing entity → 404. GET reads stay open.

### DTO-by-role
**Source:** `backend/schemas.py` (`*Create` L24/L84, `*Update` L90, `*Out` L50 with `ConfigDict(from_attributes=True)`)
**Apply to:** all new schemas. `MoneyDecimal` for money fields; `*Update` all-optional for partial-update + `exclude_none=True` in the endpoint.

### Frontend fetch/error/refetch
**Source:** `ui/app/cashflow/AccountManager.tsx` `extractDetail` (L296-308) + error-copy pattern; `TransactionModal` `handleSubmit` (L118-181)
**Apply to:** all new investments components. `/api/...` proxy (key injected server-side), `extractDetail(r)`, `"Couldn't <verb> ...: {detail}. Nothing was changed."` copy, `onChanged()`/`onSaved()` refetch on success.

### Reassign-then-delete (backend + frontend)
**Source:** backend `apply_delete_account` (`writes.py` L106-133) + `delete_account` 422 detail (`main.py` L182-196); frontend `AccountManager` delete flow (L91-150, L268-291)
**Apply to:** platform delete (D-12) — `affected_count` = holdings using the platform; `?reassign_to=` re-issue; single audited helper call.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/scheduler.py` + `main.py` lifespan | service/config | event-driven | First always-on background component in the stack; `app = FastAPI(...)` is unadorned (L96). Use `05-RESEARCH.md` Pattern 3 (APScheduler + lifespan). |
| `ui/app/investments/StalenessBadge.tsx` | component | render | No badge component exists yet; only inline pill styles + tokens to reuse. Build per `05-UI-SPEC.md` § Color + Layout notes. |

## Metadata

**Analog search scope:** `backend/` (writes.py, main.py, tools.py, models.py, schemas.py, db.py, auth), `ui/app/cashflow/` (AccountManager, TransactionModal, ConfirmDialog, page.tsx), `ui/app/styles.ts`, `alembic/versions/`
**Files scanned:** ~12 source files (graphify-guided; targeted reads)
**Pattern extraction date:** 2026-07-09
