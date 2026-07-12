# Phase 7: Investment Subsystem v2 - Pattern Map

**Mapped:** 2026-07-12
**Files analyzed:** 11 (new/modified)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `backend/fx.py` (NEW) | service/adapter-registry | request-response (external HTTP + cache) | `backend/prices.py` | exact — structural clone of the D-08 registry |
| `alembic/versions/008_fx_rate_cache.py` (NEW) | migration | CRUD (schema) | `alembic/versions/007_value_history_per_platform.py` | exact — reversible add-table/add-column pattern |
| `backend/models.py` (+`FxRateCache`, optionally `PortfolioEvent.currency`) | model | CRUD | `backend/models.py:PriceCache` (L216-236) | exact — same shape, different unique key |
| `backend/portfolio.py` (extend `portfolio_summary`, `recompute_holding_from_events`, +`value_history_series()`) | service | CRUD + transform | `backend/portfolio.py` itself (existing functions) | exact — in-place extension of the same module |
| `backend/tools.py` (+`find_platforms`, +`find_accounts`, fix `propose_add_holding`) | service (AI read-tool + proposal-producer) | request-response (agent tool call) | `backend/tools.py:find_transactions` (L412-437) | exact — same read-tool shape |
| `backend/main.py` (fix `_execute_proposal_payload` add_holding/edit_holding branches; +`GET /investments/history`) | controller (FastAPI route) | request-response | `backend/main.py:investments_summary` (L426+) for the new GET; `backend/main.py:create_holding`/`update_holding` (L362-406) for the delegation-to-writes.py pattern | exact |
| `backend/writes.py` (verify `apply_add_holding`/`apply_edit_holding` pass `platform_id`/`currency`/`asset_type` unchanged for cash/gold) | service (mutation helper) | CRUD | `backend/writes.py:apply_add_holding` (L222-244, already correct) | exact — no new pattern, just confirm cash/gold flow through |
| `backend/tests/test_fx.py` (NEW) | test | unit | `backend/tests/test_prices.py` | exact — mocked-httpx adapter test pattern |
| `ui/app/investments/AllocationPieChart.tsx` (NEW) | component | transform (client-side render) | `ui/app/cashflow/charts/CategoryDonut.tsx` | exact — same PieChart/Cell/Tooltip shape |
| `ui/app/investments/ValueHistoryChart.tsx` (NEW) | component | transform (client-side render) | `ui/app/cashflow/charts/TrendChart.tsx` | exact — same time-series line/bar chart shape (swap `Bar`→`Line`) |
| `ui/app/investments/page.tsx` (extend) | component (page) | request-response (fetch + render) | itself (existing page) + `ui/app/api/[...proxy]/route.ts` for the fetch/key pattern | role-match |

## Pattern Assignments

### `backend/fx.py` (service/adapter-registry, request-response)

**Analog:** `backend/prices.py`

**Module docstring / SSRF-mitigation pattern to mirror** (`backend/prices.py` lines 1-16):
```python
"""
Pluggable price-adapter registry + staleness + batch refresh (D-08/D-09/D-10/D-11).

`PRICE_ADAPTERS` is a `dict[str, Callable]` keyed by `asset_type` (mirrors the
`TOOLS` registry in backend/tools.py). Each adapter returns `(Decimal, source)`
on success or `None` on ANY failure — adapters NEVER raise, so one slow/failing
external source can never 500 the endpoint or abort a refresh batch (Pitfall 2,
T-05-04-DEG). On None the caller keeps the last price_cache row and marks it
stale downstream.

SSRF mitigation (T-05-04-SSRF): crypto tickers resolve ONLY via the fixed
module-level `TICKER_TO_COINGECKO_ID` map...

All money is Decimal(str(x)) — never float.
"""
```
For `fx.py`: apply the same SSRF discipline (RESEARCH Pitfall 5) — validate `currency` against `^[A-Z]{3,4}$` before interpolating into the frankfurter URL, mirroring the fixed-map approach here (not a lookup table, since currency codes are a small well-known keyspace, but the *principle* — never pass a raw user string into an external URL — carries over).

