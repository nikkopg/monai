"""
Pure per-turn agent-loop helpers (Phase 38).

No LlamaIndex import at module level (query.py and main.py load at startup,
llama stays lazy); later plans add the result cap and the tail reminder here.

tools_for_turn decides, in code and with no extra LLM call, which tools a turn
carries: the 18 reads always, the 16 propose_* writes only when the turn shows
write intent (LOOP-01). A smaller tool block is cheaper on every iteration and
the small default model picks from a shorter list more reliably.
"""

import functools
import re

# D-04 list, finalised from the eval questions. Biased towards false positives:
# an extra proposer on a read turn is harmless (it still needs the owner's
# confirm), a missing one makes the model refuse.
# Indonesian stems confirmed by the owner on 2026-10-17 (RESEARCH A3).
WRITE_RE = re.compile(
    r"\b(?:add|record|log|create|edit|change|fix|update|correct|delete|remove|rename|merge|move|"
    r"transfer|buy|bought|sell|sold|adjust|assign|reassign|(?:re)?categori[sz]e|reclassify|"
    r"deposit|withdraw|top[ -]?up)\b"
    r"|\b(?:tambah|catat|masukkan|buat|ubah|ganti|koreksi|perbaiki|hapus|buang|pindah|beli|jual|"
    r"sesuaikan|gabung|kategorikan)\w*",
    re.I,
)

_QUESTION_RE = re.compile(r"[^.?!\n]*\?")

# What the LLM sees of a tool result is str(raw) (the Python repr), so the cap
# is measured on that: 8000 chars is about 3.4k tokens of dense rows (RESEARCH
# Spike 2). A module constant, not an env setting (D-07).
CAP_CHARS = 8000
_MARKER_RESERVE = 300  # room for truncated / truncated_lists / note


def cap_for_llm(raw, cap: int = CAP_CHARS) -> str | None:
    """The LLM-visible text of a tool result, or None when it needs no change.

    None for a non-dict or a result whose str() fits `cap`, so FunctionTool keeps
    today's content byte-identical. Otherwise list fields lose items from the
    end (longest list first) until it fits; scalars stay untouched, and the
    result gains truncated, truncated_lists {key: {shown, of}} and a narrowing
    note. Never a top-level `shown` or `total`: five read tools already return a
    scalar money `total` (D-07a). The caller's dict is not mutated (D-08: the
    SSE trace and proposal extraction keep the full raw_output).
    """
    if not isinstance(raw, dict) or len(str(raw)) <= cap:
        return None
    out = dict(raw)
    of = {k: len(v) for k, v in raw.items() if isinstance(v, list) and v}
    budget = cap - _MARKER_RESERVE
    while len(str(out)) > budget:
        k = max((k for k in of if out[k]), key=lambda k: len(str(out[k])), default=None)
        if k is None:
            break
        out[k] = out[k][:-1]
    cut = {k: {"shown": len(out[k]), "of": n} for k, n in of.items() if len(out[k]) < n}
    if len(str(out)) > budget:  # nothing list-shaped left to trim: keep scalars only
        for k, v in raw.items():
            if isinstance(v, (list, dict)):
                out.pop(k, None)
                cut[k] = {"shown": 0, "of": len(v)}
    out["truncated"] = True
    out["truncated_lists"] = cut
    out["note"] = "partial result; narrow the query (period, category, limit) for the rest"
    return str(out)


def tools_for_turn(question: str, prior: list[dict] | None = None) -> frozenset[str]:
    """Tool names for one turn: READ_TOOL_NAMES, or every tool on write intent.

    `prior` is the thread's message dicts (the build_history input). Write
    intent is sticky from the last complete pair, so "yes, do that" after a
    proposal or an offer keeps the writes (D-04, D-04a). This is the seam
    Phases 39 and 41 extend by unioning their own names into the result.
    """
    from backend.chat_history import _pairs
    from backend.tools import READ_TOOL_NAMES, TOOLS

    sticky = False
    last = None
    for last in _pairs(prior or []):
        pass
    if last is not None:
        u, a = last
        parts = a.get("parts") or {}
        offered = any(WRITE_RE.search(s) for s in _QUESTION_RE.findall(a["content"] or ""))
        sticky = bool(
            WRITE_RE.search(u["content"] or "")
            or offered
            or parts.get("proposals")
            or any(str(s.get("tool", "")).startswith("propose_") for s in parts.get("steps") or [])
        )
    if sticky or WRITE_RE.search(question or ""):
        return frozenset(TOOLS)
    return READ_TOOL_NAMES


# D-27: the never-fabricate rule, restated as the last input of every model step.
TAIL_REMINDER = (
    "Reminder: every figure in your answer must come from a tool call made in this turn. "
    "If a tool returns zero, say zero. Never compute a difference or percentage yourself, "
    "and never state a total from a truncated list."
)


@functools.cache
def tail_agent_cls():
    """The FunctionAgent subclass that appends TAIL_REMINDER to every LLM call.

    The hook is FunctionAgent's private _get_streaming_response / _get_response,
    not take_step: they are the only place that sees the true final input
    [*llm_input, *scratchpad], so the reminder lands after every tool round
    (Spike 3a). It is appended to a copy at call time, so it never enters agent
    memory, events or the DB. User role (D-28): the Ollama, OpenAI and Anthropic
    adapters all accept a trailing user message after a tool message (Spike 3c);
    fall back to system role only if the eval shows the model mishandles it.
    Ollama front-truncates oldest non-system messages first and keeps the last,
    so the reminder is the protected message; the casualties are the question
    and early tool rounds (D-27a). Pinned to llama-index-core 0.14.25 because of
    the two underscore methods; test_tail_reminder_last_on_every_call is the
    tripwire for a bump. Cached so every call returns the same class.
    """
    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.core.llms import ChatMessage

    class TailFunctionAgent(FunctionAgent):
        def _tail(self, msgs):
            return [*msgs, ChatMessage(role="user", content=TAIL_REMINDER)]

        async def _get_streaming_response(self, ctx, current_llm_input, tools):
            return await super()._get_streaming_response(ctx, self._tail(current_llm_input), tools)

        async def _get_response(self, current_llm_input, tools):
            return await super()._get_response(self._tail(current_llm_input), tools)

    return TailFunctionAgent
