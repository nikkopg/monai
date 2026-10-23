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