**Registry dict shape** (`backend/prices.py` lines 117-122):
```python
PRICE_ADAPTERS: dict[str, Callable[[str], tuple[Decimal, str] | None]] = {
    "crypto": fetch_crypto_price,
    "idx_stock": fetch_idx_price,
    "mutual_fund": fetch_manual_price,
    "other": fetch_manual_price,
}
```
→ `fx.py` mirrors this as `FX_ADAPTERS: dict[str, Callable[[str, str, date], tuple[Decimal, str] | None]] = {"frankfurter": fetch_frankfurter_rate}` (already spelled out in RESEARCH.md Pattern 1 — copy verbatim, it is a direct transcription of this registry idiom).

**Adapter contract — never raises, returns `None` on any failure** (`backend/prices.py` lines 56-64, 111-115):
```python
def fetch_manual_price(ticker: str) -> tuple[Decimal, str] | None:
    """No live source for mutual_fund/other — always None so the caller's
    fallback (read the last manually-set price_cache row) is the only path."""
    return None
```
`fetch_frankfurter_rate` must follow the identical `try/except ... return None` shape (see RESEARCH.md Code Examples — already drafted against this exact convention).

**Staleness / TTL dict pattern** (`backend/prices.py` lines 47-53):
```python
TTL_BY_ASSET_TYPE: dict[str, timedelta] = {
    "crypto": timedelta(minutes=5),
    "idx_stock": timedelta(days=1),
    "mutual_fund": timedelta(days=7),
    "other": timedelta(days=7),
}
_DEFAULT_TTL = timedelta(days=7)
```
**Action required (Pitfall 1):** add explicit `"cash"` and `"gold"` entries here — do not rely on the `.get(asset_type or "", _DEFAULT_TTL)` fallback (`backend/prices.py` line 135) silently applying 7 days to cash. Gold spot moves slowly (7d TTL is fine); cash arguably needs no "price" staleness concept at all — decide explicitly per Pitfall 1 / Open Question 2 in RESEARCH.md.

**Batch-refresh error isolation to mirror if `fx.py` gets a batch-refresh helper** (`backend/prices.py` lines 148 + inline `try/except` per ticker) — one failing currency pair must never abort the whole refresh, same as `refresh_all_prices`.

---

### `backend/models.py` — `FxRateCache` (model, CRUD)

**Analog:** `backend/models.py:PriceCache` (lines 216-236)

```python
class PriceCache(Base):
    """Last known price for an instrument.

    source: 'manual' for user-set overrides; 'coingecko', 'yfinance', etc. for
    fetched prices (D-12). All prices (fetched or manual) flow through this single
    table to give one read path for "current price".
    """

    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), server_default="IDR", nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
```
`FxRateCache` swaps the natural key from `ticker` to `(rate_date, base_currency, quote_currency)` with a `UniqueConstraint` (FX-05 immutability) — RESEARCH.md's Pattern 2 code block is the ready-to-use model; this PriceCache excerpt is its structural parent (same column-naming conventions: `String(8)` for currency codes, `String(32)` for `source`, `DateTime(timezone=True) server_default="now()"` for the fetch timestamp).

**Holding/PortfolioEvent identity pattern to reuse if adding `PortfolioEvent.currency`** (`backend/models.py` lines 156-159, 187-197): composite `UniqueConstraint`/FK conventions already exist for `(ticker, platform_id)` — follow the same `String(8)` + `server_default` idiom used on `Holding.currency` (not shown above but present per RESEARCH: "already exists, String(8), default 'IDR', NOT NULL") when adding `portfolio_events.currency`.

---

### `backend/portfolio.py` (extend: currency-aware `portfolio_summary`, `recompute_holding_from_events`, new `value_history_series()`)

