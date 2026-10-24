"""Phase 39 magic-byte sniffing and filename sanitising (D-06); synthetic bytes only."""
import pytest

from backend.attachments import safe_filename, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP" + b"VP8 "
CSV = b"Date,Description,Amount\n2026-03-05,ZZ Toko,-1000\n"


@pytest.mark.parametrize(
    "data,want",
    [
        (b"%PDF-1.4\n%junk", ("pdf", "application/pdf")),
        (b"x" * 300 + b"%PDF-1.7", ("pdf", "application/pdf")),
        (PNG, ("image", "image/png")),
        (JPEG, ("image", "image/jpeg")),
        (WEBP, ("image", "image/webp")),
        (CSV, ("csv", "text/csv")),
        (b"\xef\xbb\xbf" + CSV, ("csv", "text/csv")),
        (CSV.decode().encode("utf-16"), ("csv", "text/csv")),
        (CSV.replace(b"Toko", b"Caf\xe9"), ("csv", "text/csv")),
        (b"PK\x03\x04\x14\x00\x00\x00", None),
        (b"Date,Amount\n\x00\x00junk", None),
        (b"just one line with no delimiter", None),
        (b"", None),
    ],
)
def test_sniff(data, want):
    assert sniff(data) == want


@pytest.mark.parametrize(
    "name,want",
    [
        ("../../x.csv", "x.csv"),
        ("C:\\Users\\a\\b.pdf", "b.pdf"),
        ("a\u202e\x00b.csv", "ab.csv"),
        ("n" * 200, "n" * 80),
        ("", "file"),
    ],
)
def test_safe_filename(name, want):
    assert safe_filename(name) == want
