"""Phase 41 per-turn external session and its chat wiring. In-memory synthetic servers only
(`ext_test_server.build`), slugs `zz-*`, the isolated monai_test database."""
import uuid
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from sqlalchemy import text

from backend import ext_calls, mcp_client as mc, query as q, tools as T
from backend.db import SessionLocal
from backend.evals import ext_test_server as srv
from backend.models import McpServer, Thread, ThreadMcpServer

BASE_TOOLS = ["add", "bare", "echo", "env_dump", "lookup", "nested", "send", "slow"]


async def snapshot(variant):
    """The approved_tools list Enable would have stored for this variant."""
    async with Client(FastMCPTransport(srv.build(variant))) as c:
        return [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema,
                 "sha256": mc.tool_sha(t)} for t in await c.list_tools()]


def _purge():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM mcp_servers WHERE slug LIKE 'zz-%'"))
        db.execute(text("DELETE FROM threads WHERE title LIKE 'zz41-%'"))
        db.commit()


class Env:
    def __init__(self):
        self.live: dict = {}  # slug -> variant served now ("boom" = transport raises)
        self.built: list = []  # slugs build_transport was called for
        with SessionLocal() as db:
            t = Thread(title="zz41-session")
            db.add(t)
            db.commit()
            self.tid = t.id

    async def add(self, slug="zz-synth", approved="base", live="base", enabled=True, selected=True, policies=None):
        snap = await snapshot(approved) if approved else []
        with SessionLocal() as db:
            row = McpServer(slug=slug, transport="http", url=f"https://{slug}.example.com/mcp",
                            enabled=enabled, approved_tools=snap, tool_policies=policies or {})
            db.add(row)
            db.flush()
            if selected:
                db.add(ThreadMcpServer(thread_id=self.tid, server_id=row.id))
            db.commit()
            sid = row.id
        self.live[slug] = live
        return sid

    def changed_count(self, slug):
        with SessionLocal() as db:
            return db.execute(text("SELECT changed_count FROM mcp_servers WHERE slug = :s"), {"s": slug}).scalar()

    async def open(self):
        return await mc.ExtSession.open(self.tid)


@pytest.fixture()
def env(monkeypatch):
    _purge()
    e = Env()

    def transport(spec):
        e.built.append(spec.slug)
        if e.live[spec.slug] == "boom":
            raise RuntimeError("connection refused to https://secret.example.com/?token=ZZ")
        return FastMCPTransport(srv.build(e.live[spec.slug]))

    monkeypatch.setattr(mc, "build_transport", transport)
    yield e
    _purge()


def names(s):
    return [t.metadata.name for t in s.tools]


async def test_usable(env):
    await env.add()
    s = await env.open()
    try:
        assert names(s) == [f"ext__zz-synth__{n}" for n in BASE_TOOLS]
        assert s.notices == [] and s.names == frozenset(names(s))
    finally:
        await s.aclose()


async def test_changed(env):
    await env.add(live="changed")
    s = await env.open()
    try:
        assert "ext__zz-synth__echo" not in names(s) and len(s.tools) == len(BASE_TOOLS) - 1
        assert [(n["code"], n["server"]) for n in s.notices] == [("tools_changed", "zz-synth")]
        assert env.changed_count("zz-synth") == 1
    finally:
        await s.aclose()


async def test_new_and_removed(env):
    await env.add(live="extra")
    s = await env.open()
    try:
        assert "ext__zz-synth__zz_new" not in names(s) and len(s.tools) == len(BASE_TOOLS)
        assert [n["code"] for n in s.notices] == ["tools_changed"]
    finally:
        await s.aclose()
    _purge()
    env.__init__()
    await env.add(approved="extra", live="base")
    s = await env.open()
    try:
        assert len(s.tools) == len(BASE_TOOLS) and s.notices == []
        assert env.changed_count("zz-synth") == 0
    finally:
        await s.aclose()


async def test_deny(env):
    await env.add(policies={"echo": "deny", "add": "always"})
    s = await env.open()
    try:
        assert "ext__zz-synth__echo" not in names(s) and "ext__zz-synth__add" in names(s)
    finally:
        await s.aclose()


async def test_name(env, monkeypatch):
    await env.add()
    real = mc.ext_name
    monkeypatch.setattr(mc, "ext_name", lambda slug, tool: None if tool == "echo" else real(slug, tool))
    s = await env.open()
    try:
        assert "ext__zz-synth__echo" not in names(s) and len(s.tools) == len(BASE_TOOLS) - 1
        assert s.notices == []
    finally:
        await s.aclose()


