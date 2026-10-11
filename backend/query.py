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
  agent_stream(question, *, run=None)   — async generator; yields SSE lines.
                                           It is the only agent loop, served by
                                           POST /query-stream. A producer task
                                           feeds one queue; this generator only
                                           serializes it. Every failure is a
                                           typed `error` event, never an answer.
  subscribe(run, *, redact=False)       — replay a run's buffered events, then follow
                                           live ones until [DONE]; the detached
                                           pump (chat_service) fills the buffer
  run_stream(run)                       — the POST /query-stream response body: a subscriber
  start_run(key) / find_run(id)         — one-run-per-conversation registry (CHAT_KEY)
  stop_run(run) -> list[str]            — halt the run, reject its pending chat proposals
  classify_error(exc) -> str            — duck-typed provider failure -> code
  Run                                   — dataclass: one in-flight chat run
  reset_engine() -> None                — clears _llm, _agent_workflow and its
                                           build date
"""

import asyncio
import datetime
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import anyio

from backend.config import configure_llm
from backend.tools import PERIODS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — lazy, reset-able
# ---------------------------------------------------------------------------

_llm = None
_agent_workflow = None
_agent_workflow_date: datetime.date | None = None  # the date whose TODAY the cached workflow's prompt holds

# ---------------------------------------------------------------------------
# System prompt — tool-only, no SQL, honest refusal, no fabrication
# ---------------------------------------------------------------------------

# Named periods come straight from tools.PERIODS (as mcp_server._PERIOD_HELP
# does), so the prompt can never offer a period resolve_period rejects or miss
# one it accepts (TD-02).
_NAMED_PERIODS = ", ".join(p for p in PERIODS if p != "custom")

_SYSTEM_PROMPT = f"""\
You are a personal finance assistant with access to parameterized query tools.

TODAY is {{today}}.

DATES — how to scope a query to a time range:
- Every read tool takes a `period` argument, plus optional `start_date`/`end_date` (ISO `YYYY-MM-DD`). \
Exception: recurring_charges takes no period (it looks back `months`), and compare_periods takes \
period_a and period_b, each with its own a_start_date/a_end_date or b_start_date/b_end_date.
- Named periods (use ONLY when the user's phrasing is itself relative to today):
  {_NAMED_PERIODS}.
  this_week and last_week are calendar weeks, Monday through Sunday — prefer them over \
a custom range when the user says "this week" or "last week"; they do NOT mean a rolling 7-day window.
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
average daily spending — over any period. I can also compare two periods and find recurring \
charges. I can also add, edit, or delete transactions, \
accounts, categories, and holdings."
4. Never fabricate a number. If a tool returns zero, say zero. Never compute differences \
or percentages yourself — use compare_periods.
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
10. Earlier messages in this conversation start with the date they were sent, in square \
brackets. A relative period in an earlier message ("last month", "this week") is \
relative to that message's date, not to TODAY.
11. Every figure in your answer must come from a tool call made in this turn. Never repeat or \
reuse a number from an earlier answer: call the tool again, and use compare_periods for any \
difference between periods.
12. Never write the date stamps or the "[tools used: ...]" lines in your answer; they are \
context, not output.
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

        # Tools come from the single TOOLS registry (18 read + 16 propose_*
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
        # D-15: 300 s whole-run backstop for slow-but-alive runs; it maps to
        # `timeout` via WorkflowTimedOutEvent. The idle watchdog is the real guard.
        _agent_workflow = AgentWorkflow(agents=[agent], timeout=300.0)
        _agent_workflow_date = today
    return _agent_workflow


# ---------------------------------------------------------------------------
# Failure classification — one duck-typed mapping for every provider (D-03)
# ---------------------------------------------------------------------------

_TIMEOUT_NAMES = {"TimeoutException", "APITimeoutError", "WorkflowTimeoutError"}
_CONNECTION_NAMES = {"ConnectError", "APIConnectionError", "NetworkError"}
_PROVIDER_BY_CLASS = {"Ollama": "ollama", "Anthropic": "claude", "OpenAI": "openai"}


def classify_error(exc: BaseException) -> str:
    """Map a provider/workflow exception to a typed error code.

    Duck-typed (status_code on the exception or its .response, plus MRO class
    names) so no provider SDK is imported — only one is ever configured.
    Codes: rate_limit, provider_unavailable, timeout, auth, connection,
    unknown. Timeout is checked first: openai/anthropic APITimeoutError
    subclasses APIConnectionError. Non-positive status codes (ollama mid-stream
    errors carry -1) are ignored.
    """
    names = {c.__name__ for c in type(exc).__mro__}
    if isinstance(exc, TimeoutError) or names & _TIMEOUT_NAMES:
        return "timeout"
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int) and status > 0:
        if status == 429:
            return "rate_limit"
        if status in (401, 403):
            return "auth"
        if status >= 500:
            return "provider_unavailable"
    if isinstance(exc, ConnectionError) or names & _CONNECTION_NAMES:
        return "connection"
    return "unknown"


