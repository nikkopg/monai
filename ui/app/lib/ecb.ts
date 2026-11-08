"use client";

// The ECB rate of a day for the implied-vs-ECB line (Phase 45, D-09). The only
// source is GET /api/fx/rate, a cache-only backend route: the browser never
// calls the FX vendor and never guesses a rate. A missing rate or a failed
// request is "none", which the line renders as "ECB rate unavailable".
import { useEffect, useState } from "react";

export type EcbRate = { status: "loading" | "ok" | "none"; rate?: number; rateDate?: string };

// One request per currency and day, however many cards ask. Only resolved
// rates are kept, so a failure is retried on the next mount.
const memo = new Map<string, EcbRate>();

export function useEcbRate(currency: string, isoDate: string | null, enabled = true): EcbRate {
  const on = enabled && isoDate && /^\d{4}-\d{2}-\d{2}$/.test(isoDate) ? isoDate : null;
  const key = `${currency}:${on}`;
  const [fetched, setFetched] = useState<{ key: string; value: EcbRate } | null>(null);

  useEffect(() => {
    if (!on || memo.has(key)) return;
    const ctl = new AbortController();
    (async () => {
      let value: EcbRate = { status: "none" };
      try {
        const r = await fetch(`/api/fx/rate?currency=${encodeURIComponent(currency)}&on=${on}`, {
          signal: ctl.signal,
        });
        if (r.ok) {
          const j = await r.json();
          const rate = j?.rate == null ? NaN : Number(j.rate);
          if (Number.isFinite(rate) && j.rate_date) {
            value = { status: "ok", rate, rateDate: String(j.rate_date) };
            memo.set(key, value);
          }
        }
      } catch {
        // aborted or offline: stays "none"
      }
      if (!ctl.signal.aborted) setFetched({ key, value });
    })();
    return () => ctl.abort();
  }, [key, on, currency]);

  if (!on) return { status: "none" };
  const hit = memo.get(key);
  if (hit) return hit;
  return fetched?.key === key ? fetched.value : { status: "loading" };
}