async def test_cap(env):
    await env.add(approved="wide", live="wide")
    s = await env.open()
    try:
        every = sorted(t["name"] for t in await snapshot("wide"))
        assert names(s) == [f"ext__zz-synth__{n}" for n in every[:mc.EXT_TOOL_CAP]]
        assert len(s.tools) == 16
        assert [(n["code"], n["limit"]) for n in s.notices] == [("cap", 16)]
    finally:
        await s.aclose()


async def test_too_many(env):
    await env.add(live="many")
    s = await env.open()
    try:
        assert s.tools == [] and [n["code"] for n in s.notices] == ["too_many_tools"]
    finally:
        await s.aclose()


async def test_unreachable(env):
    await env.add(slug="zz-down", live="boom")
    await env.add(slug="zz-synth")
    s = await env.open()
    try:
        assert [(n["code"], n["server"]) for n in s.notices] == [("unreachable", "zz-down")]
        assert names(s) == [f"ext__zz-synth__{n}" for n in BASE_TOOLS]
        assert "secret" not in str(s.notices) and "ZZ" not in str(s.notices)  # fixed copy, no exception text
    finally:
        await s.aclose()


async def test_not_constructed(env):
    await env.add(slug="zz-off", enabled=False)
    await env.add(slug="zz-unsel", selected=False)
    await env.add(slug="zz-synth")
    s = await env.open()
    try:
        assert env.built == ["zz-synth"]
    finally:
        await s.aclose()


async def test_lifecycle(env):
    await env.add()
    s = await env.open()
    clients = [c.client for c in s._conns]
    assert clients and all(c.is_connected() for c in clients)
    real_close = clients[0].close

    async def boom():
        raise RuntimeError("close failed")

    clients[0].close = boom
    await s.aclose()  # never raises
    clients[0].close = real_close
    await real_close()
    assert not any(c.is_connected() for c in clients)


async def test_idle_servers_are_closed(env):
    await env.add(slug="zz-many", live="many")
    await env.add(slug="zz-synth")
    s = await env.open()
    try:
        assert [c.slug for c in s._conns] == ["zz-synth"]
    finally:
        await s.aclose()


async def test_closure(env, monkeypatch):
    await env.add()
    s = await env.open()
    seen = []

    async def spy(turn, conn, tool, args, *, thread_id, turn_id):
        seen.append((turn, conn, tool, args, thread_id, turn_id))
        return {"ok": True}

    monkeypatch.setattr(ext_calls, "run_call", spy)
    tool = next(t for t in s.tools if t.metadata.name == "ext__zz-synth__echo")
    try:
        assert (await tool.acall(text="zz hi")).raw_output == {"error": "external tools need a chat turn"}
        turn, run_id = SimpleNamespace(), uuid.uuid4()
        q.TURN.set(turn)
        T.CURRENT_THREAD_ID.set(env.tid)
        T.CURRENT_TURN_ID.set(run_id)
        out = await tool.acall(text="zz hi")
        assert out.raw_output == {"ok": True}
        (t, conn, name, args, tid, rid), = seen
        assert t is turn and conn.slug == "zz-synth" and name == "echo" and args == {"text": "zz hi"}
        assert (tid, rid) == (env.tid, run_id)
        # each tool is bound to its own name
        await next(t for t in s.tools if t.metadata.name == "ext__zz-synth__add").acall(a=1, b=2)
        assert seen[-1][2] == "add"
    finally:
        q.TURN.set(None)
        await s.aclose()


# ── the pump: real start_turn, GullibleLLM, in-memory servers ──────────────

import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

from backend import chat_service  # noqa: E402
from backend.models import Attachment  # noqa: E402
from backend.tests.chat_stubs import GullibleLLM, _collect, _of_type, _payloads  # noqa: E402

ECHO = 'CALL ext__zz-synth__echo {"text": "zz hello"}'


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    q._agent_workflows.clear()


async def _until(pred, limit=5.0):
    end = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.02)


def _calls(tid):
    with SessionLocal() as db:
        return [dict(r) for r in db.execute(
            text("SELECT id, approval FROM ext_calls WHERE thread_id = :t ORDER BY created_at"), {"t": tid}).mappings()]


async def _start(env, mp, question):
    llm = GullibleLLM()
    mp.setattr(q, "_get_llm", lambda: llm)
    q._agent_workflows.clear()
    run = await chat_service.start_turn(question, env.tid)
    return run, llm, asyncio.create_task(_collect(q.run_stream(run)))


async def _approve(env, run, task):
    await _until(lambda: any(c["approval"] == "pending" for c in _calls(env.tid)))
    cid = next(c["id"] for c in _calls(env.tid) if c["approval"] == "pending")
    assert ext_calls.decide(env.tid, cid, True) == "approved"
    ext_calls.wake(cid)
    events = _payloads(await task)
    await run.pump
    return events, cid


