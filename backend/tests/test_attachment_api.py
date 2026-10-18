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
    assert p.status == "refused" and p.note and p.askable
    assert att.summary_for(p) == f"{p.note} You can still ask questions about it."


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
    assert att.summary_for(p) == f"{p.note} Nothing from this file can be used. Remove it and try another."


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


# ---------------------------------------------------------------------------
# Task 2: the routes
# ---------------------------------------------------------------------------

import json  # noqa: E402
import logging  # noqa: E402
import secrets  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from backend import attachments_api, settings  # noqa: E402
from backend import query as q  # noqa: E402
from backend.models import Account  # noqa: E402
from backend.tests.test_write_endpoints import _cleanup_account  # noqa: E402

PNG = fx.receipt_png()
MIB = 1024 * 1024


@pytest.fixture()
def env(client, api_key):
    """(client, auth headers, liquid account id, created thread ids); cleaned up afterwards."""
    db = SessionLocal()
    sfx = secrets.token_hex(3)
    cash = Account(name=f"ZZ39 Up Cash {sfx}", type="liquid", currency="IDR")
    inv = Account(name=f"ZZ39 Up Inv {sfx}", type="investment", currency="IDR")
    db.add_all([cash, inv])
    db.commit()
    made: list = []
    yield SimpleNamespace(client=client, h={"MONAI_API_KEY": api_key}, cash=cash.id, inv=inv.id, made=made)
    db.rollback()
    db.execute(text("DELETE FROM threads WHERE id = ANY(:t)"), {"t": made})
    db.commit()
    _cleanup_account(db, cash.name)
    _cleanup_account(db, inv.name)
    db.close()


def up(env, data, *, tid=None, name="stmt.csv", account=None, password=None, headers=True):
    """POST one upload; returns (response, thread id)."""
    tid = tid or uuid.uuid4()
    if tid not in env.made:
        env.made.append(tid)
    form = {"account_id": str(account or env.cash)}
    if password is not None:
        form["password"] = password
    r = env.client.post(
        f"/threads/{tid}/attachments", files={"file": (name, data, "application/octet-stream")}, data=form,
        headers=env.h if headers else {},
    )
    return r, tid


def rows_for(tid):
    with SessionLocal() as db:
        return db.execute(text("SELECT count(*) FROM attachments WHERE thread_id = :t"), {"t": tid}).scalar()


def test_both_routes_need_the_api_key(env):
    r, tid = up(env, b"a;b\n1;2\n", headers=False)
    assert r.status_code == 401 and rows_for(tid) == 0
    assert env.client.get("/attachments/locality").status_code == 401


def test_upload_creates_the_thread_and_a_second_upload_joins_it(env):
    r, tid = up(env, fx.GENERIC_ID_CSV.encode())
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"] == str(tid) and (body["kind"], body["status"], body["row_count"]) == ("csv", "ok", 3)
    assert body["summary"] == "3 rows. Parsed on this computer."
    assert "askable" not in body and body["attachment_id"]
    with SessionLocal() as db:
        assert db.get(Thread, tid).title == ""
    r2, _ = up(env, fx.GENERIC_US_CSV.encode(), tid=tid)
    assert r2.status_code == 200 and rows_for(tid) == 2


def _stub_ingest(monkeypatch, calls):
    async def fake(data, **kw):
        calls.append(len(data))
        return Parsed("csv", "ok", [], "", {})

    monkeypatch.setattr(attachments_api, "ingest", fake)


def _sized(n):
    return b"a,b\n" + b"1" * (n - 4)


def test_size_boundary_is_exact(env, monkeypatch):
    calls: list = []
    _stub_ingest(monkeypatch, calls)
    assert up(env, _sized(10 * MIB))[0].status_code == 200
    r, tid = up(env, _sized(10 * MIB + 1))
    assert r.status_code == 413 and r.json()["detail"] == "File is larger than 10 MB"
    assert calls == [10 * MIB] and rows_for(tid) == 0


def test_middleware_refuses_before_the_form_is_parsed(env, monkeypatch):
    calls: list = []
    _stub_ingest(monkeypatch, calls)
    tid = uuid.uuid4()
    # not multipart: the handler's own parsing would answer 422, only the middleware can answer 413
    r = env.client.post(f"/threads/{tid}/attachments", content=b"x" * (10 * MIB + 70_000), headers=env.h)
    assert r.status_code == 413 and calls == []


def test_missing_content_length_is_411(env):
    tid = uuid.uuid4()
    r = env.client.post(f"/threads/{tid}/attachments", content=iter([b"x" * 10]), headers=env.h)
    assert r.status_code == 411


def test_other_routes_are_not_size_guarded(env):
    r = env.client.post("/threads/not-a-thread/attachments", content=b"x", headers=env.h)
    assert r.status_code == 422  # the route's own path validation, not 411/413


def test_type_comes_from_magic_bytes(env, monkeypatch):
    r, tid = up(env, b"PK\x03\x04" + b"\x00" * 64, name="x.pdf")
    assert r.status_code == 415 and r.json()["detail"] == "Allowed types: CSV, PDF, PNG, JPEG, WebP"
    assert rows_for(tid) == 0

    async def fake(images, *, kind, account_currency, target):
        return Parsed(kind, "refused", [], "", {}, "stub")

    monkeypatch.setattr(att, "read_receipt", fake)
    r, _ = up(env, PNG, name="x.csv")
    assert r.status_code == 200 and r.json()["kind"] == "image"


