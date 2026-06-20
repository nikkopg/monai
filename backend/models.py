"""
SQLAlchemy ORM models for monai.

Schema mirrors the validated PoC design (ARCHITECTURE.md), with two
production hardening changes:
  - amount uses Numeric(18, 2) instead of float (money correctness)
  - date is a real timestamp instead of TEXT

transfer_pair_id and base_currency/fx_rate are intentionally omitted from v1
(see ARCHITECTURE.md decisions D11/D12 — multi-currency confirmed a non-issue
at full scale, 0 rows skipped across 5608 transactions).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
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


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
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
