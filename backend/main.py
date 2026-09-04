"""
monai backend — FastAPI.

Run (dev):
    cd monai
    uv run --with-requirements backend/requirements.txt uvicorn backend.main:app --reload

Endpoints:
    GET  /health
    GET  /cashflow/summary       aggregate dashboard payload (D-08)
    GET  /accounts
    POST /accounts               create an account (requires API key)
    PUT  /accounts/{id}          edit an account (requires API key)
    DELETE /accounts/{id}        delete (reassign-then-delete via ?reassign_to=) (requires API key)
    GET  /transactions?limit=50
    POST /transactions          create one (logs new spending)
    PUT  /transactions/{id}     partial-update a transaction (requires API key)
    DELETE /transactions/{id}   delete a transaction (requires API key)
    GET  /categories            category tree, tx_count + effective color, ?kind= filter (public)
    POST /categories            create a category (requires API key)
    PUT  /categories/{id}       edit a category (requires API key)
    DELETE /categories/{id}     delete (reassign-then-delete via ?reassign_to=) (requires API key)
    GET  /categories/{name}/affected-count  tx count for a category + its descendants (public)
    POST /categories/rename     rename a category (single-row, D-11) (requires API key)
    POST /categories/merge      merge one category into another (requires API key)
    POST /import                multipart CSV upload (Wallet export)
    POST /query                 natural-language question over your data
    POST /query-stream          streaming SSE agent response
    GET  /proposals             list pending proposals (public)
    POST /proposals/{id}/confirm  apply a pending proposal (requires API key)
    POST /proposals/{id}/reject   reject a pending proposal (requires API key)
    GET  /settings              effective settings, keys masked (public)
    PUT  /settings              partial-update settings (requires API key)
"""

