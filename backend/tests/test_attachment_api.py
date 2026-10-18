"""Phase 39 upload route and ingest; synthetic values; monai_test only."""
import hashlib
import uuid

import pytest
from sqlalchemy import text

from backend import attachments as att
from backend.attachments import NeedsPassword, Parsed
from backend.db import SessionLocal
from backend.models import Attachment, Thread
from backend.tests import doc_fixtures as fx

TARGET = ("ollama", "gemma4:31b-cloud", "http://localhost:11434")


async def _ingest(data, hint, password=None):
    return await att.ingest(
        data, kind_hint=hint, account_name="ZZ Cash", account_currency="IDR", password=password, target=TARGET
    )


# ---------------------------------------------------------------------------
# Task 1: ingest dispatcher, summary_for, store
# ---------------------------------------------------------------------------

async def test_ingest_csv_summary():
    p = await _ingest(fx.GENERIC_ID_CSV.encode(), "csv")
    assert (p.kind, p.status) == ("csv", "ok")
    assert att.summary_for(p) == f"{len(p.rows)} rows. Parsed on this computer."


async def test_ingest_pdf_summaries():
    p = await _ingest(fx.bca_like_statement(), "pdf")
    assert (p.kind, p.status) == ("pdf_text", "ok")
    assert att.summary_for(p) == f"{len(p.rows)} rows. Running balance verified."
    sparse = await _ingest(fx.bca_like_statement(sparse=True), "pdf")
    assert att.summary_for(sparse) == f"{len(sparse.rows)} rows. Balance verified."


async def test_ingest_tampered_statement_is_refused_with_its_note():
    p = await _ingest(fx.bca_like_statement(tamper="closing"), "pdf")
    assert p.status == "refused" and p.note
    assert att.summary_for(p) == p.note


def _fake_receipt(monkeypatch, kind_seen):
    async def fake(images, *, kind, account_currency, target):
        kind_seen.append((kind, len(images)))
        row = {"date": "2026-03-14", "amount": "-50500.00", "merchant": "ZZ", "notes": None, "category": None,
               "raw_line": None, "llm_read": True, "assumptions": []}
        return Parsed(kind, "llm_read", [row], "read", {})

    monkeypatch.setattr(att, "read_receipt", fake)


async def test_ingest_image_goes_to_vision(monkeypatch):
    seen = []
    _fake_receipt(monkeypatch, seen)
    p = await _ingest(fx.receipt_png(), "image")
    assert (p.kind, p.status) == ("image", "llm_read") and seen == [("image", 1)]
    assert att.summary_for(p) == "1 row read by the model from an image. It will be flagged for review."


async def test_ingest_scanned_pdf_goes_to_vision(monkeypatch):
    seen = []
    _fake_receipt(monkeypatch, seen)
    p = await _ingest(fx.scanned_pdf(), "pdf")
    assert p.kind == "pdf_scanned" and seen == [("pdf_scanned", 1)]


@pytest.mark.parametrize("password,wrong", [(None, False), ("zz-wrong", True)])
async def test_ingest_password_propagates(monkeypatch, password, wrong):
    def locked(data, pw):
        raise NeedsPassword(bool(pw))

    monkeypatch.setattr(att, "classify_pdf", locked)
    with pytest.raises(NeedsPassword) as e:
        await _ingest(b"%PDF-1.4", "pdf", password)
    assert e.value.wrong is wrong


async def test_ingest_image_refused_becomes_refused_parsed():
    p = await _ingest(b"\x89PNG\r\n\x1a\nnot really a png", "image")
    assert (p.kind, p.status) == ("image", "refused") and p.note == "The image could not be read."
    assert att.summary_for(p) == p.note


def test_summary_singular():
    one = Parsed("csv", "ok", [{}], "", {})
    assert att.summary_for(one) == "1 row. Parsed on this computer."


@pytest.fixture()
def thread_id():
    db = SessionLocal()
    t = Thread(title="zz39-store")
    db.add(t)
    db.commit()
    yield t.id
    db.execute(text("DELETE FROM threads WHERE id = :t"), {"t": t.id})
    db.commit()
    db.close()


def test_store_inserts_one_row(thread_id):
    data = fx.GENERIC_ID_CSV.encode()
    parsed = Parsed("csv", "ok", [{"amount": "1.00"}], "zz text", {"k": 1}, None)
    with SessionLocal() as db:
        a = att.store(db, thread_id=thread_id, filename="../zz/stmt.csv", mime="text/csv", kind="csv", data=data,
                      parsed=parsed, account_id=None)
        db.commit()
        row = db.get(Attachment, a.id)
        assert row.thread_id == thread_id and row.filename == "stmt.csv"
        assert row.sha256 == hashlib.sha256(data).hexdigest() and row.size_bytes == len(data)
        assert row.raw == data and row.extracted_text == "zz text" and row.rows == [{"amount": "1.00"}]
        assert row.meta == {"k": 1, "summary": "1 row. Parsed on this computer."}
        assert (row.parse_status, row.parse_note, row.kind, row.mime) == ("ok", None, "csv", "text/csv")
