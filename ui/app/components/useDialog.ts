"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

// Modal dialog keyboard behaviour, lifted from ConfirmDialog (Phase 36, WR-09)
// so every modal shares it (design review 2026-11-21 F002): focus moves inside
// on open (`initialFocus`, else the first field, else the first button), Escape
// calls `onClose` and is consumed in the capture phase so a drawer behind does
// not also close, Tab wraps inside, and focus returns to the opener on close.
// Pass `onClose` as null while a save is in flight to ignore Escape.

// Open dialogs, innermost last: only the top one answers Escape and Tab, so a
// ConfirmDialog over a modal closes alone. All listeners sit on document in the
// capture phase, where stopPropagation cannot keep the outer one from firing.
const open: object[] = [];

const FOCUSABLE =
  "button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href]";

export default function useDialog(
  dialogRef: RefObject<HTMLElement>,
  onClose: (() => void) | null,
  initialFocus?: RefObject<HTMLElement>
) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const me = {};
    open.push(me);
    const opener = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    const first =
      initialFocus?.current ??
      root?.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), textarea:not([disabled])") ??
      root?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (open[open.length - 1] !== me) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current?.();
      } else if (e.key === "Tab") {
        const items = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (!items || items.length === 0) return;
        const head = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (!dialogRef.current?.contains(active)) {
          e.preventDefault();
          head.focus();
        } else if (e.shiftKey && active === head) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          head.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      open.splice(open.indexOf(me), 1);
      if (opener && opener.isConnected) opener.focus();
    };
    // Mount-only: the dialog's lifetime is the effect's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