def _llm_label(workflow) -> tuple[str | None, str | None]:
    """(model, provider) of the LLM instance that runs this workflow (D-21).

    Read from the instance, never from env or app_settings, so the label is
    what actually answered. The provider is not an attribute of the LLM, so it
    is mapped from the class name (D-21a).
    """
    agents = getattr(workflow, "agents", None)
    if not isinstance(agents, dict) or not agents:
        return None, None
    llm = getattr(next(iter(agents.values())), "llm", None)
    model = getattr(llm, "model", None)
    model = model if isinstance(model, str) else None
    provider = next(
        (_PROVIDER_BY_CLASS[c.__name__] for c in type(llm).__mro__
         if c.__name__ in _PROVIDER_BY_CLASS),
        None,
    )
    return model, provider


# ---------------------------------------------------------------------------
# Run — one in-flight chat run (the registry that holds it follows below)
# ---------------------------------------------------------------------------

@dataclass
class Run:
    """State of one chat run. The detached pump (chat_service) owns it: it drives
    agent_stream and appends every non-ping SSE chunk to `events`; HTTP
    responses and re-attached clients are subscribers that only read `events`
    (D-05). agent_stream records proposal ids and exposes its workflow handler
    and producer task so Stop can halt it."""

    key: str = "chat"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    proposal_ids: list[str] = field(default_factory=list)
    handler: Any = None
    task: asyncio.Task | None = None
    stopped: bool = False  # Stop was requested; finish_run sweeps once more (D-08a)
    events: list[str] = field(default_factory=list)  # every non-ping SSE chunk, in order
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # swapped on every push
    done: bool = False  # the pump finished and [DONE] is the last event
    pump: asyncio.Task | None = None  # strong ref: asyncio keeps only weak ones (Pitfall 2)
    # Set by chat_service.start_turn; None for thread-less runs (D-11).
    thread_id: uuid.UUID | None = None
    user_message_id: uuid.UUID | None = None
    assistant_message_id: uuid.UUID | None = None
    user_seq: int | None = None


async def _halt(handler, task) -> None:
    """Idempotent workflow stop: cancel the producer task, then the workflow.

    Cancelling only the consumer orphans the workflow, so cancel_run is always
    called. It is documented never to raise and is a no-op after completion.
    """
    if task is not None and not task.done():
        task.cancel()
    if handler is not None:
        try:
            await handler.cancel_run()
        except Exception as e:  # cancel_run never raises; belt and braces
            logger.warning("cancel_run failed: %s: %s", type(e).__name__, e)


# ---------------------------------------------------------------------------
# Proposal extraction from tool trace
# ---------------------------------------------------------------------------

