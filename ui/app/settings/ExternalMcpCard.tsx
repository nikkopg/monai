"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, card, dangerBtn } from "../styles";
import McpServerForm, { UnpinnedWarning } from "./McpServerForm";
import McpToolReview from "./McpToolReview";
import {
  type McpServer,
  TRANSPORT_LABEL,
  commandLine,
  body14,
  small,
  errText,
  rowBtn,
  chipBase,
  chipNeutral,
  chipWarm,
  warmBox,
  errDetail,
  serverUrl,
  putJson,
} from "./mcpShared";

// ---------------------------------------------------------------------------
// Settings "External MCP servers" card (phase 41, plan 09; contract:
// 41-UI-SPEC.md section A, D-04, D-09, A-01). Lists servers with a state in
// words, opens ONE inline panel at a time under a row (add / edit form, tool
// review, delete confirmation). Every server-supplied string is a React text
// node; secrets are masked by the server and live only in the form.
// ---------------------------------------------------------------------------

type Panel = { kind: "add" } | { kind: "edit" | "review" | "delete"; slug: string };

export default function ExternalMcpCard() {
  const [rows, setRows] = useState<McpServer[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [rowErr, setRowErr] = useState<Record<string, string>>({});
  const [disabling, setDisabling] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteErr, setDeleteErr] = useState("");

  const addBtn = useRef<HTMLButtonElement>(null);
  const keepBtn = useRef<HTMLButtonElement>(null);
  const btns = useRef(new Map<string, HTMLButtonElement>()); // "test:slug" | "edit:slug" | "delete:slug"
  const pending = useRef<(() => boolean) | null>(null);

  async function loadList(): Promise<void> {
    try {
      const r = await fetch("/api/mcp-servers");
      if (!r.ok) {
        setListError(await errDetail(r));
        return;
      }
      setRows(await r.json());
      setListError(null);
    } catch {
      setListError("Network error");
    }
  }

  useEffect(() => {
    void loadList();
  }, []);

  // Hand focus on once its target exists (the refreshed list may not have rendered yet).
  useEffect(() => {
    if (pending.current?.()) pending.current = null;
  });

  // Delete confirmation opens on the safe choice.
  useEffect(() => {
    if (panel?.kind === "delete") keepBtn.current?.focus();
  }, [panel]);

  const focusBtn = (k: string) => {
    pending.current = () => {
      const el = btns.current.get(k);
      el?.focus();
      return !!el;
    };
  };
  const focusAdd = () => {
    pending.current = () => {
      addBtn.current?.focus();
      return true;
    };
  };

  /** Close the open panel and hand focus back to the button that opened it. */
  function closePanel(opener: () => void) {
    setPanel(null);
    setDeleteErr("");
    opener();
  }

  const toggle = (p: Panel) => setPanel((cur) => (JSON.stringify(cur) === JSON.stringify(p) ? null : p));

  async function disable(s: McpServer) {
    setDisabling(s.slug);
    setRowErr((e) => ({ ...e, [s.slug]: "" }));
    let fail = "";
    try {
      const r = await putJson(`${serverUrl(s.id)}/enabled`, { enabled: false });
      if (!r.ok) fail = await errDetail(r);
    } catch {
      fail = "Network error";
    }
    if (fail) {
      setRowErr((e) => ({ ...e, [s.slug]: `Couldn't disable ${s.slug}: ${fail}. Nothing was changed.` }));
    } else {
      setPanel((p) => (p && "slug" in p && p.slug === s.slug ? null : p));
      focusBtn(`test:${s.slug}`);
      setStatus(`${s.slug} is now off.`);
      await loadList();
    }
    setDisabling(null);
  }

  async function remove(s: McpServer) {
    setDeleting(true);
    setDeleteErr("");
    let fail = "";
    try {
      const r = await fetch(serverUrl(s.id), { method: "DELETE" });
      if (!r.ok) fail = await errDetail(r);
    } catch {
      fail = "Network error";
    }
    setDeleting(false);
    if (fail) {
      setDeleteErr(`Couldn't delete ${s.slug}: ${fail}. Nothing was changed.`);
      return;
    }
    setPanel(null);
    focusAdd();
    setStatus(`${s.slug} was deleted.`);
    await loadList();
  }

  function renderRow(s: McpServer, i: number) {
    const slug = s.slug;
    const changed = s.changed_count ?? 0;
    const opener = changed > 0 ? "Review" : "Test";
    const asking = panel?.kind === "delete" && panel.slug === slug;
    const reg = (k: string) => (el: HTMLButtonElement | null) => {
      if (el) btns.current.set(`${k}:${slug}`, el);
      else btns.current.delete(`${k}:${slug}`);
    };
    return (
      <li
        key={s.id}
        data-testid="mcp-row"
        data-server={slug}
        style={{
          listStyle: "none",
          padding: "16px 0",
          borderTop: i === 0 ? "none" : `1px solid ${tokens.color.borderInner}`,
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
          <span style={{ ...body14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{slug}</span>
          <span data-testid="mcp-transport" style={chipNeutral}>
            {TRANSPORT_LABEL[s.transport]}
          </span>
          <span data-testid="mcp-status-chip" style={s.enabled ? { ...chipBase, background: tokens.color.tintGreen } : chipNeutral}>
            {s.enabled ? "On" : "Off"}
          </span>
          {changed > 0 && (
            <span data-testid="mcp-changed" style={chipWarm}>
              {`${changed} ${changed === 1 ? "tool" : "tools"} changed, review`}
            </span>
          )}
          {!asking && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                ref={reg("test")}
                style={rowBtn}
                className="coarse-tap"
                data-testid="mcp-test"
                aria-label={`${opener} ${slug}`}
                aria-expanded={panel?.kind === "review" && panel.slug === slug}
                aria-controls={`mcp-panel-${slug}`}
                onClick={() => toggle({ kind: "review", slug })}
              >
                {opener}
              </button>
              <button
                type="button"
                ref={reg("edit")}
                style={rowBtn}
                className="coarse-tap"
                data-testid="mcp-edit"
                aria-label={`Edit ${slug}`}
                aria-expanded={panel?.kind === "edit" && panel.slug === slug}
                aria-controls={`mcp-form-${slug}`}
                onClick={() => toggle({ kind: "edit", slug })}
              >
                Edit
              </button>
              {s.enabled && (
                <button
                  type="button"
                  style={rowBtn}
                  className="coarse-tap"
                  data-testid="mcp-disable"
                  aria-label={`Disable ${slug}`}
                  disabled={disabling === slug}
                  onClick={() => void disable(s)}
                >
                  {disabling === slug ? "Disabling…" : "Disable"}
                </button>
              )}
              <button
                type="button"
                ref={reg("delete")}
                style={rowBtn}
                className="coarse-tap"
                data-testid="mcp-delete-open"
                aria-label={`Delete ${slug}`}
                onClick={() => {
                  setDeleteErr("");
                  setPanel({ kind: "delete", slug });
                }}
              >
                Delete
              </button>
            </span>
          )}
        </div>
        <div style={{ ...small, marginTop: 4, overflowWrap: "anywhere" }}>
          {s.transport === "stdio" ? commandLine(s.command, s.args) : (s.url ?? s.destination)}
        </div>
        {s.transport === "stdio" && (
          <div style={{ marginTop: 4 }}>
            <UnpinnedWarning command={s.command ?? ""} args={s.args} />
          </div>
        )}
        {rowErr[slug] && (
          <div role="alert" style={{ ...errText, marginTop: 4 }}>
            {rowErr[slug]}
          </div>
        )}

        {panel?.kind === "edit" && panel.slug === slug && (
          <McpServerForm
            server={s}
            onClose={() => closePanel(() => focusBtn(`edit:${slug}`))}
            onSaved={(n) => {
              setPanel(null);
              focusBtn(`test:${n}`);
              setStatus(`Saved ${n}.`);
              void loadList();
            }}
          />
        )}
        {panel?.kind === "review" && panel.slug === slug && (
          <McpToolReview
            server={s}
            onClose={() => closePanel(() => focusBtn(`test:${slug}`))}
            onStatus={setStatus}
            onEnabled={() => {
              setPanel(null);
              focusBtn(`test:${slug}`);
              setStatus(`${slug} is now on.`);
              void loadList();
            }}
            onGone={() => {
              setPanel(null);
              focusAdd();
              setStatus(`${slug} is no longer in the list.`);
              void loadList();
            }}
          />
        )}
        {asking && (
          <div
            role="group"
            aria-label={`Delete ${slug}`}
            data-testid="mcp-delete-confirm"
            onKeyDown={(e) => {
              if (e.key === "Escape" && !deleting) closePanel(() => focusBtn(`delete:${slug}`));
            }}
            style={{ ...warmBox, padding: 16, marginTop: 16, display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div>{`Delete ${slug}? This removes its address, headers and tool settings, and turns it off in every chat. Records of past calls stay in your chats.`}</div>
            {deleteErr && (
              <div role="alert" style={errText}>
                {deleteErr}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                style={{ ...dangerBtn, padding: "8px 16px", minHeight: 36, lineHeight: 1.5 }}
                className="coarse-tap"
                data-testid="mcp-delete"
                disabled={deleting}
                onClick={() => void remove(s)}
              >
                {deleting ? "Deleting…" : "Delete server"}
              </button>
              <button
                type="button"
                ref={keepBtn}
                style={rowBtn}
                className="coarse-tap"
                data-testid="mcp-keep"
                disabled={deleting}
                onClick={() => closePanel(() => focusBtn(`delete:${slug}`))}
              >
                Keep server
              </button>
            </div>
          </div>
        )}
      </li>
    );
  }

  return (
    <div id="external-mcp" style={card} data-testid="external-mcp-card">
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>External MCP servers</div>
      <div style={{ ...small, marginBottom: 16 }}>
        Connect tools from other MCP servers. Each server is off until you review and enable it, and every tool asks
        before it runs.
      </div>
      <div
        data-testid="mcp-safety"
        style={{
          background: tokens.color.tintNeutral,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.sm,
          padding: 16,
          marginBottom: 16,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <p style={{ ...body14, margin: 0, fontWeight: 600, color: tokens.color.ink }}>
          {'External servers are not part of monai. Whatever they return is labelled "external, unverified" and is never treated as your records.'}
        </p>
        <p style={{ ...body14, margin: 0, color: tokens.color.ink }}>
          A tool&apos;s description can steer the agent, so each one is shown exactly as the server sent it before you can
          enable the server.
        </p>
      </div>
      <div role="status" aria-live="polite" data-testid="mcp-status" style={{ ...small, minHeight: 21 }}>
        {status}
      </div>
      <div style={{ margin: "8px 0" }}>
        <button
          type="button"
          ref={addBtn}
          style={rowBtn}
          className="coarse-tap"
          data-testid="mcp-add"
          aria-expanded={panel?.kind === "add"}
          aria-controls="mcp-form-new"
          onClick={() => toggle({ kind: "add" })}
        >
          Add server
        </button>
      </div>
      {panel?.kind === "add" && (
        <McpServerForm
          server={null}
          onClose={() => closePanel(() => focusAdd())}
          onSaved={(n) => {
            setPanel(null);
            focusBtn(`test:${n}`);
            setStatus(`Added ${n}. It is off. Test it, review its tools, then enable it.`);
            void loadList();
          }}
        />
      )}
      <div aria-busy={rows === null && listError === null}>
        {listError !== null ? (
          <div role="alert" data-testid="mcp-load-error" style={{ ...errText, display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
            <span>{`Couldn't load servers: ${listError}. Check the backend is running, then try again.`}</span>
            <button type="button" style={rowBtn} className="coarse-tap" data-testid="mcp-list-retry" onClick={() => void loadList()}>
              Try again
            </button>
          </div>
        ) : rows === null ? (
          <div style={small}>Loading servers…</div>
        ) : rows.length === 0 ? (
          <div data-testid="mcp-empty">
            <div style={{ ...body14, fontWeight: 600, color: tokens.color.ink }}>No external servers yet.</div>
            <div style={small}>Add a server to give the chat agent more tools. A server you add starts switched off.</div>
          </div>
        ) : (
          <ul aria-label="External MCP servers" style={{ margin: 0, padding: 0 }}>
            {rows.map(renderRow)}
          </ul>
        )}
      </div>
    </div>
  );
}
