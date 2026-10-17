"use client";

import { useEffect, useId, useRef, useState } from "react";

import { tokens } from "../styles";

// ---------------------------------------------------------------------------
// MessageActions (37-08, 37-UI-SPEC section 5): Copy, Regenerate and Edit under a
// message. Disabled Regenerate / Edit use aria-disabled + a role="tooltip" sibling
// (never the native attribute) so the reason stays reachable by keyboard.
// ---------------------------------------------------------------------------

/** D-17: clipboard API first, off-screen textarea + execCommand as the fallback. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // fall through to the textarea path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.readOnly = true;
    ta.setAttribute("aria-hidden", "true");
    ta.style.cssText = "position:fixed;top:0;left:-9999px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

type Props = {
  copyText?: string; // completed answer's markdown source
  questionText?: string; // user message text (Edit's accessible name)
  onRegenerate?: () => void;
  onEdit?: () => void;
  disabledReason?: string | null;
  alwaysVisible?: boolean;
  error?: string | null;
  onAnnounce?: (text: string) => void;
  editRef?: (el: HTMLButtonElement | null) => void;
};

const btnStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  color: tokens.color.muted3,
  fontSize: 12,
  fontWeight: 400,
  padding: "8px 12px",
  minHeight: 36,
  cursor: "pointer",
  fontFamily: "inherit",
};

export default function MessageActions(props: Props) {
  const tipId = useId();
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function onCopy() {
    const ok = await copyText(props.copyText ?? "");
    setCopyState(ok ? "copied" : "failed");
    props.onAnnounce?.(ok ? "Answer copied." : "Couldn't copy the answer.");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopyState("idle"), 2000);
  }

  const reason = props.disabledReason ?? null;
  const disabledProps = reason
    ? { "aria-disabled": true as const, "aria-describedby": tipId }
    : {};
  const disabledStyle: React.CSSProperties = reason
    ? { opacity: 0.6, cursor: "not-allowed" }
    : {};
  // Regenerate and Edit never sit in the same row, so one tooltip id is enough.
  const guard = (fn?: () => void) => () => {
    if (!reason) fn?.();
  };

  const tooltip = reason && (
    <span
      role="tooltip"
      id={tipId}
      className="action-tooltip"
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border2}`,
        borderRadius: tokens.radius.sm,
        boxShadow: tokens.shadow.card,
        padding: "8px 12px",
        fontSize: 14,
        color: tokens.color.ink,
        maxWidth: 280,
        width: "max-content",
        zIndex: 20,
      }}
    >
      {reason}
    </span>
  );

  const hasCopy = typeof props.copyText === "string" && props.copyText !== "";
  if (!hasCopy && !props.onRegenerate && !props.onEdit) return null;

  return (
    <div>
      <div
        data-testid="message-actions"
        className={"message-actions" + (props.alwaysVisible ? " always-visible" : "")}
        style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
      >
        {hasCopy && (
          <button
            type="button"
            aria-label="Copy answer"
            className="coarse-tap action-btn"
            style={btnStyle}
            onClick={() => void onCopy()}
          >
            {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
          </button>
        )}
        {props.onRegenerate && (
          <span className="action-wrap" style={{ position: "relative" }}>
            <button
              type="button"
              aria-label="Regenerate answer"
              className="coarse-tap action-btn"
              style={{ ...btnStyle, ...disabledStyle }}
              {...disabledProps}
              onClick={guard(props.onRegenerate)}
            >
              Regenerate
            </button>
            {tooltip}
          </span>
        )}
        {props.onEdit && (
          <span className="action-wrap" style={{ position: "relative" }}>
            <button
              type="button"
              ref={props.editRef}
              aria-label={`Edit question: ${(props.questionText ?? "").slice(0, 40)}`}
              className="coarse-tap action-btn"
              style={{ ...btnStyle, ...disabledStyle }}
              {...disabledProps}
              onClick={guard(props.onEdit)}
            >
              Edit
            </button>
            {tooltip}
          </span>
        )}
      </div>
      {props.error && (
        <div
          role="alert"
          style={{ fontSize: 12, color: tokens.color.terracottaText, padding: "0 12px" }}
        >
          {props.error}
        </div>
      )}
    </div>
  );
}
