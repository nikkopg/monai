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
  agent(question) -> tuple[str, list]   — sync wrapper; returns (answer, trace)
  agent_stream(question)                — async generator; yields SSE lines
  ask(question) -> str                  — thin shim; backward-compat with /query
  reset_engine() -> None                — clears _llm + _agent_workflow singletons
"""

import asyncio
import datetime
import json
import re

from backend.config import configure_llm

# ---------------------------------------------------------------------------
# Module-level singletons — lazy, reset-able
# ---------------------------------------------------------------------------

_llm = None
_agent_workflow = None

# ---------------------------------------------------------------------------
# System prompt — tool-only, no SQL, honest refusal, no fabrication
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a personal finance assistant with access to parameterized query tools.

TODAY is {today}.

RULES:
1. You MUST only answer using the available tools. Never emit SQL.
2. Be concise — use the minimum number of tool calls needed to answer the question.
3. If a question cannot be answered by any available tool, say honestly:
   "I can't compute that reliably with my current tools — I can total spending or income, \
break spending down by category, count transactions, find your largest transactions, or compute \
average daily spending — over any period."
4. Never fabricate a number. If a tool returns zero, say zero.
5. Do not run raw SQL queries — only invoke the named tools provided.
""".strip()


# ---------------------------------------------------------------------------
# Agent / workflow builder
# ---------------------------------------------------------------------------

def _get_llm():
    global _llm
    if _llm is None:
        configure_llm()
        from llama_index.core import Settings
        _llm = Settings.llm
    return _llm


def _get_agent_workflow():
    global _llm, _agent_workflow
    if _agent_workflow is None:
        from llama_index.core.agent import AgentWorkflow, FunctionAgent
        from llama_index.core.tools import FunctionTool
        from backend.tools import (
            spending_total, income_total, net_total,
            spending_by_category, spending_in_category,
            transaction_count, largest_transactions,
            average_daily_spending, list_categories,
        )

        llm = _get_llm()

        tools = [
            FunctionTool.from_defaults(fn=spending_total),
            FunctionTool.from_defaults(fn=income_total),
            FunctionTool.from_defaults(fn=net_total),
            FunctionTool.from_defaults(fn=spending_by_category),
            FunctionTool.from_defaults(fn=spending_in_category),
            FunctionTool.from_defaults(fn=transaction_count),
            FunctionTool.from_defaults(fn=largest_transactions),
            FunctionTool.from_defaults(fn=average_daily_spending),
            FunctionTool.from_defaults(fn=list_categories),
        ]

        system_prompt = _SYSTEM_PROMPT.format(
            today=datetime.date.today().isoformat()
        )

        agent = FunctionAgent(
            tools=tools,
            llm=llm,
            system_prompt=system_prompt,
            verbose=False,
        )
        _agent_workflow = AgentWorkflow(agents=[agent], timeout=120.0)
    return _agent_workflow


# ---------------------------------------------------------------------------
# Proposal ID extraction from tool trace
# ---------------------------------------------------------------------------

def _extract_proposal_id(tool_trace: list) -> str | None:
    """Return the first proposal_id found in the tool trace, or None."""
    for step in tool_trace:
        result = step.get("result")
        if isinstance(result, dict) and "proposal_id" in result:
            return result["proposal_id"]
    return None


# ---------------------------------------------------------------------------
# Async streaming generator — yields SSE-formatted lines
# ---------------------------------------------------------------------------

async def agent_stream(question: str):
    """
    Async generator that drives the agent workflow and yields SSE lines.

    Event types emitted:
      data: {"type": "step", "msg": "thinking…"}
      data: {"type": "tool_result", "step": {"tool": ..., "args": ..., "result": ...}}
      data: {"type": "answer", "text": ..., "trace": [...], "proposal_id": ...}
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
                content = event.tool_output.content
                try:
                    result_dict = json.loads(content)
                except Exception:
                    result_dict = {"raw": content}
                step = {
                    "tool": event.tool_name,
                    "args": event.tool_kwargs,
                    "result": result_dict,
                }
                tool_trace.append(step)
                yield f"data: {json.dumps({'type': 'tool_result', 'step': step})}\n\n"

            elif isinstance(event, StopEvent):
                # StopEvent.result is AgentOutput; str(AgentOutput) = response.content
                final = event.result
                answer_text = str(final) if final is not None else ""
                proposal_id = _extract_proposal_id(tool_trace)
                payload = {
                    "type": "answer",
                    "text": answer_text,
                    "trace": tool_trace,
                    "proposal_id": proposal_id,
                }
                yield f"data: {json.dumps(payload)}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as e:
        error_payload = {
            "type": "answer",
            "text": f"I couldn't process that question reliably ({e}). Try rephrasing.",
            "trace": [],
            "proposal_id": None,
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
        yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Sync agent entry point — runs the async stream to completion
# ---------------------------------------------------------------------------

def agent(question: str) -> tuple[str, list]:
    """
    Drive the agent workflow synchronously; return (answer_text, tool_trace).

    Wraps the entire loop in try/except — never raises to the API layer.
    """
    from llama_index.core.agent.workflow.workflow_events import AgentInput, ToolCallResult
    from llama_index.core.workflow import StopEvent

    try:
        workflow = _get_agent_workflow()
        handler = workflow.run(user_msg=question, max_iterations=10)
        tool_trace: list = []
        answer_text = ""

        async def _run() -> tuple[str, list]:
            nonlocal answer_text, tool_trace
            async for event in handler.stream_events():
                if isinstance(event, ToolCallResult):
                    content = event.tool_output.content
                    try:
                        result_dict = json.loads(content)
                    except Exception:
                        result_dict = {"raw": content}
                    tool_trace.append({
                        "tool": event.tool_name,
                        "args": event.tool_kwargs,
                        "result": result_dict,
                    })
                elif isinstance(event, StopEvent):
                    final = event.result
                    answer_text = str(final) if final is not None else ""
            return answer_text, tool_trace

        # Run the async coroutine. If we're already in an event loop (e.g. in tests
        # with pytest-asyncio), use a new thread to avoid "event loop already running".
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, _run())
                answer_text, tool_trace = future.result()
        else:
            answer_text, tool_trace = asyncio.run(_run())

        return answer_text, tool_trace

    except Exception as e:
        return (
            f"I couldn't process that question reliably ({e}). Try rephrasing.",
            [],
        )


# ---------------------------------------------------------------------------
# Backward-compatible shim — POST /query handler uses this
# ---------------------------------------------------------------------------

def ask(question: str) -> str:
    """Thin shim returning only the answer text. Backward-compatible with POST /query."""
    answer, _ = agent(question)
    return answer


# ---------------------------------------------------------------------------
# Cache invalidation — called from main.py after writes
# ---------------------------------------------------------------------------

def reset_engine() -> None:
    """Clear both the LLM and agent workflow singletons (called after writes)."""
    global _llm, _agent_workflow
    _llm = None
    _agent_workflow = None


# ---------------------------------------------------------------------------
# Kept for backward-compatibility with test_router.py
# ---------------------------------------------------------------------------

def _extract_json(textval: str) -> dict:
    """Pull the first {...} JSON object out of a string (legacy; used in test_router.py)."""
    textval = textval.strip()
    textval = re.sub(r"^```(?:json)?|```$", "", textval, flags=re.MULTILINE).strip()
    start = textval.find("{")
    if start == -1:
        raise ValueError("no JSON object in model output")
    depth = 0
    for i in range(start, len(textval)):
        if textval[i] == "{":
            depth += 1
        elif textval[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(textval[start:i + 1])
    raise ValueError("unbalanced JSON in model output")
