"""Phase 39 vision path (D-11, D-11a): image preparation, then a tool-less read validated in Python.
Synthetic Pillow-drawn images only; no test reaches a real model."""
import io

import pytest
from PIL import Image

from backend import attachments as att
from backend.tests import doc_fixtures as fx


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_gps_fixture_really_carries_gps():
    assert _open(fx.receipt_png_with_gps()).getexif().get_ifd(0x8825)


def test_image_is_reencoded_without_exif():
    (out,) = att.prepare_images(fx.receipt_png_with_gps(), "image")
    im = _open(out)
    assert im.format == "PNG" and not im.getexif() and max(im.size) <= 2000


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "PNG"])
def test_jpeg_webp_png_accepted(fmt):
    (out,) = att.prepare_images(fx.receipt_png(fmt=fmt), "image")
    assert _open(out).format == "PNG"


def test_large_image_downscaled_keeping_aspect():
    (out,) = att.prepare_images(fx.receipt_png(size=(3000, 1000)), "image")
    assert _open(out).size == (2000, 667)


def test_pixel_cap_refuses_bomb(monkeypatch):
    monkeypatch.setattr(att, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(att.ImageRefused, match="too large to read safely"):
        att.prepare_images(fx.receipt_png(size=(200, 200)), "image")


def test_garbage_bytes_refused():
    with pytest.raises(att.ImageRefused, match="could not be read"):
        att.prepare_images(b"\x89PNG\r\n\x1a\nnot really", "image")


def test_scanned_pdf_capped_at_five_pages():
    out = att.prepare_images(fx.scanned_pdf(pages=7), "pdf_scanned")
    assert len(out) == 5 and all(_open(o).format == "PNG" for o in out)


def test_scanned_pdf_oversized_page_refused(monkeypatch):
    monkeypatch.setattr(att, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(att.ImageRefused, match="too large to read safely"):
        att.prepare_images(fx.scanned_pdf(), "pdf_scanned")


def test_scanned_pdf_password_forwarded(monkeypatch):
    seen = []

    def boom(data, password):
        seen.append(password)
        raise att.NeedsPassword(True)

    monkeypatch.setattr(att, "open_pdf", boom)
    with pytest.raises(att.NeedsPassword):
        att.prepare_images(b"%PDF-", "pdf_scanned", "zz-pw")
    assert seen == ["zz-pw"]
