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
from llama_index.core.llms import ChatMessage, MessageRole
from sqlalchemy import delete, func, or_, select, text, update

from backend import agent_loop, chat_tools, config, query, tools
from backend.chat_history import _pairs, _provenance, _stamp, plan_history
from backend.db import get_session_sync
from backend.attachments import purge_expired
from backend.models import Attachment, AuditLog, Message, Proposal, Thread
from backend.proposals import expire_stale, transition

logger = logging.getLogger(__name__)


def launch(
    run: query.Run, question: str, history: list | None = None,
    tool_names: frozenset[str] | None = None, compact: bool = False,
) -> None:
    """Seed the buffer with the `run` event and start the detached pump.

    Must be called from inside the running event loop. The task reference lives
    on `run.pump` (asyncio keeps only weak ones).
    """
    query.push(run, query._sse({"type": "run", "run_id": run.id}))
    run.pump = asyncio.create_task(_pump(run, question, history, tool_names, compact))


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


def _begin_turn(
    thread_id: uuid.UUID, new: bool, question: str, replace_from: uuid.UUID | None = None,
    attachment_ids=(),
):
    """Create/find the thread and store the user message; return
    (user_message_id, seq, prior messages as dicts with seq, thread summary,
    summary boundary, the thread's attachments for the manifest). One short session; with
    `replace_from` the old branch is superseded and deleted in the same commit.
    `attachment_ids` bind to the new message in that same commit; one that is not
    on this thread raises ValueError and nothing is stored (D-03)."""
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
        if attachment_ids:
            ids = set(attachment_ids)
            n = db.execute(
                text("UPDATE attachments SET message_id = :m WHERE thread_id = :t AND id = ANY(:ids)"),
                {"m": user.id, "t": thread_id, "ids": list(ids)},
            ).rowcount
            if n != len(ids):
                raise ValueError("Unknown attachment for this chat.")  # no commit: all rolled back
        db.execute(text("UPDATE threads SET updated_at = now() WHERE id = :t"), {"t": thread_id})
        atts = [
            dict(r) for r in db.execute(
                text("SELECT id, filename, kind, parse_status, parse_note, meta, "
                     "jsonb_array_length(rows) AS row_count FROM attachments "
                     "WHERE thread_id = :t ORDER BY created_at, id"),
                {"t": thread_id},
            ).mappings()
        ]
        db.commit()
        t = db.get(Thread, thread_id)
        return user.id, seq, prior, t.summary, t.summary_upto_seq or 0, atts


async def start_turn(
    question: str, thread_id: uuid.UUID | None = None, replace_from: uuid.UUID | None = None,
    attachment_ids=(),
) -> query.Run | None:
    """Start a persisted turn; None when the thread already has a run (D-05).

    The run guard goes first (409). Raises LookupError for an unknown thread
    id, ValueError for a bad `replace_from` (needs thread_id; must be a user
    message of that thread), for `attachment_ids` without a thread or not on it,
    and ReplaceConflict when a change was applied.
    A thread holding any attachment runs the reduced tool set and starts with the
    ephemeral manifest; both come from the database, never the request (D-16, D-18).
    Must run inside the event loop.
    """
    if replace_from is not None and thread_id is None:
        raise ValueError("replace_from needs thread_id")
    if attachment_ids and thread_id is None:
        raise ValueError("attachment_ids need a thread_id.")
    tid = thread_id or uuid.uuid4()
    run = query.start_run(str(tid))
    if run is None:
        return None
    try:
        user_id, seq, prior, summary, upto, atts = await asyncio.to_thread(
            _begin_turn, tid, thread_id is None, question, replace_from, attachment_ids
        )
        # Module attribute reads so tests can monkeypatch the budget and the date.
        history, to_compact = plan_history(
            prior, config.CHAT_HISTORY_TOKEN_BUDGET, query._today(), summary=summary, upto_seq=upto
        )
        tool_names = agent_loop.tools_for_turn(question, prior, attachment_thread=bool(atts))
        if atts:
            history = [ChatMessage(role=MessageRole.SYSTEM, content=chat_tools.manifest(atts)), *history]
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
        launch(run, question, history, tool_names, compact=bool(to_compact))
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
    tool_names: frozenset[str] | None = None, compact: bool = False,
) -> None:
    # create_task copied the context, so no reset is needed; tool executor
    # threads inherit the value (D-12a).
    tools.CURRENT_TURN_ID.set(uuid.UUID(run.id))
    tools.CURRENT_THREAD_ID.set(run.thread_id)
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
        # After the slot is free, so the guard does not see this run (D-21). A failed or
        # stopped turn does not spend a summariser call.
        if compact and run.thread_id is not None and state["answered"] and not run.stopped:
            schedule_compaction(run.thread_id)


