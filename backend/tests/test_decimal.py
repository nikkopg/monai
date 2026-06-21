"""Decimal serialization — Pydantic v2 round-trip tests (no DB required).

Covers FND-03 (serialization side): money amounts must validate as Decimal and
serialize as JSON numbers (not strings) at the Pydantic/JSON boundary.
"""

import json
from decimal import Decimal

import pytest
from pydantic import BaseModel

from backend.schemas import MoneyDecimal, TransactionCreate, TransactionOut


# ---------------------------------------------------------------------------
# 1. MoneyDecimal alias: JSON number output
# ---------------------------------------------------------------------------


def test_money_decimal_serializes_as_json_number():
    """MoneyDecimal must produce a JSON number (float), not a string, via model_dump_json."""

    class _M(BaseModel):
        amount: MoneyDecimal

    m = _M(amount=Decimal("123456.78"))
    payload = json.loads(m.model_dump_json())
    # Must be a float, not a str — Pydantic v2 default is str without PlainSerializer
    assert isinstance(payload["amount"], float), (
        f"expected float, got {type(payload['amount'])}: {payload['amount']!r}"
    )
    assert payload["amount"] == 123456.78


def test_money_decimal_equality_preserved():
    """Decimal value is preserved as Decimal in Python; float conversion only for JSON."""

    class _M(BaseModel):
        amount: MoneyDecimal

    m = _M(amount=Decimal("99999999.99"))
    # Python-side: stays Decimal
    assert isinstance(m.amount, Decimal)
    assert m.amount == Decimal("99999999.99")


# ---------------------------------------------------------------------------
# 2. TransactionCreate: accepts Decimal, round-trips as Decimal in Python
# ---------------------------------------------------------------------------


def test_transaction_create_accepts_decimal():
    """TransactionCreate.amount must accept a Decimal and preserve it as Decimal."""
    tx = TransactionCreate(
        date="2026-01-15T00:00:00",
        amount=Decimal("-25000.00"),
        account="Cash",
    )
    assert tx.amount == Decimal("-25000.00"), (
        f"expected Decimal('-25000.00'), got {tx.amount!r}"
    )
    assert isinstance(tx.amount, Decimal)


def test_transaction_create_rejects_non_numeric():
    """TransactionCreate.amount must reject obviously non-numeric input."""
    with pytest.raises(Exception):
        TransactionCreate(
            date="2026-01-15T00:00:00",
            amount="not-a-number",
            account="Cash",
        )


# ---------------------------------------------------------------------------
# 3. TransactionOut: serializes amount as JSON number, not string
# ---------------------------------------------------------------------------


def test_transaction_out_serializes_amount_as_json_number():
    """TransactionOut.amount must serialize as a JSON number (float), not a string."""
    # Construct via model_validate to simulate ORM read path
    tx_out = TransactionOut.model_validate(
        {
            "id": 1,
            "date": "2026-01-15T00:00:00",
            "amount": Decimal("45678.90"),
            "currency": "IDR",
            "category": "Food",
            "raw_category": "Food & Drink",
            "merchant": "Warung Pak Budi",
            "notes": None,
            "account_id": 1,
            "is_transfer": False,
        }
    )
    payload = json.loads(tx_out.model_dump_json())
    assert isinstance(payload["amount"], float), (
        f"TransactionOut.amount must be a JSON float, got {type(payload['amount'])}: {payload['amount']!r}"
    )
    assert payload["amount"] == 45678.90
