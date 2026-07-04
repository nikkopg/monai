"""
monai backend — FastAPI.

Run (dev):
    cd monai
    uv run --with-requirements backend/requirements.txt uvicorn backend.main:app --reload

Endpoints:
    GET  /health
    GET  /accounts
    GET  /transactions?limit=50
    POST /transactions          create one (logs new spending)
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
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.db import get_session
from backend.importer import _get_or_create_account, import_csv_text
from backend.models import Account, AuditLog, Holding, Proposal, Transaction
from backend.schemas import (
    AccountOut,
    ConfirmRequest,
    ImportResponse,
    ProposalOut,
    QueryRequest,
    QueryResponse,
    SettingsOut,
    SettingsUpdate,
    TransactionCreate,
    TransactionOut,
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


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(limit: int = 50, db: Session = Depends(get_session)):
    return (
        db.query(Transaction)
        .order_by(desc(Transaction.date))
        .limit(min(limit, 500))
        .all()
    )


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


@app.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_session)):
    """Effective settings (DB overrides env defaults). Public — keys masked (UI-03)."""
    return get_effective_settings(db)


@app.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_api_key)])
def write_settings(patch: SettingsUpdate, db: Session = Depends(get_session)):
    """Partial-update settings (auth-protected). Blank/absent key fields keep the
    existing stored value (UI-03, UI-04). Re-runs configure_llm() + reset_engine()
    when an LLM-relevant field changed, so the next chat request uses it."""
    changed_llm = upsert_settings(db, patch.model_dump(exclude_none=True))

    # Audit trail: masked-only, never the raw key values (T-03-14).
    audit_after = patch.model_dump(exclude_none=True)
    if KEY_ANTHROPIC_API_KEY in audit_after:
        audit_after[KEY_ANTHROPIC_API_KEY] = mask_key(audit_after[KEY_ANTHROPIC_API_KEY])
    if KEY_OPENAI_API_KEY in audit_after:
        audit_after[KEY_OPENAI_API_KEY] = mask_key(audit_after[KEY_OPENAI_API_KEY])
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
    from sqlalchemy import text as _text
    from backend.importer import _get_or_create_account

    payload = proposal.payload
    operation = payload.get("operation", "")
    rows = payload.get("rows", [])

    for row in rows:
        before = row.get("before")
        after = row.get("after")

        if operation == "add_transaction":
            # Resolve or create the account by name
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
            db.flush()
            db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                            before=None, after=after))

        elif operation == "edit_transaction":
            tx_id = row.get("id")
            tx = db.get(Transaction, tx_id)
            if tx is None:
                raise ValueError(f"Transaction {tx_id} not found during confirm")
            if after.get("category") is not None:
                tx.category = after["category"]
            if after.get("merchant") is not None:
                tx.merchant = after["merchant"]
            if after.get("amount") is not None:
                from decimal import Decimal as _D
                tx.amount = _D(str(after["amount"]))
            if after.get("notes") is not None:
                tx.notes = after["notes"]
            db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="edit",
                            before=before, after=after))

        elif operation == "delete_transaction":
            tx_id = row.get("id")
            tx = db.get(Transaction, tx_id)
            if tx is not None:
                db.delete(tx)
            db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="delete",
                            before=before, after=None))

        elif operation == "add_account":
            acc = Account(
                name=after["name"],
                type=after.get("type"),
                currency=after.get("currency"),
            )
            db.add(acc)
            db.flush()
            db.add(AuditLog(entity="account", entity_id=acc.id, operation="add",
                            before=None, after=after))

        elif operation == "edit_account":
            acc_id = row.get("id")
            acc = db.get(Account, acc_id)
            if acc is None:
                raise ValueError(f"Account {acc_id} not found during confirm")
            if after.get("name") is not None:
                acc.name = after["name"]
            if after.get("type") is not None:
                acc.type = after["type"]
            if after.get("currency") is not None:
                acc.currency = after["currency"]
            db.add(AuditLog(entity="account", entity_id=acc_id, operation="edit",
                            before=before, after=after))

        elif operation == "delete_account":
            acc_id = row.get("id")
            acc = db.get(Account, acc_id)
            if acc is not None:
                db.delete(acc)
            db.add(AuditLog(entity="account", entity_id=acc_id, operation="delete",
                            before=before, after=None))

        elif operation == "rename_category":
            old_name = row.get("old_name")
            new_name = row.get("new_name")
            db.execute(
                _text("UPDATE transactions SET category = :new WHERE category = :old"),
                {"new": new_name, "old": old_name},
            )
            db.add(AuditLog(entity="category", entity_id=None, operation="rename",
                            before={"category": old_name}, after={"category": new_name}))

        elif operation == "merge_category":
            from_name = row.get("from_name")
            into_name = row.get("into_name")
            db.execute(
                _text("UPDATE transactions SET category = :into WHERE category = :from"),
                {"into": into_name, "from": from_name},
            )
            db.add(AuditLog(entity="category", entity_id=None, operation="merge",
                            before={"category": from_name}, after={"category": into_name}))

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
