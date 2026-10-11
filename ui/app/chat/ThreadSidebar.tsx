"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { tokens, input } from "../styles";
import ConfirmDialog from "../cashflow/ConfirmDialog";

// ---------------------------------------------------------------------------
// ThreadSidebar (Phase 36, THRD-02, D-18/D-20, 36-UI-SPEC section 1).
// Recency-grouped thread list with New chat; rename and delete live in a
// per-row options menu (the inline title input and ConfirmDialog are unchanged).
// Titles are rendered as React text only. A list fetch failure is non-fatal
// (D-19a): a status line plus "Try again", never an error banner.
// ---------------------------------------------------------------------------

type Thread = { id: string; title: string; updated_at: string };

type Props = {
  activeId: string | null;
  refreshKey: number;
  open: boolean;
  onClose: () => void;
};

const GROUPS = [
  "Today",
  "Yesterday",
  "Previous 7 days",
  "Previous 30 days",
  "Older",
] as const;

const MSG_RENAME = "Couldn't rename this chat. Try again.";
const MSG_DELETE_BUSY = "This chat is still answering. Stop it first, then delete it.";
const MSG_DELETE_FAIL = "Couldn't delete this chat. Try again.";

function displayTitle(t: Thread): string {
  return t.title.trim() ? t.title : "Untitled chat";
}

// Calendar-day difference (browser local time) -> group index.
function groupIndex(updatedAt: string, now: Date): number {
  const d = new Date(updatedAt);
  if (Number.isNaN(d.getTime())) return 4;
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff <= 0) return 0;
  if (diff === 1) return 1;
  if (diff <= 7) return 2;
  if (diff <= 30) return 3;
  return 4;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

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

const rowErrStyle: CSSProperties = {
  fontSize: 12,
  color: tokens.color.terracotta,
  margin: "0 12px 8px",
  lineHeight: 1.5,
};

