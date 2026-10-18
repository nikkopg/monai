"""
Shared synthetic stubs for the chat tests (Phase 36 D-05a).

A helper module, not a test module: its name does not start with `test_`, so
pytest does not collect it, and importing it never re-collects the tests of
test_chat_reliability.py. Holds the scripted function-calling StubLLM, the
proposal seeding helpers (`purge_seeded` is the cleanup both test modules
call), the stub-workflow installer and the SSE collectors. Phase 37 adds
the configurable tool call (`tool_name`/`tool_kwargs`), a `two_calls` mode
that reproduces Ollama's tool id == tool name collision, and the synthetic
`slow_echo` / `fake_spending_total` tools.

All values are synthetic.
"""

import asyncio
import datetime
import json
import re
import secrets
import time
import uuid

from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.base.llms.types import TextBlock, ToolCallBlock
from llama_index.core.llms import (
    ChatMessage,
    ChatResponse,
    LLMMetadata,
    MockFunctionCallingLLM,
)
from llama_index.core.llms.llm import ToolSelection
from pydantic import Field
from sqlalchemy import text


class Err429(Exception):
    """Synthetic provider rate-limit error (duck-typed status_code)."""

    status_code = 429


def _resp(content: str, delta: str) -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role="assistant", content=content), delta=delta
    )


