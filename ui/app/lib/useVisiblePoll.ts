"use client";

// ---------------------------------------------------------------------------
// useVisiblePoll — one poller for the Inbox list (10 s) and the Nav counts
// (30 s). Enforces the UI-SPEC poll-hygiene contract:
//   1. one request in flight; a trigger while pending is a no-op, never queued
//   2. aborted on unmount, and nothing is set after unmount
//   3. paused while document.visibilityState is "hidden" (in-flight request
//      aborted); fetches immediately on return to visible
//   4. 8 s per-request timeout, counted as a failure
//   5. failures back off intervalMs*2^n up to maxIntervalMs (10 -> 20 -> 40 ->
//      60 s); offline after 2 consecutive failures or a window "offline"
//      event; window "online" retries at once; success resets everything
//   6. data already on screen is never cleared by a failed poll (the hook only
//      calls onData on success)
//   7. nothing polls in the automated browser pane (it reports "hidden")
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useRef, useState } from "react";

export type VisiblePollOptions<T> = {
  url: string;
  intervalMs: number;
  /** Return null to treat the response as a failed poll. */
  parse: (json: unknown) => T | null;
  onData: (data: T, dateHeader: string | null) => void;
  headers?: Record<string, string>;
  timeoutMs?: number;
  maxIntervalMs?: number;
};

export function useVisiblePoll<T>(opts: VisiblePollOptions<T>): {
  offline: boolean;
  failures: number;
  lastSuccessAt: number | null;
  refetchNow: () => void;
} {
  // Latest options live in a ref so changing callbacks never restart the poller.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const [failures, setFailures] = useState(0);
  const [browserOffline, setBrowserOffline] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const refetchRef = useRef<() => void>(() => {});

  const { url, intervalMs } = opts;

  useEffect(() => {
    // Per-effect locals: a StrictMode remount starts from scratch.
    let mounted = true;
    let inFlight = false;
    let failureCount = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;

    const isHidden = () => document.visibilityState === "hidden";
    const clearTimer = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    };

    const schedule = () => {
      clearTimer();
      if (!mounted || isHidden()) return;
      const { maxIntervalMs = 60_000 } = optsRef.current;
      const delay =
        failureCount === 0
          ? intervalMs
          : Math.min(intervalMs * 2 ** failureCount, maxIntervalMs);
      timer = setTimeout(run, delay);
    };

    async function run() {
      if (!mounted || inFlight || isHidden()) return;
      clearTimer();
      inFlight = true;
      const { timeoutMs = 8_000 } = optsRef.current;
      const ctrl = new AbortController();
      controller = ctrl;
      let timedOut = false;
      const timeout = setTimeout(() => {
        timedOut = true;
        ctrl.abort();
      }, timeoutMs);

      let ok = false;
      try {
        const res = await fetch(url, {
          signal: ctrl.signal,
          cache: "no-store",
          headers: optsRef.current.headers,
        });
        if (res.ok) {
          const parsed = optsRef.current.parse(await res.json());
          if (parsed !== null && mounted) {
            optsRef.current.onData(parsed, res.headers.get("date"));
            ok = true;
          }
        }
      } catch {
        // network error, JSON error, or abort: classified below
      } finally {
        clearTimeout(timeout);
        inFlight = false;
        controller = null;
      }

      // Abort by unmount or by the tab going hidden is not a failure.
      if (!mounted || (ctrl.signal.aborted && !timedOut)) return;

      if (ok) {
        failureCount = 0;
        setFailures(0);
        setBrowserOffline(false);
        setLastSuccessAt(Date.now());
      } else {
        failureCount += 1;
        setFailures(failureCount);
      }
      schedule();
    }

    const onVisibility = () => {
      if (isHidden()) {
        clearTimer();
        controller?.abort();
      } else {
        void run();
      }
    };
    const onOffline = () => setBrowserOffline(true);
    const onOnline = () => {
      clearTimer();
      void run();
    };

    refetchRef.current = () => {
      clearTimer();
      void run();
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    void run();

    return () => {
      mounted = false;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, [url, intervalMs]);

  const refetchNow = useCallback(() => refetchRef.current(), []);

  return {
    offline: failures >= 2 || browserOffline,
    failures,
    lastSuccessAt,
    refetchNow,
  };
}