export default function ThreadSidebar({ activeId, refreshKey, open, onClose }: Props) {
  const router = useRouter();
  const uid = useId();
  const [threads, setThreads] = useState<Thread[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [editId, setEditId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [rowErr, setRowErr] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<Thread | null>(null);
  const [focusRename, setFocusRename] = useState<string | null>(null);
  const [focusNew, setFocusNew] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLSpanElement>(null);
  const newRef = useRef<HTMLButtonElement>(null);
  const editRef = useRef<HTMLInputElement>(null);
  const skipBlur = useRef(false);
  const reqSeq = useRef(0);

  // Never blanks a loaded list while refetching; a failure keeps the old list.
  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    try {
      const r = await fetch("/api/threads");
      const d = r.ok ? await r.json() : null;
      if (seq !== reqSeq.current) return;
      if (!Array.isArray(d)) {
        setStatus("error");
        return;
      }
      setThreads(d as Thread[]);
      setRowErr({});
      setStatus("ok");
    } catch {
      if (seq === reqSeq.current) setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (editId) {
      editRef.current?.focus();
      editRef.current?.select();
    }
  }, [editId]);

  useEffect(() => {
    if (focusRename) {
      document.getElementById(`${uid}-menu-${focusRename}`)?.focus();
      setFocusRename(null);
    }
  }, [focusRename, uid]);

  // Row options menu: focus the first item on open; close on outside mousedown;
  // Escape (capture phase + stopPropagation, like ConfirmDialog) closes only the
  // menu so the mobile drawer's own Escape listener does not also fire.
  useEffect(() => {
    if (menuId === null) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuId(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setMenuId(null);
      document.getElementById(`${uid}-menu-${menuId}`)?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [menuId, uid]);

  useEffect(() => {
    if (focusNew) {
      newRef.current?.focus();
      setFocusNew(false);
    }
  }, [focusNew]);

  // Mobile drawer: focus New chat on open (the page returns focus to the toggle).
  useEffect(() => {
    if (open) newRef.current?.focus();
  }, [open]);

  function startEdit(t: Thread) {
    skipBlur.current = false;
    setRowErr((e) => ({ ...e, [t.id]: "" }));
    setEditValue(t.title);
    setEditId(t.id);
  }

  async function commitEdit(t: Thread, raw: string) {
    const next = raw.trim().slice(0, 200);
    setEditId(null);
    if (!next || next === t.title) return;
    const prev = t.title;
    setThreads((l) => l && l.map((x) => (x.id === t.id ? { ...x, title: next } : x)));
    const fail = () => {
      setThreads((l) => l && l.map((x) => (x.id === t.id ? { ...x, title: prev } : x)));
      setRowErr((e) => ({ ...e, [t.id]: MSG_RENAME }));
    };
    try {
      const r = await fetch(`/api/threads/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: next }),
      });
      if (!r.ok) fail();
    } catch {
      fail();
    }
  }

  async function doDelete(t: Thread) {
    setConfirm(null);
    const setErr = (m: string) => setRowErr((e) => ({ ...e, [t.id]: m }));
    try {
      const r = await fetch(`/api/threads/${t.id}`, { method: "DELETE" });
      if (r.status === 409) return setErr(MSG_DELETE_BUSY);
      if (!r.ok) return setErr(MSG_DELETE_FAIL);
    } catch {
      return setErr(MSG_DELETE_FAIL);
    }
    setThreads((l) => l && l.filter((x) => x.id !== t.id));
    setFocusNew(true);
    if (t.id === activeId) router.replace("/chat");
  }

  function newChat() {
    onClose();
    if (activeId !== null) router.push("/chat");
  }

  const now = new Date();
  const buckets: Thread[][] = GROUPS.map(() => []);
  for (const t of threads ?? []) buckets[groupIndex(t.updated_at, now)].push(t);

  const errorLine = status === "error" && (
    <div role="status" style={{ fontSize: 14, color: tokens.color.muted3, marginBottom: 16, lineHeight: 1.5 }}>
      Couldn&apos;t load your chats.{" "}
      <button
        type="button"
        onClick={() => void load()}
        style={{
          background: "transparent",
          border: "none",
          cursor: "pointer",
          fontSize: 14,
          color: tokens.color.ink,
          textDecoration: "underline",
          minHeight: 36,
          padding: 0,
        }}
      >
        Try again
      </button>
    </div>
  );

  return (
    <aside
      className="chat-threads"
      id="chat-threads"
      data-testid="thread-sidebar"
      data-open={open ? "true" : undefined}
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        left: 0,
        width: 240,
        overflowY: "auto",
        boxSizing: "border-box",
        padding: 16,
        background: tokens.color.panel,
        borderRight: `1px solid ${tokens.color.border2}`,
        fontFamily: tokens.font.sans,
      }}
    >
      <h2 className="sr-only">Chats</h2>
      <button
        ref={newRef}
        type="button"
        data-testid="thread-new"
        onClick={newChat}
        style={{
          width: "100%",
          minHeight: 44,
          background: tokens.color.sidebar,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.pill,
          color: tokens.color.ink,
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
          marginBottom: 16,
        }}
      >
        <span aria-hidden="true">+ </span>New chat
      </button>

      <nav aria-label="Chat threads" aria-busy={status === "loading" && threads === null ? true : undefined}>
        {errorLine}
        {status === "loading" && threads === null && (
          <div>
            <span className="sr-only" role="status">
              Loading chats…
            </span>
            {["80%", "64%", "72%"].map((w) => (
              <div
                key={w}
                aria-hidden="true"
                style={{
                  height: 16,
                  width: w,
                  background: tokens.color.borderInner,
                  borderRadius: tokens.radius.sm,
                  marginBottom: 12,
                }}
              />
            ))}
          </div>
        )}
        {threads !== null && threads.length === 0 && status === "ok" && (
          <p style={{ fontSize: 14, color: tokens.color.muted3, margin: 0, lineHeight: 1.5 }}>
            No chats yet.
            <br />
            Your conversations will show up here after your first question.
          </p>
        )}
        {GROUPS.map((name, gi) => {
          const rows = buckets[gi];
          if (rows.length === 0) return null;
          const hid = `${uid}-g${gi}`;
          return (
            <div key={name} style={{ marginBottom: 24 }}>
              <h3
                id={hid}
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: ".12em",
                  color: tokens.color.muted3,
                  margin: "0 0 8px",
                  lineHeight: 1.5,
                }}
              >
                {name}
              </h3>
              <ul
                aria-labelledby={hid}
                style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}
              >
                {rows.map((t) => {
                  const active = t.id === activeId;
                  const title = displayTitle(t);
                  const editing = editId === t.id;
                  return (
                    <li
                      key={t.id}
                      className="thread-row"
                      data-testid="thread-row"
                      aria-current={active ? "page" : undefined}
                      style={{
                        borderRadius: tokens.radius.sm,
                        border: `1px solid ${active ? tokens.color.border2 : "transparent"}`,
                        ...(active ? { background: tokens.color.card } : null),
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 4, minHeight: 42, padding: "0 12px" }}>
                        {editing ? (
                          <input
                            ref={editRef}
                            value={editValue}
                            maxLength={200}
                            aria-label="Chat title"
                            style={{ ...input, fontSize: 16, padding: "6px 10px" }}
                            onChange={(e) => setEditValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                              if (e.key === "Enter") {
                                e.preventDefault();
                                skipBlur.current = true;
                                void commitEdit(t, editValue);
                                setFocusRename(t.id);
                              } else if (e.key === "Escape") {
                                e.preventDefault();
                                skipBlur.current = true;
                                setEditId(null);
                                setFocusRename(t.id);
                              }
                            }}
                            onBlur={() => {
                              if (skipBlur.current) return;
                              void commitEdit(t, editValue);
                            }}
                          />
                        ) : (
                          <Link
                            href={`/chat?thread=${t.id}`}
                            title={title}
                            onClick={(e) => {
                              if (active) e.preventDefault();
                              else onClose();
                            }}
                            style={{
                              flex: 1,
                              minWidth: 0,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              fontSize: 14,
                              fontWeight: active ? 600 : 400,
                              color: tokens.color.ink,
                              textDecoration: "none",
                              lineHeight: "42px",
                            }}
                          >
                            {title}
                          </Link>
                        )}
                        {!editing && (
                          <span
                            ref={menuId === t.id ? menuRef : undefined}
                            className="thread-actions"
                            style={{
                              display: "inline-flex",
                              flexShrink: 0,
                              position: "relative",
                              ...(menuId === t.id ? { opacity: 1 } : null),
                            }}
                          >
                            <button
                              type="button"
                              id={`${uid}-menu-${t.id}`}
                              style={{ ...textBtn, fontSize: 16, lineHeight: 1, padding: "8px 10px" }}
                              aria-label={`Chat options: ${title}`}
                              aria-haspopup="menu"
                              aria-expanded={menuId === t.id}
                              aria-controls={menuId === t.id ? `${uid}-menulist-${t.id}` : undefined}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                setMenuId(menuId === t.id ? null : t.id);
                              }}
                            >
                              <span aria-hidden="true">⋯</span>
                            </button>
                            {menuId === t.id && (
                              /* ponytail: absolute inside the scrolling aside, so a menu on the last row extends the scroll area; switch to a portal + fixed position if that ever clips. */
                              <div
                                role="menu"
                                id={`${uid}-menulist-${t.id}`}
                                aria-labelledby={`${uid}-menu-${t.id}`}
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
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === "Tab") {
                                    setMenuId(null);
                                    return;
                                  }
                                  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
                                  e.preventDefault();
                                  const items = Array.from(
                                    e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
                                  );
                                  const i = items.indexOf(document.activeElement as HTMLElement);
                                  const step = e.key === "ArrowDown" ? 1 : -1;
                                  items[(i + step + items.length) % items.length]?.focus();
                                }}
                              >
                                <button
                                  type="button"
                                  role="menuitem"
                                  tabIndex={-1}
                                  style={{
                                    ...textBtn,
                                    display: "block",
                                    width: "100%",
                                    textAlign: "left",
                                    fontSize: 14,
                                    borderRadius: tokens.radius.sm,
                                    color: tokens.color.ink,
                                  }}
                                  onClick={() => {
                                    setMenuId(null);
                                    startEdit(t);
                                  }}
                                >
                                  Rename
                                </button>
                                <button
                                  type="button"
                                  role="menuitem"
                                  tabIndex={-1}
                                  style={{
                                    ...textBtn,
                                    display: "block",
                                    width: "100%",
                                    textAlign: "left",
                                    fontSize: 14,
                                    borderRadius: tokens.radius.sm,
                                    color: tokens.color.terracotta,
                                  }}
                                  onClick={() => {
                                    setMenuId(null);
                                    // Focus the still-mounted options button so ConfirmDialog records it as opener.
                                    document.getElementById(`${uid}-menu-${t.id}`)?.focus();
                                    setRowErr((e) => ({ ...e, [t.id]: "" }));
                                    onClose();
                                    setConfirm(t);
                                  }}
                                >
                                  Delete
                                </button>
                              </div>
                            )}
                          </span>
                        )}
                      </div>
                      {rowErr[t.id] && (
                        <div role="alert" style={rowErrStyle}>
                          {rowErr[t.id]}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      {/* Portal: the mobile drawer is display:none once closed, which would hide a fixed child. */}
      {confirm &&
        createPortal(
        <ConfirmDialog
          message={`Delete "${truncate(displayTitle(confirm), 40)}"? Its messages will be removed. Any proposals it created stay in the Inbox.`}
          confirmLabel="Delete chat"
          onConfirm={() => void doDelete(confirm)}
          onCancel={() => setConfirm(null)}
        />,
        document.body,
        )}
    </aside>
  );
}
