"""
Phase 38 compaction: lazy rolling summary, CAS writes, chunking, one in flight.

A stub summariser stands in for the provider (`query._get_llm`). All content is
synthetic (ZZ-prefixed); the DB is the isolated monai_test database.
"""

import asyncio
import logging
import uuid

import pytest
from llama_index.core.llms import ChatMessage, ChatResponse
from sqlalchemy import text

import backend.query as q
from backend import chat_service, config
from backend.db import SessionLocal
from backend.models import Message, Thread
from backend.tests.chat_stubs import (
    Err429,
    StubLLM,
    _install_stub_workflow,
    _seed_proposal,
    purge_seeded,
)

PAD = "x" * 380


class StubSummariser:
    """Records every achat call. mode: ok | 429 | empty. `hook` runs before the reply."""

    def __init__(self, text_="ZZ stub summary {n}", mode="ok", hook=None):
        self.text, self.mode, self.hook = text_, mode, hook
        self.calls: list[list[ChatMessage]] = []

    async def achat(self, messages, **kw):
        self.calls.append(list(messages))
        if self.hook:
            await self.hook()
        if self.mode == "429":
            raise Err429("synthetic")
        content = "" if self.mode == "empty" else self.text.format(n=len(self.calls))
        return ChatResponse(message=ChatMessage(role="assistant", content=content))


@pytest.fixture()
async def env(monkeypatch):
    monkeypatch.setattr(q, "_ACTIVE", {})
    monkeypatch.setattr(q, "_LAST", {})
    monkeypatch.setattr(chat_service, "_COMPACTING", set())
    threads: list = []
    yield threads
    if chat_service._BG:
        await asyncio.gather(*list(chat_service._BG), return_exceptions=True)
    db = SessionLocal()
    for t in threads:
        db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
    db.commit()
    db.close()
    purge_seeded()


def _seed(threads, pairs=3, summary=None, upto=0, assistant_parts=None, last_status="complete"):
    db = SessionLocal()
    try:
        t = Thread(title="ZZ compaction", summary=summary, summary_upto_seq=upto)
        db.add(t)
        db.flush()
        for i in range(pairs):
            db.add(Message(thread_id=t.id, seq=2 * i + 1, role="user",
                           content=f"ZZ question {i} {PAD}", status="complete", parts={}))
            last = i == pairs - 1
            db.add(Message(
                thread_id=t.id, seq=2 * i + 2, role="assistant",
                content=f"ZZ answer {i} {PAD}",
                status=last_status if last else "complete",
                parts=assistant_parts if (last and assistant_parts) else {},
            ))
        db.commit()
        threads.append(t.id)
        return t.id
    finally:
        db.close()


def _cols(tid):
    db = SessionLocal()
    try:
        t = db.get(Thread, tid)
        return t.summary, t.summary_upto_seq
    finally:
        db.close()


def _sql(stmt, **params):
    db = SessionLocal()
    db.execute(text(stmt), params)
    db.commit()
    db.close()


async def _turn(tid):
    run = await chat_service.start_turn("ZZ next", tid)
    assert run is not None
    async for _ in q.run_stream(run):
        pass
    await run.pump  # the compaction is scheduled at the end of the pump
    if chat_service._BG:
        await asyncio.gather(*list(chat_service._BG))


async def test_post_turn_runs_when_pairs_dropped(monkeypatch, env):
    _install_stub_workflow(monkeypatch, StubLLM())
    stub = StubSummariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    monkeypatch.setattr(config, "CHAT_HISTORY_TOKEN_BUDGET", 300)
    tid = _seed(env, pairs=10)
    await _turn(tid)

    summary, upto = _cols(tid)
    assert summary == "ZZ stub summary 1"
    assert 0 < upto < 22 and upto % 2 == 0  # a folded assistant seq, below the max
    assert stub.calls[0][0].content == chat_service.SUMMARY_PROMPT
    assert "Omit every amount" in stub.calls[0][0].content


async def test_no_compaction_under_budget(monkeypatch, env):
    _install_stub_workflow(monkeypatch, StubLLM())
    stub = StubSummariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    tid = _seed(env, pairs=2)
    await _turn(tid)

    assert not chat_service._BG and not stub.calls
    assert _cols(tid) == (None, 0)


async def test_schedule_skipped_while_busy(env):
    tid = uuid.uuid4()
    q._ACTIVE[str(tid)] = q.Run(key=str(tid))
    assert chat_service.schedule_compaction(tid) is None
    q._ACTIVE.clear()
    chat_service._COMPACTING.add(str(tid))
    assert chat_service.schedule_compaction(tid) is None


