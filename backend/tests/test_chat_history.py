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
"""

import datetime
import time

from llama_index.core.llms import MessageRole

from backend.chat_history import build_history

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
        "a\n[tools used: spending_in_category(category=ZZTest Food, period=this_month)]"
    )
    two = one + [{"tool": "spending_total", "args": {"period": "last_month"}}]
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=two)], 6000, TODAY)
    assert out[1].content.endswith(
        "spending_in_category(category=ZZTest Food, period=this_month), "
        "spending_total(period=last_month)]"
    )
    out = build_history([_msg("user", "q"), _msg("assistant", "a", steps=[])], 6000, TODAY)
    assert out[1].content == "a"


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
