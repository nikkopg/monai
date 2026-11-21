"use client";

import { useEffect, useState } from "react";
import { tokens } from "../styles";

// Hide amounts on the hero cards (Overview net worth, Investments total value)
// for when someone can see the screen. One preference for both cards, kept in
// this browser. It is read in a mount effect, which runs before either card's
// data arrives, so the real numbers never flash. Percentages stay visible.
const KEY = "monai.hideAmounts";

export const MASK = "••••••";

export function useHideAmounts(): [boolean, () => void] {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    try {
      setHidden(localStorage.getItem(KEY) === "1");
    } catch {
      // ignore (e.g. storage disabled)
    }
  }, []);
  function toggle() {
    const next = !hidden;
    setHidden(next);
    try {
      localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // ignore (e.g. storage disabled)
    }
  }
  return [hidden, toggle];
}

// Eye (amounts shown) or eye with a slash (hidden), on the dark hero card.
export function HideAmountsButton({ hidden, onToggle }: { hidden: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="tap44"
      aria-pressed={hidden}
      aria-label={hidden ? "Show amounts" : "Hide amounts"}
      title={hidden ? "Show amounts" : "Hide amounts"}
      onClick={onToggle}
      style={{
        display: "inline-flex",
        alignItems: "center",
        background: "transparent",
        border: "none",
        padding: 2,
        color: tokens.color.inkTextMuted,
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
        <circle cx="12" cy="12" r="3" />
        {hidden && <path d="M4 4l16 16" />}
      </svg>
    </button>
  );
}