@pytest.mark.parametrize("mode", ["429", "empty"])
async def test_failure_leaves_columns(monkeypatch, env, caplog, mode):
    stub = StubSummariser(mode=mode)
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    tid = _seed(env, pairs=3, summary="ZZ old summary", upto=2)
    with pytest.raises(Exception):
        await chat_service.compact_thread(tid, everything=True)
    assert _cols(tid) == ("ZZ old summary", 2)

    monkeypatch.setattr(config, "CHAT_HISTORY_TOKEN_BUDGET", 300)  # so the auto path has pairs
    with caplog.at_level(logging.WARNING):
        await chat_service._auto_compact(tid)
    assert "compaction failed" in caplog.text
    assert "ZZ" not in caplog.text
    assert not chat_service._COMPACTING


async def test_cas_drops_after_clear(monkeypatch, env):
    tid = _seed(env, pairs=3)

    async def clear():
        _sql("UPDATE threads SET summary = NULL, summary_upto_seq = 99 WHERE id = :t", t=tid)

    monkeypatch.setattr(q, "_get_llm", lambda: StubSummariser(hook=clear))
    res = await chat_service.compact_thread(tid, everything=True)
    assert res["compacted"] is False
    assert _cols(tid) == (None, 99)


async def test_cas_drops_when_folded_message_deleted(monkeypatch, env):
    tid = _seed(env, pairs=3)

    async def drop():
        _sql("DELETE FROM messages WHERE thread_id = :t AND seq >= 3", t=tid)

    monkeypatch.setattr(q, "_get_llm", lambda: StubSummariser(hook=drop))
    res = await chat_service.compact_thread(tid, everything=True)
    assert res["compacted"] is False
    assert _cols(tid) == (None, 0)


async def test_chunked_progressive(monkeypatch, env):
    stub = StubSummariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    monkeypatch.setattr(chat_service, "SUMMARY_INPUT_CHARS", 900)
    tid = _seed(env, pairs=6)
    res = await chat_service.compact_thread(tid, everything=True)

    assert len(stub.calls) > 1 and res == {"summary_upto_seq": 12, "has_summary": True, "compacted": True}
    for call in stub.calls:
        assert len(call[1].content.split("Conversation to fold in:\n", 1)[1]) <= 900
    assert "Current summary:\nZZ stub summary 1\n" in stub.calls[1][1].content
    assert _cols(tid) == (f"ZZ stub summary {len(stub.calls)}", 12)


async def test_one_in_flight(monkeypatch, env):
    gate = asyncio.Event()

    async def wait():
        await gate.wait()

    monkeypatch.setattr(q, "_get_llm", lambda: StubSummariser(hook=wait))
    tid = _seed(env, pairs=2)
    first = asyncio.create_task(chat_service.compact_thread(tid, everything=True))
    await asyncio.sleep(0)
    assert chat_service.thread_busy(str(tid))
    with pytest.raises(chat_service.ThreadBusy):
        await chat_service.compact_thread(tid, everything=True)
    gate.set()
    await first
    assert not chat_service._COMPACTING


async def test_summary_capped(monkeypatch, env):
    monkeypatch.setattr(q, "_get_llm", lambda: StubSummariser(text_="y" * 5000))
    tid = _seed(env, pairs=2)
    await chat_service.compact_thread(tid, everything=True)
    assert len(_cols(tid)[0]) == chat_service.SUMMARY_MAX_CHARS


async def test_input_shape(monkeypatch, env):
    stub = StubSummariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    pid, _ = _seed_proposal()
    parts = {
        "steps": [{"tool": "spending_total", "args": {"period": "last_month"},
                   "result": "ZZSECRETRESULT"}],
        "proposals": [{"id": pid, "operation": "add_transaction"}],
    }
    tid = _seed(env, pairs=1, assistant_parts=parts)
    await chat_service.compact_thread(tid, everything=True)

    body = stub.calls[0][1].content
    assert "add_transaction pending" in body
    assert "[tools used: spending_total(period=last_month)]" in body
    assert "ZZSECRETRESULT" not in body and "result" not in body.split("fold in:")[1]


async def test_nothing_to_fold(monkeypatch, env):
    stub = StubSummariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    tid = _seed(env, pairs=1, last_status="error")
    res = await chat_service.compact_thread(tid, everything=True)
    assert res == {"summary_upto_seq": 0, "has_summary": False, "compacted": False}
    assert not stub.calls and _cols(tid) == (None, 0)
