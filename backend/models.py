"""
SQLAlchemy ORM models for monai.

Schema mirrors the validated PoC design (ARCHITECTURE.md), with two
production hardening changes:
  - amount uses Numeric(18, 2) instead of float (money correctness)
  - date is a real timestamp instead of TEXT

transfer_pair_id and base_currency/fx_rate are intentionally omitted from v1
(see ARCHITECTURE.md decisions D11/D12 — multi-currency confirmed a non-issue
at full scale, 0 rows skipped across 5608 transactions).

New tables (Phase 1 — consumed in Phase 2+5):
  - AuditLog      — write-operation audit trail (before/after JSONB)
  - Proposal      — pending-confirmation records; token is a separate secret column (D-11)
  - Holding       — current investment positions; quantity Numeric(28,8), avg_cost Numeric(18,2) (D-09)
  - PortfolioEvent — buy/sell/dividend history
  - PriceCache    — last known price; source='manual'|'coingecko'/etc (D-12)
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account"
    )


class Platform(Base):
    """Investment platform / broker / exchange an instrument is held on (D-17).

    Mirrors Account's shape; `holdings.platform_id` FK is nullable so existing
    (unassigned) positions remain valid. `kind` is a free-form label
    ('broker' | 'exchange' | 'wallet' | ...) — optional.
    """

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Pitfall 5 fix: annotation changed from Mapped[float] to Mapped[Decimal]
    # to match the Numeric(18,2) column type (psycopg3 returns Decimal natively).
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(8))
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    account: Mapped["Account | None"] = relationship(
        back_populates="transactions"
    )


class AuditLog(Base):
    """Write-operation audit trail — before/after state stored as JSONB (D-10)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )


class Proposal(Base):
    """Pending-confirmation record for agentic write operations.

    The UUID `id` may appear in logs/URLs safely; the `token` column holds
    the actual high-entropy confirm secret (D-11). Tokens are single-use
    and operation-scoped (enforced in Phase 2).
    """

    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Separate high-entropy confirm token — NOT the row UUID (D-11).
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), server_default="pending", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Holding(Base):
    """Current investment position.

    quantity uses Numeric(28,8) for crypto-standard precision (D-09).
    avg_cost uses Numeric(18,2) consistent with transactions.amount (D-09).
    source of truth for current positions; portfolio_events records the history.

    Position identity is (ticker, platform_id) — Quick 260711-rb2: the same
    asset can live on multiple platforms as distinct positions. platform_id
    is REQUIRED (no more "unassigned"); ticker alone is no longer unique.
    """

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("ticker", "platform_id", name="uq_holdings_ticker_platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(8), server_default="IDR", nullable=False
    )
    asset_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Required FK to platforms (Quick 260711-rb2, Option 1): platform is part
    # of position identity — "unassigned" is retired.
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id"), nullable=False, index=True
    )
    # Explicit CoinGecko coin-id override (Tier 1): disambiguates tickers that
    # map to multiple CoinGecko coins. None falls back to the fixed symbol map.
    coingecko_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PortfolioEvent(Base):
    """Buy/sell/dividend history for an investment instrument.

    Carries platform_id (Quick 260711-rb2) so recompute derives a position
    per (ticker, platform_id) — matches Holding's identity.
    """

    __tablename__ = "portfolio_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id"), nullable=False, index=True
    )


class AppSetting(Base):
    """Key-value settings store — DB overrides env-var defaults (Phase 3)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    # Column is JSONB (see migration 003) but every setting stored here is a
    # bare scalar string (provider/model names, raw keys, currency codes) —
    # JSONB stores those as JSON string scalars. Annotation matches actual
    # usage; keeping JSONB avoids a migration.
    value: Mapped[str] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )


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


class PortfolioValueHistory(Base):
    """Daily per-position portfolio value snapshot (D-13).

    One row per holding per day (unique on (snapshot_date, ticker, platform_id),
    enforced by the migration's unique index — widened from (snapshot_date,
    ticker) in quick 260711 so a ticker held on two platforms records BOTH).
    Powers the portfolio value time-series; quantity/market_value/cost_basis
    reuse the Numeric precision conventions of Holding (28,8) and money (18,2).
    """

    __tablename__ = "portfolio_value_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), server_default="IDR", nullable=False
    )
    # Nullable: pre-existing (pre-multi-platform) rows keep NULL; new snapshots
    # always carry the holding's platform_id (part of the widened unique key).
    platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("platforms.id"), index=True, nullable=True
    )
