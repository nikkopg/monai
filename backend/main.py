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
    GET  /categories            distinct category names (public)
    GET  /categories/{name}/affected-count  count of transactions in a category (public)
    POST /categories/rename     rename a category across all transactions (requires API key)
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
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.db import get_session
from backend.importer import _get_or_create_account, import_csv_text
from backend.models import Account, AuditLog, Holding, Proposal, Transaction
from backend.writes import (
    apply_add_account,
    apply_add_transaction,
    apply_delete_account,
    apply_delete_transaction,
    apply_edit_account,
    apply_edit_transaction,
    apply_merge_category,
    apply_rename_category,
)
from backend.schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    AffectedCountResponse,
    CashflowSummary,
    CategoryMergeRequest,
    CategoryRenameRequest,
    ConfirmRequest,
    ImportResponse,
    ProposalOut,
    QueryRequest,
    QueryResponse,
    SettingsOut,
    SettingsUpdate,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
)
from backend.tools import (
    account_balances,
    income_total,
    monthly_trend,
    net_total,
    resolve_period,
    spending_by_category,
    spending_total,
)
from backend.settings import (
    KEY_ANTHROPIC_API_KEY,
    KEY_OPENAI_API_KEY,
    get_effective_settings,
    mask_key,
    upsert_settings,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="monai", version="0.1.0")

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


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(limit: int = 50, db: Session = Depends(get_session)):
    return (
        db.query(Transaction)
        .order_by(desc(Transaction.date))
        .limit(min(limit, 500))
        .all()
    )


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
    s, e = resolve_period(period, start_date, end_date)
    totals = {
        "income": income_total(period, start_date, end_date)["total"],
        "expense": spending_total(period, start_date, end_date)["total"],
        "net": net_total(period, start_date, end_date)["net"],
    }
    by_category = spending_by_category(period, start_date, end_date, limit=10)["rows"]
    accounts = account_balances(s, e)["rows"]
    trend = monthly_trend(6)["rows"]
    return CashflowSummary(totals=totals, by_category=by_category, accounts=accounts, trend=trend)


@app.post("/transactions", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    acc = _get_or_create_account(db, payload.account, payload.currency)
    tx = Transaction(
        date=payload.date,
        amount=payload.amount,
        currency=payload.currency,
        category=payload.category,
        raw_category=payload.category,
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
    apply_delete_transaction(db, tx_id, before)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"status": "deleted"}


@app.get("/categories")
def list_category_names(db: Session = Depends(get_session)):
    """Distinct category names across all transactions (open read).

    The deterministic enumeration source Plan 05's CategoryManager consumes
    (WARNING 2 fix) — reuses the same parameterized-SQL approach as
    list_categories() in tools.py rather than hand-building SQL here.
    """
    sql = "SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL ORDER BY category"
    rows = db.execute(text(sql)).fetchall()
    return {"categories": [r[0] for r in rows]}


@app.get("/categories/{name}/affected-count", response_model=AffectedCountResponse)
def category_affected_count(name: str, db: Session = Depends(get_session)):
    """Count of transactions currently in the given category (open read, D-09)."""
    count = int(
        db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE category = :cat"), {"cat": name}
        ).scalar()
        or 0
    )
    return AffectedCountResponse(category=name, affected_count=count)


@app.post("/categories/rename", dependencies=[Depends(require_api_key)])
def rename_category(req: CategoryRenameRequest, db: Session = Depends(get_session)):
    """Rename a category across all matching transactions (CASH-06)."""
    count = apply_rename_category(db, req.old_name, req.new_name)
    db.commit()
    from backend.query import reset_engine
    reset_engine()
    return {"old_name": req.old_name, "new_name": req.new_name, "affected_count": count}


@app.post("/categories/merge", dependencies=[Depends(require_api_key)])
def merge_category(req: CategoryMergeRequest, db: Session = Depends(get_session)):
    """Merge one category into another across all matching transactions (CASH-07)."""
    count = apply_merge_category(db, req.from_name, req.into_name)
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
            apply_delete_transaction(db, row.get("id"), before)

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
            db.add(AuditLog(entity="holding", entity_id=h_id, operation="edit",
                            before=before, after=after))

        elif operation == "delete_holding":
            h_id = row.get("id")
            h = db.get(Holding, h_id)
            if h is not None:
                db.delete(h)
            db.add(AuditLog(entity="holding", entity_id=h_id, operation="delete",
                            before=before, after=None))

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
