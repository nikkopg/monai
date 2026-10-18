"""Phase 39 text-PDF statement parser (D-09, D-09a, D-10); synthetic generated PDFs only."""
import io

import pdfplumber
import pytest

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
