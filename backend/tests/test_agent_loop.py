"""
Phase 38 agent-loop tests; synthetic values; monai_test only.

LOOP-01: tools_for_turn picks the 18 read tools, plus the 16 propose_* writes
when the turn shows write intent (question verb, or sticky from the last
complete pair). Wiring tests cover agent_stream's subset, the start_turn ->
agent_stream seam and the out-of-subset warning.
"""

import asyncio
import datetime
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

import backend.query as q
from backend import chat_service, skills
from backend.agent_loop import tools_for_turn
from backend.db import SessionLocal
from backend.models import Message, Thread
from backend.tests import chat_stubs
from backend.tests.chat_stubs import (
    StubLLM,
    _collect,
    _install_stub_workflow,
    _of_type,
    _payloads,
    purge_seeded,
)
from backend.tools import READ_TOOL_NAMES, TOOLS

ALL = frozenset(TOOLS)

FAKE = skills.Skill(
    name="zzeval-fake", description="Use when the owner asks for the zz review.", valid=True, reason=None,
    hash="a" * 64, path=Path("/nonexistent"), files=("SKILL.md",), allowed_tools=False,
)

WRITE_QUESTIONS = [
    "Add coffee 25000 to my Cash account",
    "record lunch 60000",
    "log a 15000 parking fee",
    "edit my last transaction",
    "change the category of that to Food",
    "fix the amount",
    "update the account name",
    "correct that date",
    "delete that transaction",
    "remove the duplicate",
    "rename Groceries to Food",
    "merge Snacks into Food",
    "move 500000 from Account A to Account B",
    "transfer 100000 to savings",
    "I bought 10 shares",
    "sell 5 units",
    "adjust my Cash balance",
    "recategorize all Example Merchant rows",
    "top up my investment account",
    "deposit 200000 into Account B",
    "tambah kopi 25000",
    "catat makan siang 60000",
    "hapus transaksi itu",
    "ubah kategorinya",
]

READ_QUESTIONS = [
    "How much did I spend this month?",
    "How much did I spend last month?",
    "How much did I spend between 2024-03-01 and 2024-03-31?",
    "How much did I spend last week?",
    "How much did I spend on ZZEval Hobbies this year?",
    "how much did i spend on zzeval hobbies this year",
    "How much did I spend on Yachts this year?",
    "What's my net worth right now?",
    "What categories do I have?",
    "What was my biggest expense last month?",
    "Show my last transaction in ZZEval Hobbies.",
    "What are my recurring charges?",
    "Compare my spending last month against this month",
    "How much did I spend on ZZEval Hobbies last month?",
    "and this month?",
    "What's the difference between those two?",
    "and the month before that?",
]

_T0 = datetime.datetime(2026, 1, 5, 9, 0, tzinfo=datetime.timezone.utc)


def _pair(user, answer, *, parts=None, status="complete"):
    return [
        {"role": "user", "content": user, "status": "complete", "parts": {}, "created_at": _T0},
        {"role": "assistant", "content": answer, "status": status, "parts": parts or {},
         "created_at": _T0},
    ]


def test_write_questions_table_covers_every_phrasing():
    assert len(WRITE_QUESTIONS) == 24


@pytest.mark.parametrize("question", WRITE_QUESTIONS)
def test_tools_for_turn_write_question_exposes_all(question):
    assert tools_for_turn(question) == ALL


@pytest.mark.parametrize("question", READ_QUESTIONS)
def test_tools_for_turn_read_question_exposes_reads_only(question):
    assert tools_for_turn(question) == READ_TOOL_NAMES
    assert len(READ_TOOL_NAMES) == 18 and len(ALL) == 34


def test_prior_none_judges_question_alone():
    assert tools_for_turn("and last month?", None) == READ_TOOL_NAMES
    assert tools_for_turn("delete it", None) == ALL


@pytest.mark.parametrize(
    "prior",
    [
        _pair("add the thing", "Proposed.", parts={"proposals": [{"id": "p1"}], "steps": []}),
        _pair("do the thing", "Done.", parts={"steps": [{"tool": "propose_add_transaction"}]}),
        _pair("add coffee 25000", "Okay."),
        _pair("how is the budget?", "Would you like me to add it to Account A?"),
    ],
    ids=["proposals", "propose_step", "write_verb_user", "assistant_offer"],
)
def test_sticky_write_intent_from_last_pair(prior):
    assert tools_for_turn("yes, do that", prior) == ALL
    assert tools_for_turn("make it 50000", prior) == ALL


def test_not_sticky_after_read_pair():
    prior = _pair("How much did I spend?", "The change was 12% versus September.")
    assert tools_for_turn("and last month?", prior) == READ_TOOL_NAMES


@pytest.mark.parametrize("status", ["error", "cancelled"])
def test_sticky_after_failed_write_turn(status):
    prior = _pair("How much did I spend?", "Total 100.") + _pair("add coffee", "", status=status)
    assert tools_for_turn("try again", prior) == ALL


def test_not_sticky_when_last_read_turn_errored():
    prior = _pair("How much did I spend?", "Total 100.") + _pair("and income?", "", status="error")
    assert tools_for_turn("and last month?", prior) == READ_TOOL_NAMES