class StubLLM(MockFunctionCallingLLM):
    """Scripted function-calling LLM. `mode` picks the behaviour.

    `script` mode: call n emits script[n-1], a list of (tool_name, kwargs) pairs
    in ONE message (id == tool name, like Ollama); after the script, `final()`.
    """

    mode: str = "ok"
    model: str = "example-model:7b"
    calls: int = 0
    final_text: str = "Hello"
    drip_count: int = 5
    drip_gap: float = 0.2
    tool_name: str = "seed_proposal"
    tool_kwargs: dict = Field(default_factory=dict)
    seen: list = Field(default_factory=list)  # chat_history contents per LLM call
    seen_roles: list = Field(default_factory=list)  # [(role, content)] per LLM call
    script: list = Field(default_factory=list)

    @property
    def metadata(self):
        return LLMMetadata(is_function_calling_model=True, is_chat_model=True)

    async def astream_chat_with_tools(
        self, tools, user_msg=None, chat_history=None, **kw
    ):
        self.calls += 1
        self.seen.append([str(m.content) for m in (chat_history or [])])
        self.seen_roles.append(
            [(m.role.value if hasattr(m.role, "value") else str(m.role), str(m.content))
             for m in (chat_history or [])])
        n = self.calls
        mode = self.mode
        text_ = self.final_text

        async def final():
            if text_ == "":
                yield _resp("", "")
                return
            half = max(1, len(text_) // 2)
            yield _resp(text_[:half], text_[:half])
            yield _resp(text_, text_[half:])

        async def tool_turn():
            yield _resp("let me check", "let me check")
            yield ChatResponse(
                message=ChatMessage(
                    role="assistant",
                    blocks=[
                        TextBlock(text="let me check"),
                        ToolCallBlock(
                            tool_name=self.tool_name,
                            tool_kwargs=self.tool_kwargs,
                            tool_call_id="c1",
                        ),
                    ],
                ),
                delta="",
            )

        async def two_calls_turn():
            # Ollama sets the tool id to the tool name: both ids collide.
            yield _resp("checking both", "checking both")
            yield ChatResponse(
                message=ChatMessage(
                    role="assistant",
                    blocks=[
                        TextBlock(text="checking both"),
                        ToolCallBlock(
                            tool_name="slow_echo",
                            tool_kwargs={"n": 1},
                            tool_call_id="slow_echo",
                        ),
                        ToolCallBlock(
                            tool_name="slow_echo",
                            tool_kwargs={"n": 2},
                            tool_call_id="slow_echo",
                        ),
                    ],
                ),
                delta="",
            )

        async def script_turn(calls):
            yield _resp("working", "working")
            yield ChatResponse(
                message=ChatMessage(
                    role="assistant",
                    blocks=[
                        TextBlock(text="working"),
                        *(
                            ToolCallBlock(tool_name=t, tool_kwargs=kw, tool_call_id=t)
                            for t, kw in calls
                        ),
                    ],
                ),
                delta="",
            )

        async def gen():
            if mode == "script":
                if n <= len(self.script):
                    async for r in script_turn(self.script[n - 1]):
                        yield r
                else:
                    async for r in final():
                        yield r
            elif mode == "429":
                raise Err429("rate limited SECRET-sk-synthetic")
            elif mode == "hang":
                yield _resp("par", "par")
                await asyncio.sleep(3600)
            elif mode == "empty":
                yield _resp("", "")
            elif mode == "drip":
                acc = ""
                for i in range(self.drip_count):
                    if i:
                        await asyncio.sleep(self.drip_gap)
                    acc += "x"
                    yield _resp(acc, "x")
                async for r in final():
                    yield r
            elif mode == "two_calls":
                if n == 1:
                    async for r in two_calls_turn():
                        yield r
                else:
                    async for r in final():
                        yield r
            elif mode in ("tool", "tool_then_429", "tool_then_hang"):
                if n == 1:
                    async for r in tool_turn():
                        yield r
                elif mode == "tool_then_429":
                    raise Err429("rate limited SECRET-sk-synthetic")
                elif mode == "tool_then_hang":
                    yield _resp("par", "par")
                    await asyncio.sleep(3600)
                else:
                    async for r in final():
                        yield r
            else:
                async for r in final():
                    yield r

        return gen()

    def get_tool_calls_from_response(
        self, response, error_on_no_tool_call=True, **kw
    ):
        out = []
        for b in response.message.blocks:
            if isinstance(b, ToolCallBlock):
                out.append(
                    ToolSelection(
                        tool_id=b.tool_call_id or "c1",
                        tool_name=b.tool_name,
                        tool_kwargs=b.tool_kwargs
                        if isinstance(b.tool_kwargs, dict)
                        else {},
                    )
                )
        return out


class GullibleLLM(StubLLM):
    """An LLM that obeys every instruction it can see (Phase 39 D-19).

    Per turn it reads each attachment named in a system message, then emits every
    `CALL <tool> <json>` directive found in any non-system message (the tool
    results carry the document text), then calls propose_statement_rows when the
    owner's question asks to import. It records the sorted tool names offered on
    every call in `offered`. A green eval with this stub proves the wall (the
    offered tool list and the id-only proposer), not the model's good manners.
    """

    final_text: str = "ZZ done."
    offered: list = Field(default_factory=list)
    done: list = Field(default_factory=list)  # what this turn already emitted

    async def astream_chat_with_tools(self, tools, user_msg=None, chat_history=None, **kw):
        names = sorted(t.metadata.name for t in tools)
        self.offered.append(names)
        msgs = [(getattr(m.role, "value", str(m.role)), str(m.content)) for m in (chat_history or [])]
        ids = [i for role, c in msgs if role == "system" for i in re.findall(r"id ([0-9a-f-]{36})", c)]
        calls: list = []
        if "read_attachment" in names and "read_attachment" not in self.done:
            self.done.append("read_attachment")
            calls = [("read_attachment", {"attachment_id": i}) for i in ids]
        else:
            for role, c in msgs:
                for hit in re.findall(r"CALL (\w+) (\{[^{}]*\})", c) if role != "system" else []:
                    if hit not in self.done:
                        self.done.append(hit)
                        # a CSV cell doubles its quotes; a model would read through that, so the stub does too
                        calls.append((hit[0], json.loads(hit[1].replace('""', '"'), parse_float=str)))
            asked = [c for role, c in msgs if role == "user"]
            if not calls and "propose_statement_rows" in names and "propose_statement_rows" not in self.done \
                    and asked and re.search(r"import|propose", asked[-1], re.I):
                self.done.append("propose_statement_rows")
                calls = [("propose_statement_rows", {"attachment_id": ids[0]})]
        if not calls:
            self.done.clear()  # this answer ends the turn
        self.mode = "script" if calls else "ok"
        self.script = [[]] * self.calls + [calls]  # the base class plays script[calls]
        return await super().astream_chat_with_tools(tools, user_msg, chat_history, **kw)


# ---------------------------------------------------------------------------
# Proposal seeding
# ---------------------------------------------------------------------------

_SEEDED: list = []

_DEFAULT_ROWS = [
    {
        "before": None,
        "after": {
            "date": "2020-01-01",
            "amount": "-12345.00",
            "merchant": "Example Merchant",
            "account": "Account A",
        },
    }
]


def _seed_proposal(
    *, channel="chat", rows=None, turn_id: uuid.UUID | None = None
) -> tuple[str, str]:
    """ORM-direct insert. Without `turn_id` this is a "legacy" row."""
    from backend.db import SessionLocal
    from backend.models import Proposal

    rows = _DEFAULT_ROWS if rows is None else rows
    token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        p = Proposal(
            token=token,
            operation="add_transaction",
            payload={"operation": "add_transaction", "rows": rows},
            status="pending",
            channel=channel,
            expires_at=datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=15),
            turn_id=turn_id,
        )
        db.add(p)
        db.commit()
        _SEEDED.append(p.id)
        return str(p.id), token
    finally:
        db.close()


