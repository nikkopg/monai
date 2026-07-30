"""Pydantic request/response models for the API."""

import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

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


class CategoryRollupChild(BaseModel):
    """A subcategory's contribution to its top-level group's rollup (CAT-04)."""

    id: int
    name: str
    color: str | None  # effective (inherited) swatch, never None in practice
    icon: str | None
    total: float


class CategoryRollup(BaseModel):
    """A top-level category group's spending rollup for the dashboard donut
    (CAT-04) — id/color/icon join the hierarchy onto tools.py's
    spending_by_category rows/children, ordered by total desc."""

    id: int
    name: str
    color: str | None
    icon: str | None
    total: float
    children: list[CategoryRollupChild]


class CashflowSummary(BaseModel):
    """Single composed payload for GET /cashflow/summary (D-08)."""

    totals: dict  # {income, expense, net} as floats
    by_category: list[CategoryRollup]  # hierarchy rollup (CAT-04, was tuple rows)
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


# ---------------------------------------------------------------------------
# Investments (INV-01/06/07) — event ledger, holdings, composed summary
# ---------------------------------------------------------------------------


class PortfolioEventCreate(BaseModel):
    """Buy/sell/dividend event body (INV-07, D-01).

    event_type is a locked literal set — a value outside {buy,sell,dividend}
    (e.g. "gift") is rejected with a 422 at the schema boundary BEFORE the
    recompute runs (T-05-03-EVT). quantity/price must be positive (V5).
    Convention for a lump-sum dividend: quantity=1, price=amount.
    """

    ticker: str
    event_type: Literal["buy", "sell", "dividend"]
    quantity: MoneyDecimal = Field(..., gt=0, description="Units; must be positive")
    price: MoneyDecimal = Field(
        ..., gt=0,
        description="Price per unit (or dividend amount) in the event's native "
                    "currency (see `currency`), positive; converted to IDR "
                    "internally at the trade-date FX rate — do NOT pre-convert.",
    )
    date: date
    platform_id: int = Field(..., description="Required — position identity is (ticker, platform_id)")
    asset_type: str | None = None
    currency: str | None = Field(
        None, description="Native currency of price; must match the parent holding's currency if one exists"
    )


class PortfolioEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    ticker: str
    event_type: str
    quantity: MoneyDecimal
    price: MoneyDecimal


# ---------------------------------------------------------------------------
# Phase 14 direct-write bodies (CHAT-09/XFER-01..03/ACCT-02) — REST path
# parallel to the confirm-before-write agent path (14-02). Every positive
# magnitude uses Field(..., gt=0); the apply_* primitives own sign
# normalization, these schemas only reject negative/zero at the boundary.
# ---------------------------------------------------------------------------


class TransferCreate(BaseModel):
    """Body for POST /transactions/transfer (XFER-01)."""

    from_account: str
    to_account: str
    amount: MoneyDecimal = Field(..., gt=0, description="Unsigned magnitude; sign is applied per leg")
    currency: str = "IDR"
    date: str | None = None
    notes: str | None = None


class InvestmentTransferCreate(BaseModel):
    """Body for POST /transactions/investment-transfer (XFER-02)."""

    from_account: str
    platform_id: int = Field(..., description="Required — no by-name resolution, mirrors account-id precedent")
    amount: MoneyDecimal = Field(..., gt=0, description="Unsigned magnitude")
    currency: str = "IDR"
    date: str | None = None
    notes: str | None = None


class FundedBuyCreate(BaseModel):
    """Body for POST /portfolio-events/funded-buy (XFER-03)."""

    source_account_name: str
    platform_id: int = Field(..., description="Required — position identity is (ticker, platform_id)")
    ticker: str
    quantity: MoneyDecimal = Field(..., gt=0, description="Units; must be positive")
    price: MoneyDecimal = Field(..., gt=0, description="Price per unit in the event's native currency")
    cash_amount: MoneyDecimal = Field(..., gt=0, description="Unsigned magnitude; the primitive always debits")
    cash_currency: str = "IDR"
    event_currency: str = "IDR"
    date: str | None = None
    notes: str | None = None
    asset_type: str | None = None


