"use client";

import { useSyncExternalStore } from "react";
import { tokens } from "../styles";

// Hide amounts, for when someone can see the screen (261121-fwp). One setting
// for the whole app, kept in this browser and mirrored onto <html> as
// data-hide-amounts: CSS blurs every `.amt` (globals.css) and RollingNumber
// rolls headline figures down to dots. AppShell applies the saved value on
// mount, before any page's data arrives, so real numbers never flash.
const KEY = "monai.hideAmounts";
const EVENT = "monai:hide-amounts";

export const MASK = "••••••";

function isHidden() {
  return document.documentElement.dataset.hideAmounts === "1";
}

function apply(hidden: boolean) {
  if (hidden) document.documentElement.dataset.hideAmounts = "1";
  else delete document.documentElement.dataset.hideAmounts;
  window.dispatchEvent(new Event(EVENT));
}

export function initHideAmounts() {
  try {
    apply(localStorage.getItem(KEY) === "1");
  } catch {
    // ignore (e.g. storage disabled)
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}

export function useHideAmounts(): [boolean, () => void] {
  const hidden = useSyncExternalStore(subscribe, isHidden, () => false);
  function toggle() {
    const next = !isHidden();
    apply(next);
    try {
      localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // ignore (e.g. storage disabled)
    }
  }
  return [hidden, toggle];
}

// Eye (amounts shown) or eye with a slash (hidden), on the dark hero card.
export function HideAmountsButton() {
  const [hidden, toggle] = useHideAmounts();
  return (
    <button
      type="button"
      className="tap44"
      aria-pressed={hidden}
      aria-label={hidden ? "Show amounts" : "Hide amounts"}
      title={hidden ? "Show amounts" : "Hide amounts"}
      onClick={toggle}
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
