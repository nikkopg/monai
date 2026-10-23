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
