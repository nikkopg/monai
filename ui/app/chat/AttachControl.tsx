"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { tokens, btnDark, btnGhost, input } from "../styles";
import { extractDetail } from "../lib/api";
import { tooltipStyle } from "./MessageActions";
import {
  ACCEPT_ATTR,
  ACCOUNT_STORAGE_KEY,
  LOCALITY_EYEBROW,
  LOCALITY_FAILED,
  LOCALITY_LOADING,
  PASSWORD_HINT,
  PASSWORD_WRONG,
  announce as say,
  fileKind,
  localityLines,
  precheck,
  uploadErrorText,
  type AttachChip,
  type Locality,
} from "./attachLabels";

// ---------------------------------------------------------------------------
// Attach control (39-UI-SPEC section 1): the upload client, the useAttachments
// hook, the toggle and the disclosure panel. The page (39-12) owns `open`, the
// thread id and focus after a successful attach.
// ---------------------------------------------------------------------------

export type UploadResponse = {
  attachment_id: string | null;
  thread_id: string;
  kind: string;
  status: string; // ok | refused | llm_read | needs_password | wrong_password
  summary: string;
  row_count: number;
};

export type UploadOutcome =
  | { kind: "ok"; data: UploadResponse }
  | { kind: "error"; status: number | "network"; text: string }
  | { kind: "aborted" };

/** POST the multipart upload. No content-type header: the browser sets the boundary. */
export async function uploadAttachment(
  threadId: string,
  file: File,
  accountId: number,
  password: string,
  signal?: AbortSignal
): Promise<UploadOutcome> {
  const body = new FormData();
  body.append("file", file);
  body.append("account_id", String(accountId));
  if (password) body.append("password", password);
  let r: Response;
  try {
    r = await fetch(`/api/threads/${threadId}/attachments`, { method: "POST", body, signal });
  } catch {
    if (signal?.aborted) return { kind: "aborted" };
    return { kind: "error", status: "network", text: uploadErrorText("network") };
  }
  if (r.ok) return { kind: "ok", data: (await r.json()) as UploadResponse };
  return { kind: "error", status: r.status, text: uploadErrorText(r.status, await extractDetail(r)) };
}

export type SubmitResult =
  | { outcome: "done"; threadId: string }
  | { outcome: "password" | "aborted" }
  | { outcome: "error"; error: string };

export type PendingPassword = { chipId: string; filename: string; wrong: boolean };

