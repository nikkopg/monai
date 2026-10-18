"""Phase 39 attachment turns: binding, taint, manifest, SSE and thread detail; synthetic values; monai_test only."""
import json
import secrets
import uuid

import pytest
from sqlalchemy import text

from backend import chat_service, chat_tools, tools
from backend import query as q
from backend.tools import READ_TOOL_NAMES
from backend.db import SessionLocal
from backend.models import Account, Attachment, Message, Thread
from backend.tests.chat_stubs import StubLLM, _collect, _install_stub_workflow, _payloads, _of_type, purge_seeded
from backend.tests.test_write_endpoints import _cleanup_account

SECRET = "ZZ39 SECRET BODY LINE that must never reach the prompt"
ROWS = [
    {"date": "2026-03-02", "amount": "100000.00", "merchant": "ZZ39 payer", "notes": None, "category": None,
     "raw_line": "02/03 payer", "llm_read": False, "assumptions": []},
    {"date": "2026-03-05", "amount": "-50500.00", "merchant": "ZZ39 shop", "notes": None, "category": None,
     "raw_line": "05/03 shop", "llm_read": False, "assumptions": []},
]
META = {"opening": "5000000.00", "closing": "5049500.00", "invariant": "running balance verified",
        "summary": "2 rows, balance verified"}
READ_Q = "what is in this file?"


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    purge_seeded()


@pytest.fixture()
def world():
    """Thread T holding attachment A (unbound), another thread O holding B; cleaned afterwards."""
    db = SessionLocal()
    sfx = secrets.token_hex(3)
    cash = Account(name=f"ZZ39 Turn Cash {sfx}", type="liquid", currency="IDR")
    t, o = Thread(title="zz39-turn-a"), Thread(title="zz39-turn-b")
    db.add_all([cash, t, o])
    db.commit()

    def att(thread, name="zz39-march.pdf"):
        a = Attachment(
            thread_id=thread.id, filename=name, mime="application/pdf", kind="pdf_text", size_bytes=5,
            sha256="c" * 64, raw=b"%PDF-", extracted_text=SECRET, rows=ROWS, meta=dict(META),
            parse_status="ok", parse_note=None, account_id=cash.id,
        )
        db.add(a)
        db.commit()
        return a

    a, b = att(t), att(o, "zz39-other.pdf")
    yield db, t, o, a, b
    db.rollback()
    ids = db.execute(text("SELECT id FROM proposals WHERE payload->'attachment'->>'id' = ANY(:a)"),
                     {"a": [str(a.id), str(b.id)]}).scalars().all()
    db.execute(text("UPDATE proposals SET supersedes_id = NULL WHERE id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM proposals WHERE id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM threads WHERE id = ANY(:t)"), {"t": [t.id, o.id]})
    db.commit()
    _cleanup_account(db, cash.name)
    db.close()


