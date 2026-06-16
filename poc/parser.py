"""
Wallet by BudgetBakers CSV parser.

Wallet exports semicolon-delimited CSVs with this header:
  account;category;currency;amount;ref_currency_amount;type;payment_type;
  payment_type_local;note;date;gps_latitude;gps_longitude;gps_accuracy_in_meters;
  warranty_in_month;transfer;payee;labels;envelope_id;custom_category

This parser:
  - Auto-detects delimiter (semicolon first, then comma)
  - Validates required columns against the header
  - Detects the primary currency from the first data row
  - Rejects (logs, skips) rows with a different currency
  - Maps Wallet columns to the normalized transactions schema
  - Returns (rows, skipped_count, primary_currency)
"""

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Columns that must be present in the header.
REQUIRED_COLUMNS = {
    "account",
    "category",
    "currency",
    "amount",
    "type",
    "note",
    "date",
    "transfer",
}

# Columns that are nice-to-have but not required.
OPTIONAL_COLUMNS = {"payee", "ref_currency_amount", "payment_type"}


def _detect_delimiter(first_line: str) -> str:
    for delim in (";", ",", "\t"):
        if delim in first_line:
            return delim
    return ";"


def _to_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def parse(path: str | Path, primary_currency: str | None = None) -> tuple[list[dict], int, str]:
    """
    Parse a Wallet BudgetBakers CSV export.

    Args:
        path: Path to the CSV file.
        primary_currency: Expected currency. If None, detected from the first row.
                          Rows with a different currency are skipped.

    Returns:
        (rows, skipped_count, detected_primary_currency)

    Raises:
        ValueError: If the file is missing required columns.
    """
    path = Path(path)

    with path.open(encoding="utf-8-sig") as f:
        raw_lines = f.readlines()

    if not raw_lines:
        raise ValueError(f"{path}: file is empty")

    delimiter = _detect_delimiter(raw_lines[0])
    reader = csv.DictReader(raw_lines, delimiter=delimiter)

    # Validate header
    if reader.fieldnames is None:
        raise ValueError(f"{path}: could not read header row")

    actual_cols = {c.strip().lower() for c in reader.fieldnames}
    missing = REQUIRED_COLUMNS - actual_cols
    if missing:
        found = sorted(actual_cols)
        expected = sorted(REQUIRED_COLUMNS)
        raise ValueError(
            f"{path}: missing required columns {sorted(missing)}\n"
            f"  expected: {expected}\n"
            f"  found:    {found}"
        )

    rows: list[dict] = []
    skipped = 0
    detected_currency: str | None = primary_currency

    for raw in reader:
        # Normalise column names (strip whitespace)
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}

        currency = row["currency"]

        # Detect primary currency from first real row
        if detected_currency is None:
            detected_currency = currency
            logger.info("Primary currency detected: %s", detected_currency)

        # Skip rows with a different currency
        if currency != detected_currency:
            logger.warning(
                "Skipping row (currency %s != primary %s): %s",
                currency,
                detected_currency,
                row.get("note", ""),
            )
            skipped += 1
            continue

        # Parse amount — Wallet uses negative for expenses
        try:
            amount = float(row["amount"])
        except ValueError:
            logger.warning("Skipping row with unparseable amount: %r", row["amount"])
            skipped += 1
            continue

        # Normalize date: "YYYY-MM-DD HH:MM:SS" → keep as-is (SQLite TEXT)
        date_str = row["date"]

        # merchant: prefer payee if non-empty, else note
        payee = row.get("payee", "").strip()
        note = row.get("note", "").strip()
        merchant = payee if payee else note

        rows.append(
            {
                "account": row["account"],
                "date": date_str,
                "amount": amount,
                "currency": currency,
                # raw_category preserves the original Wallet category
                "raw_category": row["category"],
                # category starts equal to raw_category; can be re-categorized later
                "category": row["category"],
                "merchant": merchant,
                "notes": note,
                "is_transfer": _to_bool(row["transfer"]),
            }
        )

    if detected_currency is None:
        detected_currency = ""

    logger.info(
        "Parsed %d rows, skipped %d (currency mismatch), primary currency: %s",
        len(rows),
        skipped,
        detected_currency,
    )

    return rows, skipped, detected_currency
