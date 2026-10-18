"""
build_history tests (THRD-03/04/05/07) — pure function, synthetic data only.

Tests:
  test_error_pair_excluded — error / cancelled / orphan turns are never replayed
  test_back_to_back_users_keep_last_pair — only the question that got an answer
  test_provenance_line — tool(k=v) line from parts.steps
  test_no_results_or_tokens_replayed — results and proposal tokens never leak
  test_date_stamp_local_tz — stamp uses the process TZ, not UTC
  test_earlier_dates_note — note only when a kept turn predates today
  test_budget_keeps_newest_whole_pairs / test_budget_zero_and_empty
  test_plan_history_* — summary boundary, labelled summary, budget charge, hysteresis (38-04)
"""

import datetime
import time

from llama_index.core.llms import MessageRole

from backend.chat_history import build_history, plan_history

UTC = datetime.timezone.utc
AT = datetime.datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
TODAY = datetime.date(2026, 10, 9)


def _msg(role, content, status="complete", steps=None, at=AT, parts=None):
    p = dict(parts or {})
    if steps is not None:
        p["steps"] = steps
    return {"role": role, "content": content, "status": status, "parts": p, "created_at": at}


def test_error_pair_excluded():
    msgs = [
        _msg("user", "q1"), _msg("assistant", "a1"),
        _msg("user", "q2"), _msg("assistant", "", status="error"),
        _msg("user", "q3"), _msg("assistant", "partial", status="cancelled"),
        _msg("user", "q4"),
    ]
    out = build_history(msgs, 6000, TODAY)
    assert [m.role for m in out] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert out[0].content == "[2026-10-09] q1"
    assert out[1].content == "a1"


def test_back_to_back_users_keep_last_pair():
    msgs = [_msg("user", "q1"), _msg("user", "q2"), _msg("assistant", "a2")]
    out = build_history(msgs, 6000, TODAY)
    assert len(out) == 2
    assert out[0].content.endswith("q2")


def test_provenance_line():
    one = [{"tool": "spending_in_category",
            "args": {"period": "this_month", "category": "ZZTest Food"}}]
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=one)], 6000, TODAY)
    assert out[1].content == (
        "a\n[tools used: spending_in_category(category=ZZTest Food, "
        "period=this_month (2026-10-01 to 2026-10-31))]"
    )
    two = one + [{"tool": "spending_total", "args": {"period": "last_month"}}]
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=two)], 6000, TODAY)
    assert out[1].content.endswith(
        "spending_in_category(category=ZZTest Food, period=this_month (2026-10-01 to 2026-10-31)), "
        "spending_total(period=last_month (2026-09-01 to 2026-09-30))]"
    )
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=[])], 6000, TODAY)
    assert out[1].content == "a"


def test_provenance_resolves_named_period_as_of_the_turn_date():
    """'last month' in a turn sent on 2026-08-15 meant July, whatever today is, so a
    follow-up 'the month before that' can count from a real month (eval case 17)."""
    old = datetime.datetime(2026, 8, 15, 5, 0, tzinfo=UTC)
    steps = [{"tool": "spending_in_category", "args": {"category": "ZZTest Food", "period": "last_month"}}]
    out = build_history(
        [_msg("user", "q", at=old), _msg("assistant", "a", steps=steps, at=old)], 6000, TODAY)
    assert "period=last_month (2026-07-01 to 2026-07-31)" in out[1].content
    custom = [{"tool": "spending_total", "args": {"period": "custom", "start_date": "2026-01-01"}}]
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=custom)], 6000, TODAY)
    assert "period=custom," in out[1].content and " to " not in out[1].content


def test_no_results_or_tokens_replayed():
    steps = [{"tool": "spending_total", "args": {"period": "this_month"},
              "result": {"total": "ZZRESULT999"}}]
    parts = {"proposals": [{"id": "p1", "token": "ZZTOKEN123"}]}
    out = build_history(
        [_msg("user", "q"), _msg("assistant", "a", steps=steps, parts=parts)], 6000, TODAY)
    blob = " ".join(m.content for m in out)
    assert "ZZRESULT999" not in blob and "ZZTOKEN123" not in blob


def test_date_stamp_local_tz(monkeypatch):
    try:
        monkeypatch.setenv("TZ", "Asia/Jakarta")
        time.tzset()
        late = datetime.datetime(2026, 10, 10, 18, 30, tzinfo=UTC)
        out = build_history(
            [_msg("user", "q", at=late), _msg("assistant", "a", at=late)],
            6000, datetime.date(2026, 10, 11))
        assert out[0].content == "[2026-10-11] q"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_earlier_dates_note():
    old = [_msg("user", "q"), _msg("assistant", "a")]
    out = build_history(old, 6000, datetime.date(2026, 10, 10))
    assert "may be out of date" in out[0].content
    assert out[0].content.endswith("[2026-10-09] q")
    out = build_history(old, 6000, TODAY)
    assert "may be out of date" not in out[0].content


def test_budget_keeps_newest_whole_pairs():
    msgs = []
    for i in range(5):
        msgs += [_msg("user", f"{i}" * 400), _msg("assistant", f"{i}" * 400)]
    out = build_history(msgs, 250, TODAY)
    assert len(out) % 2 == 0 and 0 < len(out) < 10
    assert out[0].role == MessageRole.USER
    assert out[-1].content.startswith("4")  # newest kept, oldest dropped