import hmac
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastmcp.utilities.lifespan import combine_lifespans
from sqlalchemy import desc, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth
from backend.auth import require_api_key
from backend.mcp_server import build_mcp
from backend.db import get_session
from backend.importer import _get_or_create_account, import_csv_text
from backend.models import Account, AuditLog, Category, Holding, Platform, PortfolioEvent, Proposal, Transaction
from backend.portfolio import portfolio_summary as compose_portfolio_summary
from backend.portfolio import value_history_series
from backend.writes import (
    apply_add_account,
    apply_add_balance_adjustment,
    apply_add_category,
    apply_add_funded_buy,
    apply_add_funded_sell,
    apply_add_holding,
    apply_add_investment_transfer,
    apply_add_platform,
    apply_add_portfolio_event,
    apply_add_transaction,
    apply_add_transfer,
    apply_delete_account,
    apply_delete_category,
    apply_delete_holding,
    apply_delete_platform,
    apply_delete_transaction,
    apply_delete_transaction_or_pair,
    apply_edit_account,
    apply_edit_category,
    apply_edit_holding,
    apply_edit_platform,
    apply_edit_transaction,
    apply_merge_category,
    apply_rename_category,
    apply_set_price,
    resolve_category_id,
)
from backend.schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    AffectedCountResponse,
    BalanceAdjustmentCreate,
    BulkActionResponse,
    BulkDeleteRequest,
    BulkRecategorizeRequest,
    CashflowSummary,
    CategoryCreate,
    CategoryMergeRequest,
    CategoryNode,
    CategoryRenameRequest,
    CategoryUpdate,
    ConfirmRequest,
    FundedBuyCreate,
    FundedSellCreate,
    ImportResponse,
    HoldingCreate,
    HoldingOut,
    HoldingUpdate,
    InvestmentTransferCreate,
    NetWorth,
    PlatformCreate,
    PlatformOut,
    PlatformUpdate,
    PortfolioEventCreate,
    PortfolioEventOut,
    PortfolioSummary,
    PriceOverrideRequest,
    ProposalOut,
    QueryRequest,
    QueryResponse,
    SettingsOut,
    SettingsUpdate,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
    TransferCreate,
    ValueHistoryResponse,
)
from backend.tools import (
    account_balances,
    income_total,
    monthly_trend,
    net_total,
    net_worth,
    resolve_period,
    spending_by_category,
    spending_total,
    _descendant_ids,
    _find_category_node,
)
from backend.settings import (
    KEY_ANTHROPIC_API_KEY,
    KEY_OPENAI_API_KEY,
    get_effective_settings,
    mask_key,
    upsert_settings,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-process daily portfolio-value snapshot scheduler (D-13/D-14).

    entrypoint.sh runs a single uvicorn process (no --workers), so exactly one
    scheduler owns the daily job — no leader election needed.
    NOTE: a future multi-worker deploy would run N schedulers; that would need
    leader election (or an external scheduler) to avoid N duplicate snapshots.
    """
    from backend.scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


# MCP server (Phase 6) — read-only, API-key-gated, co-mounted at /mcp on this
# same FastAPI process/port (MCP-01). path="/" here + app.mount("/mcp", ...)
# below == endpoint is exactly /mcp, never /mcp/mcp (RESEARCH Pitfall 3).
mcp = build_mcp()
mcp_app = mcp.http_app(path="/")

# combine_lifespans, never mcp_app.lifespan alone — monai's existing
# scheduler lifespan must keep running (RESEARCH Pitfall 1).
app = FastAPI(
    title="monai", version="0.1.0",
    lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
)

# Local-only dev frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def mcp_api_key_guard(request: Request, call_next):
    """Outer-app auth guard for the whole /mcp subtree (MCP-04, D-04).

    Registered on the outer FastAPI app (not inside the mounted mcp_app) so
    it runs BEFORE the MCP session manager sees the request (RESEARCH
    Pitfall 4). Reuses the single auth.key_ok() constant-time check — no
    new secret, no hand-rolled comparison. Accepts either the existing
    MONAI_API_KEY header or `Authorization: Bearer <key>` (same secret) for
    client-agnostic MCP clients (RESEARCH A2). Never logs the header value.
    """
    if request.url.path.startswith("/mcp"):
        if not auth._CONFIGURED_KEY:
            return JSONResponse(
                {"detail": "Server misconfigured: MONAI_API_KEY env var is not set"},
                status_code=503,
            )
        key = request.headers.get("MONAI_API_KEY")
        if key is None:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                key = auth_header[7:]
        if not auth.key_ok(key):
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    return await call_next(request)


app.mount("/mcp", mcp_app)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_session)):
    return db.query(Account).order_by(Account.name).all()


@app.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_account(payload: AccountCreate, db: Session = Depends(get_session)):
    """Create an account (CASH-05). Routed through apply_add_account (audited)."""
    acc = apply_add_account(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc


@app.put("/accounts/{account_id}", response_model=AccountOut, dependencies=[Depends(require_api_key)])
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_session)):
    """Partial-update an account (CASH-05). Only supplied fields change."""
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    before = {"id": acc.id, "name": acc.name, "type": acc.type, "currency": acc.currency}
    try:
        apply_edit_account(db, account_id, payload.model_dump(mode="json", exclude_none=True), before)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc


@app.post("/accounts/{account_id}/adjust-balance", status_code=201, dependencies=[Depends(require_api_key)])
def adjust_account_balance(account_id: int, payload: BalanceAdjustmentCreate, db: Session = Depends(get_session)):
    """Reconcile an account's derived balance to a target (ACCT-02, CHAT-09).

    Routes through apply_add_balance_adjustment — the delta is computed there
    via a fresh unfiltered SUM(amount), never re-derived here.
    """
    try:
        tx = apply_add_balance_adjustment(db, account_id, payload.target_balance)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(tx)
    from backend.query import reset_engine
    reset_engine()
    return {"transaction_id": tx.id, "amount": str(tx.amount)}


@app.delete("/accounts/{account_id}", dependencies=[Depends(require_api_key)])
def delete_account(
    account_id: int,
    reassign_to: int | None = None,
    db: Session = Depends(get_session),
):
    """Delete an account with reassign-then-delete (CASH-05, D-05/D-06).

    - No transactions → plain audited delete.
    - Has transactions and no reassign_to → 422 with affected_count (D-06); the
      exact detail shape the UI copy consumes.
    - reassign_to set → the transactions are reassigned to the target account and
      the source is deleted in ONE audited helper call (apply_delete_account
      writes the single AuditLog row capturing the reassignment target + count);
      the reassignment is NOT an inline bulk update here (WARNING 1 fix).

    The reassignment DECISION lives here; the reassignment WRITE lives in the
    audited helper (Open Question 2 — propose_delete_account stays block-only).
    """
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    before = {"id": acc.id, "name": acc.name, "type": acc.type, "currency": acc.currency}

    tx_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id = :aid"),
            {"aid": account_id},
        ).scalar()
        or 0
    )

    if tx_count > 0:
        if reassign_to is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"{tx_count} transactions use this account — reassign or delete them first",
                    "affected_count": tx_count,
                },
            )
        target = db.get(Account, reassign_to)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Reassign target account {reassign_to} not found")
        reassigned = apply_delete_account(db, account_id, before, reassign_to=reassign_to)
    else:
        reassigned = apply_delete_account(db, account_id, before)

    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted", "reassigned": reassigned}


# ---------------------------------------------------------------------------
# Platforms (D-12) — managed investment-platform entity, mirrors /accounts.
# GET is an open read; every write route requires the API key (T-05-02-AC).
# ---------------------------------------------------------------------------


@app.get("/platforms", response_model=list[PlatformOut])
def list_platforms(db: Session = Depends(get_session)):
    return db.query(Platform).order_by(Platform.name).all()


@app.post("/platforms", response_model=PlatformOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_platform(payload: PlatformCreate, db: Session = Depends(get_session)):
    """Create an investment platform (INV-01). Routed through apply_add_platform (audited)."""
    plat = apply_add_platform(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(plat)
    from backend.query import reset_engine
    reset_engine()
    return plat


@app.put("/platforms/{platform_id}", response_model=PlatformOut, dependencies=[Depends(require_api_key)])
def update_platform(platform_id: int, payload: PlatformUpdate, db: Session = Depends(get_session)):
    """Partial-update a platform (INV-01). Only supplied fields change."""
    plat = db.get(Platform, platform_id)
    if plat is None:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    before = {"id": plat.id, "name": plat.name, "kind": plat.kind}
    try:
        apply_edit_platform(db, platform_id, payload.model_dump(mode="json", exclude_none=True), before)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(plat)
    from backend.query import reset_engine
    reset_engine()
    return plat


@app.delete("/platforms/{platform_id}", dependencies=[Depends(require_api_key)])
def delete_platform(
    platform_id: int,
    reassign_to: int | None = None,
    db: Session = Depends(get_session),
):
    """Delete a platform with reassign-then-delete (INV-01, D-12).

    - No holdings → plain audited delete.
    - Has holdings and no reassign_to → 422 with affected_count; the exact
      detail shape the PlatformManager copy consumes (`detail.affected_count`).
    - reassign_to set → holdings are reassigned to the target platform and the
      source is deleted in ONE audited helper call (apply_delete_platform writes
      the single AuditLog row capturing the reassignment target + count).
    """
    plat = db.get(Platform, platform_id)
    if plat is None:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    before = {"id": plat.id, "name": plat.name, "kind": plat.kind}

    holdings_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM holdings WHERE platform_id = :pid"),
            {"pid": platform_id},
        ).scalar()
        or 0
    )

    if holdings_count > 0:
        if reassign_to is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"{holdings_count} holdings use this platform — reassign or delete them first",
                    "affected_count": holdings_count,
                },
            )
        target = db.get(Platform, reassign_to)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Reassign target platform {reassign_to} not found")
        reassigned = apply_delete_platform(db, platform_id, before, reassign_to=reassign_to)
    else:
        reassigned = apply_delete_platform(db, platform_id, before)

    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted", "reassigned": reassigned}


@app.get("/platforms/{platform_id}/detail")
def platform_detail(platform_id: int, db: Session = Depends(get_session)):
    """Scoped PnL detail for one platform (PLAT-01/D-05) — open read.

    Reuses portfolio.portfolio_summary(db)'s existing per-platform group dict
    (subtotal + holdings with realized_pnl/unrealized_pnl/current_value) — no
    new response_model, matching PortfolioSummary.groups[i]'s own Decimal-
    passthrough convention. Lazy price refresh mirrors investments_summary's
    idiom. Not registered in backend/tools.py TOOLS (D-05 — kept off the
    agent/MCP surface).
    """
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")
    from backend.prices import refresh_all_prices

    refresh_all_prices(db, force=False)  # only stale tickers (D-09), same idiom as investments_summary
    db.commit()
    summary = compose_portfolio_summary(db)
    group = next((g for g in summary["groups"] if g["platform_id"] == platform_id), None)
    return group or {
        "platform_id": platform_id, "platform_name": platform.name,
        "kind": platform.kind, "subtotal": 0, "holdings": [],
    }


# ---------------------------------------------------------------------------
# Investments (INV-01/06/07) — event ledger + direct holding override + summary.
# Every write route requires the API key (T-05-03-AC); GET /investments/summary
# is an open read composing holdings + price_cache + portfolio.py calculators.
# ---------------------------------------------------------------------------


@app.post("/portfolio-events", response_model=PortfolioEventOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_portfolio_event(payload: PortfolioEventCreate, db: Session = Depends(get_session)):
    """Log a buy/sell/dividend event (INV-07, D-01).

    event_type is validated to the {buy,sell,dividend} literal set at the schema
    boundary (422 on anything else) BEFORE apply_add_portfolio_event runs the
    recompute. The helper inserts the event, audits it, then recomputes the
    holding's qty/avg_cost from the full ledger.
    """
    try:
        ev = apply_add_portfolio_event(db, payload.model_dump(mode="json"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(ev)
    from backend.query import reset_engine
    reset_engine()
    return ev


@app.get("/portfolio-events", response_model=list[PortfolioEventOut])
def list_portfolio_events(platform_id: int, db: Session = Depends(get_session)):
    """One platform's buy/sell/dividend event ledger, date-desc (PLAT-01/D-05)
    — open read. Reuses PortfolioEventOut directly, no new DTO. Not
    registered in backend/tools.py TOOLS (D-05 — kept off the agent/MCP surface).
    """
    return (
        db.query(PortfolioEvent)
        .filter(PortfolioEvent.platform_id == platform_id)
        .order_by(desc(PortfolioEvent.date))
        .all()
    )


@app.post("/portfolio-events/funded-buy", status_code=201, dependencies=[Depends(require_api_key)])
def create_funded_buy(payload: FundedBuyCreate, db: Session = Depends(get_session)):
    """Direct (non-agent) funded 'buy' — cash leg + portfolio event (CHAT-09/XFER-03).

    Coerces quantity/price/cash_amount to float before calling apply_add_funded_buy
    (see LOAD-BEARING comment below) — apply_add_transaction/apply_add_portfolio_event
    write their `after` dict straight into AuditLog.after (JSONB), so a raw Decimal
    would break serialization even on this non-proposal REST path.
    """
    # LOAD-BEARING: coerce to float, not Decimal — apply_add_funded_buy builds an
    # inner after-dict that flows straight into AuditLog.after (JSONB); a raw
    # Decimal there raises TypeError on write (auditlog-decimal-json-gotcha).
    # float is JSON-serializable and still supports the primitive's own abs()/
    # negation, matching 14-02's propose_add_funded_buy convention exactly.
    after = {
        "source_account_name": payload.source_account_name, "platform_id": payload.platform_id,
        "ticker": payload.ticker, "quantity": float(payload.quantity), "price": float(payload.price),
        "cash_amount": float(payload.cash_amount), "cash_currency": payload.cash_currency,
        "event_currency": payload.event_currency, "date": payload.date,
        "notes": payload.notes, "asset_type": payload.asset_type,
    }
    try:
        result = apply_add_funded_buy(db, after)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(result["transaction"])
    db.refresh(result["portfolio_event"])
    from backend.query import reset_engine
    reset_engine()
    return {"transaction_id": result["transaction"].id, "portfolio_event_id": result["portfolio_event"].id}


@app.post("/portfolio-events/funded-sell", status_code=201, dependencies=[Depends(require_api_key)])
def create_funded_sell(payload: FundedSellCreate, db: Session = Depends(get_session)):
    """Direct (non-agent) funded 'sell' — cash leg + portfolio event (CHAT-09/XFER-03)."""
    # LOAD-BEARING: float, not Decimal — see create_funded_buy's comment above.
    after = {
        "source_account_name": payload.source_account_name, "platform_id": payload.platform_id,
        "ticker": payload.ticker, "quantity": float(payload.quantity), "price": float(payload.price),
        "cash_amount": float(payload.cash_amount), "cash_currency": payload.cash_currency,
        "event_currency": payload.event_currency, "date": payload.date,
        "notes": payload.notes, "asset_type": payload.asset_type,
    }
    try:
        result = apply_add_funded_sell(db, after)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(result["transaction"])
    db.refresh(result["portfolio_event"])
    from backend.query import reset_engine
    reset_engine()
    return {"transaction_id": result["transaction"].id, "portfolio_event_id": result["portfolio_event"].id}


@app.post("/holdings", response_model=HoldingOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_holding(payload: HoldingCreate, db: Session = Depends(get_session)):
    """Direct holding override — seed a position without an event history (D-03).

    Position identity is (ticker, platform_id) (Quick 260711-rb2): the same
    ticker on two different platforms is two valid rows; a duplicate
    (ticker, platform_id) violates the composite unique constraint.
    """
    try:
        holding = apply_add_holding(db, payload.model_dump(mode="json"))
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"'{payload.ticker}' already exists on that platform.",
        )
    db.refresh(holding)
    from backend.query import reset_engine
    reset_engine()
    return holding


@app.put("/holdings/{holding_id}", response_model=HoldingOut, dependencies=[Depends(require_api_key)])
def update_holding(holding_id: int, payload: HoldingUpdate, db: Session = Depends(get_session)):
    """Direct holding override — partial-update a holding (D-03). Audited."""
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail=f"Holding {holding_id} not found")
    before = {
        "id": holding.id, "ticker": holding.ticker,
        "quantity": str(holding.quantity), "avg_cost": str(holding.avg_cost),
        "asset_type": holding.asset_type, "platform_id": holding.platform_id,
    }
    try:
        apply_edit_holding(db, holding_id, payload.model_dump(mode="json", exclude_none=True), before)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError:
        # IN-01: renaming ticker onto an existing (ticker, platform_id) violates
        # the composite unique constraint — 422, not an unhandled 500.
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"'{payload.ticker or holding.ticker}' already exists on that platform.",
        )
    db.refresh(holding)
    from backend.query import reset_engine
    reset_engine()
    return holding


@app.delete("/holdings/{holding_id}", dependencies=[Depends(require_api_key)])
def delete_holding(holding_id: int, db: Session = Depends(get_session)):
    """Direct holding override — delete a holding (D-03). Audited."""
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail=f"Holding {holding_id} not found")
    before = {
        "id": holding.id, "ticker": holding.ticker,
        "quantity": str(holding.quantity), "avg_cost": str(holding.avg_cost),
    }
    apply_delete_holding(db, holding_id, before)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted"}


@app.get("/investments/summary", response_model=PortfolioSummary)
def investments_summary(db: Session = Depends(get_session)):
    """Composed portfolio payload (D-05, INV-06) — open read.

    Reads every holding, joins the latest price_cache price per ticker, and
    hands them to portfolio.py's pure calculators: platform-grouped holdings
    with per-holding unrealized/realized P&L, totals, and an 'as of' timestamp.
    A ticker with no price_cache row → null current price + null unrealized for
    that holding. Lazy refresh (D-09): stale tickers are refreshed server-side on
    load (force=False), so the summary reflects reasonably fresh prices without a
    manual button click. Per-ticker failures are swallowed inside refresh_all_prices.
    """
    from backend.prices import refresh_all_prices

    refresh_all_prices(db, force=False)  # only stale tickers (D-09)
    db.commit()
    return compose_portfolio_summary(db)


@app.get("/investments/history", response_model=ValueHistoryResponse)
def investments_history(range: str = "All", db: Session = Depends(get_session)):
    """Daily portfolio value + P&L series (VZ-02, INVX-01) — open read.

    Reads the already-populated portfolio_value_history (D-13/D-14); makes NO
    fx.get_rate call. range accepts 1M/3M/6M/All; an unrecognized token maps
    to 422 (V4/V5). No-backfill (D-13): a fresh collector returns an empty
    series, not an error.
    """
    try:
        points = value_history_series(db, range)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"points": points}


@app.post("/prices/refresh", dependencies=[Depends(require_api_key)])
def refresh_prices(db: Session = Depends(get_session)):
    """Force-fetch every ticker's live price (INV-02/03, D-09).

    Calls refresh_all_prices(force=True); per-ticker failures are swallowed
    inside (adapters return None, never raise — Pitfall 2) so one failing/slow
    source never 500s the endpoint. Returns {refreshed, skipped, failed} counts.
    """
    from backend.prices import refresh_all_prices
    from backend.query import reset_engine

    counts = refresh_all_prices(db, force=True)
    db.commit()
    reset_engine()
    return counts


@app.post("/prices/override", dependencies=[Depends(require_api_key)])
def override_price(payload: PriceOverrideRequest, db: Session = Depends(get_session)):
    """Manually set a ticker's price (INV-04, D-11). Positive-price validated at
    the schema boundary (422); writes price_cache source='manual', audited."""
    try:
        apply_set_price(db, payload.ticker, payload.price)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "ok", "ticker": payload.ticker}


# Categories tagged on is_transfer=True rows that are NOT real liquid<->liquid
# transfer-pair legs — writes.py's apply_add_balance_adjustment (category=
# 'Adjustment') and apply_add_funded_buy/_sell (category='Investment'). These
# rows have transfer_pair_id=None, same as an untagged is_transfer row, so the
# category is the only signal that distinguishes "known bookkeeping tag,
# surface it under expense/income by sign" from "unclassified is_transfer
# row, keep it out of both expense/income buckets until it's better understood"
# (17-UI-SPEC Component 2 locked semantics + RESEARCH Pitfall 5).
_NON_PAIR_TRANSFER_CATEGORIES = ("Adjustment", "Investment")


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    q: str | None = None,
    account_id: int | None = None,
    category: str | None = None,
    type: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    include_transfers: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    """Filtered, paged transaction ledger (D-01/D-02, REC-01/02/05) — open read.

    Every param is one parameterized `.filter()` — never string-built SQL
    (T-17-04). `category` resolves a parent/group name to its node + all
    descendants via tools.py's hierarchy helpers (Pitfall 3), falling back to
    an exact-string match when no node resolves. `type=transfer` keys off
    `transfer_pair_id IS NOT NULL`, NOT `is_transfer` (17-UI-SPEC Component 2,
    critical item #4) — a real transfer-pair leg. `type=expense`/`income` gate
    on sign + `transfer_pair_id IS NULL`, additionally excluding an
    unclassified is_transfer row that isn't one of the known Adjustment/
    Investment bookkeeping categories (see _NON_PAIR_TRANSFER_CATEGORIES).
    Still queries the base `transactions` table, NOT `cashflow_transactions`
    (a full ledger must include investment-account rows). Hard-capped at 500
    rows regardless of the requested `limit` (Pitfall 4) — the Records page
    pages via `offset`. Open read (no require_api_key), matching the
    unmodified endpoint's existing convention.
    """
    query = db.query(Transaction)
    if q:
        query = query.filter(
            or_(Transaction.merchant.ilike(f"%{q}%"), Transaction.notes.ilike(f"%{q}%"))
        )
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    if category is not None:
        node = _find_category_node(category)
        if node is not None:
            query = query.filter(Transaction.category_id.in_(_descendant_ids(node)))
        else:
            query = query.filter(Transaction.category == category)  # fallback exact match
    if type == "expense":
        query = query.filter(
            Transaction.amount < 0,
            Transaction.transfer_pair_id.is_(None),
            or_(Transaction.is_transfer.is_(False), Transaction.category.in_(_NON_PAIR_TRANSFER_CATEGORIES)),
        )
    elif type == "income":
        query = query.filter(
            Transaction.amount > 0,
            Transaction.transfer_pair_id.is_(None),
            or_(Transaction.is_transfer.is_(False), Transaction.category.in_(_NON_PAIR_TRANSFER_CATEGORIES)),
        )
    elif type == "transfer":
        query = query.filter(Transaction.transfer_pair_id.isnot(None))  # LOCKED: pair-id, not is_transfer (Pitfall 5)
    elif not include_transfers:
        query = query.filter(Transaction.is_transfer == False)
    if amount_min is not None:
        query = query.filter(func.abs(Transaction.amount) >= amount_min)
    if amount_max is not None:
        query = query.filter(func.abs(Transaction.amount) <= amount_max)
    if date_from:
        query = query.filter(Transaction.date >= datetime.fromisoformat(date_from))
    if date_to:
        # date_to is an inclusive calendar day from the caller's POV — widen
        # to an exclusive upper bound so a same-day timestamp isn't dropped
        # (mirrors resolve_period's [start, end) convention).
        end = datetime.fromisoformat(date_to) + timedelta(days=1)
        query = query.filter(Transaction.date < end)
    return (
        query.order_by(desc(Transaction.date))
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )


def _category_rollup(db: Session, rows: list, children: dict) -> list[dict]:
    """Join id/color/icon onto spending_by_category's name-keyed rows+children
    (11-04) to build the CategoryRollup shape (CAT-04). Root names are unique
    (top_name is always a root, per _ROLLUP_FROM's COALESCE), so descendants
    are collected per-root to avoid cross-root name collisions; color falls
    back to the nearest ancestor's when NULL (D-14), same rule as GET /categories.
    """
    cats = db.execute(
        text("SELECT id, name, parent_id, color, icon FROM categories")
    ).fetchall()
    by_id = {r[0]: {"id": r[0], "name": r[1], "parent_id": r[2], "color": r[3], "icon": r[4]} for r in cats}
    children_of: dict[int | None, list[dict]] = {}
    for node in by_id.values():
        children_of.setdefault(node["parent_id"], []).append(node)
    roots_by_name = {n["name"]: n for n in by_id.values() if n["parent_id"] is None}

    def _effective_color(node: dict) -> str | None:
        if node["color"] is not None or node["parent_id"] is None:
            return node["color"]
        return _effective_color(by_id[node["parent_id"]])

    def _descendants(node_id: int, acc: dict[str, dict]) -> None:
        for child in children_of.get(node_id, []):
            acc[child["name"]] = child
            _descendants(child["id"], acc)

    result = []
    for top_name, total in rows:
        root = roots_by_name.get(top_name)
        if root is None:
            continue
        descendants: dict[str, dict] = {}
        _descendants(root["id"], descendants)
        kids = []
        for sub_name, sub_total in children.get(top_name, []):
            node = descendants.get(sub_name)
            if node is None:
                continue
            kids.append({
                "id": node["id"], "name": node["name"],
                "color": _effective_color(node), "icon": node["icon"], "total": sub_total,
            })
        result.append({
            "id": root["id"], "name": root["name"], "color": root["color"],
            "icon": root["icon"], "total": total, "children": kids,
        })
    return result


@app.get("/cashflow/summary", response_model=CashflowSummary)
def cashflow_summary(
    period: str = "this_month",
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_session),
):
    """Single aggregate dashboard payload (D-08, CASH-01/02/03).

    Resolves the period exactly once and composes existing tools.py
    aggregations + account_balances/monthly_trend (Plan 02). trend always
    covers >=6 months regardless of the selected period (Pitfall 4). This is
    an open read (no require_api_key), matching existing GET reads.
    """
    try:
        s, e = resolve_period(period, start_date, end_date)
    except ValueError as exc:
        # Same mapping as the sibling write endpoints (update_account, etc.):
        # an unrecognized/malformed period is a client error, never a raw 500.
        # Named `exc` (not `e`) so it can't shadow the end-bound `e` above.
        raise HTTPException(status_code=422, detail=str(exc))
    totals = {
        "income": income_total(period, start_date, end_date)["total"],
        "expense": spending_total(period, start_date, end_date)["total"],
        "net": net_total(period, start_date, end_date)["net"],
    }
    by_cat_result = spending_by_category(period, start_date, end_date, limit=10)
    by_category = _category_rollup(db, by_cat_result["rows"], by_cat_result["children"])
    accounts = account_balances(s, e)["rows"]
    trend = monthly_trend(6)["rows"]
    return CashflowSummary(totals=totals, by_category=by_category, accounts=accounts, trend=trend)


@app.get("/net-worth", response_model=NetWorth)
def net_worth_endpoint(db: Session = Depends(get_session)):
    """Composed net-worth payload (D-01/D-02/D-05, NW-01/NW-02) — open read.

    liquid side = account_balances() filtered to type='liquid'; investment
    side = portfolio_summary(db).total_value. The coverage-assertion
    ValueError (schema invariant violated — accounts left unclassified) maps
    to 422, never a raw 500 (T-14-07 precedent).
    """
    try:
        result = net_worth(db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return NetWorth(**result)


@app.post("/transactions", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    acc = _get_or_create_account(db, payload.account, payload.currency)
    tx = Transaction(
        date=payload.date,
        amount=payload.amount,
        currency=payload.currency,
        category=payload.category,
        raw_category=payload.category,
        category_id=resolve_category_id(db, payload.category),  # D-08 dual-write
        merchant=payload.merchant,
        notes=payload.notes,
        account_id=acc.id,
        is_transfer=payload.is_transfer,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    # New data — invalidate the cached query engine (currency/date context)
    from backend.query import reset_engine
    reset_engine()
    return tx


@app.put("/transactions/{tx_id}", response_model=TransactionOut, dependencies=[Depends(require_api_key)])
def update_transaction(tx_id: int, payload: TransactionUpdate, db: Session = Depends(get_session)):
    """Partial-update a transaction (CASH-04). Only supplied fields change."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    before = {
        "id": tx.id,
        "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": tx.category,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "account_id": tx.account_id,
        "is_transfer": tx.is_transfer,
    }
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


@app.delete("/transactions/{tx_id}", dependencies=[Depends(require_api_key)])
def delete_transaction(tx_id: int, db: Session = Depends(get_session)):
    """Delete a transaction (CASH-04)."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    before = {
        "id": tx.id,
        "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": tx.category,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "account_id": tx.account_id,
        "is_transfer": tx.is_transfer,
    }
    deleted_ids = apply_delete_transaction_or_pair(db, tx_id, before)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted", "deleted_ids": deleted_ids}


_BULK_ACTION_MAX_IDS = 500  # blast-radius cap (T-17-06), mirrors GET /transactions' row cap


def _tx_before_dict(tx: Transaction) -> dict:
    """AuditLog `before` snapshot — same shape update_transaction/delete_transaction
    build inline, with the LOAD-BEARING str(tx.amount) (auditlog-decimal-json-gotcha)."""
    return {
        "id": tx.id,
        "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": tx.category,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "account_id": tx.account_id,
        "is_transfer": tx.is_transfer,
    }


@app.post(
    "/transactions/bulk-delete",
    response_model=BulkActionResponse,
    dependencies=[Depends(require_api_key)],
)
def bulk_delete_transactions(payload: BulkDeleteRequest, db: Session = Depends(get_session)):
    """Atomically delete every listed transaction id (D-03/REC-03).

    Reuses apply_delete_transaction_or_pair (the same pair-aware primitive the
    single DELETE endpoint above already uses) — when a listed id is one leg
    of a transfer, its sibling is looked up and deleted too even though it
    was NOT in `ids` (D-04, critical item #1), no orphan leg. A bad/nonexistent
    id is reported in skipped[] with a reason, never a 500 (T-17-05). One
    db.commit() for the whole batch; one AuditLog delete row per entity
    (written inside the primitive). ids over the 500 cap are rejected before
    any mutation (T-17-06).
    """
    if len(payload.ids) > _BULK_ACTION_MAX_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot bulk-delete more than {_BULK_ACTION_MAX_IDS} transactions at once",
        )
    deleted: list[int] = []
    skipped: list[dict] = []
    for tx_id in payload.ids:
        if tx_id in deleted:
            continue  # already removed as the sibling leg of an earlier id in this batch
        tx = db.get(Transaction, tx_id)
        if tx is None:
            skipped.append({"id": tx_id, "reason": "not found"})
            continue
        deleted.extend(apply_delete_transaction_or_pair(db, tx_id, _tx_before_dict(tx)))
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return BulkActionResponse(deleted=deleted, skipped=skipped)


@app.post(
    "/transactions/bulk-recategorize",
    response_model=BulkActionResponse,
    dependencies=[Depends(require_api_key)],
)
def bulk_recategorize_transactions(payload: BulkRecategorizeRequest, db: Session = Depends(get_session)):
    """Atomically recategorize every listed non-transfer transaction id (D-03/REC-03).

    A transfer leg (tx.is_transfer) is SKIPPED — reported in skipped[] with a
    reason, category left unchanged, never raised on (D-03, critical item #6):
    transfers are system-categorized. One db.commit() for the whole batch;
    one AuditLog edit row per recategorized entity (written inside
    apply_edit_transaction). ids over the 500 cap are rejected before any
    mutation (T-17-06).
    """
    if len(payload.ids) > _BULK_ACTION_MAX_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot bulk-recategorize more than {_BULK_ACTION_MAX_IDS} transactions at once",
        )
    recategorized: list[int] = []
    skipped: list[dict] = []
    for tx_id in payload.ids:
        tx = db.get(Transaction, tx_id)
        if tx is None:
            skipped.append({"id": tx_id, "reason": "not found"})
            continue
        if tx.is_transfer:
            skipped.append({"id": tx_id, "reason": "transfer leg — system-categorized"})
            continue
        apply_edit_transaction(db, tx_id, {"category": payload.category}, _tx_before_dict(tx), allow_paired=False)
        recategorized.append(tx_id)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return BulkActionResponse(recategorized=recategorized, skipped=skipped)


@app.post("/transactions/transfer", status_code=201, dependencies=[Depends(require_api_key)])
def create_transfer(payload: TransferCreate, db: Session = Depends(get_session)):
    """Direct (non-agent) liquid<->liquid transfer (CHAT-09/XFER-01).

    Routes through apply_add_transfer — a confirm-free write path parallel to
    the chat proposal flow, gated by require_api_key instead of a token.
    """
    leg_a_after = {
        "account": payload.from_account, "amount": str(-abs(payload.amount)),
        "currency": payload.currency, "date": payload.date, "notes": payload.notes,
    }
    leg_b_after = {
        "account": payload.to_account, "amount": str(abs(payload.amount)),
        "currency": payload.currency, "date": payload.date, "notes": payload.notes,
    }
    try:
        leg_a, leg_b = apply_add_transfer(db, leg_a_after, leg_b_after)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(leg_a)
    db.refresh(leg_b)
    from backend.query import reset_engine
    reset_engine()
    return {"leg_a_id": leg_a.id, "leg_b_id": leg_b.id, "transfer_pair_id": leg_a.transfer_pair_id}


@app.post("/transactions/investment-transfer", status_code=201, dependencies=[Depends(require_api_key)])
def create_investment_transfer(payload: InvestmentTransferCreate, db: Session = Depends(get_session)):
    """Direct (non-agent) liquid->investment funding transfer (CHAT-09/XFER-02).

    Cash leg debits the liquid source account; the investment side is a
    'deposit' PortfolioEvent using the documented CASH sentinel (ticker=CASH,
    asset_type=cash, price=1, quantity=amount — matches the existing
    asset_type=='cash' 1:1 valuation convention).
    """
    cash_leg = {
        "account": payload.from_account, "amount": str(-abs(payload.amount)),
        "currency": payload.currency, "date": payload.date, "notes": payload.notes,
    }
    event = {
        "ticker": "CASH", "event_type": "deposit", "quantity": str(abs(payload.amount)),
        "price": "1", "platform_id": payload.platform_id, "currency": payload.currency,
        "date": payload.date, "asset_type": "cash",
    }
    try:
        tx, ev = apply_add_investment_transfer(db, cash_leg, event)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(tx)
    db.refresh(ev)
    from backend.query import reset_engine
    reset_engine()
    return {"transaction_id": tx.id, "portfolio_event_id": ev.id}


@app.get("/categories", response_model=list[CategoryNode])
def list_categories(kind: str | None = None, db: Session = Depends(get_session)):
    """Category tree (open read, CAT-01): per-node tx_count is the node's
    OWN direct transaction count only (NOT summed into ancestors — that
    rollup lives in tools.py's spending_by_category for the chat/cashflow
    aggregates, not here); `color` is the row's own value, `effective_color`
    inherits the nearest ancestor's when NULL (D-14). Optional ?kind=
    filters ROOT categories by kind (D-03)."""
    rows = db.execute(
        text("SELECT id, name, parent_id, kind, color, icon, is_system FROM categories ORDER BY name")
    ).fetchall()
    counts = dict(
        db.execute(
            text(
                "SELECT category_id, COUNT(*) FROM transactions "
                "WHERE category_id IS NOT NULL GROUP BY category_id"
            )
        ).fetchall()
    )
    nodes = {
        r[0]: {
            "id": r[0], "name": r[1], "parent_id": r[2], "kind": r[3],
            "color": r[4], "effective_color": r[4], "icon": r[5], "is_system": r[6],
            "tx_count": counts.get(r[0], 0), "children": [],
        }
        for r in rows
    }
    roots: list[dict] = []
    for r in rows:
        (roots if r[2] is None else nodes[r[2]]["children"]).append(nodes[r[0]])

    def _inherit(node: dict, color: str | None) -> None:
        if node["effective_color"] is None:
            node["effective_color"] = color
        for child in node["children"]:
            _inherit(child, node["effective_color"])

    for root in roots:
        _inherit(root, None)

    if kind:
        roots = [r for r in roots if r["kind"] == kind]
    return roots


@app.post("/categories", status_code=201, dependencies=[Depends(require_api_key)])
def create_category(payload: CategoryCreate, db: Session = Depends(get_session)):
    """Create a category (CAT-01). Depth cap + kind/color inheritance
    enforced in apply_add_category; violations surface as 422."""
    try:
        cat = apply_add_category(db, payload.model_dump(mode="json"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(cat)
    from backend.query import reset_engine
    reset_engine()
    return {
        "id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "kind": cat.kind,
        "color": cat.color, "icon": cat.icon, "is_system": cat.is_system,
    }


@app.put("/categories/{category_id}", dependencies=[Depends(require_api_key)])
def update_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_session)):
    """Partial-update a category (CAT-01). System rows only allow color/icon
    changes; re-parenting re-checks the depth cap for the node's subtree
    (apply_edit_category). exclude_unset (not exclude_none) so an explicit
    parent_id is distinguishable from "not provided"."""
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    before = {
        "id": cat.id, "name": cat.name, "parent_id": cat.parent_id,
        "kind": cat.kind, "color": cat.color, "icon": cat.icon,
    }
    try:
        apply_edit_category(db, category_id, payload.model_dump(mode="json", exclude_unset=True), before)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(cat)
    from backend.query import reset_engine
    reset_engine()
    return {
        "id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "kind": cat.kind,
        "color": cat.color, "icon": cat.icon, "is_system": cat.is_system,
    }


@app.delete("/categories/{category_id}", dependencies=[Depends(require_api_key)])
def delete_category(category_id: int, reassign_to: int | None = None, db: Session = Depends(get_session)):
    """Delete a category with reassign-then-delete (CAT-02, Pitfall 3).

    - System row (Transfer/Uncategorized) -> 422 always (D-04).
    - Has subcategories -> 422 always, WITH child_count alongside
      affected_count: reassign_to only ever moves TRANSACTIONS, never
      subcategories, so a category with children can never be deleted via
      this endpoint (merge/re-parent the children first).
    - Leaf with transactions and no reassign_to -> 422 with affected_count.
    - reassign_to set -> transactions reassigned + source deleted in ONE
      audited helper call (apply_delete_category), mirroring
      apply_delete_account (WARNING 1 fix carried over from accounts).
    """
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    if cat.is_system:
        raise HTTPException(status_code=422, detail="System categories (Transfer/Uncategorized) cannot be deleted")
    before = {
        "id": cat.id, "name": cat.name, "parent_id": cat.parent_id,
        "kind": cat.kind, "color": cat.color, "icon": cat.icon,
    }

    tx_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE category_id = :cid"), {"cid": category_id}
        ).scalar() or 0
    )
    child_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM categories WHERE parent_id = :cid"), {"cid": category_id}
        ).scalar() or 0
    )

    if child_count > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"{child_count} subcategories use this category — remove or re-parent them first",
                "affected_count": tx_count,
                "child_count": child_count,
            },
        )

    if tx_count > 0:
        if reassign_to is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"{tx_count} transactions use this category — reassign or delete them first",
                    "affected_count": tx_count,
                },
            )
        target = db.get(Category, reassign_to)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Reassign target category {reassign_to} not found")

    try:
        reassigned = apply_delete_category(db, category_id, before, reassign_to=reassign_to)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted", "reassigned": reassigned}


@app.get("/categories/{name}/affected-count", response_model=AffectedCountResponse)
def category_affected_count(name: str, db: Session = Depends(get_session)):
    """Count of transactions in a category AND its descendants (open read,
    D-09). Unknown name -> 0 (matches the pre-hierarchy endpoint's behavior
    of never 404ing on a read)."""
    row = db.execute(text("SELECT id FROM categories WHERE name = :name LIMIT 1"), {"name": name}).first()
    if row is None:
        return AffectedCountResponse(category=name, affected_count=0)
    count = int(
        db.execute(
            text(
                "WITH RECURSIVE descendants AS ("
                "  SELECT id FROM categories WHERE id = :cat_id"
                "  UNION ALL"
                "  SELECT c.id FROM categories c JOIN descendants d ON c.parent_id = d.id"
                ") SELECT COUNT(*) FROM transactions WHERE category_id IN (SELECT id FROM descendants)"
            ),
            {"cat_id": row[0]},
        ).scalar()
        or 0
    )
    return AffectedCountResponse(category=name, affected_count=count)


@app.post("/categories/rename", dependencies=[Depends(require_api_key)])
def rename_category(req: CategoryRenameRequest, db: Session = Depends(get_session)):
    """Rename a category (single-row UPDATE, D-11); ValueError (ambiguous
    name, missing name, system row, or name collision) -> 422."""
    try:
        count = apply_rename_category(db, req.old_name, req.new_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"old_name": req.old_name, "new_name": req.new_name, "affected_count": count}


@app.post("/categories/merge", dependencies=[Depends(require_api_key)])
def merge_category(req: CategoryMergeRequest, db: Session = Depends(get_session)):
    """Merge one category into another (D-11); ValueError (ambiguous/missing
    name, system row, or source has children) -> 422."""
    try:
        count = apply_merge_category(db, req.from_name, req.into_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"from_name": req.from_name, "into_name": req.into_name, "affected_count": count}


@app.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_session)):
    """Effective settings (DB overrides env defaults). Public — keys masked (UI-03)."""
    return get_effective_settings(db)


@app.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_api_key)])
def write_settings(patch: SettingsUpdate, db: Session = Depends(get_session)):
    """Partial-update settings (auth-protected). Blank/absent key fields keep the
    existing stored value (UI-03, UI-04). Re-runs configure_llm() + reset_engine()
    when an LLM-relevant field changed, so the next chat request uses it."""
    # Defer the settings commit so it lands in the same transaction as the
    # audit row below — a crash between the two must not leave a persisted
    # settings change with no audit trail.
    changed_llm = upsert_settings(db, patch.model_dump(exclude_none=True), commit=False)

    # Audit trail: masked-only, never the raw key values (T-03-14). A blank
    # key field means "keep existing" (upsert skips it), so omit it from the
    # audit rather than record a misleading mask_key("") -> null.
    audit_after = patch.model_dump(exclude_none=True)
    for key_field in (KEY_ANTHROPIC_API_KEY, KEY_OPENAI_API_KEY):
        if audit_after.get(key_field):
            audit_after[key_field] = mask_key(audit_after[key_field])
        else:
            audit_after.pop(key_field, None)
    db.add(AuditLog(entity="settings", entity_id=None, operation="update",
                    before=None, after=audit_after))
    db.commit()

    if changed_llm:
        from backend.config import configure_llm
        from backend.query import reset_engine
        configure_llm(overrides=get_effective_settings(db, raw_keys=True))
        reset_engine()

    return get_effective_settings(db)


@app.post("/import", response_model=ImportResponse, dependencies=[Depends(require_api_key)])
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_session)):
    raw = await file.read()
    try:
        text_content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text")
    try:
        parsed, inserted, skipped, currency = import_csv_text(db, text_content)
    except ValueError as e:
        raise HTTPException(422, str(e))
    from backend.query import reset_engine
    reset_engine()
    return ImportResponse(parsed=parsed, inserted=inserted, skipped=skipped, currency=currency)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from backend.query import ask
    try:
        answer = ask(req.question)
    except Exception as e:
        raise HTTPException(500, f"Query failed: {e}")
    return QueryResponse(question=req.question, answer=answer)


@app.post("/query-stream")
async def query_stream(req: QueryRequest):
    """Stream agent reasoning as SSE events (CHAT-01, D-08)."""
    from backend.query import agent_stream
    return StreamingResponse(
        agent_stream(req.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Proposal executor — applies payload rows atomically and writes audit_log
# ---------------------------------------------------------------------------

def _execute_proposal_payload(db: Session, proposal: Proposal) -> None:
    """Apply all operations in a proposal's payload to the target tables.

    Writes one AuditLog row per affected row. Called inside the confirm
    endpoint's single db.commit() — never commits independently (CHAT-06).
    All SQL is parameterized (correctness-by-construction mandate).
    """
    payload = proposal.payload
    operation = payload.get("operation", "")
    rows = payload.get("rows", [])

    for row in rows:
        before = row.get("before")
        after = row.get("after")

        if operation == "add_transaction":
            apply_add_transaction(db, after)

        elif operation == "edit_transaction":
            apply_edit_transaction(db, row.get("id"), after, before)

        elif operation == "delete_transaction":
            apply_delete_transaction_or_pair(db, row.get("id"), before)

        elif operation == "add_account":
            apply_add_account(db, after)

        elif operation == "edit_account":
            apply_edit_account(db, row.get("id"), after, before)

        elif operation == "delete_account":
            apply_delete_account(db, row.get("id"), before)

        elif operation == "rename_category":
            apply_rename_category(db, row.get("old_name"), row.get("new_name"))

        elif operation == "merge_category":
            apply_merge_category(db, row.get("from_name"), row.get("into_name"))

        elif operation == "add_holding":
            apply_add_holding(db, after)

        elif operation == "edit_holding":
            apply_edit_holding(db, row.get("id"), after, before)

        elif operation == "delete_holding":
            h_id = row.get("id")
            h = db.get(Holding, h_id)
            if h is not None:
                db.delete(h)
            db.add(AuditLog(entity="holding", entity_id=h_id, operation="delete",
                            before=before, after=None))

        elif operation in (
            "add_transfer", "add_investment_transfer", "add_funded_buy",
            "add_funded_sell", "add_balance_adjustment",
        ):
            # Malformed/mismatched payload keys must surface as a clean 422,
            # never an unhandled KeyError -> 500 (Pitfall 3, autonomous
            # decision 4) — the confirm endpoint already maps ValueError to 422.
            try:
                if operation == "add_transfer":
                    apply_add_transfer(db, after["leg_a"], after["leg_b"])

                elif operation == "add_investment_transfer":
                    apply_add_investment_transfer(db, after["cash_leg"], after["event"])

                elif operation == "add_funded_buy":
                    apply_add_funded_buy(db, after)

                elif operation == "add_funded_sell":
                    apply_add_funded_sell(db, after)

                elif operation == "add_balance_adjustment":
                    apply_add_balance_adjustment(db, row["account_id"], row["target_balance"])
            except (KeyError, TypeError) as e:
                raise ValueError(f"malformed payload for {operation!r}: {e}")

        else:
            raise ValueError(f"Unknown proposal operation: {operation!r}")


# ---------------------------------------------------------------------------
# Proposal endpoints
# ---------------------------------------------------------------------------

@app.get("/proposals", response_model=list[ProposalOut])
def list_proposals(status: str = "pending", db: Session = Depends(get_session)):
    """List proposals by status. Public endpoint — token is never serialized."""
    return db.query(Proposal).filter(Proposal.status == status).order_by(
        desc(Proposal.created_at)
    ).all()


@app.post(
    "/proposals/{proposal_id}/confirm",
    response_model=ProposalOut,
    dependencies=[Depends(require_api_key)],
)
def confirm_proposal(
    proposal_id: uuid.UUID,
    req: ConfirmRequest,
    db: Session = Depends(get_session),
):
    """Apply a pending proposal atomically. Requires API key + valid token.

    Check order (Pitfall 3 — prevents replay):
      1. Load by id → 404 if missing
      2. status == "pending" → 409 if not pending
      3. expires_at > now() → 410 if expired
      4. hmac.compare_digest(token) → 401 if wrong
      5. Execute payload + write audit_log rows + mark confirmed (single commit)
    """
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}")
    if datetime.now(timezone.utc) > proposal.expires_at:
        raise HTTPException(status_code=410, detail="Proposal expired — ask again to redo this")
    if not hmac.compare_digest(req.token, proposal.token):
        raise HTTPException(status_code=401, detail="Invalid confirmation token")

    try:
        _execute_proposal_payload(db, proposal)
        proposal.status = "confirmed"
        proposal.confirmed_at = datetime.now(timezone.utc)
        db.commit()
    except ValueError as e:
        # IN-02: delegated apply_* helpers raise ValueError for domain errors
        # (currency mismatch, "Holding not found", bad range) — map to 422 like
        # every direct REST write endpoint, not a generic 500.
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Conflicts with an existing record: {e.orig}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Write failed: {e}")

    from backend.query import reset_engine
    reset_engine()
    return proposal


@app.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalOut,
    dependencies=[Depends(require_api_key)],
)
def reject_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    """Reject a pending proposal. No target mutation; no audit row.
    Requires API key.
    """
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}")
    proposal.status = "rejected"
    db.commit()
    return proposal
