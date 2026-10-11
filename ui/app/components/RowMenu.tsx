"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { tokens } from "../styles";

// ---------------------------------------------------------------------------
// RowMenu (quick 261011-mgj): the one per-row "⋯" options menu, lifted from the
// chat sidebar (261011-lfz). The caller supplies the full aria-label
// ("<Noun> options: <name>") and the items; RowMenu owns open state, focus
// handling and keyboard behaviour. Choosing an item closes the menu, refocuses
// the ⋯ button, THEN runs onSelect, so a ConfirmDialog opened by the item
// records the still-mounted ⋯ (not the unmounting menuitem) as its opener.
// ---------------------------------------------------------------------------

export type RowMenuItem = {
  label: string;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
  title?: string;
};

type Props = {
  label: string;
  items: RowMenuItem[];
  id?: string;
  className?: string;
};

const textBtn: CSSProperties = {
  background: "transparent",
  border: "none",
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 400,
  color: tokens.color.muted3,
  padding: 8,
  minHeight: 36,
};

export default function RowMenu({ label, items, id, className }: Props) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const btnId = id ?? `${uid}-btn`;
  const listId = `${uid}-list`;

  // Focus the first item on open; close on outside mousedown; Escape (capture
  // phase + stopPropagation, like ConfirmDialog) closes only the menu so the
  // mobile chat drawer's own Escape listener does not also fire.
  useEffect(() => {
    if (!open) return;
    wrapRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      btnRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <span
      ref={wrapRef}
      className={className}
      style={{
        display: "inline-flex",
        flexShrink: 0,
        position: "relative",
        ...(open ? { opacity: 1 } : null),
      }}
    >
      <button
        ref={btnRef}
        type="button"
        id={btnId}
        style={{ ...textBtn, fontSize: 16, lineHeight: 1, padding: "8px 10px" }}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {open && (
        /* ponytail: absolute inside the row, so in a scrolling container (chat sidebar) a menu on the last row extends the scroll area; switch to a portal + fixed position if it ever clips. */
        <div
          role="menu"
          id={listId}
          aria-labelledby={btnId}
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            zIndex: 10,
            minWidth: 120,
            background: tokens.color.card,
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: tokens.radius.sm,
            boxShadow: tokens.shadow.card,
            padding: 4,
            whiteSpace: "nowrap",
          }}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              setOpen(false);
              return;
            }
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            const els = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
            const i = els.indexOf(document.activeElement as HTMLElement);
            const step = e.key === "ArrowDown" ? 1 : -1;
            els[(i + step + els.length) % els.length]?.focus();
          }}
        >
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              tabIndex={-1}
              title={it.title}
              aria-disabled={it.disabled ? true : undefined}
              style={{
                ...textBtn,
                display: "block",
                width: "100%",
                textAlign: "left",
                fontSize: 14,
                borderRadius: tokens.radius.sm,
                color: it.disabled
                  ? tokens.color.muted2
                  : it.destructive
                    ? tokens.color.terracotta
                    : tokens.color.ink,
                ...(it.disabled ? { cursor: "not-allowed" } : null),
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (it.disabled) return;
                setOpen(false);
                btnRef.current?.focus();
                it.onSelect();
              }}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