def test_sticky_only_looks_at_the_last_complete_pair():
    prior = _pair("add coffee 25000", "Okay.") + _pair("How much did I spend?", "Total 100.")
    assert tools_for_turn("and last month?", prior) == READ_TOOL_NAMES


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_agent_stream_subset_default_and_explicit(monkeypatch):
    import asyncio

    seen = []

    def fake(tool_names=None):
        seen.append(tool_names)
        wf = MagicMock()
        wf.run.side_effect = RuntimeError("synthetic")
        return wf

    monkeypatch.setattr(q, "_get_agent_workflow", fake)

    async def drain(gen):
        return [line async for line in gen]

    asyncio.run(drain(q.agent_stream("How much did I spend this month?")))
    asyncio.run(drain(q.agent_stream("delete that transaction")))
    explicit = frozenset({"spending_total"})
    asyncio.run(drain(q.agent_stream("anything", tool_names=explicit)))
    assert seen == [READ_TOOL_NAMES, ALL, explicit]


@pytest.fixture()
def thread_id():
    db = SessionLocal()
    t = Thread(title="ZZTest sticky")
    db.add(t)
    db.commit()
    tid = t.id
    db.close()
    yield tid
    db = SessionLocal()
    db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": tid})
    db.commit()
    db.close()


async def _start(monkeypatch, question, tid):
    monkeypatch.setattr(q, "_ACTIVE", {})
    monkeypatch.setattr(q, "_LAST", {})
    got: dict = {}

    async def stub(question, **kw):
        got.update(kw)
        yield "data: " + json.dumps(
            {"type": "answer", "text": "ok", "trace": [], "proposals": []}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(q, "agent_stream", stub)
    run = await chat_service.start_turn(question, tid)
    await run.pump
    return got, run.thread_id


async def test_start_turn_sticky_after_proposal(monkeypatch, thread_id):
    db = SessionLocal()
    db.add(Message(thread_id=thread_id, seq=1, role="user", content="coffee 25000 please"))
    db.add(Message(
        thread_id=thread_id, seq=2, role="assistant", content="Proposed.",
        parts={"proposals": [{"id": str(uuid.uuid4()), "operation": "add_transaction"}],
               "steps": []},
    ))
    db.commit()
    db.close()
    got, _ = await _start(monkeypatch, "yes, do that", thread_id)
    assert got["tool_names"] == ALL


async def test_start_turn_read_question_gets_reads_only(monkeypatch):
    got, tid = await _start(monkeypatch, "How much did I spend this month?", None)
    assert got["tool_names"] == READ_TOOL_NAMES
    db = SessionLocal()
    db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": tid})
    db.commit()
    db.close()


async def test_out_of_subset_call_is_logged_and_turn_continues(monkeypatch, caplog):
    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", tool_name="propose_add_account"))
    with caplog.at_level(logging.WARNING, logger="backend.query"):
        lines = await _collect(q.agent_stream("How much did I spend this month?"))
    assert _of_type(_payloads(lines), "answer")
    hits = [r for r in caplog.records if "propose_add_account" in r.getMessage()]
    assert len(hits) == 1 and hits[0].levelno == logging.WARNING


# ---------------------------------------------------------------------------
# LOOP-02: LLM-only result cap (D-07, D-07a)
# ---------------------------------------------------------------------------


def _rows(n):
    return [{"date": "2020-01-01", "merchant": f"ZZ Merchant {i}", "amount": -10000.0} for i in range(n)]


def test_cap_small_or_non_dict_returns_none():
    from backend.agent_loop import cap_for_llm

    assert cap_for_llm({"tool": "x", "rows": _rows(3)}) is None


def test_cap_non_dict_is_left_alone():
    from backend.agent_loop import cap_for_llm

    assert cap_for_llm("a" * 20000) is None
    assert cap_for_llm([1, 2, 3]) is None


def test_cap_trims_rows_keeps_scalars():
    import ast

    from backend.agent_loop import CAP_CHARS, cap_for_llm

    raw = {"tool": "find_transactions", "rows": _rows(300), "total": 4321.0, "period": "custom"}
    s = cap_for_llm(raw)
    assert len(s) <= CAP_CHARS
    out = ast.literal_eval(s)
    k = len(out["rows"])
    assert 0 < k < 300 and out["rows"] == raw["rows"][:k]
    assert out["total"] == 4321.0 and out["period"] == "custom"
    assert out["truncated"] is True
    assert out["truncated_lists"] == {"rows": {"shown": k, "of": 300}}
    assert "narrow the query" in out["note"]
    assert len(raw["rows"]) == 300  # input never mutated


def test_cap_longest_list_first_and_only_trimmed_lists_listed():
    import ast

    from backend.agent_loop import cap_for_llm

    raw = {"groups": _rows(300), "categories": ["A", "B"], "total": 1.0}
    out = ast.literal_eval(cap_for_llm(raw))
    assert out["categories"] == ["A", "B"]
    assert list(out["truncated_lists"]) == ["groups"]


def test_cap_never_writes_shown_or_total_markers():
    import ast

    from backend.agent_loop import cap_for_llm

    out = ast.literal_eval(cap_for_llm({"rows": _rows(300)}))
    assert "total" not in out and "shown" not in out


def test_cap_keeps_the_tools_own_note():
    import ast

    from backend.agent_loop import cap_for_llm

    out = ast.literal_eval(cap_for_llm({"groups": _rows(300), "note": "ZZ caveat"}))
    assert out["note"].startswith("ZZ caveat (") and "narrow the query" in out["note"]


async def test_zero_arg_tool_is_never_capped():
    """list_categories takes no args, so it cannot be narrowed: the LLM sees all of it."""
    from backend import query

    def zz_reference():
        return {"tool": "zz_reference", "categories": [{"name": f"ZZ Group {i}", "children": []} for i in range(400)]}

    def zz_rows(limit: int = 50):
        return {"tool": "zz_rows", "rows": _rows(300)}

    whole = await query._llm_tool("zz_reference", zz_reference).acall()
    assert "truncated" not in whole.content and "ZZ Group 399" in whole.content
    capped = await query._llm_tool("zz_rows", zz_rows).acall()
    assert "'truncated': True" in capped.content


def test_cap_huge_nested_dict_keeps_only_scalars():
    import ast

    from backend.agent_loop import CAP_CHARS, cap_for_llm

    raw = {"tool": "x", "total": 7.0, "nested": {f"k{i}": "ZZ" * 50 for i in range(500)}, "rows": [{"a": "Z" * 9000}]}
    s = cap_for_llm(raw)
    assert len(s) <= CAP_CHARS
    out = ast.literal_eval(s)
    assert out["total"] == 7.0 and "nested" not in out and "rows" not in out
    assert out["truncated_lists"]["nested"] == {"shown": 0, "of": 500}
    assert out["truncated_lists"]["rows"] == {"shown": 0, "of": 1}


# ---------------------------------------------------------------------------
# LOOP-02 / LOOP-03: tool wrapper (cap callback, serial writes, dedupe, order)
# ---------------------------------------------------------------------------


class _Probe:
    """Records in-flight count, its maximum and start order across tool threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.now = self.max = 0
        self.started: list = []

    def run(self, tag, secs):
        with self.lock:
            self.now += 1
            self.max = max(self.max, self.now)
            self.started.append(tag)
        time.sleep(secs)
        with self.lock:
            self.now -= 1


@pytest.fixture()
def cleanup():
    ids: list = []
    yield ids
    purge_seeded()
    db = SessionLocal()
    for t in ids:
        db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
    db.commit()
    db.close()


async def test_serial_proposers(monkeypatch):
    probe = _Probe()

    def slow_propose(n: int) -> dict:
        """Synthetic proposer."""
        probe.run(n, 0.1)
        return {"tool": "slow_propose", "n": n}

    llm = StubLLM(mode="script", script=[[("slow_propose", {"n": 1}), ("slow_propose", {"n": 2})]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"slow_propose": slow_propose})
    lines = await _collect(q.agent_stream("ZZ two writes"))
    assert probe.max == 1 and probe.started == [1, 2]
    assert len(_of_type(_payloads(lines), "tool_result")) == 2


async def test_six_proposers_serial(monkeypatch):
    probe = _Probe()

    def slow_propose(n: int) -> dict:
        """Synthetic proposer."""
        probe.run(n, 0.02)
        return {"tool": "slow_propose", "n": n}

    llm = StubLLM(mode="script", script=[[("slow_propose", {"n": i}) for i in range(6)]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"slow_propose": slow_propose})
    lines = await _collect(q.agent_stream("ZZ six writes"))
    assert probe.max == 1 and sorted(probe.started) == list(range(6))
    assert len(_of_type(_payloads(lines), "tool_result")) == 6


async def test_parallel_reads_overlap(monkeypatch):
    probe = _Probe()

    def spending_total() -> dict:
        """Synthetic read."""
        probe.run("s", 0.3)
        return {"tool": "spending_total", "total": 1.0}

    def income_total() -> dict:
        """Synthetic read."""
        probe.run("i", 0.3)
        return {"tool": "income_total", "total": 2.0}

    llm = StubLLM(mode="script", script=[[("spending_total", {}), ("income_total", {})]])
    _install_stub_workflow(
        monkeypatch, llm, extra_tools={"spending_total": spending_total, "income_total": income_total})
    await _collect(q.agent_stream("ZZ two reads"))
    assert probe.max == 2


def _proposal_rows(turn_id):
    db = SessionLocal()
    try:
        return db.execute(
            text("SELECT id, token, payload FROM proposals WHERE turn_id = :t ORDER BY created_at, id"),
            {"t": turn_id}).all()
    finally:
        db.close()


def _assistant_parts(tid):
    db = SessionLocal()
    try:
        m = db.query(Message).filter(Message.thread_id == tid, Message.role == "assistant").one()
        return m.parts
    finally:
        db.close()


async def test_dedupe_one_row(monkeypatch, cleanup):
    llm = StubLLM(mode="script", script=[[("seed_proposal", {})], [("seed_proposal", {})]])
    _install_stub_workflow(monkeypatch, llm)
    run = await chat_service.start_turn("ZZ add it", None)
    cleanup.append(run.thread_id)
    payloads = _payloads(await _collect(q.run_stream(run)))

    rows = _proposal_rows(uuid.UUID(run.id))
    assert len(rows) == 1
    results = _of_type(payloads, "tool_result")
    assert [r["step"]["result"]["proposal_id"] for r in results] == [str(rows[0].id)] * 2
    assert [r["step"]["result"].get("duplicate_of_earlier_call") for r in results] == [None, True]
    assert "no new proposal was created" in "".join(llm.seen[2])
    answer = _of_type(payloads, "answer")[0]
    assert [p["id"] for p in answer["proposals"]] == [str(rows[0].id)]
    assert run.proposal_ids == [str(rows[0].id)]
    assert [p["id"] for p in _assistant_parts(run.thread_id)["proposals"]] == [str(rows[0].id)]
    assert rows[0].token not in json.dumps(llm.seen)


async def test_proposal_order_matches_creation_order(monkeypatch, cleanup):
    def seed_with(n: int) -> dict:
        """Synthetic proposer whose payload amount encodes n."""
        from backend.tools import _make_proposal

        pid, token = _make_proposal(
            "add_transaction",
            {"operation": "add_transaction",
             "rows": [{"before": None, "after": {"amount": str(n * 1000)}}]},
            "chat")
        chat_stubs._SEEDED.append(uuid.UUID(pid))
        return {"tool": "seed_with", "proposal_id": pid, "proposal_token": token}

    llm = StubLLM(mode="script", script=[[("seed_with", {"n": i}) for i in (1, 2, 3)]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"seed_with": seed_with})
    run = await chat_service.start_turn("ZZ add three", None)
    cleanup.append(run.thread_id)
    payloads = _payloads(await _collect(q.run_stream(run)))

    rows = _proposal_rows(uuid.UUID(run.id))
    db_ids = [str(r.id) for r in rows]
    assert [int(r.payload["rows"][0]["after"]["amount"]) // 1000 for r in rows] == [1, 2, 3]
    assert [p["id"] for p in _of_type(payloads, "answer")[0]["proposals"]] == db_ids
    assert [p["id"] for p in _assistant_parts(run.thread_id)["proposals"]] == db_ids


async def test_cap_llm_sees_trimmed_sse_sees_full(monkeypatch):
    full = {"tool": "find_transactions", "rows": _rows(300), "total": 4321.0}

    def find_transactions(limit: int = 50) -> dict:
        """Synthetic read."""
        return full

    llm = StubLLM(mode="script", script=[[("find_transactions", {})]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"find_transactions": find_transactions})
    lines = await _collect(q.agent_stream("ZZ big read"))
    second = "".join(llm.seen[1])
    assert "truncated_lists" in second and "4321.0" in second
    assert len(second) < len(str(full))
    result = _of_type(_payloads(lines), "tool_result")[0]["step"]["result"]
    assert len(result["rows"]) == 300


async def test_stall_regression_guard(monkeypatch):
    """GET /health stays fast while a 2 s tool runs inside a turn (D-10).

    A regression guard, green before and after the async wrapper: RESEARCH D-09a
    found sync tools already ran in an executor. Not a red-to-green test.
    """
    import httpx

    from backend.main import app

    started, finished = threading.Event(), threading.Event()

    def spending_total() -> dict:
        """Synthetic slow read."""
        started.set()
        time.sleep(2)
        finished.set()
        return {"tool": "spending_total", "total": 1.0}

    started.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        # Warm up: the cold first run has a ~250 ms import gap (RESEARCH Pitfall 10).
        _install_stub_workflow(monkeypatch, StubLLM())
        await _collect(q.agent_stream("ZZ warm up"))
        await c.get("/health")
        _install_stub_workflow(
            monkeypatch, StubLLM(mode="script", script=[[("spending_total", {})]]),
            extra_tools={"spending_total": spending_total})
        task = asyncio.create_task(_collect(q.agent_stream("ZZ stall probe")))
        assert await asyncio.to_thread(started.wait, 5)
        t0 = time.monotonic()
        r = await c.get("/health")
        elapsed = time.monotonic() - t0
        assert r.status_code == 200 and elapsed < 0.2
        assert not finished.is_set()
        await task


# ---------------------------------------------------------------------------
# 38-05: tail reminder agent and prompt rules (LOOP-07, D-15, D-07)
# ---------------------------------------------------------------------------


def test_prompt_rules():
    p = q._SYSTEM_PROMPT
    assert "13. For a request that needs two or more separate changes" in p
    assert "repeat the numbered plan in your final answer" in p
    assert "14. A tool result marked truncated is partial" in p
    assert "I can also add, edit, or delete transactions" in p  # rule 3 untouched (D-06)


def test_workflow_uses_tail_agent(monkeypatch):
    from llama_index.core.llms import MockLLM

    from backend import agent_loop

    monkeypatch.setattr(q, "_agent_workflows", {})
    monkeypatch.setattr(q, "_get_llm", lambda: MockLLM())
    cls = agent_loop.tail_agent_cls()
    assert cls is agent_loop.tail_agent_cls()
    assert isinstance(q._get_agent_workflow().agents["Agent"], cls)
    assert isinstance(q._get_agent_workflow(READ_TOOL_NAMES).agents["Agent"], cls)


def _slow_echo(n: int) -> dict:
    """Synthetic read."""
    return {"tool": "slow_echo", "n": n}


def _two_rounds():
    return StubLLM(mode="script", script=[[("slow_echo", {"n": 1})], [("slow_echo", {"n": 2})]])


def _assert_tail_last(llm, calls):
    from backend.agent_loop import TAIL_REMINDER

    assert len(llm.seen_roles) == calls
    for call in llm.seen_roles:
        assert call[-1] == ("system", TAIL_REMINDER)
        assert sum(c == TAIL_REMINDER for _, c in call) == 1


async def test_tail_reminder_last_on_every_call(monkeypatch):
    from backend import agent_loop

    llm = _two_rounds()
    _install_stub_workflow(
        monkeypatch, llm, agent_cls=agent_loop.tail_agent_cls(), extra_tools={"slow_echo": _slow_echo})
    await _collect(q.agent_stream("ZZ two rounds"))
    _assert_tail_last(llm, 3)
    for call in llm.seen_roles[1:]:
        assert call[-2][0] == "tool"


async def test_tail_reminder_never_streamed_or_persisted(monkeypatch, cleanup):
    from backend import agent_loop

    first = agent_loop.TAIL_REMINDER.split(".")[0]
    llm = _two_rounds()
    _install_stub_workflow(
        monkeypatch, llm, agent_cls=agent_loop.tail_agent_cls(), extra_tools={"slow_echo": _slow_echo})
    question = "ZZ persisted reminder"
    run = await chat_service.start_turn(question, None)
    cleanup.append(run.thread_id)
    lines = await _collect(q.run_stream(run))
    _assert_tail_last(llm, 3)
    assert not any(first in line for line in lines)
    db = SessionLocal()
    rows = db.query(Message).filter(Message.thread_id == run.thread_id).order_by(Message.seq).all()
    db.close()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == question
    assert all(first not in (r.content or "") and first not in json.dumps(r.parts) for r in rows)


async def test_tail_reminder_on_long_trimmed_thread(monkeypatch):
    from backend import agent_loop
    from backend.chat_history import plan_history

    msgs = []
    for i in range(40):
        msgs += _pair(f"ZZ question {i} " + "x" * 400, f"ZZ answer {i} " + "y" * 400)
    history, _ = plan_history(msgs, 600, datetime.date(2026, 1, 6), summary="ZZ synthetic summary")
    assert len(history) < 80
    llm = _two_rounds()
    _install_stub_workflow(
        monkeypatch, llm, agent_cls=agent_loop.tail_agent_cls(), extra_tools={"slow_echo": _slow_echo})
    await _collect(q.agent_stream("ZZ long", history=history))
    _assert_tail_last(llm, 3)
    for call in llm.seen_roles:
        assert call[0] == ("system", "synthetic")
        assert call[1][1].startswith("Summary of earlier conversation")


def _convert_ollama(ms):
    from llama_index.llms.ollama import Ollama

    return Ollama(model="example-model:7b")._convert_to_ollama_messages(ms)


def _convert_openai(ms):
    from llama_index.llms.openai.utils import to_openai_message_dicts

    return to_openai_message_dicts(ms)


def _convert_anthropic(ms):
    from llama_index.llms.anthropic.utils import messages_to_anthropic_messages

    return messages_to_anthropic_messages(ms)  # (messages, system_prompt)


@pytest.mark.parametrize(
    "pkg,convert",
    [("llama_index.llms.ollama", _convert_ollama),
     ("llama_index.llms.openai", _convert_openai),
     ("llama_index.llms.anthropic", _convert_anthropic)],
)
def test_adapter_trailing_system(pkg, convert):
    """D-28: a trailing system reminder after a tool message survives conversion.
    Ollama and OpenAI keep it as the last message; Anthropic folds it into the
    system prompt."""
    pytest.importorskip(pkg)
    from llama_index.core.base.llms.types import ToolCallBlock
    from llama_index.core.llms import ChatMessage

    from backend.agent_loop import TAIL_REMINDER

    msgs = [
        ChatMessage(role="system", content="synthetic"),
        ChatMessage(role="user", content="ZZ question"),
        ChatMessage(role="assistant", content="", blocks=[
            ToolCallBlock(tool_call_id="call_1", tool_name="slow_echo", tool_kwargs={"n": 1})]),
        ChatMessage(role="tool", content="{'n': 1}", additional_kwargs={"tool_call_id": "call_1"}),
        ChatMessage(role="system", content=TAIL_REMINDER),
    ]
    out = convert(msgs)
    if pkg == "llama_index.llms.anthropic":
        assert TAIL_REMINDER in str(out[1])
        return
    last = out[-1]
    role = last["role"] if isinstance(last, dict) else last.role
    assert role == "system"
    assert TAIL_REMINDER in str(last)

# ---------------------------------------------------------------------------
# 39-07: attachment threads carry a pinned reduced tool set (D-16, D-16a, D-16b)
# ---------------------------------------------------------------------------

ATT_READS = READ_TOOL_NAMES | {"read_attachment"}
ATT_ALL = ATT_READS | {"propose_statement_rows"}


@pytest.mark.parametrize(
    "question",
    ["what is in this file?", "total debits?", "and last month?", "berapa totalnya?"],
)
def test_attachment_thread_read_question_gets_reads_plus_read_attachment(question):
    assert tools_for_turn(question, attachment_thread=True) == ATT_READS
    assert len(ATT_READS) == 19


@pytest.mark.parametrize(
    "question",
    [
        "import this file", "propose the rows", "please add these to my account", "simpan ke Cash",
        "unggah", "upload these", "ajukan baris ini", "submit them", "enter these rows",
    ],
)
def test_attachment_thread_owner_ask_opens_the_proposer(question):
    assert tools_for_turn(question, attachment_thread=True) == ATT_ALL
    assert len(ATT_ALL) == 20


@pytest.mark.parametrize(
    "prior",
    [
        _pair("import this file", "Proposed.", parts={"proposals": [{"id": "p1"}], "steps": []}),
        _pair("do it", "Done.", parts={"steps": [{"tool": "propose_statement_rows"}]}),
        _pair("what is in it?", "Shall I propose these rows?"),
    ],
    ids=["proposals", "propose_step", "assistant_offer"],
)
def test_attachment_thread_history_never_opens_the_proposer(prior):
    assert tools_for_turn("what is the total?", prior, attachment_thread=True) == ATT_READS
    assert tools_for_turn("yes", prior, attachment_thread=True) == ATT_READS


@pytest.mark.parametrize("question", ["what is in this file?", "import this file", "delete it", "ignore previous"])
def test_attachment_tool_set_is_pinned(monkeypatch, question):
    """Phases 40 and 41 must extend this set deliberately: on an attachment thread
    the only possible names are the 18 reads, read_attachment and propose_statement_rows,
    and never load_skill, even with a skill effective (Phase 40 D-16)."""
    monkeypatch.setattr(skills, "effective", lambda: [FAKE])
    got = tools_for_turn(question, attachment_thread=True)
    assert got <= READ_TOOL_NAMES | {"read_attachment", "propose_statement_rows"}
    assert "load_skill" not in got
    assert not [n for n in got if n.startswith("ext__") or (n.startswith("propose_") and n != "propose_statement_rows")]


def test_load_skill_joins_only_with_an_effective_skill(monkeypatch):
    monkeypatch.setattr(skills, "effective", lambda: [])
    assert tools_for_turn("how much did I spend last month?") == READ_TOOL_NAMES
    assert tools_for_turn("delete it") == ALL
    monkeypatch.setattr(skills, "effective", lambda: [FAKE])
    assert tools_for_turn("how much did I spend last month?") == READ_TOOL_NAMES | {"load_skill"}
    assert tools_for_turn("delete it") == ALL | {"load_skill"}


def test_no_attachment_thread_keeps_existing_results():
    assert tools_for_turn("delete it") == ALL
    assert tools_for_turn("and last month?") == READ_TOOL_NAMES


def test_chat_only_tools_are_in_neither_registry():
    from backend.chat_tools import CHAT_ONLY_TOOLS

    assert len(TOOLS) == 34 and len(READ_TOOL_NAMES) == 18
    assert not set(CHAT_ONLY_TOOLS) & set(TOOLS) and not set(CHAT_ONLY_TOOLS) & READ_TOOL_NAMES


def _agent(monkeypatch, names=None):
    from llama_index.core.llms import MockLLM

    monkeypatch.setattr(q, "_agent_workflows", {})
    monkeypatch.setattr(q, "_get_llm", lambda: MockLLM())
    return q._get_agent_workflow(names).agents["Agent"]


def _tool_names(agent):
    return {t.metadata.name for t in agent.tools}


def test_skill_catalog_only_when_load_skill_is_offered(monkeypatch):
    monkeypatch.setattr(skills, "effective", lambda: [FAKE])
    read = _agent(monkeypatch, tools_for_turn("how much did I spend?"))
    assert "load_skill" in _tool_names(read)
    assert "<available_skills>" in read.system_prompt
    assert "zzeval-fake: Use when the owner asks for the zz review." in read.system_prompt
    att = _agent(monkeypatch, tools_for_turn("what is in this file?", attachment_thread=True))
    assert "load_skill" not in _tool_names(att) and "<available_skills>" not in att.system_prompt
    plain = _agent(monkeypatch, READ_TOOL_NAMES)
    assert "<available_skills>" not in plain.system_prompt


def test_skill_catalog_survives_braces(monkeypatch):
    braces = skills.Skill(**{**FAKE.__dict__, "description": "Use for {today} and {0} braces"})
    monkeypatch.setattr(skills, "effective", lambda: [braces])
    agent = _agent(monkeypatch, READ_TOOL_NAMES | {"load_skill"})
    assert "zzeval-fake: Use for {today} and {0} braces" in agent.system_prompt


def test_skills_fingerprint_rebuilds_the_workflow(monkeypatch):
    from llama_index.core.llms import MockLLM

    monkeypatch.setattr(q, "_agent_workflows", {})
    monkeypatch.setattr(q, "_get_llm", lambda: MockLLM())
    names = READ_TOOL_NAMES | {"load_skill"}
    monkeypatch.setattr(skills, "effective", lambda: [FAKE])
    wf1 = q._get_agent_workflow(names)
    assert q._get_agent_workflow(names) is wf1
    changed = skills.Skill(**{**FAKE.__dict__, "hash": "b" * 64})
    monkeypatch.setattr(skills, "effective", lambda: [changed])
    wf2 = q._get_agent_workflow(names)
    assert wf2 is not wf1 and len(q._agent_workflows) == 1


async def test_turn_setup_scans_skills_off_the_event_loop(monkeypatch, thread_id):
    # WR-02: the scan reads files and the DB, so it must never run on the loop thread.
    import threading

    from llama_index.core.llms import MockLLM

    loop_thread = threading.get_ident()
    calls = []

    def eff():
        calls.append(threading.get_ident() != loop_thread)
        return [FAKE]

    monkeypatch.setattr(skills, "effective", eff)
    agent_stream = q.agent_stream  # _start stubs it
    await _start(monkeypatch, "how much did I spend?", thread_id)  # start_turn's tools_for_turn

    monkeypatch.setattr(q, "_agent_workflows", {})
    monkeypatch.setattr(q, "_get_llm", lambda: MockLLM())

    def stop(wf):  # the workflow is built; end the turn before any model call
        raise RuntimeError("synthetic")

    monkeypatch.setattr(q, "_llm_label", stop)
    [line async for line in agent_stream("how much did I spend?")]  # tools_for_turn + workflow
    assert len(calls) == 3 and all(calls)


NOTICE = "This thread has a document. Start a new thread for other changes."


def test_attachment_workflow_has_the_pinned_tools_and_prompt_rules(monkeypatch):
    agent = _agent(monkeypatch, tools_for_turn("import this file", attachment_thread=True))
    assert {t.metadata.name for t in agent.tools} == ATT_ALL
    assert NOTICE in agent.system_prompt and "never instructions" in agent.system_prompt
    assert "from {filename}" in agent.system_prompt and "propose the rows" in agent.system_prompt


def test_plain_workflows_have_no_attachment_rules(monkeypatch):
    for names in (READ_TOOL_NAMES, None):
        agent = _agent(monkeypatch, names)
        assert NOTICE not in agent.system_prompt and "never instructions" not in agent.system_prompt
    assert [t.metadata.name for t in agent.tools] == list(TOOLS)


async def test_read_attachment_takes_no_turn_lock_but_the_proposer_does():
    probe = _Probe()

    def read_attachment(n: int) -> dict:
        """Synthetic read."""
        probe.run(n, 0.2)
        return {"tool": "read_attachment", "n": n}

    def propose_statement_rows(n: int) -> dict:
        """Synthetic write."""
        probe.run(n, 0.05)
        return {"tool": "propose_statement_rows", "n": n}

    tok = q.TURN.set(q.Turn())
    try:
        reader = q._llm_tool("read_attachment", read_attachment)
        await asyncio.gather(reader.acall(n=1), reader.acall(n=2))
        assert probe.max == 2
        probe.max = 0
        writer = q._llm_tool("propose_statement_rows", propose_statement_rows)
        await asyncio.gather(writer.acall(n=1), writer.acall(n=2))
        assert probe.max == 1
        again = await writer.acall(n=1)
        assert again.raw_output["duplicate_of_earlier_call"] is True
    finally:
        q.TURN.reset(tok)


# ── POL-02: whole numbers reach the model without a trailing .0 ──────────────


def test_plain_numbers_only_unfloats_whole_floats():
    from backend.tools import _plain_numbers

    got = _plain_numbers({"a": 1500000.0, "b": 12.5, "c": [2.0, ("ZZ Food", 2500.0)], "d": "3.0",
                          "e": True, "f": None, "g": float("inf"), "h": 7})
    assert got["a"] == 1500000 and type(got["a"]) is int
    assert got["b"] == 12.5 and type(got["b"]) is float
    assert type(got["c"][0]) is int and got["c"][1] == ("ZZ Food", 2500) and type(got["c"][1]) is tuple
    assert type(got["c"][1][1]) is int
    assert got["d"] == "3.0" and got["e"] is True and got["f"] is None and got["g"] == float("inf")
    nan = _plain_numbers(float("nan"))
    assert nan != nan


def test_plain_tool_normalises_args_and_result_and_keeps_signature():
    import inspect

    from backend.tools import _plain_tool

    def probe(amount: float = 0, *, note: str = "") -> dict:
        """Synthetic doc."""
        return {"amount_seen": amount, "type": type(amount).__name__, "out": amount * 1.0}

    wrapped = _plain_tool(probe)
    assert wrapped.__name__ == "probe" and wrapped.__doc__ == "Synthetic doc."
    assert inspect.signature(wrapped) == inspect.signature(probe)
    got = wrapped(amount=-25000.0)
    assert got["type"] == "int" and got["out"] == -25000 and type(got["out"]) is int
    assert wrapped(12.5)["out"] == 12.5


def test_every_registry_tool_is_wrapped_and_counts_hold():
    from backend.tools import READ_TOOL_NAMES

    assert len(TOOLS) == 34 and len(READ_TOOL_NAMES) == 18
    assert all(hasattr(fn, "__wrapped__") for fn in TOOLS.values())


async def test_whole_amounts_reach_the_model_plain(monkeypatch):
    from backend.tools import _plain_tool

    def spending_total(period: str = "this_month") -> dict:
        """Synthetic read."""
        return {"tool": "spending_total", "total": 1500000.0, "pair": ("ZZ Food", 2500.0), "share": 12.5}

    llm = StubLLM(mode="script", script=[[("spending_total", {})]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"spending_total": _plain_tool(spending_total)})
    lines = await _collect(q.agent_stream("ZZ plain read"))
    second = "".join(llm.seen[1])
    assert "'total': 1500000," in second and "('ZZ Food', 2500)" in second and "12.5" in second
    assert not re.search(r"\d\.0(?!\d)", second)
    step = _of_type(_payloads(lines), "tool_result")[0]["step"]["result"]
    assert step["total"] == 1500000


# ── POL-01: the model reads one line per recurring group ─────────────────────


def _zz_groups(n: int) -> list[dict]:
    out = []
    for i in range(n):
        usd = i == 1
        g = {
            "label": f"ZZ Sub {i:02d}", "key_type": "text", "category": "ZZ Bills",
            "cadence": ("weekly", "monthly", "quarterly", "yearly")[i % 4], "median_interval_days": 30.0,
            "currency": "USD" if usd else "IDR",
            "typical_amount": 9.99 if usd else 100000.0 + i * 1000, "amount_min": 1.0, "amount_max": 2.0,
            "typical_amount_idr": 160000.0 if usd else 100000.0 + i * 1000,
            "est_monthly": 1234567.0 - i * 10000, "occurrences": 12, "first_date": "1996-01-01",
            "last_date": "1996-12-01", "status": "lapsed" if i == 2 else "active",
            "confidence": ("high", "medium", "low")[i % 3],
            "evidence": [{"id": j, "date": "1996-01-01", "amount": 100000.0, "account_id": 1} for j in range(12)],
        }
        if g["status"] == "active":
            g["next_expected"] = "1997-01-01"
            g["overdue"] = i == 3
        out.append(g)
    return out


def _zz_recurring(n: int = 20) -> dict:
    return {"tool": "recurring_charges", "currency": "IDR", "months": 24, "total_detected": n,
            "groups": _zz_groups(n), "note": "Likely recurring.", "fx_note": "ZZ rate note"}


def test_recurring_for_llm_one_line_per_group_under_the_cap():
    import copy

    from backend.agent_loop import CAP_CHARS, recurring_for_llm

    raw = _zz_recurring()
    before = copy.deepcopy(raw)
    view = recurring_for_llm(raw)
    assert raw == before
    assert len(str(view)) < CAP_CHARS
    assert len(view["groups"]) == 20 and all(isinstance(g, str) for g in view["groups"])
    assert "evidence" not in str(view)
    for k in ("tool", "currency", "months", "total_detected", "note", "fx_note"):
        assert view[k] == raw[k]
    first = view["groups"][0]
    assert "ZZ Sub 00" in first and "weekly" in first and "1,234,567" in first and "high confidence" in first
    assert "1,234,567.00" not in first and "next expected 1997-01-01" in first
    assert "9.99 USD" in view["groups"][1] and "IDR a month" in view["groups"][1]
    assert "lapsed" in view["groups"][2] and "next expected" not in view["groups"][2]
    assert "overdue since 1997-01-01" in view["groups"][3]


def test_recurring_line_gives_a_monthly_idr_charge_one_figure():
    """POL-01: its typical amount equals its monthly cost, and with both the model kept only the typical."""
    from backend.agent_loop import recurring_for_llm

    group = {"label": "ZZ Sub", "cadence": "monthly", "est_monthly": 50000.0, "typical_amount": 50000.0,
             "currency": "IDR", "confidence": "low", "status": "active", "last_date": "1996-03-01"}
    raw = {"tool": "recurring_charges", "currency": "IDR", "groups": [group, {**group, "currency": "USD", "typical_amount": 3.0}]}
    idr, usd = recurring_for_llm(raw)["groups"]
    assert "50,000 IDR a month" in idr and "typically" not in idr
    assert "50,000 IDR a month" in usd and "typically 3.00 USD" in usd


def test_recurring_for_llm_fits_the_default_limit_under_the_cap():
    from backend.agent_loop import CAP_CHARS, recurring_for_llm

    raw = _zz_recurring()
    raw["groups"] = (raw["groups"] * 3)[:50]
    view = recurring_for_llm(raw)
    assert len(view["groups"]) == 50 and len(str(view)) < CAP_CHARS


def test_recurring_for_llm_passes_a_refusal_through():
    from backend.agent_loop import recurring_for_llm

    err = {"tool": "recurring_charges", "error": "no rate"}
    assert recurring_for_llm(err) is err


async def test_recurring_groups_all_reach_the_model_but_sse_keeps_evidence(monkeypatch):
    raw = _zz_recurring()

    def recurring_charges(months: int = 24, limit: int = 20) -> dict:
        """Synthetic read."""
        return raw

    llm = StubLLM(mode="script", script=[[("recurring_charges", {})]])
    _install_stub_workflow(monkeypatch, llm, extra_tools={"recurring_charges": recurring_charges})
    lines = await _collect(q.agent_stream("ZZ recurring"))
    second = "".join(llm.seen[1])
    assert all(f"ZZ Sub {i:02d}" in second for i in range(20)) and "truncated" not in second
    result = _of_type(_payloads(lines), "tool_result")[0]["step"]["result"]
    assert len(result["groups"]) == 20 and len(result["groups"][0]["evidence"]) == 12
