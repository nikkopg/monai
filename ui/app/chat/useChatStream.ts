"use client";

import { useEffect, useRef } from "react";

import { CANCEL_TIMEOUT_MS } from "./errors";
import type { Source } from "./labels";

type SseMessage = Record<string, unknown>;

/**
 * Parse one SSE response: events are separated by a blank line, lines starting
 * with ":" are keep-alive pings, `[DONE]` ends the stream. Resolves "done" on
 * `[DONE]`, "ended" when the body closes first (or `shouldStop` turns true).
 * Shared by send (POST /query-stream) and attach (GET /threads/{id}/stream).
 */
export async function readSse(
  resp: Response,
  onEvent: (msg: SseMessage) => void,
  shouldStop?: () => boolean
): Promise<"done" | "ended"> {
  if (!resp.body) return "ended";
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (!shouldStop?.()) {
    const { done: eof, value } = await reader.read();
    if (eof) break;

    buf += decoder.decode(value, { stream: true });
    const messages = buf.split("\n\n");
    buf = messages.pop() ?? "";

    for (const message of messages) {
      if (shouldStop?.()) return "ended"; // late events after Stop are dropped
      if (message.startsWith(":")) continue; // keep-alive ping: invisible
      const dataLine = message.replace(/^data: /, "").trim();
      if (dataLine === "[DONE]") return "done";
      if (!dataLine) continue;
      let msg: SseMessage;
      try {
        msg = JSON.parse(dataLine);
      } catch {
        continue;
      }
      onEvent(msg);
    }
  }
  return "ended";
}

export type StreamOutcome =
  | { kind: "done" | "ended" | "none" | "error" | "stale" | "stopped" }
  | { kind: "status"; status: number };

/**
 * Owns the in-flight stream of the open chat view: abort handle, run id, the
 * synchronous double-submit guard and the stopped flag. `gen` makes a detached
 * stream inert: its late events and its cleanup never touch a newer view.
 */