def _extract_proposals(tool_trace: list) -> list[dict]:
    """Return one entry per propose_* call, in call order.

    A single pass over tool_trace: any step whose result dict carries both
    proposal_id and proposal_token contributes {"id", "token"}. Each entry is
    then hydrated with operation, payload and expires_at (ISO 8601) from its
    DB row in ONE short SELECT (D-19) — the DB is authoritative. Those are
    None when there is no row (or the lookup fails: a DB hiccup must never
    hide the answer; the UI then shows its cannot-approve notice). Tokens
    surface only in the terminal answer/error event to the originating chat
    session — never in a tool_result event or the public trace (T-02-07).
    """
    proposals = []
    for step in tool_trace:
        result = step.get("result")
        if isinstance(result, dict) and "proposal_id" in result and "proposal_token" in result:
            proposals.append({
                "id": result["proposal_id"], "token": result["proposal_token"],
                "operation": None, "payload": None, "expires_at": None,
            })
    if not proposals:
        return proposals

    by_uuid: dict[uuid.UUID, list[dict]] = {}
    for p in proposals:
        try:
            by_uuid.setdefault(uuid.UUID(str(p["id"])), []).append(p)
        except ValueError:
            continue  # not a row id (test mocks use arbitrary strings)
    if not by_uuid:
        return proposals
    try:
        from sqlalchemy import select

        from backend.db import get_session_sync
        from backend.models import Proposal

        with get_session_sync() as db:
            rows = db.execute(
                select(Proposal).where(Proposal.id.in_(list(by_uuid)))
            ).scalars().all()
            for row in rows:
                for p in by_uuid[row.id]:
                    p["operation"] = row.operation
                    p["payload"] = row.payload
                    p["expires_at"] = row.expires_at.isoformat()
    except Exception as e:
        logger.warning("proposal hydration failed: %s: %s", type(e).__name__, e)
    return proposals


# ---------------------------------------------------------------------------
# Async streaming generator — yields SSE-formatted lines
# ---------------------------------------------------------------------------

_DONE = "data: [DONE]\n\n"


def _sse(payload: dict) -> str:
    # default=str: tool results (e.g. net_worth's holdings) carry raw Decimals.
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _error_event(code, model, provider, proposals, idle_seconds=None) -> str:
    """SSE error line. Carries only a typed code — never exception text or the
    question (D-04). `proposals` and `idle_seconds` are omitted when empty."""
    payload: dict = {"type": "error", "code": code, "model": model, "provider": provider}
    if idle_seconds is not None:
        payload["idle_seconds"] = idle_seconds
    if proposals:
        payload["proposals"] = proposals
    return _sse(payload)


def _log_failure(exc: BaseException) -> None:
    # Class and message only — never the question (D-04).
    logger.warning("chat run failed: %s: %s", type(exc).__name__, exc)


