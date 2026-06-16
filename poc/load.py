"""
CLI loader: parse a Wallet CSV and load it into the SQLite database.

Usage:
    python -m poc.load path/to/export.csv
    python -m poc.load path/to/export.csv --db path/to/custom.db
    python -m poc.load path/to/export.csv --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

sys.path.insert(0, str(Path(__file__).parent.parent))

from poc.db import DB_PATH, get_connection, init_db, insert_transactions
from poc.parser import parse


def main():
    ap = argparse.ArgumentParser(description="Load a Wallet CSV export into monai.db")
    ap.add_argument("csv", help="Path to the exported CSV file")
    ap.add_argument("--db", default=str(DB_PATH), help="Path to the SQLite database")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only; do not write to DB",
    )
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"File not found: {csv_path}")

    db_path = Path(args.db)

    rows, skipped, currency = parse(csv_path)
    print(f"Parsed {len(rows)} rows ({skipped} skipped, currency: {currency})")

    if args.dry_run:
        print("Dry run — nothing written.")
        return

    init_db(db_path)
    with get_connection(db_path) as conn:
        n = insert_transactions(conn, rows)
    print(f"Inserted {n} transactions into {db_path}")


if __name__ == "__main__":
    main()
