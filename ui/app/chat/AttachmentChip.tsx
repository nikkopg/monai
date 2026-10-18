"use client";

import { tokens } from "../styles";
import { PURGED_SUFFIX, PURGED_TITLE, chipText, pillStatus, type AttachChip, type ChipTone } from "./attachLabels";

// ---------------------------------------------------------------------------
// Tray chips (before Ask) and read-only pills (under the sent user bubble),
// 39-UI-SPEC sections 3 and 4. State is carried by words; fill and rule only
// reinforce. Every server string is a React text node.
// ---------------------------------------------------------------------------

const toneStyle: Record<ChipTone, React.CSSProperties> = {
  plain: { background: tokens.color.card },
  warm: { background: tokens.color.tintWarm, borderLeft: `3px solid ${tokens.color.border2}` },
  refused: { background: tokens.color.tintWarm, borderLeft: `3px solid ${tokens.color.terracotta}` },
};

const list: React.CSSProperties = { listStyle: "none", padding: 0, margin: 0, display: "flex", flexWrap: "wrap", gap: 8 };

const cut = (s: string) => (s.length > 200 ? s.slice(0, 199) + "…" : s);

const nameStyle: React.CSSProperties = {
  fontWeight: 600,
  color: tokens.color.ink,
  display: "inline-block",
  maxWidth: "28ch",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  verticalAlign: "bottom",
};

const purgedNote = (
  <span title={PURGED_TITLE} style={{ color: tokens.color.muted3, fontWeight: 400 }}>
    {PURGED_SUFFIX}
  </span>
);

export function AttachmentTray({ chips, onRemove }: { chips: AttachChip[]; onRemove: (localId: string) => void }) {
  if (chips.length === 0) return null;
  return (
    <ul aria-label="Attachments" data-testid="attach-tray" style={list}>
      {chips.map((c) => {
        const t = chipText(c);
        return (
          <li
            key={c.localId}
            data-testid="attach-chip"
            style={{
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: tokens.radius.md,
              padding: "8px 12px",
              maxWidth: "100%",
              display: "flex",
              alignItems: "flex-start",
              gap: 8,
              fontSize: 14,
              lineHeight: 1.5,
              color: tokens.color.ink,
              ...toneStyle[t.tone],
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div>
                <span title={c.filename} style={nameStyle}>{c.filename}</span>
                {" · "}
                {t.status}
                {t.purged && purgedNote}
              </div>
              {t.detail && (
                <div title={t.detail} style={{ color: tokens.color.muted3, overflowWrap: "anywhere" }}>
                  {cut(t.detail)}
                </div>
              )}
            </div>
            <button
              type="button"
              data-testid="attach-chip-remove"
              className="coarse-tap"
              aria-label={`Remove ${c.filename} from your question`}
              onClick={() => onRemove(c.localId)}
              style={{
                width: 32,
                height: 32,
                background: "transparent",
                border: "none",
                color: tokens.color.muted3,
                fontSize: 14,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <span aria-hidden="true">×</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function MessageAttachments({ items }: { items: AttachChip[] }) {
  if (items.length === 0) return null;
  return (
    <ul aria-label="Attachments" style={{ ...list, justifyContent: "flex-end", marginTop: 8 }}>
      {items.map((c) => (
        <li
          key={c.localId}
          data-testid="message-attachment"
          style={{
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: tokens.radius.pill,
            padding: "4px 12px",
            fontSize: 14,
            lineHeight: 1.5,
            color: tokens.color.ink,
            fontVariantNumeric: "tabular-nums",
            ...toneStyle[chipText(c).tone],
          }}
        >
          <span title={c.filename} style={nameStyle}>{c.filename}</span>
          {" · "}
          {pillStatus(c)}
          {c.purgedAt !== null && purgedNote}
        </li>
      ))}
    </ul>
  );
}