**Analog:** the module's own existing functions — this is an in-place extension, not a new pattern.

**Module docstring convention to extend** (lines 1-18):
```python
"""
Average-cost portfolio accounting from the event ledger (D-01/D-02).
...
Composed reads (portfolio_summary) live here too so the API layer stays a thin
router: it reads holdings + the latest price_cache row per ticker and hands
them to these pure calculators.
"""
```

**`recompute_holding_from_events` — buy/sell/dividend accumulator to extend for FX-03/FX-04** (lines 40-97, full function read):
```python
def recompute_holding_from_events(db: Session, ticker: str, platform_id: int) -> dict:
    ...
    for ev in events:
        if ev.event_type == "buy":
            total_cost += ev.price * ev.quantity
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price - avg_cost) * ev.quantity
            total_cost -= avg_cost * ev.quantity
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            realized_pnl += ev.price * ev.quantity
            dividend_total += ev.price * ev.quantity
    avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
    ...
```
**Action (FX-03/Pitfall 4):** insert an FX-conversion step before accumulating into `total_cost` — convert `ev.price * ev.quantity` to IDR at `fx.get_rate(ev.currency, "IDR", ev.date)` before the `total_cost +=` line, per RESEARCH's recommended approach (a). Preserve the exact `avg_cost` invariant (D-02: sell leaves avg_cost unchanged) — do not restructure the accumulator, only inject a conversion multiply at the two `total_cost` mutation sites.

**`unrealized_pnl` — the `None`-propagation contract to mirror for FX failures** (lines 102-113):
```python
def unrealized_pnl(
    current_price: Decimal | None, avg_cost: Decimal, qty: Decimal
) -> Decimal | None:
    """... Returns None when there is no current price... callers surface it
    as null, not zero."""
    if current_price is None:
        return None
    return (current_price - avg_cost) * qty
```
**Anti-pattern to avoid (RESEARCH):** never let a failed FX lookup default to rate=1.0 — propagate `None` exactly like this function does for missing prices.