async def agent_stream(
    question: str,
    *,
    run: Run | None = None,
    idle_timeout: float | None = None,
    ping_interval: float = 15.0,
    history: list | None = None,
):
    """
    Async generator that drives the agent workflow and yields SSE lines.

    `history`: prior turns as ChatMessages built by
    backend.chat_history.build_history; passed to the workflow as chat_history
    only when non-empty.

    A producer task consumes the workflow's events into one asyncio.Queue and
    this generator only serializes the queue (D-13). `run`, when given, gets
    the workflow handler, the producer task and each proposal id as it
    arrives (D-10).

    Event types emitted:
      data: {"type": "step", "msg": "thinking…"}
      data: {"type": "tool_result", "step": {"tool": ..., "args": ..., "result": ...}}
      data: {"type": "answer", "text": ..., "trace": [...], "model": ..., "provider": ...,
             "proposals": [{"id", "token", "operation", "payload", "expires_at"}, ...],
             "proposal_id": ..., "proposal_token": ...}
        (proposal_id/proposal_token mirror proposals[0]; None when there are none)
      data: {"type": "error", "code": ..., "model": ..., "provider": ...,
             "idle_seconds"?: ..., "proposals"?: [...]}
        (code: rate_limit | provider_unavailable | timeout | idle_timeout |
         auth | connection | empty | unknown)
      data: [DONE]
    There is no server retry and no provider fallback (D-07).
    """
    from llama_index.core.agent.workflow.workflow_events import AgentInput, ToolCallResult
    from workflows.errors import WorkflowCancelledByUser
    from workflows.events import (
        IdleReleasedEvent,
        StopEvent,
        WorkflowCancelledEvent,
        WorkflowFailedEvent,
        WorkflowTimedOutEvent,
    )

    from backend import config

    # Read at call time through the module so tests can monkeypatch it (D-14a).
    idle = float(config.CHAT_IDLE_TIMEOUT_SECONDS if idle_timeout is None else idle_timeout)

    model = provider = None
    try:
        workflow = _get_agent_workflow()
        model, provider = _llm_label(workflow)
        if history:
            handler = workflow.run(user_msg=question, chat_history=history, max_iterations=10)
        else:
            handler = workflow.run(user_msg=question, max_iterations=10)
    except Exception as e:
        _log_failure(e)
        yield _error_event(classify_error(e), model, provider, None)
        yield _DONE
        return

    queue: asyncio.Queue = asyncio.Queue()
    tool_trace: list = []
    terminal = False  # a terminal event (answer / error / cancel) was handled

    def emit_error(code: str, idle_seconds: float | None = None) -> None:
        nonlocal terminal
        terminal = True
        queue.put_nowait(_error_event(
            code, model, provider, _extract_proposals(tool_trace), idle_seconds))

    async def produce() -> None:
        nonlocal terminal
        try:
            try:
                async with asyncio.timeout(idle) as cm:
                    async for event in handler.stream_events():
                        # D-14: ANY workflow event (incl. streamed deltas we do
                        # not forward) proves liveness. Pings never reach here.
                        cm.reschedule(asyncio.get_running_loop().time() + idle)
                        if isinstance(event, AgentInput):
                            queue.put_nowait(_sse({"type": "step", "msg": "thinking…"}))

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
                            # D-10: record the id as the result arrives, before any answer.
                            if run is not None and isinstance(result_dict, dict) \
                                    and result_dict.get("proposal_id"):
                                run.proposal_ids.append(str(result_dict["proposal_id"]))
                            queue.put_nowait(_sse({"type": "tool_result", "step": step}))

                        # Terminal dispatch (D-01a): Failed, TimedOut, Cancelled and
                        # IdleReleased all SUBCLASS StopEvent, so they must be tested
                        # before the plain StopEvent or a failure reads as an answer.
                        elif isinstance(event, WorkflowFailedEvent):
                            _log_failure(event.exception)
                            emit_error(classify_error(event.exception))

                        elif isinstance(event, WorkflowTimedOutEvent):
                            emit_error("timeout")

                        elif isinstance(event, (WorkflowCancelledEvent, IdleReleasedEvent)):
                            terminal = True  # a cancel: no answer, no error

                        elif isinstance(event, StopEvent):
                            # StopEvent.result is AgentOutput; str(AgentOutput) = response.content
                            final = event.result
                            answer_text = str(final) if final is not None else ""
                            if answer_text.strip() == "" and not tool_trace:
                                emit_error("empty")  # D-06
                                continue
                            terminal = True
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
                            queue.put_nowait(_sse({
                                "type": "answer",
                                "text": answer_text,
                                "trace": public_trace,
                                "model": model,
                                "provider": provider,
                                "proposals": proposals,
                                "proposal_id": first["id"] if first else None,
                                "proposal_token": first["token"] if first else None,
                            }))
            except TimeoutError as e:
                if not cm.expired():
                    raise  # a provider timeout, not the watchdog: classify_error maps it
                await handler.cancel_run()
                logger.warning("agent run idle for %ss; cancelled", idle)
                emit_error("idle_timeout", idle_seconds=idle)

            # The stream can swallow a failure; awaiting the handler re-raises it (D-01).
            try:
                await handler
            except WorkflowCancelledByUser:
                pass
            except Exception as e:
                if not terminal:  # a WorkflowFailedEvent already logged it (IN-04)
                    _log_failure(e)
                    emit_error(classify_error(e))
        except Exception as e:
            _log_failure(e)
            if not terminal:
                emit_error(classify_error(e))
        finally:
            queue.put_nowait(None)

    producer = asyncio.create_task(produce())
    if run is not None:
        run.handler, run.task = handler, producer
    try:
        # Pings live only here, so they never reset the producer's idle timer
        # (D-13). The installed uvicorn advertises ASGI spec 2.3, so Starlette
        # detects a disconnect without a send; on a server advertising 2.4+
        # this ping becomes the disconnect detector (RESEARCH Findings 3 B).
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), ping_interval)
            except TimeoutError:
                # A producer cancelled before its first step never runs its
                # finally, so no sentinel comes: end on its own death (IN-01).
                if producer.done() and queue.empty():
                    break
                yield ": ping\n\n"
                continue
            if item is None:
                break
            yield item
        yield _DONE
    finally:
        # Starlette cancels this generator on disconnect at the anyio level, so
        # every plain await here would re-raise CancelledError. Shield (D-12a).
        with anyio.CancelScope(shield=True):
            await _halt(handler, producer)


