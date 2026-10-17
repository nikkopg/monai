"""
Chat turn lifecycle (Phase 36, D-10).

`launch` starts a detached pump task that drives query.agent_stream and fills
the run's event buffer (D-05a). HTTP responses and re-attached clients are
subscribers of that buffer (query.subscribe); a disconnect only ends the
subscriber, never the turn (D-06). Only POST /query-stream/{run_id}/cancel
stops a run.

The pump's finally runs under a cancel shield and always ends the buffer with
[DONE] and frees the registry slot, even when the pump itself is cancelled.

Threads (D-05, D-11): `start_turn` persists the user turn before the run starts
and builds the replayed history from the stored messages. The pump persists the
assistant turn (token-free parts) before [DONE], so a client that sees [DONE]
can always read the finished turn back. Every DB step uses its own short
session; none is held across the stream.
"""

import asyncio
import json
import logging
import uuid

import anyio
from sqlalchemy import delete, func, or_, select, text, update

from backend import agent_loop, config, query, tools
from backend.chat_history import plan_history
from backend.db import get_session_sync
from backend.models import AuditLog, Message, Proposal, Thread
from backend.proposals import expire_stale, transition

logger = logging.getLogger(__name__)


def launch(
    run: query.Run, question: str, history: list | None = None,
    tool_names: frozenset[str] | None = None,
) -> None:
    """Seed the buffer with the `run` event and start the detached pump.

    Must be called from inside the running event loop. The task reference lives
    on `run.pump` (asyncio keeps only weak ones).
    """
    query.push(run, query._sse({"type": "run", "run_id": run.id}))
    run.pump = asyncio.create_task(_pump(run, question, history, tool_names))


def title_from(text_: str, limit: int = 60) -> str:
    """First question, whitespace collapsed, cut at a word boundary (D-13)."""
    s = " ".join(text_.split())
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0] or s[:limit]
    return cut.rstrip(" ,.;:") + "…"


class ReplaceConflict(Exception):
    """A proposal at or after the replace point was applied, so the turn cannot
    be redone (the route maps this to 409)."""


def _replace_branch(db, thread_id: uuid.UUID, question: str, replace_from: uuid.UUID) -> None:
    """Supersede pending chat proposals, then delete the target message and
    everything after it (D-18, D-19). Caller commits, so it is all-or-nothing.
    A target at or below the thread's summary boundary drops the stored summary and
    moves the boundary to just before it (D-26a)."""
    target = db.get(Message, replace_from)
    if target is None or target.thread_id != thread_id or target.role != "user":
        raise ValueError("Message not found in this thread")  # explicit, never an FK error
    t = db.get(Thread, thread_id)
    if target.seq <= (t.summary_upto_seq or 0):
        # The summary may describe turns about to be deleted, so drop it. The boundary
        # moves to just before the target: hidden messages stay hidden and nothing
        # deleted is summarised (D-26a).
        t.summary = None
        t.summary_upto_seq = target.seq - 1
    doomed = db.execute(
        select(Message).where(Message.thread_id == thread_id, Message.seq >= target.seq)
    ).scalars().all()
    ids: set[uuid.UUID] = set()
    for m in doomed:
        for p in (m.parts or {}).get("proposals", []):
            try:
                ids.add(uuid.UUID(p["id"]))
            except (ValueError, KeyError, TypeError):
                pass
    locked = db.execute(
        select(Proposal)
        .where(or_(Proposal.id.in_(ids), Proposal.message_id.in_([m.id for m in doomed])))
        .order_by(Proposal.id)
        .with_for_update()
    ).scalars().all()
    if any(p.status == "confirmed" for p in locked):
        raise ReplaceConflict("This answer's changes were already applied")
    reason = "regenerated" if question.strip() == target.content.strip() else "edited"
    for p in locked:
        if p.channel == "chat" and p.status == "pending":
            transition(p, "superseded")
            db.add(AuditLog(
                entity="proposal", entity_id=None, operation="superseded",
                before={"proposal_id": str(p.id), "status": "pending"},
                after={"status": "superseded", "reason": reason, "thread_id": str(thread_id)},
            ))
    # Proposal rows survive the delete: messages FK is ON DELETE SET NULL.
    db.execute(delete(Message).where(Message.thread_id == thread_id, Message.seq >= target.seq))
    db.flush()


def _begin_turn(thread_id: uuid.UUID, new: bool, question: str, replace_from: uuid.UUID | None = None):
    """Create/find the thread and store the user message; return
    (user_message_id, seq, prior messages as dicts with seq, thread summary,
    summary boundary). One short session; with
    `replace_from` the old branch is superseded and deleted in the same commit."""
    with get_session_sync() as db:
        if new:
            db.add(Thread(id=thread_id, title=title_from(question)))
            db.flush()
        elif db.get(Thread, thread_id) is None:
            raise LookupError("Thread not found")  # never an FK IntegrityError
        if replace_from is not None:
            _replace_branch(db, thread_id, question, replace_from)
        prior = [
            {
                "role": m.role,
                "content": m.content,
                "status": m.status,
                "parts": m.parts,
                "created_at": m.created_at,
                "seq": m.seq,
            }
            for m in db.execute(
                select(Message).where(Message.thread_id == thread_id).order_by(Message.seq)
            ).scalars()
        ]
        seq = (
            db.execute(
                select(func.max(Message.seq)).where(Message.thread_id == thread_id)
            ).scalar()
            or 0
        ) + 1
        user = Message(
            thread_id=thread_id, seq=seq, role="user", content=question,
            status="complete", parts={},
        )
        db.add(user)
        db.flush()
        db.execute(text("UPDATE threads SET updated_at = now() WHERE id = :t"), {"t": thread_id})
        db.commit()
        t = db.get(Thread, thread_id)
        return user.id, seq, prior, t.summary, t.summary_upto_seq or 0


