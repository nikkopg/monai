"""Phase 39 text-PDF statement parser (D-09, D-09a, D-10); synthetic generated PDFs only."""
import base64
import io
from datetime import date
from decimal import Decimal

import pdfplumber
import pytest

from backend import attachments as att
from backend.tests import doc_fixtures as fx


def _text(data: bytes, page: int = 0) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return pdf.pages[page].extract_text()


def test_fixtures_roundtrip_through_pdfplumber():
    assert "SALDO AWAL" in _text(fx.bca_like_statement())
    assert "TOTAL DEBIT" in _text(fx.mandiri_like_statement())
    with pdfplumber.open(io.BytesIO(fx.bca_like_statement(pages_n=3))) as pdf:
        assert len(pdf.pages) == 3
    with pdfplumber.open(io.BytesIO(fx.many_pages_pdf(4))) as pdf:
        assert len(pdf.pages) == 4
    with pdfplumber.open(io.BytesIO(fx.scanned_pdf())) as pdf:
        assert pdf.pages[0].chars == [] and len(pdf.pages[0].images) == 1


@pytest.mark.skipif(fx.ENC_PDF_B64 is None, reason="no encrypted fixture: pypdf was not approved")
def test_encrypted_fixture_needs_a_password():
    import base64

    from pdfplumber.utils.exceptions import PdfminerException

    with pytest.raises(PdfminerException):
        pdfplumber.open(io.BytesIO(base64.b64decode(fx.ENC_PDF_B64)))


# --- the parser -------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the PDF parser must not call the LLM")

    monkeypatch.setattr("backend.query._get_llm", boom)


def parse(data, password=None):
    return att.parse_pdf_statement(data, password, account_currency="IDR")


def refused(data, note=None, startswith=None):
    p = parse(data)
    assert p.status == "refused" and p.rows == []
    if note:
        assert p.note == note
    if startswith:
        assert p.note.startswith(startswith), p.note
    return p