export function useChatStream() {
  const busyRef = useRef(false); // synchronous double-submit guard
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);
  const stoppedRef = useRef(false);
  const genRef = useRef(0);
  // WR-01: set while a Stop that beat the `run` event waits for it. The stream
  // stays open (events still delivered) until the run id is known, so the cancel
  // route can halt the server run, and until the `thread` event, so a new
  // thread is not lost. A disconnect alone only detaches (D-06).
  const holdRef = useRef<{ onRun: (id: string | null) => void } | null>(null);

  function releaseHold() {
    holdRef.current = null;
    abortRef.current?.abort();
  }

  async function open(
    url: string,
    init: RequestInit,
    onEvent: (msg: SseMessage) => void,
    allowNone: boolean
  ): Promise<StreamOutcome> {
    busyRef.current = true;
    stoppedRef.current = false;
    const gen = ++genRef.current;
    const stale = () => gen !== genRef.current;
    const ac = new AbortController();
    abortRef.current = ac;
    const wrapped = (m: SseMessage) => {
      if (m.type === "run" && typeof m.run_id === "string") {
        runIdRef.current = m.run_id;
        holdRef.current?.onRun(m.run_id);
      }
      onEvent(m);
      if (m.type === "thread" && holdRef.current) releaseHold();
    };
    const settle = (kind: "done" | "ended" | "error"): StreamOutcome =>
      stale() ? { kind: "stale" } : stoppedRef.current ? { kind: "stopped" } : { kind };
    try {
      const resp = await fetch(url, { ...init, signal: ac.signal });
      if (allowNone && resp.status === 204) return stale() ? { kind: "stale" } : { kind: "none" };
      // Never read or show `detail` (D-02): the caller maps the status alone.
      if (!resp.ok || !resp.body) return stale() ? { kind: "stale" } : { kind: "status", status: resp.status };
      const r = await readSse(resp, wrapped, () => (stoppedRef.current && !holdRef.current) || stale());
      return settle(r);
    } catch {
      return settle("error");
    } finally {
      // Only the invocation that still owns the shared refs may clear them.
      if (!stale()) {
        holdRef.current?.onRun(null); // the stream ended before the run event
        holdRef.current = null;
        abortRef.current = null;
        busyRef.current = false;
      }
    }
  }

  function send(
    question: string,
    threadId: string | null,
    onEvent: (msg: SseMessage) => void
  ) {
    runIdRef.current = null;
    return open(
      "/api/query-stream",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(threadId ? { question, thread_id: threadId } : { question }),
      },
      onEvent,
      false
    );
  }

  // Re-attach to a running turn; the caller sets runIdRef from active_run first.
  function attach(threadId: string, onEvent: (msg: SseMessage) => void) {
    return open(`/api/threads/${threadId}/stream`, { method: "GET" }, onEvent, true);
  }

  // Stop: tell the server to cancel (deterministic) and abort the fetch. The two
  // are not ordered; the cancel reply lists the proposals the server rejected.
  // Resolves null when a Stop is already in flight.
  async function stop(): Promise<string[] | null> {
    if (stoppedRef.current) return null;
    stoppedRef.current = true;
    let runId = runIdRef.current;
    if (!runId && abortRef.current) {
      runId = await new Promise<string | null>((resolve) => {
        const t = setTimeout(() => {
          releaseHold();
          resolve(null);
        }, CANCEL_TIMEOUT_MS);
        holdRef.current = {
          onRun: (id) => {
            clearTimeout(t);
            resolve(id);
          },
        };
      });
    }
    // Bounded: a hung DB behind the cancel route must not pin "Stopping…" for ever.
    const cancelAc = new AbortController();
    const cancelTimer = setTimeout(() => cancelAc.abort(), CANCEL_TIMEOUT_MS);
    const cancel: Promise<string[]> = runId
      ? fetch(`/api/query-stream/${runId}/cancel`, {
          method: "POST",
          signal: cancelAc.signal,
        })
          .then((r) => (r.ok ? r.json() : { rejected: [] }))
          .then((d) => (Array.isArray(d.rejected) ? (d.rejected as string[]) : []))
          .catch(() => [])
          .finally(() => clearTimeout(cancelTimer))
      : Promise.resolve([]);
    if (!holdRef.current) abortRef.current?.abort(); // else released on the `thread` event
    return cancel;
  }

  // Leave the view: abort client-side only. Never calls the cancel route (D-06),
  // the run keeps going on the server.
  function detach() {
    genRef.current++;
    holdRef.current?.onRun(null);
    holdRef.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
    stoppedRef.current = false;
  }

  return { busyRef, runIdRef, stoppedRef, send, attach, stop, detach };
}

// ---- Answer lane (D-03, D-24) ------------------------------------------------
// Pure reducers over one assistant message's streamed state. The lane rule
// (Pitfall 14): narration streamed before a tool call is a working note, never
// the answer; only the `answer` event's text is final.

export type StepEntry = {
  kind: "step";
  callId: string | null;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done";
  startedAt: number | null;
  ms: number | null;
  sources: Source[];
  failed: boolean;
};
export type NoteEntry = { kind: "note"; iteration: number; text: string };
export type TimelineEntry = StepEntry | NoteEntry;
export type Lane = {
  draft: string;
  draftIteration: number | null;
  timeline: TimelineEntry[];
};
export const EMPTY_LANE: Lane = { draft: "", draftIteration: null, timeline: [] };

function draftToNote(lane: Lane, fallbackIteration: number): TimelineEntry[] {
  if (!lane.draft.trim()) return lane.timeline;
  return [
    ...lane.timeline,
    { kind: "note", iteration: lane.draftIteration ?? fallbackIteration, text: lane.draft },
  ];
}

export function laneAppend(lane: Lane, text: string, iteration: number): Lane {
  if (lane.draftIteration !== null && iteration > lane.draftIteration) {
    return { draft: text, draftIteration: iteration, timeline: draftToNote(lane, iteration) };
  }
  return { ...lane, draft: lane.draft + text, draftIteration: iteration };
}