async def start_turn(
    question: str, thread_id: uuid.UUID | None = None, replace_from: uuid.UUID | None = None
) -> query.Run | None:
    """Start a persisted turn; None when the thread already has a run (D-05).

    The run guard goes first (409). Raises LookupError for an unknown thread
    id, ValueError for a bad `replace_from` (needs thread_id; must be a user
    message of that thread) and ReplaceConflict when a change was applied.
    Must run inside the event loop.
    """
    if replace_from is not None and thread_id is None:
        raise ValueError("replace_from needs thread_id")
    tid = thread_id or uuid.uuid4()
    run = query.start_run(str(tid))
    if run is None:
        return None
    try:
        user_id, seq, prior, summary, upto = await asyncio.to_thread(
            _begin_turn, tid, thread_id is None, question, replace_from
        )
        # Module attribute reads so tests can monkeypatch the budget and the date.
        history, _ = plan_history(
            prior, config.CHAT_HISTORY_TOKEN_BUDGET, query._today(), summary=summary, upto_seq=upto
        )
        tool_names = agent_loop.tools_for_turn(question, prior)
        run.thread_id, run.user_message_id, run.user_seq = tid, user_id, seq
        run.assistant_message_id = uuid.uuid4()
        query.push(
            run,
            query._sse(
                {
                    "type": "thread",
                    "thread_id": str(tid),
                    "user_message_id": str(user_id),
                    "assistant_message_id": str(run.assistant_message_id),
                }
            ),
        )
        launch(run, question, history, tool_names)
    except BaseException:
        # Not via release_run: a never-finished run must not become _LAST.
        if query._ACTIVE.get(run.key) is run:
            del query._ACTIVE[run.key]
        raise
    return run


def _persist_end(run: query.Run, state: dict) -> None:
    """Store the assistant turn and back-fill proposals.message_id (D-11)."""
    if run.thread_id is None:
        return
    with get_session_sync() as db:
        status = "cancelled" if run.stopped else ("complete" if state["answered"] else "error")
        turn = uuid.UUID(run.id)
        ids = [uuid.UUID(i) for i in run.proposal_ids]
        rows = db.execute(
            select(Proposal.id, Proposal.operation)
            .where((Proposal.turn_id == turn) | (Proposal.id.in_(ids)))
            .order_by(Proposal.created_at, Proposal.id)
        ).all()
        parts: dict = {
            "steps": state["steps"],
            "proposals": [{"id": str(r.id), "operation": r.operation} for r in rows],
            "provider": {"name": state["provider"], "model": state["model"]},
        }
        if status == "error":
            parts["error"] = {"code": state["error"] or "unknown"}
        parts = json.loads(json.dumps(parts, default=str))  # no Decimal reaches JSONB
        db.add(
            Message(
                id=run.assistant_message_id, thread_id=run.thread_id, seq=run.user_seq + 1,
                role="assistant", content=state["text"] if status == "complete" else "",
                status=status, parts=parts,
            )
        )
        db.flush()  # autoflush is off: the row must exist before SQL references its id
        db.execute(text("UPDATE threads SET updated_at = now() WHERE id = :t"), {"t": run.thread_id})
        db.execute(
            text("UPDATE proposals SET message_id = :a WHERE turn_id = :t"),
            {"a": run.assistant_message_id, "t": turn},
        )
        db.commit()
        # WR-02: a Stop that landed after `status` was read ran mark_cancelled
        # before this INSERT committed and matched nothing; stop_run sets
        # `stopped` first, so re-checking here closes the race.
        if status == "complete" and run.stopped:
            mark_cancelled(run.assistant_message_id)


def _observe(state: dict, chunk: str) -> None:
    """Record what the persisted turn needs from one SSE chunk (never results)."""
    if not chunk.startswith("data: ") or chunk.startswith(query.TOKEN_PREFIX):
        return  # token deltas are ephemeral (D-04) and never parsed per token
    try:
        p = json.loads(chunk[6:])
    except ValueError:
        return
    t = p.get("type")
    if t == "tool_result":
        step = p.get("step") or {}
        rec = {"tool": step.get("tool"), "args": step.get("args") or {}}
        if isinstance(p.get("ms"), int):
            rec["ms"] = p["ms"]
        if p.get("sources"):
            rec["sources"] = p["sources"]
        state["steps"].append(rec)
    elif t == "answer":
        state.update(answered=True, text=p.get("text") or "", model=p.get("model"), provider=p.get("provider"))
    elif t == "error":
        state.update(error=p.get("code"), model=p.get("model"), provider=p.get("provider"))


