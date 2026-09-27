"""
AI query layer — multi-step agentic loop (correct by construction).

The LlamaIndex FunctionAgent plans and chains the 9 read tools in tools.py
across multiple steps within a single turn, then synthesizes a natural-language
answer. It never writes raw SQL — the tool SQL is hand-written and tested in
tools.py, and relative dates are resolved in Python, so the model cannot get
the year, the expense/income sign, or column names wrong.

If no tool can answer the question, the agent says so honestly and enumerates
what it CAN do — refusing beats a confident wrong number for a money app.

Public surface:
  agent_stream(question)                — async generator; yields SSE lines.
                                           It is the only agent loop, served by
                                           POST /query-stream.
  reset_engine() -> None                — clears _llm, _agent_workflow and its
                                           build date
"""

import datetime
import json

from backend.config import configure_llm

# ---------------------------------------------------------------------------
# Module-level singletons — lazy, reset-able
# ---------------------------------------------------------------------------

_llm = None
_agent_workflow = None
_agent_workflow_date: datetime.date | None = None  # the date whose TODAY the cached workflow's prompt holds

# ---------------------------------------------------------------------------
# System prompt — tool-only, no SQL, honest refusal, no fabrication
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a personal finance assistant with access to parameterized query tools.

TODAY is {today}.