def test_bca_like_ok_every_row_has_a_balance():
    p = parse(fx.bca_like_statement())
    assert p.kind == "pdf_text" and p.status == "ok" and p.askable
    assert [r["amount"] for r in p.rows] == ["-50500.00", "2000000.00", "-15000.00"]
    assert [r["date"] for r in p.rows] == ["2026-03-02", "2026-03-05", "2026-03-09"]
    assert p.rows[0]["merchant"].startswith("ZZ KOPI TRSF") and "REF 5000" in p.rows[0]["raw_line"]
    assert p.rows[0]["llm_read"] is False and p.rows[0]["assumptions"] == []
    m = p.meta
    assert m["opening"] == "5000000.00" and m["closing"] == "6934500.00"
    assert m["separator"]["sep"] == "." and m["layout"] == "bca_like" and m["pages"] == 1
    assert m["invariant"] == "running balance verified" and m["row_count"] == 3
    assert m["period"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert m["hidden_white_chars"] == 0 and m["dropped_chars"] == 0


def test_mandiri_like_signs_from_the_balance_delta():
    p = parse(fx.mandiri_like_statement())
    assert p.status == "ok" and p.meta["layout"] == "mandiri_like" and p.meta["separator"]["sep"] == ","
    assert [r["amount"] for r in p.rows] == ["-1250000.00", "2000000.00", "-15000.50"]
    assert p.meta["invariant"] == "running balance verified"


def test_bca_sparse_balances_and_unmarked_credit():
    rows = (
        (date(2026, 3, 2), "ZZ A", Decimal("-10000.00")),
        (date(2026, 3, 3), "ZZ B", Decimal("30000.00")),
        (date(2026, 3, 4), "ZZ C", Decimal("5000.00")),
        (date(2026, 3, 5), "ZZ D", Decimal("-2500.50")),
    )
    p = parse(fx.bca_like_statement(rows, sparse=True))
    assert p.status == "ok" and p.meta["invariant"] == "balance verified"
    assert [r["amount"] for r in p.rows] == ["-10000.00", "30000.00", "5000.00", "-2500.50"]
    refused(fx.bca_like_statement(rows, sparse=True, tamper="closing"), "Closing balance off by -500.00.")
    refused(fx.bca_like_statement(rows, sparse=True, tamper="balance"), startswith="Running balance off at 2026-03-03")


def test_tampered_closing_names_the_difference_in_the_files_style():
    p = refused(fx.bca_like_statement(tamper="closing"), "Closing balance off by -500.00.")
    assert p.askable and "SALDO AKHIR" in p.text
    refused(fx.mandiri_like_statement(tamper="closing"), "Closing balance off by -500,00.")


def test_tampered_running_balance():
    refused(
        fx.bca_like_statement(tamper="balance"),
        "Running balance off at 2026-03-05: expected 6,949,500.00 got 6,949,600.00.",
    )
    refused(fx.mandiri_like_statement(tamper="balance"), startswith="Running balance off at 2026-03-05")


def test_dropped_row_is_refused():
    refused(fx.bca_like_statement(tamper="drop_row"), startswith="Running balance off")
    refused(fx.mandiri_like_statement(tamper="drop_row"), startswith="Running balance off")


def test_tampered_footer_is_refused():
    refused(fx.bca_like_statement(tamper="footer"), "The statement's footer totals don't match its rows.")
    refused(fx.mandiri_like_statement(tamper="footer"), "The statement's footer totals don't match its rows.")


def test_missing_opening_closing_and_period():
    refused(fx.bca_like_statement(tamper="no_opening"), "No opening balance found.")
    refused(fx.bca_like_statement(tamper="no_closing"), "No closing balance found.")
    p = refused(
        fx.bca_like_statement(tamper="no_period"),
        "No statement period found, so the year of each row is unknown.",
    )
    assert p.askable


def test_december_to_january_rolls_the_year():
    rows = (
        (date(2025, 12, 28), "ZZ A", Decimal("-1000.00")),
        (date(2026, 1, 2), "ZZ B", Decimal("2000.00")),
    )
    p = parse(fx.bca_like_statement(rows, period=(date(2025, 12, 1), date(2026, 1, 31))))
    assert p.status == "ok" and [r["date"] for r in p.rows] == ["2025-12-28", "2026-01-02"]


def test_multi_page_statement_matches_single_page():
    one = parse(fx.bca_like_statement())
    three = parse(fx.bca_like_statement(pages_n=3))
    assert three.status == "ok" and three.meta["pages"] == 3
    assert [(r["date"], r["amount"]) for r in three.rows] == [(r["date"], r["amount"]) for r in one.rows]
    two = parse(fx.mandiri_like_statement(pages_n=2))
    assert two.status == "ok" and len(two.rows) == 3


def test_row_with_no_marker_and_no_balance_is_refused_not_guessed():
    refused(
        fx.mandiri_like_statement(tamper="no_balance"),
        "Row 2 (2026-03-05) has no debit or credit marker and no balance to tell its direction.",
    )


def test_page_cap():
    p = refused(fx.many_pages_pdf(61), "61 pages exceed the 60-page limit.")
    assert p.text == "" and not p.askable


def test_hidden_text_is_counted_or_dropped():
    p = parse(fx.hidden_white_text_pdf())
    assert p.status == "ok"
    assert p.meta["hidden_white_chars"] > 0 and p.meta["dropped_chars"] > 0
    assert p.text.count(fx.HIDDEN_LINE) == 1  # the white line stays, the 1 pt line goes
    assert all(fx.HIDDEN_LINE not in (r["merchant"] or "") for r in p.rows)


def test_classify_pdf():
    assert att.classify_pdf(fx.scanned_pdf(), None) == ("pdf_scanned", 1)
    assert att.classify_pdf(fx.bca_like_statement(), None) == ("pdf_text", 1)
    assert att.classify_pdf(fx.scanned_pdf(2), None) == ("pdf_scanned", 2)


def test_password_error_maps_without_leaking(monkeypatch, caplog):
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    def boom(*a, **k):
        raise PdfminerException(PDFPasswordIncorrect())

    monkeypatch.setattr(pdfplumber, "open", boom)
    secret = "zz-sentinel-pw"
    with pytest.raises(att.NeedsPassword) as e:
        att.open_pdf(b"%PDF-", secret)
    assert e.value.wrong is True and secret not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__
    with pytest.raises(att.NeedsPassword) as e:
        att.open_pdf(b"%PDF-", None)
    assert e.value.wrong is False
    with pytest.raises(att.NeedsPassword):
        parse(b"%PDF-", secret)
    assert secret not in caplog.text


needs_real = pytest.mark.skipif(fx.ENC_PDF_B64 is None, reason="no encrypted fixture: pypdf was not approved")


@needs_real
def test_real_encrypted_pdf_without_and_with_wrong_password():
    data = base64.b64decode(fx.ENC_PDF_B64)
    with pytest.raises(att.NeedsPassword) as e:
        att.open_pdf(data, None)
    assert e.value.wrong is False
    with pytest.raises(att.NeedsPassword) as e:
        att.open_pdf(data, "zz-wrong")
    assert e.value.wrong is True


@needs_real
def test_real_encrypted_pdf_opens_with_the_right_password(caplog):
    p = parse(base64.b64decode(fx.ENC_PDF_B64), fx.ENC_PDF_PASSWORD)
    assert p.status == "ok"
    assert fx.ENC_PDF_PASSWORD not in repr(p.meta) + (p.note or "") + caplog.text


@pytest.mark.parametrize(
    "line, want",
    [
        ("PERIODE : 01/12/2025 - 31/01/2026", (date(2025, 12, 1), date(2026, 1, 31))),
        ("Periode Mei 2026", (date(2026, 5, 1), date(2026, 5, 31))),
        ("Period: Agu 2025 - Okt 2025", (date(2025, 8, 1), date(2025, 10, 31))),
        ("no such line", None),
    ],
)
def test_period_forms(line, want):
    assert att._period(line) == want


def test_row_outside_the_period_is_refused():
    rows = ((date(2026, 5, 2), "ZZ A", Decimal("-1000.00")),)
    refused(fx.bca_like_statement(rows), startswith="Row 1 (02/05) has a date")
