"""
Wallet by BudgetBakers CSV import.

Self-contained (does not import from the throwaway poc/ package). Parses the
semicolon-delimited Wallet export, validates required columns, enforces a single
primary currency, and bulk-inserts into Postgres via SQLAlchemy.
"""

import csv
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import Account, Transaction

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "account", "category", "currency", "amount", "type", "note", "date", "transfer",
}

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _detect_delimiter(first_line: str) -> str:
    for delim in (";", ",", "\t"):
        if delim in first_line:
            return delim
    return ";"


def _parse_date(value: str) -> datetime:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value!r}")


def parse_csv(text_content: str, primary_currency: str | None = None) -> tuple[list[dict], int, str]:
    """
    Parse Wallet CSV text into normalized transaction dicts.

    Returns (rows, skipped_count, detected_primary_currency).
    Raises ValueError on missing required columns.
    """
    lines = text_content.splitlines(keepends=True)
    if not lines:
        raise ValueError("CSV is empty")

    delimiter = _detect_delimiter(lines[0])
    reader = csv.DictReader(lines, delimiter=delimiter)

    if reader.fieldnames is None:
        raise ValueError("Could not read CSV header")

    actual = {c.strip().lower() for c in reader.fieldnames}
    missing = REQUIRED_COLUMNS - actual
    if missing:
        raise ValueError(
            f"Missing required columns {sorted(missing)}\n"
            f"  expected: {sorted(REQUIRED_COLUMNS)}\n"
            f"  found:    {sorted(actual)}"
        )

    rows: list[dict] = []
    skipped = 0
    detected = primary_currency

    for raw in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        currency = row["currency"]

        if detected is None:
            detected = currency

        if currency != detected:
            logger.warning("Skip row (currency %s != %s): %s", currency, detected, row.get("note", ""))
            skipped += 1
            continue

        try:
            amount = float(row["amount"])
        except ValueError:
            logger.warning("Skip row, bad amount: %r", row["amount"])
            skipped += 1
            continue

        payee = row.get("payee", "").strip()
        note = row.get("note", "").strip()

        rows.append({
            "account": row["account"],
            "date": _parse_date(row["date"]),
            "amount": amount,
            "currency": currency,
            "category": row["category"],
            "raw_category": row["category"],
            "merchant": payee if payee else note,
            "notes": note,
            "is_transfer": row["transfer"].strip().lower() == "true",
        })

    return rows, skipped, (detected or "")


def _get_or_create_account(db: Session, name: str, currency: str) -> Account:
    acc = db.query(Account).filter(Account.name == name).one_or_none()
    if acc is None:
        acc = Account(name=name, currency=currency)
        db.add(acc)
        db.flush()  # assign id
    return acc


def insert_rows(db: Session, rows: list[dict]) -> int:
    inserted = 0
    for r in rows:
        acc = _get_or_create_account(db, r["account"], r["currency"])
        db.add(Transaction(
            date=r["date"],
            amount=r["amount"],
            currency=r["currency"],
            category=r["category"],
            raw_category=r["raw_category"],
            merchant=r["merchant"],
            notes=r["notes"],
            account_id=acc.id,
            is_transfer=r["is_transfer"],
        ))
        inserted += 1
    db.commit()
    return inserted


def import_csv_text(db: Session, text_content: str) -> tuple[int, int, int, str]:
    """Parse + insert. Returns (parsed, inserted, skipped, currency)."""
    rows, skipped, currency = parse_csv(text_content)
    inserted = insert_rows(db, rows)
    return len(rows), inserted, skipped, currency
