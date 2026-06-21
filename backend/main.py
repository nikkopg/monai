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
"""

import logging

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.importer import _get_or_create_account, import_csv_text
from backend.models import Account, Transaction
from backend.schemas import (
    AccountOut,
    ImportResponse,
    QueryRequest,
    QueryResponse,
    TransactionCreate,
    TransactionOut,
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


@app.post("/transactions", response_model=TransactionOut, status_code=201)
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


@app.post("/import", response_model=ImportResponse)
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
