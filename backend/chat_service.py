"""
Chat turn lifecycle (Phase 36, D-10).

`launch` starts a detached pump task that drives query.agent_stream and fills
the run's event buffer (D-05a). HTTP responses and re-attached clients are
subscribers of that buffer (query.subscribe); a disconnect only ends the
subscriber, never the turn (D-06). Only POST /query-stream/{run_id}/cancel
stops a run.

The pump's finally runs under a cancel shield and always ends the buffer with
[DONE] and frees the registry slot, even when the pump itself is cancelled.
"""

import asyncio
import logging
import uuid

import anyio

from backend import query, tools

logger = logging.getLogger(__name__)


def launch(run: query.Run, question: str, history: list | None = None) -> None:
    """Seed the buffer with the `run` event and start the detached pump.

    Must be called from inside the running event loop. The task reference lives
    on `run.pump` (asyncio keeps only weak ones).
    """
    query.push(run, query._sse({"type": "run", "run_id": run.id}))
    run.pump = asyncio.create_task(_pump(run, question, history))


async def _pump(run: query.Run, question: str, history: list | None) -> None:
    # create_task copied the context, so no reset is needed; tool executor
    # threads inherit the value (D-12a).
    tools.CURRENT_TURN_ID.set(uuid.UUID(run.id))
    try:
        # Attribute lookup on the module, never a from-import: tests and
        # test_auth monkeypatch backend.query.agent_stream.
        async for chunk in query.agent_stream(question, run=run, history=history):
            if chunk.startswith(":") or chunk == query._DONE:
                continue  # pings are the subscriber's own; [DONE] is withheld to the end
            query.push(run, chunk)
    except Exception as e:
        # Class and message only: never the question or any payload.
        logger.warning("chat pump failed: %s: %s", type(e).__name__, e)
        query.push(run, query._error_event("unknown", None, None, None))
    finally:
        with anyio.CancelScope(shield=True):
            await query.finish_run(run)