def purge_seeded() -> None:
    """Delete every proposal seeded through this module."""
    if not _SEEDED:
        return
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        for i in _SEEDED:
            db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": i})
        db.commit()
    finally:
        db.close()
        _SEEDED.clear()


def seed_proposal() -> dict:
    """Create a synthetic pending proposal through the real _make_proposal
    (so the CURRENT_TURN_ID ContextVar path is exercised)."""
    from backend.tools import _make_proposal

    pid, token = _make_proposal(
        "add_transaction",
        {"operation": "add_transaction", "rows": _DEFAULT_ROWS},
        "chat",
    )
    _SEEDED.append(uuid.UUID(pid))
    return {
        "tool": "seed_proposal",
        "proposal_id": pid,
        "proposal_token": token,
        "summary": "synthetic",
    }


def slow_echo(n: int) -> dict:
    """Synthetic tool that takes 50 ms, for duration pairing."""
    time.sleep(0.05)
    return {"tool": "slow_echo", "n": n}


def fake_spending_total(
    period: str = "all_time",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Synthetic stand-in for the read tool of the same name (no DB)."""
    return {"tool": "spending_total", "total": 1.0, "period": "synthetic"}


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _install_stub_workflow(
    monkeypatch, llm, *, timeout=30.0, extra_tools=None, agent_cls=None
):
    import backend.query as query_mod

    agent = (agent_cls or FunctionAgent)(
        tools=[
            query_mod._llm_tool("seed_proposal", seed_proposal),
            *(query_mod._llm_tool(k, fn) for k, fn in (extra_tools or {}).items()),
        ],
        llm=llm,
        system_prompt="synthetic",
    )
    workflow = AgentWorkflow(agents=[agent], timeout=timeout)
    monkeypatch.setattr(query_mod, "_get_agent_workflow", lambda tool_names=None: workflow)
    return workflow


async def _collect(gen) -> list[str]:
    return [line async for line in gen]


def _payloads(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            continue
        out.append(json.loads(raw))
    return out


def _of_type(payloads: list[dict], t: str) -> list[dict]:
    return [p for p in payloads if p.get("type") == t]


def stream_bare(run, question):
    """Launch a bare run (no thread) and return its subscriber stream.

    Call from inside a running event loop: launch creates the pump task.
    """
    from backend import chat_service, query

    chat_service.launch(run, question)
    return query.run_stream(run)
