"use client";

import { useEffect, useState } from "react";

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
// ---------------------------------------------------------------------------

export default function RollingNumber({
  value,
  format,
}: {
  value: number;
  format: (n: number) => string;
}) {
  const text = format(value);
  // First paint shows every strip at 0; the next frame moves them, so the
  // initial roll is a real transition.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    // A hidden tab never fires rAF: show the value rather than zeros.
    if (document.visibilityState === "hidden") setReady(true);
    return () => cancelAnimationFrame(id);
  }, []);

  const chars = Array.from(text);
  return (
    <span className="roll">
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {chars.map((c, i) => {
          const key = chars.length - i;
          return /\d/.test(c) ? (
            <span
              key={key}
              className="roll-digit"
              data-d={c}
              style={{ "--d": ready ? Number(c) : 0 } as React.CSSProperties}
            />
          ) : (
            <span key={key} className="roll-char" data-c={c} />
          );
        })}
      </span>
    </span>
  );
}