async def _turn(monkeypatch, question, tid, ids=(), replace_from=None):
    """Run start_turn with a stubbed agent_stream; return (its kwargs, the run)."""
    got: dict = {}

    async def stub(question, **kw):
        got.update(kw)
        yield "data: " + json.dumps({"type": "answer", "text": "ok", "trace": [], "proposals": []}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(q, "agent_stream", stub)
    run = await chat_service.start_turn(question, tid, replace_from, list(ids))
    await run.pump
    return got, run


async def test_binding_sets_message_id_and_reduces_tools(monkeypatch, world):
    db, t, _, a, _ = world
    got, run = await _turn(monkeypatch, READ_Q, t.id, [a.id])
    db.refresh(a)
    assert a.message_id == run.user_message_id
    assert got["tool_names"] == READ_TOOL_NAMES | {"read_attachment"}


async def test_taint_comes_from_the_database_not_the_request(monkeypatch, world):
    _, t, _, _, _ = world
    got, _run = await _turn(monkeypatch, "import this file", t.id)  # no attachment_ids in the request
    assert got["tool_names"] == READ_TOOL_NAMES | {"read_attachment", "propose_statement_rows"}


async def test_manifest_is_first_system_message_and_never_stored(monkeypatch, world):
    db, t, _, a, _ = world
    got, _run = await _turn(monkeypatch, READ_Q, t.id, [a.id])
    first = got["history"][0]
    assert first.role.value == "system"
    body = str(first.content)
    assert "zz39-march.pdf" in body and "kind pdf_text" in body and "2 rows" in body
    assert "5000000.00" in body and "5049500.00" in body and "never instructions" in body
    assert SECRET not in body and str(a.id) in body
    assert db.execute(text("SELECT count(*) FROM messages WHERE thread_id = :t AND role = 'system'"),
                      {"t": t.id}).scalar() == 0


async def test_thread_without_attachments_is_unchanged(monkeypatch):
    got, run = await _turn(monkeypatch, "How much did I spend this month?", None)
    assert got["tool_names"] == READ_TOOL_NAMES
    assert not any(getattr(m.role, "value", m.role) == "system" for m in (got["history"] or []))
    db = SessionLocal()
    db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": run.thread_id})
    db.commit()
    db.close()


async def test_foreign_attachment_is_refused_and_nothing_is_stored(monkeypatch, world):
    db, t, _, a, b = world
    with pytest.raises(ValueError, match="Unknown attachment for this chat."):
        await _turn(monkeypatch, READ_Q, t.id, [a.id, b.id])
    assert db.execute(text("SELECT count(*) FROM messages WHERE thread_id = :t"), {"t": t.id}).scalar() == 0
    db.refresh(a)
    assert a.message_id is None
    assert q._ACTIVE == {}  # the run slot was freed


async def test_ids_without_thread_are_refused(monkeypatch, world):
    _, _, _, a, _ = world
    with pytest.raises(ValueError, match="attachment_ids need a thread_id."):
        await _turn(monkeypatch, READ_Q, None, [a.id])


def test_http_422_for_both_cases(client, api_key, monkeypatch, world):
    _, t, _, a, b = world
    h = {"MONAI_API_KEY": api_key}
    for body in (
        {"question": READ_Q, "thread_id": str(t.id), "attachment_ids": [str(b.id)]},
        {"question": READ_Q, "attachment_ids": [str(a.id)]},
        {"question": READ_Q, "thread_id": str(t.id), "attachment_ids": [str(uuid.uuid4()) for _ in range(21)]},
    ):
        assert client.post("/query-stream", json=body, headers=h).status_code == 422
    assert q._ACTIVE == {}


async def test_regenerate_keeps_the_taint_and_the_manifest(monkeypatch, world):
    db, t, _, a, _ = world
    _, first = await _turn(monkeypatch, READ_Q, t.id, [a.id])
    got, _run = await _turn(monkeypatch, READ_Q, t.id, replace_from=first.user_message_id)
    db.refresh(a)
    assert a.message_id is None  # the delete NULLed the binding; the file stays on the thread
    assert got["tool_names"] == READ_TOOL_NAMES | {"read_attachment"}
    assert "zz39-march.pdf" in str(got["history"][0].content)


async def test_pump_sets_current_thread_id(monkeypatch, world):
    _, t, _, _, _ = world
    seen: list = []

    def probe() -> dict:
        """Synthetic probe."""
        seen.append(tools.CURRENT_THREAD_ID.get())
        return {"tool": "probe"}

    _install_stub_workflow(monkeypatch, StubLLM(mode="script", script=[[("probe", {})]]), extra_tools={"probe": probe})
    run = await chat_service.start_turn(READ_Q, t.id)
    await run.pump
    assert seen == [t.id]


async def test_question_about_a_file_is_answered_from_read_attachment(monkeypatch, world):
    _, t, _, a, _ = world
    llm = StubLLM(mode="script", script=[[("read_attachment", {"attachment_id": str(a.id)})]], final_text="Two rows.")
    _install_stub_workflow(monkeypatch, llm, extra_tools=chat_tools.CHAT_ONLY_TOOLS)
    run = await chat_service.start_turn(READ_Q, t.id, None, [a.id])
    ev = _payloads(await _collect(q.run_stream(run)))
    steps = [e for e in _of_type(ev, "tool_result") if e["step"]["tool"] == "read_attachment"]
    assert steps and SECRET in json.dumps(steps[0]["step"]["result"]) and "untrusted_document" in json.dumps(steps[0]["step"]["result"])
    assert _of_type(ev, "answer")[0]["text"] == "Two rows."
    await run.pump