export function useAttachments(onAnnounce?: (text: string) => void) {
  const [chips, setChips] = useState<AttachChip[]>([]);
  const [pendingPassword, setPending] = useState<PendingPassword | null>(null);
  const ctl = useRef(new Map<string, AbortController>());
  const seq = useRef(0);

  const submit = useCallback(
    async (threadId: string, file: File, accountId: number, password: string): Promise<SubmitResult> => {
      // A password retry re-uses the chip that asked for it.
      const id = pendingPassword?.chipId ?? `attach-${++seq.current}`;
      const ac = new AbortController();
      ctl.current.set(id, ac);
      const fresh: AttachChip = {
        localId: id, attachmentId: null, filename: file.name, kind: fileKind(file.name),
        state: "uploading", summary: "", rowCount: 0, purgedAt: null, messageId: null,
      };
      setChips((cs) => (cs.some((c) => c.localId === id) ? cs.map((c) => (c.localId === id ? fresh : c)) : [...cs, fresh]));
      setPending(null);

      const out = await uploadAttachment(threadId, file, accountId, password, ac.signal);
      ctl.current.delete(id);
      if (out.kind === "aborted" || ac.signal.aborted) return { outcome: "aborted" };
      const patch = (p: Partial<AttachChip>) =>
        setChips((cs) => cs.map((c) => (c.localId === id ? { ...c, ...p } : c)));

      if (out.kind === "error") {
        patch({ state: "failed", summary: out.text });
        onAnnounce?.(out.text);
        return { outcome: "error", error: out.text };
      }
      const d = out.data;
      if (d.status === "needs_password" || d.status === "wrong_password") {
        patch({ state: "needs_password" });
        setPending({ chipId: id, filename: file.name, wrong: d.status === "wrong_password" });
        onAnnounce?.(say.needsPassword(file.name));
        return { outcome: "password" };
      }
      const state = d.status === "ok" ? "ok" : d.status === "llm_read" ? "llm_read" : "refused";
      patch({ state, attachmentId: d.attachment_id, kind: d.kind, summary: d.summary, rowCount: d.row_count });
      onAnnounce?.(state === "refused" ? say.unreadable(file.name, d.summary) : say.attached(file.name, d.summary));
      return { outcome: "done", threadId: d.thread_id };
    },
    [pendingPassword, onAnnounce]
  );

  /** Abort an in-flight upload, or drop the chip. */
  const remove = useCallback(
    (localId: string) => {
      const c = chips.find((x) => x.localId === localId);
      ctl.current.get(localId)?.abort();
      ctl.current.delete(localId);
      setChips((cs) => cs.filter((x) => x.localId !== localId));
      setPending((p) => (p?.chipId === localId ? null : p));
      if (c) onAnnounce?.(c.state === "uploading" ? say.cancelled(c.filename) : say.removed(c.filename));
    },
    [chips, onAnnounce]
  );

  /** Leaving the thread: abort what is in flight and empty the tray. */
  const clear = useCallback(() => {
    ctl.current.forEach((ac) => ac.abort());
    ctl.current.clear();
    setChips([]);
    setPending(null);
  }, []);

  /**
   * On Ask: every chip the server stored goes with the question (the server
   * decides what a refused file contributes). Those chips leave the tray; a chip
   * still waiting for a password stays.
   */
  const clearSent = useCallback((): { ids: string[]; sent: AttachChip[] } => {
    const sent = chips.filter((c) => c.attachmentId !== null);
    setChips((cs) => cs.filter((c) => c.state === "needs_password" || c.state === "uploading"));
    return { ids: sent.map((c) => c.attachmentId as string), sent };
  }, [chips]);

  return {
    chips,
    pendingPassword,
    submit,
    remove,
    clear,
    clearSent,
    anyUploading: chips.some((c) => c.state === "uploading"),
  };
}

// ---------------------------------------------------------------------------
// Toggle
// ---------------------------------------------------------------------------

