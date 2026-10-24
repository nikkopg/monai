"use client";

import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

import { card, dangerBtn } from "../styles";

// ---------------------------------------------------------------------------
// ConfirmDialog — small reusable modal for destructive confirmations (D-03).
// No analog in the existing codebase (first modal/overlay) — built from
// `card` + `dangerBtn`. Reused for: delete transaction, delete account (both
// the plain-delete and reassign-then-delete branches), and merge category.
// NOT used for category rename (non-destructive, no dialog per UI-SPEC).
//
// The optional `children` slot lets AccountManager inject a destination
// `<select>` when the delete attempt comes back 422 (reassign-then-delete,
// D-06) — the dialog's message + confirm button stay the same shape, only
// the body content between message and buttons changes.
// ---------------------------------------------------------------------------

type Props = {
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

export default function ConfirmDialog({
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  children,
}: Props) {
  const msgId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  // Dialog a11y (Phase 36): initial focus on Cancel, Escape cancels, focus
  // returns to whatever opened the dialog if it is still in the document, Tab
  // wraps inside the dialog (WR-09), and Escape is consumed here (capture phase)
  // so a drawer's own Escape listener behind it does not also fire.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancelRef.current();
      } else if (e.key === "Tab") {
        const items = dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href]"
        );
        if (!items || items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (!dialogRef.current?.contains(active)) {
          e.preventDefault();
          first.focus();
        } else if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (opener && opener.isConnected) opener.focus();
    };
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      ref={dialogRef}
      aria-labelledby={msgId}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,17,21,0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
      }}
      onClick={onCancel}
    >
      <div
        style={{ ...card, maxWidth: 360, width: "100%", padding: 24, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <p id={msgId} style={{ fontSize: 14, fontWeight: 400, margin: "0 0 16px", color: "#23201b" }}>
          {message}
        </p>
        {children && <div style={{ marginBottom: 16 }}>{children}</div>}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            style={{
              background: "transparent",
              color: "#6f6857",
              border: "none",
              padding: "8px 16px",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {cancelLabel}
          </button>
          <button type="button" style={dangerBtn} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
