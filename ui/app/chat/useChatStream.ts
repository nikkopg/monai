"use client";

import { useRef } from "react";

import { CANCEL_TIMEOUT_MS } from "./errors";

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
      if (m.type === "run" && typeof m.run_id === "string") runIdRef.current = m.run_id;
      onEvent(m);
    };
    const settle = (kind: "done" | "ended" | "error"): StreamOutcome =>
      stale() ? { kind: "stale" } : stoppedRef.current ? { kind: "stopped" } : { kind };
    try {
      const resp = await fetch(url, { ...init, signal: ac.signal });
      if (allowNone && resp.status === 204) return stale() ? { kind: "stale" } : { kind: "none" };
      // Never read or show `detail` (D-02): the caller maps the status alone.
      if (!resp.ok || !resp.body) return stale() ? { kind: "stale" } : { kind: "status", status: resp.status };
      const r = await readSse(resp, wrapped, () => stoppedRef.current || stale());
      return settle(r);
    } catch {
      return settle("error");
    } finally {
      // Only the invocation that still owns the shared refs may clear them.
      if (!stale()) {
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
    const runId = runIdRef.current;
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
    abortRef.current?.abort();
    return cancel;
  }

  // Leave the view: abort client-side only. Never calls the cancel route (D-06),
  // the run keeps going on the server.
  function detach() {
    genRef.current++;
    abortRef.current?.abort();
    abortRef.current = null;
    busyRef.current = false;
    stoppedRef.current = false;
  }

  return { busyRef, runIdRef, stoppedRef, send, attach, stop, detach };
}
