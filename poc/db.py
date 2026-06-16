import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "monai.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accounts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL UNIQUE,
    type     TEXT,
    currency TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    currency     TEXT    NOT NULL,
    category     TEXT,
    raw_category TEXT,
    merchant     TEXT,
    notes        TEXT,
    account_id   INTEGER REFERENCES accounts(id),
    is_transfer  INTEGER NOT NULL DEFAULT 0
);

CREATE VIEW IF NOT EXISTS date_helpers AS
SELECT
    date('now', 'start of month')                          AS current_month_start,
    date('now', 'start of month', '+1 month', '-1 day')   AS current_month_end,
    date('now', 'start of month', '-1 month')              AS last_month_start,
    date('now', 'start of month', '-1 day')                AS last_month_end,
    date('now', 'start of year')                           AS current_year_start,
    date('now', 'start of year', '+3 month', '-1 day')     AS q1_end,
    date('now', 'start of year', '+3 month')               AS q2_start,
    date('now', 'start of year', '+6 month', '-1 day')     AS q2_end,
    date('now', 'start of year', '+6 month')               AS q3_start,
    date('now', 'start of year', '+9 month', '-1 day')     AS q3_end,
    date('now', 'start of year', '+9 month')               AS q4_start,
    date('now', 'start of year', '+12 month', '-1 day')    AS q4_end;
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def get_or_create_account(conn: sqlite3.Connection, name: str, currency: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO accounts (name, currency) VALUES (?, ?)", (name, currency)
    )
    return cur.lastrowid


def insert_transactions(conn: sqlite3.Connection, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        account_id = get_or_create_account(conn, row["account"], row["currency"])
        conn.execute(
            """
            INSERT INTO transactions
                (date, amount, currency, category, raw_category, merchant, notes,
                 account_id, is_transfer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["date"],
                row["amount"],
                row["currency"],
                row.get("category"),
                row.get("raw_category"),
                row.get("merchant"),
                row.get("notes"),
                account_id,
                1 if row.get("is_transfer") else 0,
            ),
        )
        inserted += 1
    return inserted
