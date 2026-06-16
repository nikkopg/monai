import textwrap
from pathlib import Path

import pytest

from poc.parser import parse, REQUIRED_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, content: str, filename="test.csv") -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content))
    return p


MINIMAL_HEADER = (
    "account;category;currency;amount;ref_currency_amount;type;"
    "payment_type;payment_type_local;note;date;gps_latitude;gps_longitude;"
    "gps_accuracy_in_meters;warranty_in_month;transfer;payee;labels;"
    "envelope_id;custom_category"
)


def _make_row(
    account="Cash",
    category="Food",
    currency="IDR",
    amount="-50000.00",
    note="lunch",
    date="2024-04-01 12:00:00",
    transfer="false",
    payee="",
    type_="Expenses",
) -> str:
    return (
        f"{account};{category};{currency};{amount};{amount};"
        f"{type_};TRANSFER;Bank transfer;{note};{date};"
        f";;;0;{transfer};{payee};;1001;false"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_basic_expense(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row()}\n",
        )
        rows, skipped, currency = parse(csv)
        assert len(rows) == 1
        assert skipped == 0
        assert currency == "IDR"
        r = rows[0]
        assert r["amount"] == -50000.0
        assert r["raw_category"] == "Food"
        assert r["category"] == "Food"
        assert r["notes"] == "lunch"
        assert r["is_transfer"] is False
        assert r["account"] == "Cash"

    def test_transfer_row_flagged(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row(transfer='true', category='TRANSFER', amount='300000.00', type_='Income')}\n",
        )
        rows, _, _ = parse(csv)
        assert rows[0]["is_transfer"] is True

    def test_payee_preferred_over_note(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row(payee='McDonald', note='fast food')}\n",
        )
        rows, _, _ = parse(csv)
        assert rows[0]["merchant"] == "McDonald"

    def test_note_used_when_payee_empty(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row(payee='', note='beli sate')}\n",
        )
        rows, _, _ = parse(csv)
        assert rows[0]["merchant"] == "beli sate"

    def test_multiple_rows(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n"
            f"{_make_row(amount='-10000.00')}\n"
            f"{_make_row(amount='-20000.00')}\n",
        )
        rows, skipped, _ = parse(csv)
        assert len(rows) == 2
        assert skipped == 0


class TestMissingColumns:
    def test_missing_required_column_raises(self, tmp_path):
        # Header missing "transfer"
        bad_header = "account;category;currency;amount;type;note;date"
        csv = _write_csv(
            tmp_path,
            f"{bad_header}\nCash;Food;IDR;-1000;Expenses;test;2024-01-01 00:00:00\n",
        )
        with pytest.raises(ValueError, match="missing required columns"):
            parse(csv)

    def test_error_message_includes_diff(self, tmp_path):
        bad_header = "account;category;currency;amount;type;note;date"
        csv = _write_csv(
            tmp_path,
            f"{bad_header}\nCash;Food;IDR;-1000;Expenses;test;2024-01-01 00:00:00\n",
        )
        with pytest.raises(ValueError) as exc_info:
            parse(csv)
        msg = str(exc_info.value)
        assert "expected:" in msg
        assert "found:" in msg

    def test_all_required_columns_present(self, tmp_path):
        # Smoke-test that REQUIRED_COLUMNS is a subset of the Wallet header
        wallet_cols = set(MINIMAL_HEADER.lower().split(";"))
        missing = REQUIRED_COLUMNS - wallet_cols
        assert not missing, f"REQUIRED_COLUMNS not covered by Wallet header: {missing}"


class TestMultiCurrency:
    def test_foreign_currency_row_skipped(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n"
            f"{_make_row(currency='IDR', amount='-50000')}\n"
            f"{_make_row(currency='USD', amount='-10.00')}\n",
        )
        rows, skipped, currency = parse(csv)
        assert len(rows) == 1
        assert skipped == 1
        assert currency == "IDR"

    def test_explicit_primary_currency_filters(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n"
            f"{_make_row(currency='IDR')}\n"
            f"{_make_row(currency='USD')}\n",
        )
        rows, skipped, _ = parse(csv, primary_currency="IDR")
        assert len(rows) == 1
        assert skipped == 1

    def test_all_same_currency_none_skipped(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n"
            f"{_make_row(currency='IDR')}\n"
            f"{_make_row(currency='IDR')}\n"
            f"{_make_row(currency='IDR')}\n",
        )
        rows, skipped, _ = parse(csv)
        assert len(rows) == 3
        assert skipped == 0


class TestIsTransferDetection:
    def test_false_string_is_false(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row(transfer='false')}\n",
        )
        rows, _, _ = parse(csv)
        assert rows[0]["is_transfer"] is False

    def test_true_string_is_true(self, tmp_path):
        csv = _write_csv(
            tmp_path,
            f"{MINIMAL_HEADER}\n{_make_row(transfer='true')}\n",
        )
        rows, _, _ = parse(csv)
        assert rows[0]["is_transfer"] is True


class TestEmptyAndEdgeCases:
    def test_empty_file_raises(self, tmp_path):
        csv = tmp_path / "empty.csv"
        csv.write_text("")
        with pytest.raises(ValueError, match="empty"):
            parse(csv)

    def test_header_only_returns_empty_rows(self, tmp_path):
        csv = _write_csv(tmp_path, f"{MINIMAL_HEADER}\n")
        rows, skipped, currency = parse(csv)
        assert rows == []
        assert skipped == 0
        assert currency == ""
