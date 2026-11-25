"use client";

import { useId, useRef } from "react";
import type { ReactNode } from "react";

import useDialog from "../components/useDialog";
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
// the body content between message and buttons changes. `confirmDisabled`
// (default false) greys out the confirm button when there is nothing to confirm.
// ---------------------------------------------------------------------------

type Props = {
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  confirmDisabled?: boolean;
};

export default function ConfirmDialog({
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  children,
  confirmDisabled = false,
}: Props) {
  const msgId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Dialog a11y (Phase 36): initial focus on Cancel, Escape cancels, Tab wraps,
  // focus returns to the opener. Shared with every modal via useDialog.
  useDialog(dialogRef, onCancel, cancelRef);

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
        <p id={msgId} style={{ fontSize: "var(--fs-body, 14px)", fontWeight: 400, margin: "0 0 16px", color: "#23201b" }}>
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
              fontSize: "var(--fs-body, 14px)",
              cursor: "pointer",
            }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            style={confirmDisabled ? { ...dangerBtn, opacity: 0.5, cursor: "not-allowed" } : dangerBtn}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
