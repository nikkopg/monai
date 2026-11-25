"use client";

import { useEffect, useState } from "react";
import { MASK, useHideAmounts } from "./HideAmounts";

// ---------------------------------------------------------------------------
// RollingNumber — a scoreboard-style figure: each digit is a 0–9 strip that
// rolls up or down to its new digit (globals.css .roll-digit). It rolls from
// 0 on first show and from the old digits when the value changes. Only for a
// card's headline figure; lists stay static.
//
// The strips are drawn with ::before content, so the DOM text is just the
// screen-reader copy of the formatted value (`.sr-only`) — tests and assistive
// tech read "1,234,567", never "0123456789". Digits are keyed from the
// right so the units digit keeps its strip when the number gains a digit.
// prefers-reduced-motion turns the transition off (globals.css).
//
// Hide amounts (261121-fwp), for the hero figures that pass `hideable`:
// hiding rolls every digit down to 0 while the figure fades out, then the dots
// fade in; showing rolls up from 0 as on first show. The real value never
// reaches the DOM while hidden.
// ---------------------------------------------------------------------------

// How long hiding rolls and fades before the dots replace the figure: the
// .roll[data-hiding] opacity transition in globals.css. The digit roll itself
// is 0.8s ease-out, so it is mostly done by then.
const HIDE_MS = 500;

export default function RollingNumber({
  value,
  format,
  hideable = false,
}: {
  value: number;
  format: (n: number) => string;
  hideable?: boolean;
}) {
  const [hideAmounts] = useHideAmounts();
  const hidden = hideable && hideAmounts;
  const [masked, setMasked] = useState(hidden);
  // First paint shows every strip at 0; the next frame moves them, so the
  // initial roll (and the roll back after hiding) is a real transition.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (hidden) {
      const instant =
        document.visibilityState === "hidden" || matchMedia("(prefers-reduced-motion: reduce)").matches;
      const t = setTimeout(() => {
        setMasked(true);
        // So the next show starts its strips at 0 and rolls up.
        setReady(false);
      }, instant ? 0 : HIDE_MS);
      return () => clearTimeout(t);
    }
    setMasked(false);
    const id = requestAnimationFrame(() => setReady(true));
    // A hidden tab never fires rAF: show the value rather than zeros.
    if (document.visibilityState === "hidden") setReady(true);
    return () => cancelAnimationFrame(id);
  }, [hidden]);

  if (masked && hidden) {
    return (
      <span className="roll roll-mask">
        <span className="sr-only">Hidden amount</span>
        <span aria-hidden="true">{MASK}</span>
      </span>
    );
  }

  const text = format(value);
  const chars = Array.from(text);
  return (
    <span className="roll" data-hiding={hidden || undefined}>
      <span className="sr-only">{hidden ? "Hidden amount" : text}</span>
      <span aria-hidden="true">
        {chars.map((c, i) => {
          const key = chars.length - i;
          return /\d/.test(c) ? (
            <span
              key={key}
              className="roll-digit"
              data-d={hidden ? "0" : c}
              style={{ "--d": ready && !hidden ? Number(c) : 0 } as React.CSSProperties}
            />
          ) : (
            <span key={key} className="roll-char" data-c={c} />
          );
        })}
      </span>
    </span>
  );
}
