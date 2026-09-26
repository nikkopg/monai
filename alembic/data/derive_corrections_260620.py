"""Derive the 177-row net-worth-correction fixture from the archival Wallet CSV.

This is a standalone, one-off derivation tool. It lives in `alembic/data/`
(not `alembic/versions/`) because Alembic only scans `versions/` for revision
files; nothing imports this module at migration time — migration `014`
(`alembic/versions/014_recon_backfill.py`) reads the CSV this script
produces, never this script itself.

Input: `report_2026-06-20_132532.csv`, expected at the repo root. This file
is the pre-data-loss archival export from Wallet (BudgetBakers) and is
PERMANENTLY UNTRACKED via `.gitignore`'s `report_*.csv` pattern — it holds
the user's full personal financial history and must never enter git.

This script is the documented, reproducible derivation behind D-11's
fixture: only the 177 rows the live-DB anti-join identifies as missing are
written out to `alembic/data/corrections_260620.csv`. That output is still
personal financial data, so it is gitignored too and stays on this machine.

Row-count trap (verified live 2026-09-06, see 20-RESEARCH.md Pitfall 2):
`wc -l` on the archival export reports 5628 lines, NOT the true row count of
5608 — 20 embedded newlines live inside quoted `note` fields, which a naive
line-based count miscounts as extra rows. Only a real CSV parse
(`csv.DictReader`) gives the correct 5608. Any row-count assertion in this
script or in migration 014 must derive from a real parse, never `wc -l`.

Decimal-matching trap (20-RESEARCH.md Pitfall 3): matching `(date, amount)`
keys via `float`/`round` on one side and the DB's native `Decimal` on the
other silently misclassifies 100% of rows as missing. Both sides of the key
MUST route through `Decimal(...).quantize(Decimal("1.00"))`.
"""

import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from backend.db import engine

_ARCHIVAL_CSV = Path(__file__).resolve().parent.parent.parent / "report_2026-06-20_132532.csv"
_OUTPUT_CSV = Path(__file__).resolve().parent / "corrections_260620.csv"

_EXPECTED_ROW_COUNT = 5608
_EXPECTED_MISSING_TOTAL = 177

_OUTPUT_FIELDNAMES = ["orig_account", "date", "amount", "category", "is_transfer"]


def _quantize(amount) -> Decimal:
    return Decimal(str(amount)).quantize(Decimal("1.00"))


def derive_missing_rows(archival_csv_path=_ARCHIVAL_CSV) -> list[dict]:
    """Parse the archival export, anti-join it against live `transactions` on
    `(date, amount)`, and return the rows absent from the live database.

    Raises ValueError naming actual-vs-expected unless the parsed row count
    is exactly 5608, and again unless the anti-join yields exactly 177 rows
    — a silent partial match here
    would produce a wrong correction set (D-02).
    """
    with open(archival_csv_path, newline="", encoding="utf-8") as f:
        # Semicolon-delimited — the Wallet export, unlike category_mapping.csv,
        # uses `;` (verified by reading the header this session).
        csv_rows = list(csv.DictReader(f, delimiter=";"))

    if len(csv_rows) != _EXPECTED_ROW_COUNT:
        raise ValueError(
            f"Archival CSV parsed to {len(csv_rows)} rows, expected exactly "
            f"{_EXPECTED_ROW_COUNT}. Do not trust `wc -l` here (it reports "
            "5628 due to embedded newlines in quoted note fields) — this "
            "count comes from a real csv.DictReader parse. Aborting rather "
            "than derive a fixture from an unexpected input."
        )

    with engine.connect() as conn:
        live_keys = {
            (row[0].date().isoformat(), _quantize(row[1]))
            for row in conn.execute(text("SELECT date, amount FROM transactions"))
        }

    missing = [
        row
        for row in csv_rows
        if (row["date"][:10], _quantize(row["amount"])) not in live_keys
    ]

    total = len(missing)
    if total != _EXPECTED_MISSING_TOTAL:
        raise ValueError(
            f"Anti-join produced {total} missing row(s), expected exactly "
            f"{_EXPECTED_MISSING_TOTAL}. The live database may have moved "
            "since this derivation was verified — aborting rather than write "
            "a silently wrong fixture."
        )

    return missing


def write_fixture(missing_rows: list[dict], output_path=_OUTPUT_CSV) -> None:
    """Write the local 177-row fixture: comma-delimited, header exactly
    `orig_account,date,amount,category,is_transfer`, sorted by
    (date, orig_account, amount) for a stable git diff. Carries only the
    columns the reconstruction needs (D-11) — note/payee/labels/GPS columns
    from the archival export are dropped."""
    out_rows = [
        {
            "orig_account": row["account"],
            "date": row["date"][:10],
            "amount": str(_quantize(row["amount"])),
            "category": row["category"],
            "is_transfer": "true" if row["transfer"] == "true" else "false",
        }
        for row in missing_rows
    ]
    out_rows.sort(key=lambda r: (r["date"], r["orig_account"], r["amount"]))

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUTPUT_FIELDNAMES)
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)


def main() -> None:
    missing = derive_missing_rows()
    write_fixture(missing)

    by_account = Counter(r["account"] for r in missing)
    sums: dict[str, Decimal] = {}
    for r in missing:
        sums[r["account"]] = sums.get(r["account"], Decimal("0.00")) + _quantize(r["amount"])

    print(f"Derived {len(missing)} missing rows -> {_OUTPUT_CSV}")
    for account in sorted(by_account):
        print(f"  {account}: {by_account[account]} rows, sum {sums[account]}")


if __name__ == "__main__":
    main()
