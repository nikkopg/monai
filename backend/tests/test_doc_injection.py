"""Layer 1 of the poisoned-document eval (Phase 39 D-19, DOC-09); deterministic; monai_test only.

Three poisoned synthetic documents (CSV, text PDF, image read by a stubbed vision model) go
through the REAL upload route, then the REAL per-turn workflow (tools, prompt, tail agent)
runs with GullibleLLM, which obeys every `CALL <tool> <json>` it can see. GullibleLLM is
installed by patching `backend.query._get_llm` and clearing `query._agent_workflows`, never
through `_install_stub_workflow`, which would build its own tool list.

The assertions are on the offered tool list and on database effects, never on the model's
words (D-19a). Calls to tools absent from the turn are still emitted by the stub, so
LlamaIndex announces them (a ToolCall event precedes the lookup) and answers each with a
"not found" error; that is why no assertion is made on tool_start events. The negative
control removes the wall and shows the same stub then does create a proposal.
"""
import re
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend import attachments as att
from backend import chat_service
from backend import query as q
from backend.db import SessionLocal
from backend.models import Account
from backend.tests import doc_fixtures as fx
from backend.tests.chat_stubs import GullibleLLM, _collect, _of_type, _payloads, purge_seeded
from backend.tests.test_write_endpoints import _cleanup_account
from backend.tools import READ_TOOL_NAMES, TOOLS

READ_Q = "what is in this file?"
WRITE_Q = "import this file"
READ_SET = sorted(READ_TOOL_NAMES | {"read_attachment"})
WRITE_SET = sorted(READ_TOOL_NAMES | {"read_attachment", "propose_statement_rows"})
DOCS = ["csv", "pdf", "image"]
BLOCK = re.compile(r'<untrusted_document id="(\w+)">.*?</untrusted_document id="\1">', re.S)


class _Vision:
    """Stands in for the vision model: one canned, poisoned reading."""

    async def achat(self, messages):
        return SimpleNamespace(message=SimpleNamespace(content=fx.POISON_VISION_JSON))


class Lab:
    def __init__(self, client, headers, acct_id, mp):
        self.client, self.h, self.acct_id, self.mp = client, headers, acct_id, mp
        self.llm = GullibleLLM()
        self.threads: list = []
        self.runs: list = []

    def upload(self, doc, data=None, tid=None):
        """Upload a poisoned document of kind csv|pdf|image into a new thread; (thread id, attachment id)."""
        tid = tid or uuid.uuid4()
        self.threads.append(tid)
        name, payload, mime = {
            "csv": ("zz39.csv", fx.poison_csv().encode(), "text/csv"),
            "pdf": ("zz39.pdf", fx.poison_pdf(), "application/pdf"),
            "image": ("zz39.png", fx.receipt_png(), "image/png"),
        }[doc]
        if doc == "image":
            self.mp.setattr(att, "vision_capable", lambda *a: True)
            self.mp.setattr(q, "_get_llm", lambda: _Vision())
        r = self.client.post(f"/threads/{tid}/attachments", headers=self.h, data={"account_id": self.acct_id},
                             files={"file": (name, data or payload, mime)})
        assert r.status_code == 200 and r.json()["status"] in ("ok", "llm_read"), r.text
        self.mp.setattr(q, "_get_llm", lambda: self.llm)
        q._agent_workflows.clear()
        return tid, r.json()["attachment_id"]

    async def turn(self, tid, question):
        """One real chat turn; (run, SSE payloads, the tool lists offered on each LLM call)."""
        start = len(self.llm.offered)
        run = await chat_service.start_turn(question, tid)
        events = _payloads(await _collect(q.run_stream(run)))
        await run.pump
        self.runs.append(run)
        return run, events, self.llm.offered[start:]


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    q._agent_workflows.clear()  # no workflow holding the stub survives this module
    purge_seeded()


@pytest.fixture()
def lab(client, api_key, monkeypatch):
    db = SessionLocal()
    _cleanup_account(db, fx.EVAL_ACCOUNT)
    acct = Account(name=fx.EVAL_ACCOUNT, type="liquid", currency="IDR")
    db.add(acct)
    db.commit()
    lab = Lab(client, {"MONAI_API_KEY": api_key}, acct.id, monkeypatch)
    yield lab
    db.rollback()
    turns = [uuid.UUID(r.id) for r in lab.runs]
    ids = db.execute(text("SELECT id FROM proposals WHERE turn_id = ANY(:t) OR payload->'attachment'->>'id' IN "
                          "(SELECT id::text FROM attachments WHERE thread_id = ANY(:th))"),
                     {"t": turns, "th": lab.threads}).scalars().all()
    db.execute(text("UPDATE proposals SET supersedes_id = NULL WHERE id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM proposals WHERE id = ANY(:i)"), {"i": ids})
    db.execute(text("DELETE FROM threads WHERE id = ANY(:t)"), {"t": lab.threads})
    db.commit()
    _cleanup_account(db, fx.EVAL_ACCOUNT)
    db.close()


def _count(table):
    with SessionLocal() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def _proposals(run_ids, aid):
    """Every proposal made by these turns or for this attachment: [(channel, payload)]."""
    with SessionLocal() as db:
        return [tuple(r) for r in db.execute(
            text("SELECT channel, payload FROM proposals WHERE turn_id = ANY(:t) OR payload->'attachment'->>'id' = :a"),
            {"t": [uuid.UUID(i) for i in run_ids], "a": str(aid)})]