export function AttachToggle({
  expanded,
  onToggle,
  disabledReason,
}: {
  expanded: boolean;
  onToggle: () => void;
  disabledReason?: string | null;
}) {
  const tipId = useId();
  const reason = disabledReason ?? null;
  return (
    <span className="action-wrap" style={{ position: "relative", display: "flex" }}>
      <button
        type="button"
        id="attach-toggle"
        data-testid="attach-toggle"
        className="coarse-tap"
        aria-label="Attach a file"
        aria-expanded={expanded}
        aria-controls="attach-panel"
        {...(reason ? { "aria-disabled": true as const, "aria-describedby": tipId } : {})}
        onClick={() => {
          if (!reason) onToggle();
        }}
        style={{
          background: tokens.color.sidebar,
          color: reason ? tokens.color.muted3 : tokens.color.ink,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: 14,
          padding: "0 16px",
          fontSize: 14,
          fontWeight: 600,
          fontFamily: "inherit",
          minHeight: 36,
          cursor: reason ? "not-allowed" : "pointer",
          opacity: reason ? 0.6 : 1,
        }}
      >
        <span aria-hidden="true">+ </span>Attach
      </button>
      {reason && (
        <span role="tooltip" id={tipId} className="action-tooltip" style={tooltipStyle}>
          {reason}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

type Account = { id: number; name: string; type: string };

// The locality answer is cached for the page session.
let localityCache: Locality | null = null;

const field: React.CSSProperties = { fontSize: 14, fontWeight: 600, color: tokens.color.ink, display: "block", marginBottom: 4 };
const hint: React.CSSProperties = { fontSize: 12, color: tokens.color.muted3, marginTop: 4 };
const errText: React.CSSProperties = { fontSize: 14, color: tokens.color.terracottaText };
const textBtn: React.CSSProperties = {
  background: "transparent", border: "none", fontFamily: "inherit", fontSize: 14, minHeight: 36,
  cursor: "pointer", padding: "0 4px",
};

function readSaved(): string | null {
  try {
    return localStorage.getItem(ACCOUNT_STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveAccount(id: string) {
  try {
    localStorage.setItem(ACCOUNT_STORAGE_KEY, id);
  } catch {
    // storage disabled: the choice just isn't remembered
  }
}

export function AttachPanel({
  open,
  onClose,
  onSubmit,
  pendingPassword,
}: {
  open: boolean;
  /** `sent` is true after a successful attach: the page then focuses the composer input. */
  onClose: (sent: boolean) => void;
  onSubmit: (file: File, accountId: number, password: string) => Promise<SubmitResult>;
  pendingPassword: PendingPassword | null;
}) {
  const [loc, setLoc] = useState<Locality | "loading" | "failed">(localityCache ?? "loading");
  const [tick, setTick] = useState(0);
  const [accounts, setAccounts] = useState<Account[] | "loading" | "failed">("loading");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [accountId, setAccountId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const pwRef = useRef<HTMLInputElement>(null);
  const focused = useRef(false);

  useEffect(() => {
    if (!open || localityCache) return;
    setLoc("loading");
    fetch("/api/attachments/locality")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("locality"))))
      .then((d) => {
        if (typeof d?.local !== "boolean") throw new Error("locality");
        localityCache = { local: d.local, destination: d.destination ?? null };
        setLoc(localityCache);
      })
      .catch(() => setLoc("failed"));
  }, [open, tick]);

  useEffect(() => {
    if (!open) return;
    setAccounts("loading");
    fetch("/api/accounts")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("accounts"))))
      .then((all: Account[]) => {
        const liquid = all.filter((a) => a.type === "liquid").sort((a, b) => a.name.localeCompare(b.name));
        setAccounts(liquid);
        const saved = readSaved();
        setAccountId((cur) => cur || (liquid.some((a) => String(a.id) === saved) ? (saved as string) : ""));
      })
      .catch(() => setAccounts("failed"));
  }, [open]);

  // Focus the first enabled control once, when the notice is on screen.
  useEffect(() => {
    if (!open) {
      focused.current = false;
      return;
    }
    if (focused.current || loc === "loading") return;
    focused.current = true;
    (loc === "failed" ? retryRef : fileRef).current?.focus();
  }, [open, loc]);

  useEffect(() => {
    if (pendingPassword) pwRef.current?.focus();
  }, [pendingPassword]);

  if (!open) return null;

  const kind = file ? fileKind(file.name) : null;
  const locReady = typeof loc === "object";
  const ready =
    file !== null && accountId !== "" && locReady && !submitting && (!pendingPassword || password !== "");

  function pick(f: File | null) {
    const err = f ? precheck(f) : null;
    setError(err ?? "");
    if (err) {
      setFile(null);
      setFileKey((k) => k + 1); // a refused file is not kept: reset the input
    } else {
      setFile(f);
    }
  }

  function close(sent: boolean) {
    // The file stays while a password is pending, so reopening can retry it.
    if (!pendingPassword || sent) {
      setFile(null);
      setFileKey((k) => k + 1);
    }
    setPassword("");
    setError("");
    onClose(sent);
    if (!sent) document.getElementById("attach-toggle")?.focus();
  }

  async function submit() {
    if (!file || !ready) return;
    const pw = password;
    setPassword(""); // cleared the moment the request is sent
    setError("");
    setSubmitting(true);
    saveAccount(accountId);
    const res = await onSubmit(file, Number(accountId), pw);
    setSubmitting(false);
    if (res.outcome === "done") close(true);
    else if (res.outcome === "error") {
      setError(res.error);
      setFile(null);
      setFileKey((k) => k + 1);
    }
  }

  const lines = locReady ? localityLines(loc, kind) : [];
  const box: React.CSSProperties = {
    background: locReady && loc.local ? tokens.color.tintNeutral : tokens.color.tintWarm,
    border: `1px solid ${tokens.color.border2}`,
    borderRadius: tokens.radius.sm,
    padding: "12px 16px",
    fontSize: 14,
    color: tokens.color.ink,
    lineHeight: 1.5,
  };

  return (
    <div
      id="attach-panel"
      data-testid="attach-panel"
      role="group"
      aria-labelledby="attach-heading"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !submitting) close(false);
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
        fontFamily: tokens.font.sans,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 id="attach-heading" style={{ margin: 0, fontSize: 16, fontWeight: 600, lineHeight: 1.4, color: tokens.color.ink }}>
          Attach a file
        </h2>
        <button type="button" className="coarse-tap" disabled={submitting} onClick={() => close(false)} style={{ ...textBtn, color: tokens.color.muted3 }}>
          Close
        </button>
      </div>

      <div id="attach-locality" data-testid="attach-locality" aria-busy={loc === "loading"} style={box}>
        <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", color: tokens.color.muted3 }}>
          {LOCALITY_EYEBROW}
        </div>
        {loc === "loading" && <div>{LOCALITY_LOADING}</div>}
        {loc === "failed" && (
          <div>
            {LOCALITY_FAILED}{" "}
            <button
              type="button"
              ref={retryRef}
              className="coarse-tap"
              onClick={() => setTick((t) => t + 1)}
              style={{ ...textBtn, color: tokens.color.ink, textDecoration: "underline" }}
            >
              Try again
            </button>
          </div>
        )}
        {lines.map((l) => (
          <div key={l.lead + l.text}>
            {l.lead && <span style={{ fontWeight: 600 }}>{l.lead} </span>}
            {l.text}
          </div>
        ))}
      </div>

      <div>
        <label htmlFor="attach-file" style={field}>File</label>
        <input
          key={fileKey}
          ref={fileRef}
          type="file"
          id="attach-file"
          data-testid="attach-file"
          accept={ACCEPT_ATTR}
          disabled={!locReady || submitting}
          aria-describedby="attach-locality attach-file-hint attach-file-error"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        <div id="attach-file-hint" style={hint}>CSV, PDF, PNG, JPEG or WebP. Up to 10 MB.</div>
        <div id="attach-file-error" data-testid="attach-file-error" role="alert" style={errText}>{error}</div>
      </div>

      <div>
        {accounts === "loading" || (Array.isArray(accounts) && accounts.length > 0) ? (
          <>
            <label htmlFor="attach-account" style={field}>Add rows to account</label>
            <select
              id="attach-account"
              data-testid="attach-account"
              value={accountId}
              disabled={submitting}
              onChange={(e) => setAccountId(e.target.value)}
              style={{ ...input, fontSize: 14 }}
            >
              <option value="" disabled>Choose an account</option>
              {Array.isArray(accounts) &&
                accounts.map((a) => (
                  <option key={a.id} value={String(a.id)}>{a.name}</option>
                ))}
            </select>
            <div style={hint}>monai doesn&apos;t guess the account from the file.</div>
          </>
        ) : (
          <div style={{ fontSize: 14, color: tokens.color.ink }}>
            {accounts === "failed"
              ? "Couldn't load your accounts."
              : "No account can take transactions yet. Add one in Cash flow first."}
          </div>
        )}
      </div>

      {pendingPassword && (
        <div>
          <label htmlFor="attach-password" style={field}>PDF password</label>
          <input
            ref={pwRef}
            type="password"
            id="attach-password"
            data-testid="attach-password"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ ...input, fontSize: 14 }}
          />
          <div style={hint}>{PASSWORD_HINT}</div>
          <div role="alert" style={errText}>{pendingPassword.wrong ? PASSWORD_WRONG : ""}</div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          data-testid="attach-submit"
          className="coarse-tap"
          disabled={!ready}
          onClick={() => void submit()}
          style={{ ...btnDark, fontSize: 14, minHeight: 36, opacity: ready ? 1 : 0.5, cursor: ready ? "pointer" : "not-allowed" }}
        >
          {submitting ? (kind === "image" ? "Reading the image…" : "Uploading…") : "Attach file"}
        </button>
        <button
          type="button"
          className="coarse-tap"
          disabled={submitting}
          onClick={() => close(false)}
          style={{ ...btnGhost, fontSize: 14, minHeight: 36 }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