DATES — how to scope a query to a time range:
- Every read tool takes a `period` argument, plus optional `start_date`/`end_date` (ISO `YYYY-MM-DD`).
- Named periods (use ONLY when the user's phrasing is itself relative to today):
  all_time, this_month, last_month, this_year, last_year, last_30_days, last_90_days.
- For ANY specific/absolute range — a named calendar month, a year, a quarter, or an \
explicit "from X to Y" — you MUST pass period="custom" with start_date and end_date. \
end_date is INCLUSIVE (the last day you want counted).
  * "food in June 2026"  → spending_in_category(category="food", period="custom", start_date="2026-06-01", end_date="2026-06-30")
  * "spending in 2025"   → spending_total(period="custom", start_date="2025-01-01", end_date="2025-12-31")
  * "how much on transport in March 2026" → spending_in_category(category="transport", period="custom", start_date="2026-03-01", end_date="2026-03-31")
- NEVER leave period at its "all_time" default when the user named a specific time range — \
doing so sums across every year on record and returns a wrong, inflated number.

RULES:
1. You MUST only answer using the available tools. Never emit SQL.
2. Be concise — use the minimum number of tool calls needed to answer the question.
3. If a question cannot be answered by any available tool, say honestly:
   "I can't compute that reliably with my current tools — I can total spending or income, \
break spending down by category, count transactions, find your largest transactions, or compute \
average daily spending — over any period. I can also add, edit, or delete transactions, \
accounts, categories, and holdings."
4. Never fabricate a number. If a tool returns zero, say zero.
5. Do not run raw SQL queries — only invoke the named tools provided.
6. For write requests (add/edit/delete a transaction, account, category, or holding), \
use the propose_* tools. These create a proposal for user approval — they do NOT \
change any data. The user approves or declines through the chat UI, not via the agent.
7. For a "fix all X" or batch request (e.g. recategorize all Gojek transactions), \
build a SINGLE batch proposal — do not call propose_* once per row.
8. For deletes of accounts with dependent transactions, the propose_delete_account tool \
will refuse and return an error — relay that refusal honestly: explain the dependent count \
and suggest the user reassign or remove those transactions first.
9. Never add an approval or declination tool — the user acts on proposals through the \
HTTP endpoint in the UI, not through the agent.
""".strip()


# ---------------------------------------------------------------------------
# Agent / workflow builder
# ---------------------------------------------------------------------------

def _today() -> datetime.date:
    """Single date source for the agent's TODAY and the test seam.

    Tests patch backend.query._today directly, because datetime.date.today
    is a C-level type method and can't be monkeypatched. Follows the process
    TZ (Asia/Jakarta per docker-compose.yml) — unchanged timezone behavior.
    """
    return datetime.date.today()


def _get_llm():
    global _llm
    if _llm is None:
        configure_llm()
        from llama_index.core import Settings
        _llm = Settings.llm
    return _llm


def _get_agent_workflow():
    global _agent_workflow, _agent_workflow_date
    today = _today()
    # A new calendar day rebuilds the workflow so the prompt's TODAY never
    # goes stale on a day with no writes (AGENT-05).
    if _agent_workflow is None or _agent_workflow_date != today:
        from llama_index.core.agent import AgentWorkflow, FunctionAgent
        from llama_index.core.tools import FunctionTool
        from backend.tools import TOOLS

        llm = _get_llm()

        # Tools come from the single TOOLS registry (16 read + 16 propose_*
        # writes); descriptions live in the functions' docstrings. A new
        # tool needs only a TOOLS entry — nothing here changes.
        tools = [
            FunctionTool.from_defaults(fn=fn, name=name)
            for name, fn in TOOLS.items()
        ]

        system_prompt = _SYSTEM_PROMPT.format(today=today.isoformat())

        agent = FunctionAgent(
            tools=tools,
            llm=llm,
            system_prompt=system_prompt,
            verbose=False,
        )
        _agent_workflow = AgentWorkflow(agents=[agent], timeout=120.0)
        _agent_workflow_date = today
    return _agent_workflow


# ---------------------------------------------------------------------------
# Proposal extraction from tool trace
# ---------------------------------------------------------------------------

def _extract_proposals(tool_trace: list) -> list[dict]:
    """Return one {"id", "token"} entry per propose_* call, in call order.

    A single pass over tool_trace: any step whose result dict carries both
    proposal_id and proposal_token contributes one entry. Tokens surface only
    in the SSE answer event to the originating chat session — they are never
    emitted in a tool_result event or the public trace (T-02-07).
    """
    proposals = []
    for step in tool_trace:
        result = step.get("result")
        if isinstance(result, dict) and "proposal_id" in result and "proposal_token" in result:
            proposals.append({"id": result["proposal_id"], "token": result["proposal_token"]})
    return proposals


# ---------------------------------------------------------------------------
# Async streaming generator — yields SSE-formatted lines
# ---------------------------------------------------------------------------

async def agent_stream(question: str):
    """
    Async generator that drives the agent workflow and yields SSE lines.

    Event types emitted:
      data: {"type": "step", "msg": "thinking…"}
      data: {"type": "tool_result", "step": {"tool": ..., "args": ..., "result": ...}}
      data: {"type": "answer", "text": ..., "trace": [...], "proposals": [{"id": ..., "token": ...}, ...], "proposal_id": ..., "proposal_token": ...}
        (proposal_id/proposal_token mirror proposals[0]; None when there are none)
      data: [DONE]
    """
    from llama_index.core.agent.workflow.workflow_events import AgentInput, ToolCallResult
    from llama_index.core.workflow import StopEvent

    try:
        workflow = _get_agent_workflow()
        handler = workflow.run(user_msg=question, max_iterations=10)
        tool_trace: list = []

        async for event in handler.stream_events():
            if isinstance(event, AgentInput):
                yield f"data: {json.dumps({'type': 'step', 'msg': 'thinking…'})}\n\n"

            elif isinstance(event, ToolCallResult):
                # Prefer the untouched dict LlamaIndex's FunctionTool.call() sets on
                # ToolOutput.raw_output — event.tool_output.content is a Python-repr
                # STRING of that dict, so json.loads(content) always raises and would
                # silently drop proposal_id/proposal_token on every write-tool call.
                raw_output = getattr(event.tool_output, "raw_output", None)
                if isinstance(raw_output, dict):
                    result_dict = raw_output
                else:
                    content = event.tool_output.content
                    try:
                        result_dict = json.loads(content)
                    except Exception:
                        result_dict = {"raw": content}

                # T-02-07: strip proposal_token out of the trace-visible result dict
                # so it never appears in the persisted/collapsible tool-call log.
                # It will be surfaced as a dedicated top-level field in the answer event.
                trace_result = {k: v for k, v in result_dict.items()
                                if k != "proposal_token"} if isinstance(result_dict, dict) \
                    else result_dict

                step = {
                    "tool": event.tool_name,
                    "args": event.tool_kwargs,
                    "result": trace_result,
                }
                # Keep the full result_dict (with token) in tool_trace so
                # _extract_proposals can read the tokens.
                tool_trace.append({
                    "tool": event.tool_name,
                    "args": event.tool_kwargs,
                    "result": result_dict,  # full dict — used for token extraction only
                    "_trace_result": trace_result,  # token-stripped — used in answer trace
                })
                # default=str: some tool results (e.g. net_worth's holdings) carry
                # raw Decimal fields that json.dumps can't serialize natively.
                yield f"data: {json.dumps({'type': 'tool_result', 'step': step}, default=str)}\n\n"

            elif isinstance(event, StopEvent):
                # StopEvent.result is AgentOutput; str(AgentOutput) = response.content
                final = event.result
                answer_text = str(final) if final is not None else ""
                # One scan for every proposal of the turn, in call order. The
                # token surfaces ONLY here — to the originating chat session
                # via the SSE answer event (T-02-07, single-use 15-min TTL).
                proposals = _extract_proposals(tool_trace)
                # Build the public trace using token-stripped results (T-02-07)
                public_trace = [
                    {
                        "tool": s["tool"],
                        "args": s["args"],
                        "result": s.get("_trace_result", s["result"]),
                    }
                    for s in tool_trace
                ]
                # Singular fields mirror proposals[0] for compatibility (accepted
                # AGENT-06 scope) — from the same scan, not a second extraction.
                first = proposals[0] if proposals else None
                payload = {
                    "type": "answer",
                    "text": answer_text,
                    "trace": public_trace,
                    "proposals": proposals,
                    "proposal_id": first["id"] if first else None,
                    "proposal_token": first["token"] if first else None,
                }
                yield f"data: {json.dumps(payload, default=str)}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as e:
        error_payload = {
            "type": "answer",
            "text": f"I couldn't process that question reliably ({e}). Try rephrasing.",
            "trace": [],
            "proposals": [],
            "proposal_id": None,
            "proposal_token": None,
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
        yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Cache invalidation — called from main.py after writes
# ---------------------------------------------------------------------------

def reset_engine() -> None:
    """Clear the LLM, the agent workflow and its build date (called after writes)."""
    global _llm, _agent_workflow, _agent_workflow_date
    _llm = None
    _agent_workflow = None
    _agent_workflow_date = None
