"""Phase 41 turn seam, per-run workflow and prompt block (stub LLMs only; synthetic values).

Covers the Turn hold seam for the idle watchdog, the ledger taint counter, the stream
`emit`, the per-run workflow that carries external tools, its fixed prompt block, and the
Stop / end-of-run sweeps of pending external calls.
"""
import asyncio

from backend import query as q


# ── seam ────────────────────────────────────────────────────────────────────

async def test_seam_hold_suspends_and_release_rearms():
    loop = asyncio.get_running_loop()
    turn = q.Turn()
    async with asyncio.timeout(1) as cm:
        turn.idle_cm, turn.idle = cm, 1.0
        turn.hold_idle()
        assert cm.when() is None
        turn.hold_idle()
        turn.release_idle()
        assert cm.when() is None  # nested: still held
        turn.release_idle()
        assert abs(cm.when() - (loop.time() + 1.0)) < 0.2


async def test_seam_release_without_hold_stays_at_zero():
    turn = q.Turn()
    turn.release_idle()
    assert turn.holds == 0


# ── taint ───────────────────────────────────────────────────────────────────

async def _call(name):
    tool = q._llm_tool(name, lambda: {"tool": name})
    return await tool.async_fn()


async def test_taint_read_tool_touches_the_ledger():
    turn = q.Turn()
    q.TURN.set(turn)
    await _call("list_categories")
    assert turn.ledger_touched is True and turn.ledger_seq == 1


async def test_taint_load_skill_is_exempt():
    turn = q.Turn()
    q.TURN.set(turn)
    await _call("load_skill")
    assert turn.ledger_touched is False


async def test_taint_propose_tool_touches_the_ledger():
    turn = q.Turn()
    q.TURN.set(turn)
    await _call("propose_add_transaction")
    assert turn.ledger_touched is True


async def test_taint_no_turn_is_harmless():
    q.TURN.set(None)
    assert await _call("list_categories") == {"tool": "list_categories"}


async def test_taint_property_follows_the_cleared_count():
    turn = q.Turn()
    turn.ledger_seq = 2
    turn.ledger_cleared = 1
    assert turn.ledger_touched is True
    turn.ledger_cleared = 2
    assert turn.ledger_touched is False


# ── defaults ────────────────────────────────────────────────────────────────

async def test_defaults_fresh_turn():
    turn = q.Turn()
    assert (turn.holds, turn.ledger_touched, turn.idle_cm) == (0, False, None)
    assert turn.emit({"type": "notice"}) is None


# ── per-run workflow, prompt block, names ───────────────────────────────────

import logging  # noqa: E402
import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend import ext_calls, mcp_client  # noqa: E402
from backend.agent_loop import TAIL_REMINDER, tail_agent_cls  # noqa: E402
from backend.db import SessionLocal  # noqa: E402
from backend.models import Thread  # noqa: E402
from backend.tests.chat_stubs import GullibleLLM, _collect, _of_type, _payloads  # noqa: E402

NAMES = frozenset({"list_categories"})
SCHEMA = {"type": "object", "properties": {}}


async def _noop(**_):
    return {}


def _ext_tool(fn, name="ext__zzt__wait"):
    return mcp_client.make_tool(name, "synthetic external tool", SCHEMA, fn)


def _agent(workflow):
    return next(iter(workflow.agents.values()))


@pytest.fixture()
def gullible(monkeypatch):
    llm = GullibleLLM()
    monkeypatch.setattr(q, "_get_llm", lambda: llm)
    q._agent_workflows.clear()
    yield llm
    q._agent_workflows.clear()


def test_builder_cached_path_is_unchanged(gullible):
    wf = q._get_agent_workflow(NAMES)
    assert wf is q._get_agent_workflow(NAMES) and wf._timeout == 300.0
    assert [t.metadata.name for t in _agent(wf).tools] == ["list_categories"]
    assert q._EXTERNAL_RULES not in _agent(wf).system_prompt


def test_builder_external_run_is_fresh_and_has_no_timeout(gullible):
    tool = _ext_tool(_noop)
    wf = q._build_agent_workflow(NAMES, [], extra_tools=[tool], extra_prompt=q._EXTERNAL_RULES, timeout=None)
    assert wf._timeout is None and q._agent_workflows == {}
    assert [t.metadata.name for t in _agent(wf).tools] == ["list_categories", "ext__zzt__wait"]


def test_prompt_block_comes_last_after_the_base_prompt(gullible):
    base = q._get_agent_workflow(NAMES)
    wf = q._build_agent_workflow(NAMES, [], extra_prompt=q._EXTERNAL_RULES)
    prompt = _agent(wf).system_prompt
    assert prompt.startswith(_agent(base).system_prompt) and prompt.endswith(q._EXTERNAL_RULES)
    assert "{" not in q._EXTERNAL_RULES and "untrusted_external" in q._EXTERNAL_RULES