async def _pump(
    run: query.Run, question: str, history: list | None,
    tool_names: frozenset[str] | None = None,
) -> None:
    # create_task copied the context, so no reset is needed; tool executor
    # threads inherit the value (D-12a).
    tools.CURRENT_TURN_ID.set(uuid.UUID(run.id))
    state: dict = {
        "steps": [], "text": "", "answered": False, "error": None,
        "model": None, "provider": None,
    }
    try:
        # Attribute lookup on the module, never a from-import: tests and
        # test_auth monkeypatch backend.query.agent_stream.
        async for chunk in query.agent_stream(
            question, run=run, history=history, tool_names=tool_names
        ):
            if chunk.startswith(":") or chunk == query._DONE:
                continue  # pings are the subscriber's own; [DONE] is withheld to the end
            _observe(state, chunk)
            query.push(run, chunk)
    except Exception as e:
        # Class and message only: never the question or any payload.
        logger.warning("chat pump failed: %s: %s", type(e).__name__, e)
        state["error"] = "unknown"
        query.push(run, query._error_event("unknown", None, None, None))
    finally:
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.to_thread(_persist_end, run, state)
            except Exception as e:  # a persistence failure must never keep the slot
                logger.warning("chat persist failed: %s: %s", type(e).__name__, e)
            await query.finish_run(run)  # sweep if stopped, [DONE], release (D-05a)


# ---------------------------------------------------------------------------
# Thread data helpers (the routes in 36-06 call these)
# ---------------------------------------------------------------------------


def _thread_row(t: Thread) -> dict:
    return {"id": t.id, "title": t.title, "updated_at": t.updated_at}


def list_threads(db, limit: int = 200) -> list[dict]:
    rows = db.execute(select(Thread).order_by(Thread.updated_at.desc()).limit(limit)).scalars()
    return [_thread_row(t) for t in rows]


def thread_detail(db, thread_id: uuid.UUID) -> dict | None:
    """Thread with its messages; each referenced proposal joined live (D-16).

    Proposal entries are built field by field: the row also holds `token` and
    `code`, which must never leave the server here (T-02-07).
    """
    expire_stale(db)  # lazy expiry so a stale pending card reads expired
    t = db.get(Thread, thread_id)
    if t is None:
        return None
    msgs = list(
        db.execute(
            select(Message).where(Message.thread_id == thread_id).order_by(Message.seq)
        ).scalars()
    )
    wanted: set[uuid.UUID] = set()
    for m in msgs:
        for p in (m.parts or {}).get("proposals", []):
            try:
                wanted.add(uuid.UUID(p["id"]))
            except (ValueError, KeyError, TypeError):
                pass
    live = {
        r.id: r
        for r in (
            db.execute(select(Proposal).where(Proposal.id.in_(wanted))).scalars() if wanted else []
        )
    }
    out = []
    for m in msgs:
        parts = dict(m.parts or {})
        entries = []
        for p in parts.get("proposals", []):
            try:
                row = live.get(uuid.UUID(p["id"]))
            except (ValueError, TypeError):
                row = None
            if row is None:
                entries.append(
                    {"id": p.get("id"), "operation": p.get("operation"), "payload": None,
                     "status": "missing", "expires_at": None}
                )
            else:
                entries.append(
                    {"id": str(row.id), "operation": row.operation, "payload": row.payload,
                     "status": row.status, "expires_at": row.expires_at}
                )
        parts["proposals"] = entries
        out.append(
            {"id": m.id, "seq": m.seq, "role": m.role, "content": m.content,
             "status": m.status, "created_at": m.created_at, "parts": parts}
        )
    return {**_thread_row(t), "messages": out}


def rename_thread(db, thread_id: uuid.UUID, title: str) -> dict | None:
    title = title.strip()
    if not 1 <= len(title) <= 200:
        raise ValueError("Title must be 1-200 characters")
    t = db.get(Thread, thread_id)
    if t is None:
        return None
    t.title = title  # no updated_at bump: only persisted messages do (D-13)
    db.commit()
    return _thread_row(t)


def delete_thread(db, thread_id: uuid.UUID) -> bool:
    """Messages cascade in the DB; proposals keep their rows (message_id NULL).
    The 'run active' 409 check stays in the route."""
    t = db.get(Thread, thread_id)
    if t is None:
        return False
    db.delete(t)
    db.commit()
    return True


def mark_cancelled(message_id: uuid.UUID) -> bool:
    """A Stop that lands after the answer was persisted (within the 34 D-11
    retention) flips the stored turn so it is never replayed (D-06a)."""
    with get_session_sync() as db:
        # Dict form: the proposals status-write grep guard is about proposals only.
        n = db.execute(
            update(Message)
            .where(Message.id == message_id, Message.status == "complete")
            .values({"status": "cancelled", "content": ""})
        ).rowcount
        db.commit()
        return bool(n)
