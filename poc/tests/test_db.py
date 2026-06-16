import sqlite3
from pathlib import Path

import pytest

from poc.db import init_db, get_connection, get_or_create_account, insert_transactions


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


class TestSchema:
    def test_wal_mode(self, db):
        conn = sqlite3.connect(db)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_tables_created(self, db):
        conn = sqlite3.connect(db)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
        conn.close()
        assert "accounts" in tables
        assert "transactions" in tables
        assert "date_helpers" in tables

    def test_no_transfer_pair_id_column(self, db):
        conn = sqlite3.connect(db)
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        conn.close()
        assert "transfer_pair_id" not in cols

    def test_date_helpers_view_returns_row(self, db):
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT * FROM date_helpers").fetchone()
        conn.close()
        assert row is not None
        assert row[0]  # current_month_start is non-empty


class TestInsert:
    def test_insert_transaction(self, db):
        with get_connection(db) as conn:
            n = insert_transactions(
                conn,
                [
                    {
                        "account": "Cash",
                        "date": "2024-04-01 12:00:00",
                        "amount": -50000.0,
                        "currency": "IDR",
                        "category": "Food",
                        "raw_category": "Food",
                        "merchant": "beli sate",
                        "notes": "beli sate",
                        "is_transfer": False,
                    }
                ],
            )
        assert n == 1

    def test_account_auto_created(self, db):
        with get_connection(db) as conn:
            insert_transactions(
                conn,
                [
                    {
                        "account": "Savings",
                        "date": "2024-04-01 12:00:00",
                        "amount": 1000000.0,
                        "currency": "IDR",
                        "category": "Income",
                        "raw_category": "Income",
                        "merchant": "",
                        "notes": "salary",
                        "is_transfer": False,
                    }
                ],
            )
            row = conn.execute(
                "SELECT id FROM accounts WHERE name = 'Savings'"
            ).fetchone()
        assert row is not None

    def test_transfer_flag_stored(self, db):
        with get_connection(db) as conn:
            insert_transactions(
                conn,
                [
                    {
                        "account": "Cash",
                        "date": "2024-04-01",
                        "amount": 200000.0,
                        "currency": "IDR",
                        "category": "TRANSFER",
                        "raw_category": "TRANSFER",
                        "merchant": "",
                        "notes": "",
                        "is_transfer": True,
                    }
                ],
            )
            row = conn.execute(
                "SELECT is_transfer FROM transactions WHERE notes = ''"
            ).fetchone()
        assert row["is_transfer"] == 1