def test_budget_zero_and_empty():
    msgs = [_msg("user", "q"), _msg("assistant", "a")]
    assert build_history(msgs, 0, TODAY) == []
    assert build_history([], 6000, TODAY) == []


def _drain(gen):
    import asyncio

    async def go():
        return [line async for line in gen]

    return asyncio.run(go())


def test_agent_stream_passes_history_only_when_given(monkeypatch):
    from unittest.mock import MagicMock

    from llama_index.core.llms import ChatMessage

    import backend.query as query

    wf = MagicMock()
    wf.run.side_effect = RuntimeError("synthetic")
    monkeypatch.setattr(query, "_get_agent_workflow", lambda tool_names=None: wf)

    hist = [ChatMessage(role=MessageRole.USER, content="x")]
    _drain(query.agent_stream("q", history=hist))
    assert wf.run.call_args.kwargs["chat_history"] is hist
    _drain(query.agent_stream("q"))
    assert "chat_history" not in wf.run.call_args.kwargs


def test_system_prompt_has_history_rules():
    from backend.query import _SYSTEM_PROMPT

    for needle in ("relative to that message's date", "in this turn", "[tools used: ...]"):
        assert needle in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# plan_history (Phase 38-04): summary boundary, labelled summary, hysteresis
# ---------------------------------------------------------------------------


def _seq_pairs(n, size=0):
    """n synthetic complete pairs with seq 1..2n; size pads each text to ~size chars."""
    out = []
    for i in range(n):
        pad = "x" * size
        u = _msg("user", f"Q{i}{pad}")
        a = _msg("assistant", f"A{i}{pad}")
        u["seq"], a["seq"] = 2 * i + 1, 2 * i + 2
        out += [u, a]
    return out


def _contents(out):
    return [m.content for m in out]


def test_plan_history_boundary_hides_older_pairs():
    msgs = _seq_pairs(4)
    out, _ = plan_history(msgs, 6000, TODAY, upto_seq=4)
    assert [c.split("] ")[-1] for c in _contents(out)[::2]] == ["Q2", "Q3"]
    assert len(plan_history(msgs, 6000, TODAY, upto_seq=0)[0]) == 8


def test_plan_history_missing_seq_counts_as_after_boundary():
    msgs = [_msg("user", "q"), _msg("assistant", "a")]
    assert len(plan_history(msgs, 6000, TODAY, upto_seq=9)[0]) == 2


def test_plan_history_summary_is_labelled_user_message_first():
    out, _ = plan_history(_seq_pairs(2), 6000, TODAY, summary="ZZ synthetic summary", upto_seq=2)
    assert out[0].role == MessageRole.USER
    assert out[0].content.startswith("Summary of earlier conversation (as of 2026-10-09;")
    assert "any figure in it may be stale, re-query any figure" in out[0].content
    assert "ZZ synthetic summary" in out[0].content
    assert len(out) == 3 and out[1].role == MessageRole.USER
    # No message at the boundary seq: the date falls back to today.
    out, _ = plan_history(_seq_pairs(2), 6000, TODAY, summary="s", upto_seq=99)
    assert "(as of 2026-10-09;" in out[0].content


def test_plan_history_summary_cost_charged_first():
    msgs = _seq_pairs(2, size=400)  # ~200 tokens per pair
    assert len(plan_history(msgs, 420, TODAY)[0]) == 4
    out, _ = plan_history(msgs, 420, TODAY, summary="s" * 400, upto_seq=0)  # ~120 tokens
    assert len(out) == 3  # summary + one pair


def test_plan_history_cleared_boundary_replays_nothing():
    out, to_compact = plan_history(_seq_pairs(4), 6000, TODAY, summary=None, upto_seq=8)
    assert out == [] and to_compact == []


def test_plan_history_under_budget_has_nothing_to_compact():
    assert plan_history(_seq_pairs(3), 6000, TODAY)[1] == []


def test_plan_history_hysteresis_folds_to_half_budget():
    msgs = _seq_pairs(20, size=187)  # ~100 tokens per pair
    out, to_compact = plan_history(msgs, 1000, TODAY)
    assert len(out) == 20  # this turn still replays every pair that fit
    assert [u["seq"] for u, _ in to_compact] == list(range(1, 30, 2))  # 15 oldest, seq order
    # Compacting them leaves 5 pairs (<= 500 tokens) and nothing more to fold next turn.
    out, again = plan_history(msgs, 1000, TODAY, summary="s", upto_seq=30)
    assert again == [] and len(out) == 11


def test_plan_history_newest_kept_pair_never_folded():
    msgs = _seq_pairs(3, size=400)
    msgs += [_msg("user", "u" * 2400), _msg("assistant", "a" * 2400)]  # ~1200 tokens alone
    msgs[-2]["seq"], msgs[-1]["seq"] = 7, 8
    out, to_compact = plan_history(msgs, 1300, TODAY)
    assert len(out) == 2 and out[0].content.endswith("u" * 2400)
    assert [u["seq"] for u, _ in to_compact] == [1, 3, 5]


def test_build_history_is_plan_history_wrapper():
    msgs = _seq_pairs(5, size=300)
    assert build_history(msgs, 250, TODAY) == plan_history(msgs, 250, TODAY)[0]


def test_plan_history_earlier_dates_note_skips_summary():
    out, _ = plan_history(_seq_pairs(1), 6000, datetime.date(2026, 10, 10), summary="s", upto_seq=0)
    assert "may be out of date" not in out[0].content
    assert "may be out of date" in out[1].content