export function laneToolStart(
  lane: Lane,
  ev: { call_id: string; tool: string; args: Record<string, unknown>; iteration: number },
  now: number
): Lane {
  const step: StepEntry = {
    kind: "step",
    callId: ev.call_id,
    tool: ev.tool,
    args: ev.args ?? {},
    status: "running",
    startedAt: now,
    ms: null,
    sources: [],
    failed: false,
  };
  return {
    draft: "",
    draftIteration: null,
    timeline: [...draftToNote(lane, ev.iteration), step],
  };
}

export function laneToolResult(
  lane: Lane,
  ev: {
    call_id?: string | null;
    step: { tool: string; args?: Record<string, unknown>; result?: unknown };
    ms?: number | null;
    sources?: Source[];
  }
): Lane {
  const result = ev.step.result;
  const failed = !!result && typeof result === "object" && "error" in (result as object);
  const done = {
    status: "done" as const,
    ms: typeof ev.ms === "number" ? ev.ms : null,
    sources: ev.sources ?? [],
    failed,
  };
  const idx = ev.call_id
    ? lane.timeline.findIndex(
        (e) => e.kind === "step" && e.callId === ev.call_id && e.status === "running"
      )
    : -1;
  if (idx >= 0) {
    const timeline = lane.timeline.slice();
    timeline[idx] = { ...(timeline[idx] as StepEntry), ...done };
    return { ...lane, timeline };
  }
  const step: StepEntry = {
    kind: "step",
    callId: ev.call_id ?? null,
    tool: ev.step.tool,
    args: ev.step.args ?? {},
    startedAt: null,
    ...done,
  };
  return { ...lane, timeline: [...lane.timeline, step] };
}

/** Persisted `parts.steps` to done steps; ms and sources only when stored (D-09). */
export function stepsFromParts(
  steps?: { tool: string; args?: Record<string, unknown>; ms?: number; sources?: Source[] }[]
): TimelineEntry[] {
  return (steps ?? []).map((s) => ({
    kind: "step",
    callId: null,
    tool: s.tool,
    args: s.args ?? {},
    status: "done",
    startedAt: null,
    ms: typeof s.ms === "number" ? s.ms : null,
    sources: s.sources ?? [],
    failed: false,
  }));
}

// ---- Token buffer (D-05) -----------------------------------------------------
// Deltas accumulate and flush at most every `delayMs` via setTimeout. Never an
// animation-frame timer: the hidden automated browser pane never runs those.

export function createTokenBuffer(
  onFlush: (text: string, iteration: number) => void,
  delayMs = 50
) {
  let text = "";
  let iteration: number | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clear() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }
  function flush() {
    clear();
    const t = text;
    const it = iteration;
    text = "";
    iteration = null;
    if (t && it !== null) onFlush(t, it);
  }
  return {
    push(delta: string, it: number) {
      if (iteration !== null && iteration !== it) flush();
      text += delta;
      iteration = it;
      if (timer === null) timer = setTimeout(flush, delayMs);
    },
    /** Return what is pending without calling onFlush. */
    take() {
      clear();
      const out = { text, iteration };
      text = "";
      iteration = null;
      return out;
    },
    cancel() {
      clear();
      text = "";
      iteration = null;
    },
  };
}

export function useTokenBuffer(
  onFlush: (text: string, iteration: number) => void,
  delayMs = 50
) {
  const flushRef = useRef(onFlush);
  flushRef.current = onFlush; // never call a stale closure
  const bufRef = useRef<ReturnType<typeof createTokenBuffer> | null>(null);
  if (bufRef.current === null) {
    bufRef.current = createTokenBuffer((t, i) => flushRef.current(t, i), delayMs);
  }
  useEffect(() => () => bufRef.current?.cancel(), []);
  return bufRef.current;
}
