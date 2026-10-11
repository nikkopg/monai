"""
Thread-run engine tests (Phase 36 plan 03): the server-owned turn.

Detach, re-attach and replay are tested at the query / chat_service level with
anyio task groups, never through the HTTP client: the session TestClient gives
each request its own event loop, so a detached task would die with it
(Pitfall 4).

Tests:
  test_make_proposal_stamps_turn_id, test_turn_id_reaches_tool_executor_thread
      -- CURRENT_TURN_ID stamps chat proposals only (D-12a)
  test_stop_rejects_by_turn_id, test_fallback_sweep_only_matches_rows_without_turn_id
      -- Stop is precise per turn (D-12)

All values are synthetic. The DB is the isolated monai_test database.
"""

import asyncio
import contextvars
import datetime
import uuid

import pytest

from backend import query as q
from backend import tools
from backend.tests.chat_stubs import (
    StubLLM,
    _collect,
    _install_stub_workflow,
    _of_type,
    _payloads,
    _seed_proposal,
    purge_seeded,
)


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    purge_seeded()


def _status_of(pid: str) -> str:
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        return db.get(Proposal, uuid.UUID(str(pid))).status
    finally:
        db.close()


def _turn_id_of(pid: str):
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        return db.get(Proposal, uuid.UUID(str(pid))).turn_id
    finally:
        db.close()


def _delete(*pids: str) -> None:
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        for pid in pids:
            row = db.get(Proposal, uuid.UUID(str(pid)))
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# turn_id plumbing (D-12a)
# ---------------------------------------------------------------------------


def test_make_proposal_stamps_turn_id():
    turn = uuid.uuid4()
    payload = {"operation": "add_transaction", "rows": []}
    made: list[str] = []
    try:

        def inside():
            tools.CURRENT_TURN_ID.set(turn)
            chat_id, _ = tools._make_proposal("add_transaction", payload, "chat")
            mcp_id, _ = tools._make_proposal("add_transaction", payload, "mcp")
            made.extend([chat_id, mcp_id])
            return chat_id, mcp_id

        chat_id, mcp_id = contextvars.copy_context().run(inside)
        unset_id, _ = tools._make_proposal("add_transaction", payload, "chat")
        made.append(unset_id)

        assert _turn_id_of(chat_id) == turn
        assert _turn_id_of(mcp_id) is None
        assert _turn_id_of(unset_id) is None
    finally:
        _delete(*made)


async def test_turn_id_reaches_tool_executor_thread(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text="Done"))
    turn = uuid.uuid4()

    async def drive():
        tools.CURRENT_TURN_ID.set(turn)
        return await _collect(q.agent_stream("synthetic question"))

    lines = await asyncio.create_task(drive())
    answer = _of_type(_payloads(lines), "answer")[0]
    pid = answer["proposals"][0]["id"]

    assert _turn_id_of(pid) == turn


# ---------------------------------------------------------------------------
# Stop rejects by turn id (D-12)
# ---------------------------------------------------------------------------


def test_stop_rejects_by_turn_id():
    run_a = q.Run(key="a")
    run_b = q.Run(key="b")
    # A's rows predate A.started_at: only the turn id can catch them.
    run_a.started_at = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(minutes=1)
    mine, _ = _seed_proposal(turn_id=uuid.UUID(run_a.id))
    theirs, _ = _seed_proposal(turn_id=uuid.UUID(run_b.id))
    mcp, _ = _seed_proposal(channel="mcp")

    assert q.reject_run_proposals(run_a) == [mine]
    assert _status_of(mine) == "rejected"
    assert _status_of(theirs) == "pending"
    assert _status_of(mcp) == "pending"


def test_fallback_sweep_only_matches_rows_without_turn_id():
    run_c = q.Run(key="c")
    run_c.started_at = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(minutes=1)
    legacy, _ = _seed_proposal()
    other_turn, _ = _seed_proposal(turn_id=uuid.uuid4())

    assert q.reject_run_proposals(run_c) == [legacy]
    assert _status_of(legacy) == "rejected"
    assert _status_of(other_turn) == "pending"
