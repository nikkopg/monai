"""Pydantic request/response models for the API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    date: datetime
    amount: float = Field(..., description="Signed: negative = expense, positive = income")
    currency: str = "IDR"
    category: str | None = None
    merchant: str | None = None
    notes: str | None = None
    account: str = Field(..., description="Account name; created if it doesn't exist")
    is_transfer: bool = False


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: datetime
    amount: float
    currency: str
    category: str | None
    raw_category: str | None
    merchant: str | None
    notes: str | None
    account_id: int | None
    is_transfer: bool


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str | None
    currency: str | None


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    answer: str


class ImportResponse(BaseModel):
    parsed: int
    inserted: int
    skipped: int
    currency: str