# ---------------------------------------------------------------------------
# Rolling summary (Phase 38, D-21..D-25)
# ---------------------------------------------------------------------------

SUMMARY_INPUT_CHARS = 12000  # per summariser call; a longer fold is chunked (D-21a b)
SUMMARY_MAX_CHARS = 1500  # stored summary cap (D-21a e)

SUMMARY_PROMPT = (
    "You are summarising a personal-finance chat so the assistant can use it as context later. "
    "Fold the new conversation into the current summary.\n"
    "Keep: what the owner asked, the filters, periods as absolute dates (YYYY-MM-DD or month and "
    "year), the accounts, categories and merchants named, decisions, and the outcome of each "
    "proposed change (applied, rejected, pending, expired).\n"
    "Omit every amount, total, balance, count and percentage; write \"a figure was given\" "
    "instead, because the assistant re-queries any number.\n"
    "Plain text, at most 1200 characters, no preamble."
)

# ponytail: in-process, valid for the single uvicorn worker (same assumption as query._ACTIVE).
_COMPACTING: set[str] = set()
_BG: set[asyncio.Task] = set()  # strong refs: asyncio keeps only weak ones


class ThreadBusy(Exception):
    """A run or a compaction is already active for the thread (routes map this to 409)."""


def thread_busy(key: str) -> bool:
    return key in query._ACTIVE or key in _COMPACTING


def _load_for_compaction(thread_id: uuid.UUID):
    """(summary, upto, messages as dicts in seq order, {proposal_id: (operation, status)}), or None."""
    with get_session_sync() as db:
        t = db.get(Thread, thread_id)
        if t is None:
            return None
        msgs = [
            {"id": m.id, "seq": m.seq, "role": m.role, "content": m.content,
             "status": m.status, "parts": m.parts, "created_at": m.created_at}
            for m in db.execute(
                select(Message).where(Message.thread_id == thread_id).order_by(Message.seq)
            ).scalars()
        ]
        ids: set[uuid.UUID] = set()
        for m in msgs:
            for p in (m["parts"] or {}).get("proposals", []):
                try:
                    ids.add(uuid.UUID(p["id"]))
                except (ValueError, KeyError, TypeError):
                    pass
        outcomes = {
            str(r.id): (r.operation, r.status)
            for r in (
                db.execute(
                    select(Proposal.id, Proposal.operation, Proposal.status).where(Proposal.id.in_(ids))
                ) if ids else []
            )
        }
        return t.summary, t.summary_upto_seq or 0, msgs, outcomes


def _render_pair(u: dict, a: dict, outcomes: dict) -> str:
    """Owner text, final answer, provenance and proposal op/status only; never tool results (D-22)."""
    out = f"[{_stamp(u['created_at'])}] Owner: {u['content']}\nAssistant: {a['content']}"
    parts = a.get("parts") or {}
    if prov := _provenance(parts.get("steps")):
        out += "\n" + prov
    changes = [
        f"{o[0]} {o[1]}"
        for p in parts.get("proposals", [])
        if (o := outcomes.get(p.get("id")))
    ]
    if changes:
        out += f"\n[changes: {'; '.join(changes)}]"
    return out[:SUMMARY_INPUT_CHARS]


def _chunks(pairs: list[tuple[dict, dict]], outcomes: dict) -> list[tuple[str, dict]]:
    """Consecutive rendered pairs grouped to at most SUMMARY_INPUT_CHARS: (text, last assistant)."""
    out: list[tuple[str, dict]] = []
    cur: list[str] = []
    size = 0
    for u, a in pairs:
        r = _render_pair(u, a, outcomes)
        if cur and size + 2 + len(r) > SUMMARY_INPUT_CHARS:
            out.append(("\n\n".join(cur), last))
            cur, size = [], 0
        size += len(r) + (2 if cur else 0)
        cur.append(r)
        last = a
    if cur:
        out.append(("\n\n".join(cur), last))
    return out


def _cas_write(thread_id: uuid.UUID, summary: str, new: int, old: int, msg_id: uuid.UUID) -> bool:
    """Write only if the boundary is unchanged and the last folded message still exists, so a
    /clear, a replace or another compaction that won the race makes this a no-op (D-21a c)."""
    with get_session_sync() as db:
        n = db.execute(
            text(
                "UPDATE threads SET summary = :s, summary_upto_seq = :new "
                "WHERE id = :t AND summary_upto_seq = :old "
                "AND EXISTS (SELECT 1 FROM messages WHERE id = :m AND thread_id = :t)"
            ),
            {"s": summary, "new": new, "t": thread_id, "old": old, "m": msg_id},
        ).rowcount
        db.commit()
        return n == 1


