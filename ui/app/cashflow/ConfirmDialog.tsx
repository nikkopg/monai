"use client";

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
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

export default function ConfirmDialog({
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  children,
}: Props) {
  return (
    <div
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
        <p style={{ fontSize: 14, fontWeight: 400, margin: "0 0 16px", color: "#23201b" }}>
          {message}
        </p>
        {children && <div style={{ marginBottom: 16 }}>{children}</div>}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              background: "transparent",
              color: "#8b8474",
              border: "none",
              padding: "8px 16px",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button type="button" style={dangerBtn} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
