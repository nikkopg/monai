"""Phase 39 vision path (D-11, D-11a): image preparation, then a tool-less read validated in Python.
Synthetic Pillow-drawn images only; no test reaches a real model."""
import asyncio
import io
import json
import logging

import httpx
import pytest
from llama_index.core.llms import ChatMessage, ChatResponse, ImageBlock, TextBlock
from PIL import Image

from backend import attachments as att
from backend.tests import doc_fixtures as fx
from backend.tests.chat_stubs import Err429


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


# ---------------------------------------------------------------------------
# read_receipt: one tool-less call, a Python-only validator
# ---------------------------------------------------------------------------

TARGET = ("ollama", "gemma4:31b-cloud", "http://localhost:11434")
READING = {
    "date": "2026-03-14", "total": "50.500", "currency": "Rp", "merchant": "ZZ Synthetic Shop",
    "items": [{"name": "ZZ tea", "amount": "20.500"}, {"name": "ZZ rice", "amount": "30.000"}],
    "address": "x",
}


class FakeVisionLLM:
    def __init__(self, content="", exc=None):
        self.content, self.exc, self.calls = content, exc, []

    async def achat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.exc:
            raise self.exc
        return ChatResponse(message=ChatMessage(role="assistant", content=self.content))


@pytest.fixture
def llm(monkeypatch):
    fake = FakeVisionLLM()
    monkeypatch.setattr("backend.query._get_llm", lambda: fake)
    monkeypatch.setattr(att, "vision_capable", lambda *a: True)
    return fake


def read(llm, content, images=1, currency="IDR"):
    llm.content = content if isinstance(content, str) else "```json\n" + json.dumps(content) + "\n```"
    return asyncio.run(att.read_receipt([b"png"] * images, kind="image", account_currency=currency, target=TARGET))


def test_fenced_reading_becomes_one_flagged_row(llm):
    p = read(llm, READING)
    assert (p.kind, p.status) == ("image", "llm_read")
    (row,) = p.rows
    assert (row["date"], row["amount"], row["merchant"]) == ("2026-03-14", "-50500", "ZZ Synthetic Shop")
    assert row["llm_read"] is True and row["assumptions"] == []
    assert row["raw_line"] is None and p.meta["invariant"] == "none" and p.meta["row_count"] == 1
    assert p.text.startswith("{") and "```" not in p.text


def test_items_that_dont_add_up_are_advisory(llm):
    bad = {**READING, "items": [{"name": "ZZ tea", "amount": "20.500"}, {"name": "ZZ rice", "amount": "19.500"}]}
    p = read(llm, bad)
    assert p.status == "llm_read" and p.meta["invariant"] == "none"
    assert p.rows[0]["assumptions"] == ["The line items don't add up to the total."]
    assert p.meta["items_sum_matches"] is False


def test_currency_missing_is_assumed_idr_and_foreign_is_refused(llm):
    p = read(llm, {**READING, "currency": None})
    assert p.status == "llm_read" and p.rows[0]["assumptions"] == ["Currency not printed; assumed IDR."]
    p = read(llm, {**READING, "currency": "USD"})
    assert p.status == "refused" and p.note == "The receipt is in USD, not IDR; nothing can be proposed."
    assert p.text  # still askable


def test_json_number_total_never_goes_through_binary_float(llm):
    p = read(llm, '{"date": "2026-03-14", "total": 50500, "items": []}')
    assert p.rows[0]["amount"] == "-50500"
    p = read(llm, '{"date": "2026-03-14", "total": 50.5, "items": []}')
    assert p.rows[0]["amount"] == "-50.5"


@pytest.mark.parametrize(
    "content, keeps_text",
    [
        ("I can't read this image.", False),
        ('{"date": "2026-03-14", "items": []}', True),                      # no total
        ({**READING, "date": "14/03/2026"}, True),                          # not ISO
        ({**READING, "date": "2026-02-30"}, True),                          # not a real day
        ({**READING, "total": "abc"}, True),
        ({**READING, "total": "0"}, True),
    ],
)
def test_invalid_reading_refused_with_fixed_note(llm, content, keeps_text):
    p = read(llm, content)
    assert p.status == "refused" and p.rows == [] and p.note
    assert "abc" not in p.note and "14/03" not in p.note
    assert bool(p.text) is keeps_text


def test_non_vision_model_refused_and_never_called(llm, monkeypatch):
    monkeypatch.setattr(att, "vision_capable", lambda *a: False)
    p = read(llm, READING)
    assert p.status == "refused" and p.rows == [] and not p.askable
    assert p.note == "The configured model (Ollama Cloud (gemma4:31b-cloud)) can't read images. Nothing was read."
    assert llm.calls == []


@pytest.mark.parametrize(
    "exc, note",
    [
        (Err429(), "The model quota is exhausted; the file was not read. Try again later."),
        (asyncio.TimeoutError(), "The model took too long to read the image."),
        (RuntimeError("zz-secret"), "The model could not read the file right now."),
    ],
)
def test_provider_errors_are_refusals(llm, exc, note):
    llm.exc = exc
    p = read(llm, "")
    assert p.status == "refused" and p.note == note and not p.askable


def test_one_call_one_message_no_tools_no_format(llm):
    read(llm, READING, images=5)
    ((messages, kwargs),) = llm.calls
    (msg,) = messages
    assert [type(b) for b in msg.blocks] == [TextBlock] + [ImageBlock] * 5
    assert kwargs == {}


def test_hanging_model_hits_the_wait_for(llm, monkeypatch):
    async def slow(*a, **k):
        await asyncio.sleep(10)

    llm.achat = slow
    monkeypatch.setattr(att, "VISION_TIMEOUT", 0.05)
    p = read(llm, "")
    assert p.note == "The model took too long to read the image."


def test_vision_capable_probes_ollama_show(monkeypatch):
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(url=url, json=json, timeout=timeout)
        return httpx.Response(200, json={"capabilities": ["completion", "vision"]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    assert att.vision_capable("ollama", "m", "http://h:1") is True
    assert seen["url"] == "http://h:1/api/show" and seen["json"] == {"model": "m"} and seen["timeout"] == 5

    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: httpx.Response(200, json={"capabilities": ["completion"]}, request=httpx.Request("POST", "http://x"))
    )
    assert att.vision_capable("ollama", "m", "http://h:1") is False


def test_vision_capable_cloud_providers_need_no_call(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no call expected"))
    assert att.vision_capable("claude", "m", "") is True and att.vision_capable("openai", "m", "") is True


def test_vision_capable_connection_error_false_and_logs_class_only(monkeypatch, caplog):
    def post(*a, **k):
        raise httpx.ConnectError("zz-secret-detail")

    monkeypatch.setattr(httpx, "post", post)
    with caplog.at_level(logging.WARNING):
        assert att.vision_capable("ollama", "m", "http://h:1") is False
    assert "ConnectError" in caplog.text and "zz-secret-detail" not in caplog.text


def test_read_vision_json_shapes():
    r = att.read_vision_json('```json\n{"date":"2026-03-14","total":"1","extra":1}\n```')
    assert (r.date, r.total, r.items) == ("2026-03-14", "1", [])
    r = att.read_vision_json('Here you go: {"date":"2026-03-14","total":"1"} thanks')  # braces fallback
    assert r.total == "1"
    for bad in ("nope", "[1]", '{"date": "2026-03-14"}'):
        with pytest.raises(ValueError):
            att.read_vision_json(bad)
