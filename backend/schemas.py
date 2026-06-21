"""Pydantic request/response models for the API."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# ---------------------------------------------------------------------------
# Shared money type
# ---------------------------------------------------------------------------

# Validates as Decimal (preserving precision on the Python side), serializes
# as a JSON number (float) instead of the Pydantic v2 default string.
# Use for all amount/price/quantity fields across all schemas (D-14, D-15).
# Ref: Pydantic v2 Pitfall 4 — Decimal serializes as string without this.
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]


class TransactionCreate(BaseModel):
    date: datetime
    amount: MoneyDecimal = Field(..., description="Signed: negative = expense, positive = income")
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
    amount: MoneyDecimal
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