def _detail(tid):
    with SessionLocal() as db:
        return chat_service.thread_detail(db, tid)


async def test_turn_persist_and_detail(env, monkeypatch):
    await env.add()
    run, llm, task = await _start(env, monkeypatch, ECHO)
    events, cid = await _approve(env, run, task)
    (card,) = _of_type(events, "approval_required")
    assert (card["server"], card["call_id"]) == ("zz-synth", str(cid))
    assert _of_type(events, "ext_call") and _of_type(events, "answer")
    assert "ext__zz-synth__echo" in llm.offered[0]
    d = _detail(env.tid)
    (c,) = d["ext_calls"]
    assert c["id"] == cid and c["message_id"] == run.assistant_message_id
    assert (c["approval"], c["decided_via"], c["receipt"]) == ("approved", "user", "confirmed")
    assert c["destination"] == "zz-synth.example.com" and c["leaves_machine"] is True
    assert c["server_slug"] == "zz-synth" and c["tool"] == "echo" and c["args"] == {"text": "zz hello"}
    assert "notices" not in d["messages"][-1]["parts"]


async def test_reload_shows_pending_from_server_state(env, monkeypatch):
    await env.add()
    run, llm, task = await _start(env, monkeypatch, ECHO)
    await _until(lambda: any(c["approval"] == "pending" for c in _calls(env.tid)))
    (c,) = _detail(env.tid)["ext_calls"]  # the run is active: the orphan sweep leaves it
    assert c["approval"] == "pending" and c["message_id"] is None and c["receipt"] is None
    seen = []
    async for chunk in q.subscribe(run):
        seen += _payloads([chunk])
        if _of_type(seen, "approval_required"):
            break
    assert _of_type(seen, "approval_required")
    await _approve(env, run, task)


async def test_notices_stream_and_persist(env, monkeypatch):
    await env.add(live="changed")
    run, llm, task = await _start(env, monkeypatch, "hello")
    events = _payloads(await task)
    await run.pump
    (n,) = _of_type(events, "notice")
    assert (n["code"], n["server"]) == ("tools_changed", "zz-synth")
    assert events.index(n) < events.index(_of_type(events, "answer")[0])
    with SessionLocal() as db:
        parts = db.execute(text("SELECT parts FROM messages WHERE id = :i"), {"i": run.assistant_message_id}).scalar()
    assert parts["notices"] == [{"code": "tools_changed", "server": "zz-synth", "message": n["message"]}]
    assert _detail(env.tid)["messages"][-1]["parts"]["notices"] == parts["notices"]


async def test_attachment_thread_never_opens_a_session(env, monkeypatch):
    await env.add()
    with SessionLocal() as db:
        db.add(Attachment(thread_id=env.tid, filename="zz41.csv", mime="text/csv", kind="csv",
                          size_bytes=1, sha256="0" * 64, parse_status="ok"))
        db.commit()
    opened = []

    async def spy(thread_id):
        opened.append(thread_id)
        raise AssertionError("must not open")

    monkeypatch.setattr(mc.ExtSession, "open", spy)
    run, llm, task = await _start(env, monkeypatch, "what is in this file?")
    await task
    await run.pump
    assert opened == [] and env.built == []
    assert llm.offered and not any(n.startswith("ext__") for names_ in llm.offered for n in names_)


def _fake_agent(seen):
    async def fake(question, *, run, history, tool_names):  # only the pre-Phase-41 keywords
        seen.append(run.ext)
        yield q._sse({"type": "answer", "text": "zz ok", "model": "m", "provider": "p"})
    return fake


async def test_no_session_tools_keeps_old_keywords(env, monkeypatch):
    await env.add(selected=False)
    seen = []
    monkeypatch.setattr(q, "agent_stream", _fake_agent(seen))
    run = await chat_service.start_turn("hello", env.tid)
    await _collect(q.run_stream(run))
    await run.pump
    assert seen == [False] and env.built == []
    assert _detail(env.tid)["messages"][-1]["status"] == "complete"


async def test_session_failure_logs_class_only(env, monkeypatch, caplog):
    async def boom(thread_id):
        raise RuntimeError("secret-detail ZZ")

    monkeypatch.setattr(mc.ExtSession, "open", boom)
    monkeypatch.setattr(q, "agent_stream", _fake_agent([]))
    with caplog.at_level(logging.WARNING, logger="backend.chat_service"):
        run = await chat_service.start_turn("hello", env.tid)
        await _collect(q.run_stream(run))
        await run.pump
    msgs = [r.getMessage() for r in caplog.records if "external session" in r.getMessage()]
    assert msgs == ["external session failed: RuntimeError"]
    assert _detail(env.tid)["messages"][-1]["status"] == "complete"