**`snapshot_all_holdings` — per-row try/except isolation pattern to mirror in `value_history_series()`** (lines 236-283):
```python
def snapshot_all_holdings(db: Session) -> dict:
    ...
    for h in db.query(Holding).all():
        try:
            ...
        except Exception:
            logger.warning("snapshot failed for ticker %s", h.ticker, exc_info=True)
            failed += 1
    return {"written": written, "skipped": skipped, "failed": failed}
```
`value_history_series()` (VZ-02's data source, reading `PortfolioValueHistory` — already imported at the top of `portfolio.py`, line 30) should follow the same "pure calculator, read-only, no commit" convention as `portfolio_summary`.

**Cash valuation special-case (Pitfall 1 / Open Question 2):** `portfolio_summary` currently calls `_latest_price(db, ticker)` unconditionally (line ~116-129 area). Add an explicit `if h.asset_type == "cash": value = h.quantity * fx.get_rate(h.currency, "IDR", today)` branch *before* the price-cache read, per RESEARCH's recommendation — do not write a synthetic `price_cache` row.

---

### `backend/tools.py` — `find_platforms` / `find_accounts` (read tool, request-response)

**Analog:** `backend/tools.py:find_transactions` (lines 412-437, full function)

```python
def find_transactions(
    merchant: str | None = None,
    category: str | None = None,
    period="all_time",
    start_date=None,
    end_date=None,
    kind="all",
    limit=10,
) -> dict:
    """Search/filter individual transactions and return their ids, dates, amounts,
    categories, merchants, and account ids, so the agent can resolve a merchant or
    category ... to a concrete transaction id before calling propose_edit_transaction
    or propose_delete_transaction. ... Rows are ordered most-recent-first, so
    rows[0] is "my last X".
    """
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"lim": max(1, min(int(limit), 50))}
    clauses = ["is_transfer = false"]
    if merchant is not None:
        clauses.append("merchant ILIKE :merchant")
        p["merchant"] = f"%{merchant}%"
    ...
```
`find_platforms(name: str | None = None, limit: int = 10) -> dict` and `find_accounts(name: str | None = None, limit: int = 10) -> dict` follow this exact shape: optional `ILIKE` filter, `limit` clamped via `max(1, min(int(limit), 50))`, most-recent/most-relevant first, returning ids so the agent can resolve name→id before a propose_* call. Reuse `_account_to_dict` (line 519-520, already exists) for `find_accounts`'s row serialization; write a new `_platform_to_dict` following the identical one-line dict-literal convention.

**Register both in the `TOOLS` dict** — locate the dict (mirrors `PRICE_ADAPTERS`'s registry idiom) and add `"find_platforms": find_platforms, "find_accounts": find_accounts,` entries alongside the existing `find_transactions`.

**Fix `propose_add_holding` to accept + pass `platform_id`** (`backend/tools.py` lines 802-828, full function — current buggy version, missing the parameter entirely):
```python
def propose_add_holding(
    ticker: str,
    quantity: float,
    avg_cost: float,
    purchase_date: str | None = None,
    currency: str = "IDR",
    asset_type: str | None = None,
) -> dict:
    """Propose adding a new holding (investment position). ..."""
    after = {
        "ticker": ticker,
        "quantity": str(Decimal(str(quantity))),
        "avg_cost": str(Decimal(str(avg_cost))),
        "purchase_date": purchase_date,
        "currency": currency,
        "asset_type": asset_type,
    }
    payload = {"operation": "add_holding", "rows": [{"before": None, "after": after}]}
    proposal_id, proposal_token = _make_proposal("add_holding", payload)
    return {
        "tool": "propose_add_holding",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Add holding: {quantity} {ticker} @ {avg_cost} {currency}",
        ...
    }
```
**Fix:** add a `platform_id: int` parameter and include it in the `after` dict — this is CH-01's first of two required fixes (see Pitfall 2).

---

### `backend/main.py` — fix `_execute_proposal_payload`'s duplicated `add_holding`/`edit_holding` branches (controller, request-response)

**Analog A (the bug to delete) — current inline duplication** (`backend/main.py` lines 757-789, full both branches):
```python
elif operation == "add_holding":
    from decimal import Decimal as _D
    h = Holding(
        ticker=after["ticker"],
        quantity=_D(str(after["quantity"])),
        avg_cost=_D(str(after["avg_cost"])),
        purchase_date=datetime.fromisoformat(after["purchase_date"]).date()
            if after.get("purchase_date") else None,
        currency=after.get("currency", "IDR"),
        asset_type=after.get("asset_type"),
    )
    db.add(h)
    db.flush()
    db.add(AuditLog(entity="holding", entity_id=h.id, operation="add",
                    before=None, after=after))

elif operation == "edit_holding":
    from decimal import Decimal as _D
    h_id = row.get("id")
    h = db.get(Holding, h_id)
    if h is None:
        raise ValueError(f"Holding {h_id} not found during confirm")
    if after.get("quantity") is not None:
        h.quantity = _D(str(after["quantity"]))
    if after.get("avg_cost") is not None:
        h.avg_cost = _D(str(after["avg_cost"]))
    if after.get("purchase_date") is not None:
        h.purchase_date = datetime.fromisoformat(after["purchase_date"]).date()
    if after.get("currency") is not None:
        h.currency = after["currency"]
    if after.get("asset_type") is not None:
        h.asset_type = after["asset_type"]
    db.add(AuditLog(entity="holding", entity_id=h_id, operation="edit", ...))
```
**Neither branch reads `after.get("platform_id")` anywhere** — this is Pitfall 2's exact root cause.

**Analog B (the target pattern — delegate to writes.py, already correct)** (`backend/main.py` lines 362-384 `create_holding`, 387-406 `update_holding`):
```python
@app.post("/holdings", response_model=HoldingOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_holding(payload: HoldingCreate, db: Session = Depends(get_session)):
    try:
        holding = apply_add_holding(db, payload.model_dump(mode="json"))
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    ...
```
And the corresponding `writes.py` helper it calls, which already handles `platform_id` correctly (`backend/writes.py` lines 222-244 area, `apply_add_holding` — verified via RESEARCH.md Code Examples):
```python
def apply_add_holding(db: Session, after: dict) -> Holding:
    holding = Holding(
        ticker=after["ticker"],
        quantity=Decimal(str(after["quantity"])),
        avg_cost=Decimal(str(after["avg_cost"])),
        purchase_date=date.fromisoformat(after["purchase_date"]) if after.get("purchase_date") else None,
        currency=after.get("currency", "IDR"),
        asset_type=after.get("asset_type"),
        platform_id=after.get("platform_id"),
        coingecko_id=after.get("coingecko_id"),
    )
    db.add(holding)
    db.flush()
    db.add(AuditLog(entity="holding", entity_id=holding.id, operation="add", before=None, after=after))
    return holding
```
**Fix (Pitfall 2, CH-01 fix #2 of 2):** replace the entire `add_holding`/`edit_holding` inline branches in `_execute_proposal_payload` with calls to `apply_add_holding(db, after)` / `apply_edit_holding(db, row["id"], after, before)` — deletes ~35 lines, automatically inherits `platform_id`/`coingecko_id` handling. This is the exact fix RESEARCH.md's Anti-Patterns section and Pitfall 2 both call out.

**New `GET /investments/history` endpoint — analog** (`backend/main.py` line 426+, `investments_summary`, an open GET reading from `portfolio.py`):
```python
@app.get("/investments/summary", response_model=PortfolioSummary)
def investments_summary(db: Session = Depends(get_session)):
    """Composed portfolio payload (D-05, INV-06) — open read. ..."""
```
`GET /investments/history` mirrors this: no `Depends(require_api_key)` (open read, matches ASVS V4 guidance in RESEARCH), calls a new `portfolio.value_history_series(db, range_param)` pure function, returns a Pydantic response model following the `PortfolioSummary` schema-naming convention (`*Out`/`*Response` family in `backend/schemas.py`).

---

### `alembic/versions/008_fx_rate_cache.py` (migration, CRUD)

**Analog:** `alembic/versions/007_value_history_per_platform.py` (full file read, lines 1-60+)

```python
"""portfolio_value_history: widen unique key to (snapshot_date, ticker, platform_id)

Revision ID: c1d2e3f4a5b6
Revises: 8a4c2e6f91b3
Create Date: 2026-07-12
...
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "8a4c2e6f91b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolio_value_history",
        sa.Column("platform_id", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE ... best-effort backfill ...")
    op.create_foreign_key("fk_pvh_platform", "portfolio_value_history", "platforms", ["platform_id"], ["id"])
    op.create_index("ix_portfolio_value_history_platform_id", "portfolio_value_history", ["platform_id"])
    op.drop_index("ix_portfolio_value_history_date_ticker", table_name="portfolio_value_history")
    op.create_index(
        "ix_portfolio_value_history_date_ticker_platform",
        "portfolio_value_history", ["snapshot_date", "ticker", "platform_id"], unique=True,
    )


def downgrade() -> None:
    ...  # reverses each op in inverse order
```
**Convention to copy:** docstring explains *what* + *why* + backfill semantics; `revision`/`down_revision` as literal hash strings; every `upgrade()` op has a matching `downgrade()` inverse; use `op.create_table` (not `add_column`) for the brand-new `fx_rate_cache` table, following the same index/constraint-naming convention (`ix_<table>_<cols>`, `fk_<short>_<target>`, `uq_<table>_<cols>`).

---

## Shared Patterns

### Adapter registry (D-08)
**Source:** `backend/prices.py` lines 47-53 (TTL dict), 117-122 (`PRICE_ADAPTERS` dict), 56-64/111-115 (never-raise contract)
**Apply to:** `backend/fx.py` — `FX_ADAPTERS` dict, `fetch_frankfurter_rate` (never raises, returns `None`), immutable cache read/write mirroring `PriceCache`'s single-read-path design.

### Money as Decimal, never float
**Source:** `backend/portfolio.py` line 16 ("All money math is Decimal — never float"), `backend/writes.py:apply_add_holding` (`Decimal(str(after["quantity"]))`)
**Apply to:** every new FX rate, cash amount, gold gram quantity — `Decimal(str(x))` construction, never bare float arithmetic.

### `None`-propagation for missing data (never fabricate)
**Source:** `backend/portfolio.py:unrealized_pnl` lines 102-113
**Apply to:** `fx.get_rate()` returning `None` on cache-miss + adapter failure — valuation code must propagate `None`/"unavailable", never default to rate=1.0 (explicit anti-pattern call-out in RESEARCH.md).

### Per-row/per-ticker try/except isolation
**Source:** `backend/portfolio.py:snapshot_all_holdings` lines 236-283, `backend/prices.py:refresh_all_prices` lines 148+
**Apply to:** any batch FX-rate refresh or multi-currency valuation loop — one failing currency pair or ticker must never abort the whole batch/request.

### ValueError → 422 at the API boundary
**Source:** `backend/main.py:create_holding` (lines 370-380), `update_holding` (lines 398-401)
**Apply to:** `GET /investments/history` and any new write path — domain layer raises `ValueError`, `main.py` translates to `HTTPException(422)`.

### Delegate-to-writes.py, don't duplicate
**Source:** `backend/main.py:create_holding`/`update_holding` (call `apply_add_holding`/`apply_edit_holding`) vs. `_execute_proposal_payload`'s current duplicated inline branches (lines 757-789)
**Apply to:** the CH-01 fix — this is the single most load-bearing pattern in this phase's backend work.

### Recharts fixed-height wrapper + dark theme tooltip
**Source:** `ui/app/cashflow/charts/TrendChart.tsx` (full file), `ui/app/cashflow/charts/CategoryDonut.tsx` (full file)
**Apply to:** `AllocationPieChart.tsx` (clone `CategoryDonut.tsx` almost verbatim — swap `category`/`total` for asset-type-or-platform grouping keys and current IDR market value) and `ValueHistoryChart.tsx` (clone `TrendChart.tsx` — swap `Bar` for `Line`/`LineChart`, `month` for a date axis, add the time-range selector per VZ-02). Both existing charts share:
```tsx
<div style={{ width: "100%", height: 280 }}>
  <ResponsiveContainer>
    {/* chart */}
  </ResponsiveContainer>
</div>
```
This explicit-height wrapper is **load-bearing** (documented Pitfall in 04-RESEARCH.md: `ResponsiveContainer` renders blank inside a grid/flex parent with no resolvable height) — do not omit it.

## No Analog Found

None — every file in this phase has a strong (exact) analog already in the codebase. This phase is explicitly a valuation-layer/migration extension of already-shipped Phase 5 machinery (per RESEARCH.md's own framing), not new-subsystem greenfield work, except for the two new Recharts components, which have direct analogs in the Phase 4 cashflow charts directory.

## Metadata

**Analog search scope:** `backend/` (prices.py, portfolio.py, tools.py, main.py, writes.py, models.py), `alembic/versions/`, `ui/app/cashflow/charts/`, `ui/app/investments/`
**Files scanned:** ~12 (via graphify query + targeted grep/Read, no full-file re-reads)
**Pattern extraction date:** 2026-07-12

## PATTERN MAPPING COMPLETE
