"use client";

import { useEffect, useRef, useState } from "react";

import { tokens } from "../styles";

// ---------------------------------------------------------------------------
// ServersMenu (41-UI-SPEC B1, D-12, PC-03): the composer's per-chat choice of
// external MCP servers. An existing thread PUTs the full set on every tick; a new
// thread only reports the choice (the page sends it as mcp_server_ids on the
// first question). On a thread with a document the toggle is aria-disabled with
// a visible reason (39 D-16). Every server string is a React text node.
// ---------------------------------------------------------------------------

export type MenuServer = {
  id: string;
  slug: string;
  transport: string;
  destination: string;
  changed_count: number | null;
};

const TRANSPORT: Record<string, string> = { http: "Streamable HTTP", sse: "SSE", stdio: "Local command" };
const REASON = "This chat has a document, so external servers can't be used here. Start a new chat for those.";

const body14: React.CSSProperties = { fontSize: 14, lineHeight: 1.5, color: tokens.color.muted3, margin: 0 };

export default function ServersMenu({
  servers,
  selected,
  threadId,
  attachmentThread,
  onChange,
}: {
  servers: MenuServer[];
  selected: string[];
  threadId: string | null;
  attachmentThread: boolean;
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const toggleRef = useRef<HTMLButtonElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);

  // Switching threads closes the panel and clears the last result.
  useEffect(() => {
    setOpen(false);
    setStatus("");
  }, [threadId]);

  useEffect(() => {
    if (open) firstRef.current?.focus();
  }, [open]);

  if (servers.length === 0) return null;

  const sorted = [...servers].sort((a, b) => a.slug.localeCompare(b.slug));
  const on = sorted.filter((s) => selected.includes(s.id)).map((s) => s.slug);
  const summary =
    on.length === 0
      ? "No servers on for this chat."
      : `On for this chat: ${on.slice(0, 3).join(", ")}${on.length > 3 ? ` and ${on.length - 3} more` : ""}`;

  function close() {
    setOpen(false);
    toggleRef.current?.focus();
  }

  async function tick(id: string, checked: boolean) {
    if (saving) return;
    const next = checked ? [...selected, id] : selected.filter((x) => x !== id);
    if (threadId === null) {
      onChange(next);
      return;
    }
    setSaving(true);
    setStatus("Saving…");
    try {
      const r = await fetch(`/api/threads/${threadId}/mcp-servers`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ server_ids: next }),
      });
      if (r.ok) {
        onChange(next);
        setStatus("Servers for this chat updated.");
      } else {
        const d = await r.json().catch(() => ({}));
        const detail = typeof d?.detail === "string" ? d.detail : `HTTP ${r.status}`;
        setStatus(`Couldn't update servers: ${detail}. Your previous choice is unchanged.`);
      }
    } catch {
      setStatus("Couldn't update servers: Network error. Your previous choice is unchanged.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, fontFamily: tokens.font.sans }}>
      {open && !attachmentThread && (
        <div
          id="servers-panel"
          data-testid="servers-panel"
          role="group"
          aria-labelledby="servers-heading"
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
          }}
          style={{
            background: tokens.color.card,
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: tokens.radius.md,
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 16,
            maxHeight: "min(60vh, 420px)",
            overflowY: "auto",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 id="servers-heading" style={{ margin: 0, fontSize: 16, fontWeight: 600, lineHeight: 1.4, color: tokens.color.ink }}>
              Servers for this chat
            </h2>
            <button
              type="button"
              className="coarse-tap"
              onClick={close}
              style={{ background: "transparent", border: "none", fontFamily: "inherit", fontSize: 14, minHeight: 36, cursor: "pointer", padding: "0 4px", color: tokens.color.muted3 }}
            >
              Close
            </button>
          </div>

          {sorted.map((s, i) => (
            <label key={s.id} style={{ display: "flex", gap: 8, minHeight: 36, alignItems: "flex-start" }}>
              <input
                ref={i === 0 ? firstRef : undefined}
                type="checkbox"
                data-testid="servers-option"
                data-server={s.slug}
                checked={selected.includes(s.id)}
                aria-disabled={saving}
                onChange={(e) => void tick(s.id, e.target.checked)}
                style={{ width: 20, height: 20, margin: "8px 0 0" }}
              />
              <span style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{s.slug}</span>
                <span style={{ ...body14, overflowWrap: "anywhere" }}>
                  {TRANSPORT[s.transport] ?? s.transport} · {s.destination}
                </span>
                {(s.changed_count ?? 0) > 0 && (
                  <span style={body14}>Some of its tools are held back until you review them in Settings.</span>
                )}
              </span>
            </label>
          ))}

          <span style={{ fontSize: 12, color: tokens.color.muted3 }}>
            Changes apply from your next question. Every tool still asks before it runs unless you set it to Always in Settings.
          </span>
          <div role="status" aria-live="polite" data-testid="servers-status" style={body14}>
            {threadId === null ? "" : status}
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <button
          ref={toggleRef}
          type="button"
          id="servers-toggle"
          data-testid="servers-toggle"
          className="coarse-tap"
          aria-label="Servers for this chat"
          aria-expanded={open && !attachmentThread}
          aria-controls="servers-panel"
          {...(attachmentThread ? { "aria-disabled": true as const, "aria-describedby": "servers-reason" } : {})}
          onClick={() => {
            if (attachmentThread) return;
            if (open) close();
            else setOpen(true);
          }}
          style={{
            background: tokens.color.sidebar,
            color: attachmentThread ? tokens.color.muted3 : tokens.color.ink,
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: 14,
            padding: "0 16px",
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "inherit",
            minHeight: 36,
            cursor: attachmentThread ? "not-allowed" : "pointer",
            opacity: attachmentThread ? 0.6 : 1,
          }}
        >
          Servers{on.length > 0 && !attachmentThread ? ` (${on.length})` : ""}
        </button>
        {attachmentThread ? (
          <span id="servers-reason" data-testid="servers-reason" style={body14}>
            {REASON}
          </span>
        ) : (
          <span id="servers-summary" data-testid="servers-summary" style={body14}>
            {summary}
          </span>
        )}
      </div>
    </div>
  );
}
