"""Phase 39 code-only CSV attachment parser (D-08, D-08a, D-12); synthetic values only."""
import pytest

from backend import attachments as att
from backend.attachments import SEP_ASSUMPTION, DMY_ASSUMPTION, parse_csv_attachment
from backend.tests import doc_fixtures as fx


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the CSV parser must not call the LLM")

    monkeypatch.setattr("backend.query._get_llm", boom)


def parse(text, account="ZZ Cash", cur="IDR", encoding="utf-8"):
    data = text if isinstance(text, bytes) else text.encode(encoding)
    return parse_csv_attachment(data, account_name=account, account_currency=cur)


def test_wallet_keeps_picked_account_non_transfer_rows():
    p = parse(fx.WALLET_CSV)
    assert p.kind == "csv" and p.status == "ok"
    assert [r["amount"] for r in p.rows] == ["-45000.00", "3000000.00"]
    assert [r["date"] for r in p.rows] == ["2026-03-05", "2026-03-06"]
    assert p.rows[0]["merchant"] == "ZZ Warung" and p.rows[0]["notes"] == "lunch"
    assert p.rows[0]["category"] == "Food"
    assert p.rows[1]["merchant"] == "bonus"  # no payee: the note stands in
    assert p.meta["format"] == "wallet"
    assert p.meta["skipped_other_account"] == 2 and p.meta["skipped_transfer"] == 1
    assert "2" in p.note and "1" in p.note
    assert p.askable


def test_wallet_account_match_is_casefold():
    assert len(parse(fx.WALLET_CSV, account="zz cash").rows) == 2


def test_wallet_currency_mismatch_refused():
    p = parse(fx.WALLET_USD_CSV)
    assert p.status == "refused" and p.rows == []
    assert p.note == "1 row is in USD, not IDR; nothing was proposed."
    assert p.askable


def test_generic_indonesian():
    p = parse(fx.GENERIC_ID_CSV)
    assert p.status == "ok"
    assert [r["amount"] for r in p.rows] == ["-1250000.00", "2000000.00", "-15000.50"]
    assert [r["date"] for r in p.rows] == ["2026-03-25", "2026-03-26", "2026-03-02"]
    assert p.meta["separator"] == {"sep": ",", "evidence": "values"}
    assert p.meta["date_order"] == {"order": "dmy", "evidence": "values"}
    assert p.meta["delimiter"] == ";" and p.meta["format"] == "generic"
    assert p.meta["assumptions"] == [] and p.rows[0]["assumptions"] == []
    assert p.rows[0]["merchant"] == "ZZ Kopi" and p.rows[0]["llm_read"] is False


def test_generic_us_quoted_commas():
    p = parse(fx.GENERIC_US_CSV)
    assert p.status == "ok"
    assert [r["amount"] for r in p.rows] == ["-1250.50", "2000.00"]
    assert p.rows[0]["merchant"] == "ZZ Store, Main"
    assert p.rows[0]["date"] == "2026-03-25"
    assert p.meta["separator"]["sep"] == "." and p.meta["date_order"]["order"] == "mdy"


def test_no_evidence_flags_every_row():
    p = parse(fx.NO_EVIDENCE_CSV)
    assert p.status == "ok"
    assert [r["amount"] for r in p.rows] == ["-1250", "-20000"]  # "." read as thousands
    assert p.rows[0]["date"] == "2026-04-03"  # day first
    for r in p.rows:
        assert SEP_ASSUMPTION in r["assumptions"] and DMY_ASSUMPTION in r["assumptions"]
    assert p.meta["assumptions"] == [SEP_ASSUMPTION, DMY_ASSUMPTION]
    assert p.meta["separator"]["evidence"] == "none" and p.meta["date_order"]["evidence"] == "none"


def test_contradictory_dates_refused():
    p = parse(fx.CONTRADICTORY_DATES_CSV)
    assert p.status == "refused"
    assert p.note == "Dates in this file can't be read in one order."


def test_ambiguous_headers_refused_with_headers_listed():
    p = parse(fx.AMBIGUOUS_HEADERS_CSV)
    assert p.status == "refused"
    assert "Amount" in p.note and "Jumlah" in p.note


def test_unmapped_headers_refused():
    p = parse(fx.UNMAPPED_CSV)
    assert p.status == "refused"
    assert p.note.startswith("No date column. Headers found:")
    assert "Description" in p.note


def test_both_debit_and_credit_refused_with_line():
    p = parse(fx.BOTH_FILLED_CSV)
    assert p.status == "refused" and "Line 3" in p.note


def test_unparseable_amount_refused_with_line():
    p = parse(fx.BAD_AMOUNT_CSV)
    assert p.status == "refused" and "Line 3" in p.note
    assert "12abc" not in p.note  # no cell value is echoed


def test_over_500_rows_refused_but_askable():
    p = parse(fx.over_500_csv())
    assert p.status == "refused" and p.rows == []
    assert p.note == "501 rows exceed the 500-row batch limit."
    assert p.askable and "ZZ Row 500" in p.text


def test_utf16_and_cp1252_decode():
    p = parse(fx.GENERIC_US_CSV.encode("utf-16"))
    assert p.status == "ok" and p.meta["encoding"] == "utf-16"
    p = parse(fx.GENERIC_US_CSV.replace("Main", "Café").encode("cp1252"))
    assert p.meta["encoding"] == "cp1252" and "Café" in p.rows[0]["merchant"]


def test_raw_line_capped_and_text_kept():
    p = parse(fx.GENERIC_US_CSV)
    assert p.text.startswith("Date,Description,Amount")
    assert len(p.rows[0]["raw_line"]) <= 200
    long = "Date,Description,Amount\n2026-03-05," + "ZZ" * 300 + ",-1000\n"
    assert len(parse(long).rows[0]["raw_line"]) == 200


def test_empty_and_header_only_refused():
    assert parse("").status == "refused"
    assert parse("Date,Description,Amount\n").status == "refused"


def test_row_dicts_follow_the_contract():
    for r in parse(fx.WALLET_CSV).rows:
        assert set(r) == {"date", "amount", "merchant", "notes", "category", "raw_line", "llm_read", "assumptions"}
        assert isinstance(r["amount"], str)


def test_date_order_inference_unit():
    assert att.infer_date_order(["2026-03-05"]) == ("iso", "values")
    assert att.infer_date_order([]) == ("dmy", "none")
    assert att.parse_date("5/3/26", "dmy") == "2026-03-05"
    assert att.parse_date("5/3/70", "mdy") == "1970-05-03"
