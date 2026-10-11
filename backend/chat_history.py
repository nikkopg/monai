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

Messages are dicts: {"role", "content", "status", "parts", "created_at"} in
seq order (DB rows in the app, plain dicts in the eval).
"""

import datetime

from llama_index.core.llms import ChatMessage, MessageRole

PROVENANCE_ARG_CHARS = 200

EARLIER_DATES_NOTE = (
    "(Earlier messages were sent on the dates shown; relative periods in them are "
    "relative to those dates and their figures may be out of date.)"
)


def _stamp(created_at: datetime.datetime) -> str:
    # Process TZ, the same source as query._today(); never .date() on the UTC value.
    return created_at.astimezone().date().isoformat()


def _provenance(steps: list[dict] | None) -> str:
    """'[tools used: tool(k=v, ...)]' from tool + args only; '' when no steps."""
    calls: list[str] = []
    for s in steps or []:
        args = s.get("args") or {}
        rendered = ", ".join(f"{k}={args[k]}" for k in sorted(args))[:PROVENANCE_ARG_CHARS]
        call = f"{s.get('tool')}({rendered})"
        if not calls or calls[-1] != call:  # collapse consecutive exact duplicates
            calls.append(call)
    return f"[tools used: {', '.join(calls)}]" if calls else ""


def _pairs(messages: list[dict]):
    """Yield (user, assistant) where a user is immediately followed by a complete assistant."""
    for u, a in zip(messages, messages[1:]):
        if u["role"] == "user" and a["role"] == "assistant" and a["status"] == "complete":
            yield u, a


def build_history(
    messages: list[dict], budget_tokens: int, today: datetime.date
) -> list[ChatMessage]:
    """Replayable ChatMessages, newest whole pairs first within budget_tokens (len//4 each)."""
    kept: list[tuple[str, str, str]] = []  # newest first: (stamp, user_text, assistant_text)
    used = 0
    for u, a in reversed(list(_pairs(messages))):
        stamp = _stamp(u["created_at"])
        u_text = f"[{stamp}] {u['content']}"
        prov = _provenance((a.get("parts") or {}).get("steps"))
        a_text = f"{a['content']}\n{prov}" if prov else a["content"]
        cost = len(u_text) // 4 + len(a_text) // 4
        if used + cost > budget_tokens:
            break
        used += cost
        kept.append((stamp, u_text, a_text))
    kept.reverse()
    if kept and any(stamp < today.isoformat() for stamp, _, _ in kept):
        stamp, u_text, a_text = kept[0]
        kept[0] = (stamp, f"{EARLIER_DATES_NOTE}\n{u_text}", a_text)
    out: list[ChatMessage] = []
    for _, u_text, a_text in kept:
        out.append(ChatMessage(role=MessageRole.USER, content=u_text))
        out.append(ChatMessage(role=MessageRole.ASSISTANT, content=a_text))
    return out