# ---------------------------------------------------------------------------
# Run registry — one run per conversation (D-16), Stop and disconnect cleanup
# ---------------------------------------------------------------------------

CHAT_KEY = "chat"  # Phase 36 re-keys this to the thread id; nothing else changes

# ponytail: in-process registry, valid only because uvicorn runs a single
# worker (entrypoint.sh). Upgrade to a DB or Redis lock if that ever changes.
_ACTIVE: dict[str, Run] = {}
_LAST: dict[str, Run] = {}  # last-finished run per key, kept until the next starts (D-11)

_LAST_MAX = 20


def start_run(key: str) -> Run | None:
    """Register a new run for `key`; None when one is already active (D-05)."""
    if key in _ACTIVE:
        return None
    run = Run(key=key)
    _ACTIVE[key] = run
    _LAST.pop(key, None)
    return run


def find_run(run_id: str) -> Run | None:
    """The active or last-finished run with this id, else None."""
    for registry in (_ACTIVE, _LAST):
        for run in registry.values():
            if run.id == run_id:
                return run
    return None


def release_run(run: Run) -> None:
    """Free the slot; the identity check never clobbers a replacement run."""
    if _ACTIVE.get(run.key) is run:
        del _ACTIVE[run.key]
        _LAST[run.key] = run
        # ponytail: oldest-first eviction at 20 finished runs; a Stop on an
        # evicted run 404s. Raise the cap or persist runs if that ever matters.
        while len(_LAST) > _LAST_MAX:
            del _LAST[next(iter(_LAST))]


def reject_run_proposals(run: Run) -> list[str]:
    """Reject the run's still-pending CHAT proposals; return every rejected id.

    Mirrors POST /proposals/{id}/reject: SELECT ... FOR UPDATE, chat channel
    only, transition, commit, no audit row (D-08). Rows are matched by
    recorded id or by turn id (the run id, stamped by tools.CURRENT_TURN_ID, so
    it also catches a propose tool that finished in its executor thread after
    the cancel, D-08a). The created-since-start sweep is only a fallback for
    legacy rows without a turn id: runs are per thread, so an unrestricted
    sweep would reject another thread's proposals (Pitfall 7). MCP-channel rows
    are never touched. Already-rejected rows are reported too, so a cancel
    racing an earlier sweep still answers with the full set (Pitfall 2).
    """
    from sqlalchemy import and_, or_, select

    from backend.db import get_session_sync
    from backend.models import Proposal
    from backend.proposals import transition

    ids = []
    for pid in run.proposal_ids:
        try:
            ids.append(uuid.UUID(pid))
        except ValueError:
            continue
    with get_session_sync() as db:
        rows = db.execute(
            select(Proposal)
            .where(or_(
                Proposal.id.in_(ids),
                Proposal.turn_id == uuid.UUID(run.id),
                and_(
                    Proposal.turn_id.is_(None),
                    Proposal.channel == "chat",
                    Proposal.created_at >= run.started_at,
                ),
            ))
            .order_by(Proposal.id)  # fixed lock order: Stop and disconnect cannot deadlock
            .with_for_update()
        ).scalars().all()
        for p in rows:
            if p.channel == "chat" and p.status == "pending":
                transition(p, "rejected")
        db.commit()
        return [str(p.id) for p in rows if p.channel == "chat" and p.status == "rejected"]


