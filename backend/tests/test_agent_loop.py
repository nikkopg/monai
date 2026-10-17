"""
Phase 38 agent-loop tests; synthetic values; monai_test only.

LOOP-01: tools_for_turn picks the 18 read tools, plus the 16 propose_* writes
when the turn shows write intent (question verb, or sticky from the last
complete pair). Wiring tests cover agent_stream's subset, the start_turn ->
agent_stream seam and the out-of-subset warning.
"""

import datetime
import json
import logging
import threading
import time
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

import backend.query as q
from backend import chat_service
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


def test_not_sticky_when_last_turn_errored():
    prior = _pair("How much did I spend?", "Total 100.") + _pair("add coffee", "", status="error")
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

    def find_transactions() -> dict:
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
