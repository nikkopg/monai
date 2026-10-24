"""
Replayed chat history — pure, no DB and no clock (D-14).

What history carries (THRD-04): the user's text, the assistant's final answer,
and one provenance line naming the tools that produced it. Tool results,
payloads and proposal tokens are never replayed (following the Onyx
reference): a stale number in context is how a model repeats an old figure as
if it were current, so the model must re-query.

Each user message is stamped with the local date it was sent, so a relative
period ("last month") in an old turn stays anchored to that turn's date.

Only complete user/assistant pairs are replayed (D-12, THRD-07): a user
message is kept only when the very next message is an assistant message with
status "complete". Error and cancelled turns, orphan questions and the
earlier of back-to-back questions therefore never come back as history.

Summary boundary (Phase 38, D-19/D-20): pairs at or below threads.summary_upto_seq
are never replayed. A stored summary leads as a hidden user-role context message,
labelled so the model re-queries any figure; it is never listed or shown. plan_history
also returns the pairs a later compaction should fold, with hysteresis (D-21a): it
folds down to half the budget so a long thread does not pay a summariser call per turn.

Messages are dicts: {"role", "content", "status", "parts", "created_at"[, "seq"]} in
seq order (DB rows in the app, plain dicts in the eval; no seq = after the boundary).
"""

import datetime

from llama_index.core.llms import ChatMessage, MessageRole

PROVENANCE_ARG_CHARS = 200

SUMMARY_LABEL = "Summary of earlier conversation (as of {date}; any figure in it may be stale, re-query any figure):"

EARLIER_DATES_NOTE = (
    "(Earlier messages were sent on the dates shown; relative periods in them are "
    "relative to those dates and their figures may be out of date.)"
)


def _stamp(created_at: datetime.datetime) -> str:
    # Process TZ, the same source as query._today(); never .date() on the UTC value.
    return created_at.astimezone().date().isoformat()


def _resolved(period, asked_on: datetime.date | None) -> str:
    """' (YYYY-MM-DD to YYYY-MM-DD)' for a named period as of the turn's own date, so a
    follow-up such as "the month before that" can count from a real month; '' otherwise."""
    if asked_on is None or not isinstance(period, str) or period.lower() in ("custom", "all_time"):
        return ""
    from backend.tools import resolve_period

    try:
        s, e = resolve_period(period, today=asked_on)
    except ValueError:
        return ""
    return f" ({s.isoformat()} to {(e - datetime.timedelta(days=1)).isoformat()})"


def _provenance(steps: list[dict] | None, asked_on: datetime.date | None = None) -> str:
    """'[tools used: tool(k=v, ...)]' from tool + args only; '' when no steps. A named
    period also shows the dates it meant on asked_on (the turn's stamp date)."""
    calls: list[str] = []
    for s in steps or []:
        args = s.get("args") or {}
        rendered = ", ".join(
            f"{k}={args[k]}{_resolved(args[k], asked_on) if k == 'period' else ''}" for k in sorted(args)
        )[:PROVENANCE_ARG_CHARS]
        call = f"{s.get('tool')}({rendered})"
        if not calls or calls[-1] != call:  # collapse consecutive exact duplicates
            calls.append(call)
    return f"[tools used: {', '.join(calls)}]" if calls else ""


def _pairs(messages: list[dict]):
    """Yield (user, assistant) where a user is immediately followed by a complete assistant."""
    for u, a in zip(messages, messages[1:]):
        if u["role"] == "user" and a["role"] == "assistant" and a["status"] == "complete":
            yield u, a


def plan_history(
    messages: list[dict],
    budget_tokens: int,
    today: datetime.date,
    *,
    summary: str | None = None,
    upto_seq: int = 0,
    compact_to: float = 0.5,
) -> tuple[list[ChatMessage], list[tuple[dict, dict]]]:
    """(history, pairs to compact): newest whole pairs first within budget_tokens (len//4 each).

    Pairs whose user seq is <= upto_seq are hidden (a message without seq counts as after
    the boundary). A non-empty summary leads as a labelled user message and is charged first.
    The second value is [] unless pairs were dropped; then it is the dropped pairs plus the
    oldest kept ones, folded until the verbatim tail costs <= compact_to * budget (the newest
    kept pair stays). Folding below the budget stops a long thread from paying one
    summariser call per turn (D-21a). This turn's history still holds every pair that fit.
    """
    rows = []  # oldest first: (user, assistant, stamp, user_text, assistant_text, cost)
    for u, a in _pairs(messages):
        if u.get("seq") is not None and u["seq"] <= upto_seq:
            continue
        stamp = _stamp(u["created_at"])
        u_text = f"[{stamp}] {u['content']}"
        prov = _provenance((a.get("parts") or {}).get("steps"), datetime.date.fromisoformat(stamp))
        a_text = f"{a['content']}\n{prov}" if prov else a["content"]
        rows.append((u, a, stamp, u_text, a_text, len(u_text) // 4 + len(a_text) // 4))
    out: list[ChatMessage] = []
    used = 0
    if summary:
        as_of = next(
            (_stamp(m["created_at"]) for m in messages if m.get("seq") == upto_seq),
            today.isoformat(),
        )
        text = f"{SUMMARY_LABEL.format(date=as_of)}\n{summary}"
        out.append(ChatMessage(role=MessageRole.USER, content=text))
        used = len(text) // 4
    start = len(rows)
    while start > 0 and used + rows[start - 1][5] <= budget_tokens:
        start -= 1
        used += rows[start][5]
    kept = rows[start:]
    fold = start
    if start:
        tail = sum(r[5] for r in kept)
        while tail > compact_to * budget_tokens and fold < len(rows) - 1:
            tail -= rows[fold][5]
            fold += 1
    if kept and any(r[2] < today.isoformat() for r in kept):
        first = kept[0]
        kept[0] = first[:3] + (f"{EARLIER_DATES_NOTE}\n{first[3]}",) + first[4:]
    for _, _, _, u_text, a_text, _ in kept:
        out.append(ChatMessage(role=MessageRole.USER, content=u_text))
        out.append(ChatMessage(role=MessageRole.ASSISTANT, content=a_text))
    return out, [(r[0], r[1]) for r in rows[:fold]]


def build_history(
    messages: list[dict], budget_tokens: int, today: datetime.date
) -> list[ChatMessage]:
    """Replayable ChatMessages, newest whole pairs first within budget_tokens (len//4 each)."""
    return plan_history(messages, budget_tokens, today)[0]