async def stop_run(run: Run) -> list[str]:
    """Halt the workflow, then reject the run's pending chat proposals."""
    run.stopped = True
    await _halt(run.handler, run.task)
    return await asyncio.to_thread(reject_run_proposals, run)


async def finish_run(run: Run) -> None:
    """The pump's terminal step: sweep if stopped, mark done, end the buffer, free the slot.

    A completed, unstopped run never sweeps. A stopped run sweeps again even
    though its stream ended cleanly: a propose tool still running in its
    executor thread when Stop swept (D-08a) has committed by now, and its row
    would otherwise stay pending and approvable. A client disconnect no longer
    reaches here: it only detaches a subscriber (D-06).
    """
    try:
        if run.stopped:
            try:
                await asyncio.to_thread(reject_run_proposals, run)
            except Exception as e:
                logger.warning("reject_run_proposals failed: %s: %s", type(e).__name__, e)
    finally:
        run.done = True
        push(run, _DONE)
        release_run(run)


def push(run: Run, chunk: str) -> None:
    """Append a chunk to the run's buffer and wake every subscriber (pump only).

    Swapping in a fresh Event before setting the old one means a subscriber that
    captured `run.wake` before draining can never miss a wake-up.
    """
    run.events.append(chunk)
    old, run.wake = run.wake, asyncio.Event()
    old.set()


def redact_tokens(chunk: str) -> str:
    """Strip proposal tokens from an answer/error SSE chunk (T-02-07, D-08).

    Only the original stream's terminal event may carry a token; a re-attached
    subscriber gets proposals without `token` and `proposal_token` null.
    Anything else (pings, [DONE], step/tool_result events) is returned as is.
    """
    if '"token"' not in chunk and '"proposal_token"' not in chunk:
        return chunk
    if not chunk.startswith("data: "):
        return chunk
    try:
        p = json.loads(chunk[len("data: "):].strip())
    except ValueError:
        return chunk
    if not isinstance(p, dict) or p.get("type") not in ("answer", "error"):
        return chunk
    for pr in p.get("proposals") or []:
        pr.pop("token", None)
    if "proposal_token" in p:
        p["proposal_token"] = None
    return _sse(p)


async def subscribe(run: Run, *, redact: bool = False, ping_interval: float = 15.0):
    """Replay the run's buffered events in order, then follow live ones until [DONE].

    A cancelled subscriber has no cleanup on purpose: that is the detach (D-06).
    Pings are the subscriber's own, never part of the buffer.
    """
    i = 0
    while True:
        wake = run.wake  # capture BEFORE reading the list
        while i < len(run.events):
            chunk = run.events[i]
            i += 1
            yield redact_tokens(chunk) if redact else chunk
            if chunk == _DONE:
                return
        if run.done:
            return
        try:
            await asyncio.wait_for(wake.wait(), ping_interval)
        except TimeoutError:
            yield ": ping\n\n"


async def run_stream(run: Run):
    """SSE response body of a launched run: a subscriber, not the owner (D-05).

    Emitting the `run` (and `thread`) events is the launcher's job (D-07a).
    """
    async for chunk in subscribe(run):
        yield chunk


# ---------------------------------------------------------------------------
# Cache invalidation — called from main.py after writes
# ---------------------------------------------------------------------------

def reset_engine() -> None:
    """Clear the LLM, the agent workflow and its build date (called after writes)."""
    global _llm, _agent_workflow, _agent_workflow_date
    _llm = None
    _agent_workflow = None
    _agent_workflow_date = None