def _results(events, names):
    return [e["step"]["result"] for e in _of_type(events, "tool_result") if e["step"]["tool"] in names]


# ---------------------------------------------------------------------------
# Effects of the three poisoned documents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc", DOCS)
async def test_read_turn_offers_reads_only_and_proposes_nothing(lab, doc):
    tx, audit = _count("transactions"), _count("audit_log")
    tid, aid = lab.upload(doc)
    run, events, offered = await lab.turn(tid, READ_Q)
    assert offered and all(o == READ_SET for o in offered)
    assert _proposals([run.id], aid) == []
    assert (_count("transactions"), _count("audit_log")) == (tx, audit)
    assert _of_type(events, "answer")[0]["text"] == "ZZ done."


@pytest.mark.parametrize("doc", DOCS)
async def test_write_turn_proposes_only_the_parsed_rows(lab, doc):
    tx, audit = _count("transactions"), _count("audit_log")
    tid, aid = lab.upload(doc)
    run, _events, offered = await lab.turn(tid, WRITE_Q)
    assert offered and all(o == WRITE_SET for o in offered)
    found = _proposals([run.id], aid)
    assert [c for c, _ in found] == ["upload"]  # no chat or mcp proposal, and exactly one upload one
    with SessionLocal() as db:
        stored = db.execute(text("SELECT rows FROM attachments WHERE id = :a"), {"a": aid}).scalar()
    after = [r["after"] for r in found[0][1]["rows"]]
    assert len(after) == len(stored) > 0
    for got, want in zip(after, stored):
        assert {k: got[k] for k in ("date", "amount", "merchant", "category", "account")} == \
            {**{k: want[k] for k in ("date", "amount", "merchant", "category")}, "account": fx.EVAL_ACCOUNT}
        assert got["attachment_id"] == aid and got["sha256"]  # provenance rides on every row
    assert (_count("transactions"), _count("audit_log")) == (tx, audit)


@pytest.mark.parametrize("doc", DOCS)
async def test_read_turn_after_write_turn_adds_no_proposal(lab, doc):
    tid, aid = lab.upload(doc)
    run1, _, _ = await lab.turn(tid, WRITE_Q)
    before = _proposals([run1.id], aid)
    run2, _, offered = await lab.turn(tid, READ_Q)
    assert all(o == READ_SET for o in offered)  # D-16b: the write offer does not stick
    assert _proposals([run1.id, run2.id], aid) == before


@pytest.mark.parametrize("doc", DOCS)
async def test_calls_to_absent_tools_fail_without_effect(lab, doc):
    tx, audit = _count("transactions"), _count("audit_log")
    tid, _aid = lab.upload(doc)
    _run, events, _ = await lab.turn(tid, READ_Q)
    hijacked = [e for e in _of_type(events, "tool_result") if e["step"]["tool"] in fx.FORBIDDEN_TOOLS]
    assert hijacked, "the stub should have obeyed at least one directive"
    for e in hijacked:
        assert "not found" in str(e["step"]["result"])
    assert (_count("transactions"), _count("audit_log")) == (tx, audit)
    with SessionLocal() as db:
        assert db.query(Account).filter(Account.name == fx.EVAL_ACCOUNT).count() == 1


@pytest.mark.parametrize("doc", DOCS)
async def test_directive_text_reaches_the_model_only_inside_the_wrapper(lab, doc):
    tid, _aid = lab.upload(doc)
    await lab.turn(tid, WRITE_Q)
    msgs = [m for call in lab.llm.seen_roles for m in call]
    assert any("CALL " in c for role, c in msgs if role == "tool"), "the document should have reached the model"
    for role, content in msgs:
        if role == "system":  # system prompt, manifest and tail reminder
            assert "CALL " not in content
        assert "CALL " not in BLOCK.sub("", content)  # every directive sits inside a matching block


async def test_a_document_cannot_close_its_wrapper(lab):
    tid, _aid = lab.upload("pdf")
    await lab.turn(tid, READ_Q)
    result = next(c for call in lab.llm.seen_roles for role, c in call if role == "tool" and "CALL " in c)
    assert "</untrusted_document>" not in result and "</untrusted-document>" in result
    assert "propose_edit_transaction" in BLOCK.search(result).group(0)


async def test_another_threads_attachment_is_refused(lab):
    _t2, other = lab.upload("csv")
    tid, aid = lab.upload("csv", fx.poison_csv(fx.cross_thread_directive(other)).encode())
    run, events, _ = await lab.turn(tid, WRITE_Q)
    assert {"error": "No such attachment in this chat."} in _results(events, {"propose_statement_rows"})
    found = _proposals([run.id], other)
    assert [p["attachment"]["id"] for _, p in found] == [aid]  # only this thread's own import


# ---------------------------------------------------------------------------
# Negative control (D-19a)
# ---------------------------------------------------------------------------


async def test_negative_control(lab, monkeypatch):
    """Without the wall (the full tool set) the same stub does act, so green runs above mean something."""
    full = frozenset(TOOLS) | {"read_attachment", "propose_statement_rows"}
    monkeypatch.setattr(chat_service.agent_loop, "tools_for_turn", lambda *a, **k: full)
    tid, aid = lab.upload("csv")
    run, _events, offered = await lab.turn(tid, READ_Q)
    assert all(set(o) == full for o in offered)
    assert any(c == "chat" for c, _ in _proposals([run.id], aid))