def test_prompt_skills_catalog_precedes_the_block(gullible, monkeypatch):
    from backend import skills

    monkeypatch.setattr(skills, "catalog", lambda eff: "ZZ-CATALOG")
    prompt = _agent(q._build_agent_workflow(NAMES, [object()], extra_prompt=q._EXTERNAL_RULES)).system_prompt
    assert prompt.index("ZZ-CATALOG") < prompt.index(q._EXTERNAL_RULES)


def test_prompt_tail_reminder_is_still_last():
    from llama_index.core.llms import ChatMessage

    out = tail_agent_cls()(tools=[], llm=GullibleLLM(), system_prompt="x")._tail(
        [ChatMessage(role="user", content="hi")])
    assert str(out[-1].content) == TAIL_REMINDER and out[-1].role.value == "system"


async def _stream(question, tool, idle=0.5, **kw):
    lines = await _collect(q.agent_stream(question, idle_timeout=idle, tool_names=frozenset(),
                                          ext_tools=[tool], **kw))
    return _payloads(lines)


async def test_names_external_tool_is_not_warned_about(gullible, caplog):
    async def fn(**_):
        return {"tool": "ext__zzt__wait", "ok": True}

    with caplog.at_level(logging.WARNING, logger=q.logger.name):
        events = await _stream("CALL ext__zzt__wait {}", _ext_tool(fn))
    assert _of_type(events, "answer")
    assert "not in this turn's subset" not in caplog.text


async def test_wait_past_idle_survives_while_held(gullible):
    async def fn(**_):
        turn = q.TURN.get()
        turn.hold_idle()
        try:
            await asyncio.sleep(1.5)
        finally:
            turn.release_idle()
        return {"tool": "ext__zzt__wait", "ok": True}

    events = await _stream("CALL ext__zzt__wait {}", _ext_tool(fn))
    assert _of_type(events, "answer") and not _of_type(events, "error")


async def test_wait_past_idle_without_a_hold_times_out(gullible):
    async def fn(**_):
        await asyncio.sleep(1.5)
        return {"tool": "ext__zzt__wait"}

    events = await _stream("CALL ext__zzt__wait {}", _ext_tool(fn))
    assert [e["code"] for e in _of_type(events, "error")] == ["idle_timeout"]


async def test_wait_past_idle_a_hang_after_release_times_out(gullible):
    async def fn(**_):
        turn = q.TURN.get()
        turn.hold_idle()
        turn.release_idle()
        await asyncio.sleep(1.5)
        return {"tool": "ext__zzt__wait"}

    events = await _stream("CALL ext__zzt__wait {}", _ext_tool(fn))
    assert [e["code"] for e in _of_type(events, "error")] == ["idle_timeout"]


async def test_emit_reaches_the_stream_before_the_answer(gullible):
    note = {"type": "notice", "code": "zz", "server": "zzt", "message": "zz"}

    async def fn(**_):
        q.TURN.get().emit(note)
        return {"tool": "ext__zzt__wait", "ok": True}

    events = await _stream("CALL ext__zzt__wait {}", _ext_tool(fn))
    types = [e["type"] for e in events]
    assert note in events and types.index("notice") < types.index("answer")


# ── stop / end-of-run sweeps ────────────────────────────────────────────────

@pytest.fixture()
def pending():
    def purge():
        with SessionLocal() as db:
            db.execute(text("DELETE FROM threads WHERE title = 'zz turn'"))
            db.execute(text("DELETE FROM audit_log WHERE entity = 'external_tool_call' "
                            "AND after->>'server' = 'zz-synth'"))
            db.commit()

    purge()
    with SessionLocal() as db:
        t = Thread(title="zz turn")
        db.add(t)
        db.commit()
        tid = t.id
    conn = SimpleNamespace(slug="zz-synth", server_id=None, destination="zz.example.com", leaves_machine=True)

    def make(run):
        return ext_calls.insert_call(thread_id=tid, turn_id=uuid.UUID(run.id), conn=conn, tool="echo",
                                     args={"text": "ZZ"}, approved=False, reason=None)

    yield make
    purge()


def _state(cid):
    row = ext_calls.read_call(cid)
    return row["approval"], row["decided_via"]


async def test_stop_denies_the_runs_pending_calls(pending):
    run = q.Run(ext=True)
    cid = pending(run)
    await q.stop_run(run)
    assert _state(cid) == ("denied", "stop")


async def test_stop_wakes_a_waiter(pending, monkeypatch):
    woken = []
    monkeypatch.setattr(ext_calls, "wake", woken.append)
    run = q.Run(ext=True)
    cid = pending(run)
    await q.stop_run(run)
    assert woken == [str(cid)]


async def test_stop_finish_run_expires_leftovers_on_a_plain_end(pending):
    run = q.Run(ext=True)
    cid = pending(run)
    await q.finish_run(run)
    assert _state(cid) == ("expired", "expiry")


async def test_stop_without_ext_touches_nothing(pending):
    run = q.Run(ext=False)
    cid = pending(run)
    await q.stop_run(run)
    await q.finish_run(run)
    assert _state(cid) == ("pending", None)