class FundedSellCreate(BaseModel):
    """Body for POST /portfolio-events/funded-sell (XFER-03)."""

    source_account_name: str
    platform_id: int = Field(..., description="Required — position identity is (ticker, platform_id)")
    ticker: str
    quantity: MoneyDecimal = Field(..., gt=0, description="Units; must be positive")
    price: MoneyDecimal = Field(..., gt=0, description="Price per unit in the event's native currency")
    cash_amount: MoneyDecimal = Field(..., gt=0, description="Unsigned magnitude; the primitive always credits")
    cash_currency: str = "IDR"
    event_currency: str = "IDR"
    date: str | None = None
    notes: str | None = None
    asset_type: str | None = None


class BalanceAdjustmentCreate(BaseModel):
    """Body for POST /accounts/{account_id}/adjust-balance (ACCT-02).

    NO gt=0 on target_balance — a target balance may legitimately be zero or
    negative (e.g. a liability account). account_id comes from the path, not
    the body.
    """

    target_balance: MoneyDecimal


class HoldingCreate(BaseModel):
    """Direct holding override body (D-03 escape hatch)."""

    ticker: str
    quantity: MoneyDecimal
    avg_cost: MoneyDecimal
    purchase_date: date | None = None
    currency: str = "IDR"
    asset_type: str | None = None
    platform_id: int = Field(..., description="Required — position identity is (ticker, platform_id)")
    coingecko_id: str | None = None


class HoldingUpdate(BaseModel):
    """Partial-update body for a direct holding override — all fields Optional."""

    ticker: str | None = None
    quantity: MoneyDecimal | None = None
    avg_cost: MoneyDecimal | None = None
    purchase_date: date | None = None
    asset_type: str | None = None
    platform_id: int | None = None
    coingecko_id: str | None = None


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    quantity: MoneyDecimal
    avg_cost: MoneyDecimal
    purchase_date: date | None
    currency: str
    asset_type: str | None
    platform_id: int | None
    coingecko_id: str | None


class PortfolioSummary(BaseModel):
    """Composed GET /investments/summary payload (D-05, INV-06).

    Built from a plain dict (portfolio.portfolio_summary), not an ORM row.
    Money fields inside `groups` are already Decimal; the dict passthrough keeps
    them serialized as JSON numbers via portfolio.py's own shaping.
    """

    groups: list  # [{platform_id, platform_name, kind, subtotal, holdings:[...]}]
    asset_type_groups: list = []  # [{asset_type, total_value}] — VZ-01 pie data contract
    total_value: MoneyDecimal
    total_unrealized_pnl: MoneyDecimal
    total_realized_pnl: MoneyDecimal
    as_of: str


class ValueHistoryPointOut(BaseModel):
    """One day's point in the GET /investments/history series (VZ-02, INVX-01)."""

    date: date
    total_market_value: MoneyDecimal
    total_pnl: MoneyDecimal


class ValueHistoryResponse(BaseModel):
    """GET /investments/history payload — a list of daily points, already
    range-filtered server-side (VZ-02)."""

    points: list[ValueHistoryPointOut]


class PriceOverrideRequest(BaseModel):
    """Manual price override body (INV-04, D-11, T-05-04-INP).

    price must be a positive Decimal — a negative/zero price is rejected with a
    422 at the schema boundary (V5) BEFORE apply_set_price runs.
    """

    ticker: str
    price: MoneyDecimal = Field(..., gt=0, description="New price per unit in IDR; positive")


class CategoryCreate(BaseModel):
    """Body for POST /categories (CAT-01). `kind` and `color` are required
    only at root (parent_id=None); below root, kind is always forced to the
    parent's root kind (D-03) and color may be omitted to inherit (D-14) —
    enforced in apply_add_category, not here, since the requirement is
    conditional on parent_id."""

    name: str
    parent_id: int | None = None
    kind: str | None = None
    color: str | None = None
    icon: str | None = None


class CategoryUpdate(BaseModel):
    """Partial-update body for editing a category — all fields Optional.

    Unlike AccountUpdate, the API layer reads this with model_dump(...,
    exclude_unset=True) rather than exclude_none — an explicit parent_id
    (including a future null-to-root case) must be distinguishable from
    "not provided" (see apply_edit_category).
    """

    name: str | None = None
    parent_id: int | None = None
    kind: str | None = None
    color: str | None = None
    icon: str | None = None


class CategoryNode(BaseModel):
    """One node in the GET /categories tree response (CAT-01, D-14)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    kind: str
    color: str | None
    effective_color: str | None
    icon: str | None
    is_system: bool
    tx_count: int
    children: list["CategoryNode"] = []


CategoryNode.model_rebuild()


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