@pytest.mark.parametrize("which", ["missing", "investment"])
def test_account_must_be_a_liquid_account(env, which):
    acct = 2_000_000_000 if which == "missing" else env.inv
    r, tid = up(env, fx.GENERIC_ID_CSV.encode(), account=acct)
    assert r.status_code == 422 and r.json()["detail"] == "Choose an account that can take transactions."
    assert rows_for(tid) == 0
    with SessionLocal() as db:
        assert db.get(Thread, tid) is None


SENTINEL = "zz-sentinel-pw-39"


def test_password_flow_never_leaks_the_password(env, monkeypatch, caplog):
    async def fake(data, *, password, **kw):
        if password is None:
            raise NeedsPassword(False)
        if password != SENTINEL + "-right":
            raise NeedsPassword(True)
        return Parsed("pdf_text", "ok", [], "t", {"invariant": "balance verified"})

    monkeypatch.setattr(attachments_api, "ingest", fake)
    caplog.set_level(logging.DEBUG)
    tid = uuid.uuid4()
    bodies = []
    for pw, status in [(None, "needs_password"), (SENTINEL + "-wrong", "wrong_password"), (SENTINEL + "-right", "ok")]:
        r, _ = up(env, b"%PDF-1.4 zz", tid=tid, name="s.pdf", password=pw)
        assert r.status_code == 200 and r.json()["status"] == status
        bodies.append(r.text)
        if status != "ok":
            assert r.json()["attachment_id"] is None and rows_for(tid) == 0
    with SessionLocal() as db:
        dump = db.execute(
            text("SELECT row_to_json(a)::text || coalesce(encode(raw, 'escape'), '') FROM attachments a "
                 "WHERE thread_id = :t"), {"t": tid},
        ).scalars().all()
    assert len(dump) == 1
    everything = "\n".join(bodies + dump + [rec.getMessage() for rec in caplog.records])
    assert SENTINEL not in everything


def test_overlong_password_is_a_fixed_422_that_does_not_echo(env):
    r, tid = up(env, b"%PDF-1.4 zz", name="s.pdf", password=SENTINEL + "x" * 300)
    assert r.status_code == 422 and r.json() == {"detail": "The password is too long."}
    assert SENTINEL not in r.text and rows_for(tid) == 0


def test_validation_error_does_not_echo_the_password(env):
    tid = uuid.uuid4()  # no file part: FastAPI's own 422
    r = env.client.post(
        f"/threads/{tid}/attachments", data={"account_id": str(env.cash), "password": SENTINEL}, files={"x": ("x", b"y")},
        headers=env.h,
    )
    assert r.status_code == 422 and SENTINEL not in r.text


def test_malformed_pdf_is_a_4xx(env):
    r, tid = up(env, b"%PDF-1.4\nthis is not a pdf", name="bad.pdf")
    assert r.status_code == 422 and rows_for(tid) == 0


def test_any_upload_runs_the_lazy_purge(env):
    db = SessionLocal()
    old = Thread(title="zz39-old")
    db.add(old)
    db.commit()
    env.made.append(old.id)
    a = Attachment(thread_id=old.id, filename="o.csv", mime="text/csv", kind="csv", size_bytes=3, sha256="d" * 64,
                   raw=b"a,b", parse_status="ok")
    db.add(a)
    db.commit()
    db.execute(text("UPDATE attachments SET created_at = now() - interval '8 days' WHERE id = :i"), {"i": a.id})
    db.commit()
    assert up(env, fx.GENERIC_ID_CSV.encode())[0].status_code == 200
    db.expire_all()
    assert db.get(Attachment, a.id).raw is None
    db.close()


def test_first_question_titles_an_upload_created_thread(env, monkeypatch):
    monkeypatch.setattr(q, "_ACTIVE", {})
    monkeypatch.setattr(q, "_LAST", {})

    async def stub(question, **kw):
        yield "data: " + json.dumps({"type": "answer", "text": "ok", "trace": [], "proposals": []}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(q, "agent_stream", stub)
    r, tid = up(env, fx.GENERIC_ID_CSV.encode())
    assert r.status_code == 200
    question = "what did I spend on parking?"
    s = env.client.post("/query-stream", json={"question": question, "thread_id": str(tid)}, headers=env.h)
    assert s.status_code == 200
    got = env.client.get(f"/threads/{tid}", headers=env.h).json()
    assert got["title"] == question
    q._ACTIVE.clear()
    q._LAST.clear()


def test_locality_default_config(env, monkeypatch):
    for var in ("LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        settings, "get_effective_settings",
        lambda db: {"llm_provider": "ollama", "llm_model": settings._model_env_default("ollama")},
    )
    r = env.client.get("/attachments/locality", headers=env.h)
    assert r.status_code == 200
    assert r.json() == {"local": False, "destination": "Ollama Cloud (gemma4:31b-cloud)"}
