"use client";

import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// CountUp — a number that rolls to its value: from 0 on first show, then from
// the previous value when it changes (switching period or range). Only for a
// card's headline figure; lists stay static. It shows the final value at once
// when the viewer asks for reduced motion, or in a hidden tab (the automated
// browser pane), where requestAnimationFrame never fires and the number would
// otherwise stay stuck mid-roll.
// ---------------------------------------------------------------------------

const DURATION_MS = 700;
const easeOut = (t: number) => 1 - (1 - t) ** 3;

function skipMotion(): boolean {
  if (typeof window === "undefined") return true;
  if (document.visibilityState === "hidden") return true;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

export default function CountUp({
  value,
  format,
}: {
  value: number;
  format: (n: number) => string;
}) {
  const [shown, setShown] = useState(value);
  const from = useRef(0);

  useEffect(() => {
    const start = from.current;
    from.current = value;
    if (skipMotion() || start === value) {
      setShown(value);
      return;
    }
    setShown(start); // no one-frame flash of the final value
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / DURATION_MS);
      setShown(t === 1 ? value : start + (value - start) * easeOut(t));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <>{format(shown)}</>;
}