async def compact_thread(thread_id: uuid.UUID, *, everything: bool) -> dict | None:
    """Fold complete pairs after the boundary into the thread summary, chunk by chunk.

    None when the thread is missing. Raises ThreadBusy when a run or a compaction is
    active. Provider and empty-summary errors propagate; the columns keep the last
    committed chunk and nothing retries (D-21).
    """
    key = str(thread_id)
    if thread_busy(key):
        raise ThreadBusy(key)
    _COMPACTING.add(key)  # before the first await
    try:
        loaded = await asyncio.to_thread(_load_for_compaction, thread_id)
        if loaded is None:
            return None
        summary, upto, msgs, outcomes = loaded
        if everything:
            pairs = [(u, a) for u, a in _pairs(msgs) if u["seq"] > upto]
        else:
            pairs = plan_history(
                msgs, config.CHAT_HISTORY_TOKEN_BUDGET, query._today(), summary=summary, upto_seq=upto
            )[1]
        if not pairs:
            return {"summary_upto_seq": upto, "has_summary": bool(summary), "compacted": False}
        chunks = _chunks(pairs, outcomes)
        for i, (chunk_text, last_a) in enumerate(chunks):
            async with asyncio.timeout(config.CHAT_IDLE_TIMEOUT_SECONDS):
                resp = await query._get_llm().achat([
                    ChatMessage(role=MessageRole.SYSTEM, content=SUMMARY_PROMPT),
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Current summary:\n" + (summary or "(none)")
                        + "\n\nConversation to fold in:\n" + chunk_text,
                    ),
                ])
            new_summary = (resp.message.content or "").strip()[:SUMMARY_MAX_CHARS]
            if not new_summary:
                raise ValueError("empty summary")
            target = msgs[-1] if everything and i == len(chunks) - 1 else last_a
            if not await asyncio.to_thread(
                _cas_write, thread_id, new_summary, target["seq"], upto, target["id"]
            ):
                logger.info("compaction result dropped: the thread changed")
                return {"summary_upto_seq": upto, "has_summary": bool(summary), "compacted": False}
            summary, upto = new_summary, target["seq"]
        return {"summary_upto_seq": upto, "has_summary": True, "compacted": True}
    finally:
        _COMPACTING.discard(key)


async def _auto_compact(thread_id: uuid.UUID) -> None:
    try:
        await compact_thread(thread_id, everything=False)
    except ThreadBusy:
        pass  # a later turn retries
    except Exception as e:  # class and message only: the summary text is never logged
        logger.warning("compaction failed: %s: %s", type(e).__name__, e)


def schedule_compaction(thread_id: uuid.UUID) -> asyncio.Task | None:
    """Fire-and-forget post-turn compaction; None (skipped) while the thread is busy (D-21)."""
    if thread_busy(str(thread_id)):
        return None
    task = asyncio.create_task(_auto_compact(thread_id))
    _BG.add(task)
    task.add_done_callback(_BG.discard)
    return task


def clear_thread(thread_id: uuid.UUID) -> dict | None:
    """Hide every message from the prompt and drop the summary; messages stay (D-24)."""
    with get_session_sync() as db:
        row = db.execute(
            text(
                "UPDATE threads SET summary = NULL, summary_upto_seq = "
                "COALESCE((SELECT max(seq) FROM messages WHERE thread_id = :t), 0) "
                "WHERE id = :t RETURNING summary_upto_seq"
            ),
            {"t": thread_id},
        ).first()
        db.commit()
        return None if row is None else {"summary_upto_seq": row[0], "has_summary": False}


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
    `code`, which must never leave the server here (T-02-07). Also lists the
    thread's attachments (never raw, text or rows) after the lazy purge (D-07).
    """
    expire_stale(db)  # lazy expiry so a stale pending card reads expired
    purge_expired(db)
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
                     "status": "missing", "expires_at": None, "channel": None}
                )
            else:
                entries.append(
                    {"id": str(row.id), "operation": row.operation, "payload": query.slim_payload(row),
                     "status": row.status, "expires_at": row.expires_at, "channel": row.channel}
                )
        parts["proposals"] = entries
        out.append(
            {"id": m.id, "seq": m.seq, "role": m.role, "content": m.content,
             "status": m.status, "created_at": m.created_at, "parts": parts}
        )
    atts = db.execute(
        select(Attachment).where(Attachment.thread_id == thread_id).order_by(Attachment.created_at, Attachment.id)
    ).scalars()
    return {
        **_thread_row(t), "messages": out,
        "attachments": [
            {"id": a.id, "filename": a.filename, "kind": a.kind, "status": a.parse_status,
             "summary": (a.meta or {}).get("summary", ""), "row_count": len(a.rows or []),
             "message_id": a.message_id, "purged_at": a.purged_at}
            for a in atts
        ],
        "summary_upto_seq": t.summary_upto_seq or 0, "has_summary": bool(t.summary),
    }


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
