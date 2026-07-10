"""Pydantic request/response models for the API."""

import uuid as _uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

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


class CashflowSummary(BaseModel):
    """Single composed payload for GET /cashflow/summary (D-08)."""

    totals: dict  # {income, expense, net} as floats
    by_category: list  # rows from spending_by_category
    accounts: list  # rows from account_balances (id/name/current_balance/period_net)
    trend: list  # rows from monthly_trend (month/income/expense/net)


class TransactionUpdate(BaseModel):
    """Partial-update body for editing a transaction — all fields Optional.

    None means "keep existing", matching the after.get(...) is not None
    semantics used by the shared write-tool helpers / propose_edit_transaction.
    """

    date: str | None = None
    amount: MoneyDecimal | None = None
    category: str | None = None
    merchant: str | None = None
    account: str | None = None
    notes: str | None = None
    is_transfer: bool | None = None


class AccountCreate(BaseModel):
    name: str
    type: str | None = None
    currency: str | None = "IDR"


class AccountUpdate(BaseModel):
    """Partial-update body for editing an account — all fields Optional."""

    name: str | None = None
    type: str | None = None
    currency: str | None = None


class PlatformCreate(BaseModel):
    name: str
    kind: str | None = None


class PlatformUpdate(BaseModel):
    """Partial-update body for editing a platform — all fields Optional."""

    name: str | None = None
    kind: str | None = None


class PlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str | None


class CategoryRenameRequest(BaseModel):
    old_name: str
    new_name: str


class CategoryMergeRequest(BaseModel):
    from_name: str
    into_name: str


class AffectedCountResponse(BaseModel):
    """Response shape for the category affected-count read and rename/merge
    responses, so the UI can show the count actually applied (D-09).
    """

    category: str
    affected_count: int


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


class ProposalOut(BaseModel):
    """Proposal serialized for API responses.

    NOTE: the `token` field is DELIBERATELY EXCLUDED — it is never returned
    in GET /proposals or any list/read path (T-02-07). The token is surfaced
    only in the agent_stream SSE answer event to the originating chat session.
    """

    model_config = ConfigDict(from_attributes=True)

    id: _uuid.UUID
    operation: str
    payload: dict
    status: str
    expires_at: datetime
    created_at: datetime
    confirmed_at: datetime | None


class ConfirmRequest(BaseModel):
    """Body for POST /proposals/{id}/confirm."""

    token: str


# ---------------------------------------------------------------------------
# Settings (UI-03, UI-04) — locked enums per app_settings design
# ---------------------------------------------------------------------------

_VALID_PROVIDERS = {"ollama", "claude", "openai"}
_VALID_PRICE_SOURCES = {"coingecko", "yfinance", "manual"}


class SettingsOut(BaseModel):
    """Effective settings response — built from a plain dict
    (get_effective_settings), never from an ORM row, so no from_attributes.
    Raw key values NEVER appear here, only their masked derived forms.
    """

    llm_provider: str
    llm_model: str
    anthropic_api_key_masked: str | None = None
    openai_api_key_masked: str | None = None
    base_currency: str
    price_data_source: str


class SettingsUpdate(BaseModel):
    """Partial-update body for PUT /settings — all fields Optional.

    A None or blank/empty-string value for any field means "keep existing"
    (enforced server-side in backend.settings.upsert_settings).
    """

    llm_provider: str | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    base_currency: str | None = None
    price_data_source: str | None = None

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, v: str | None) -> str | None:
        # None/"" both mean "keep existing" (upsert_settings filters these out);
        # only a non-empty, non-member value is rejected here.
        if v and v not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid llm_provider={v!r}. Valid: {sorted(_VALID_PROVIDERS)}"
            )
        return v

    @field_validator("price_data_source")
    @classmethod
    def _validate_price_data_source(cls, v: str | None) -> str | None:
        if v and v not in _VALID_PRICE_SOURCES:
            raise ValueError(
                f"Invalid price_data_source={v!r}. Valid: {sorted(_VALID_PRICE_SOURCES)}"
            )
        return v
