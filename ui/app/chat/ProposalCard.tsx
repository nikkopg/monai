"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { tokens, btn, btnGhost } from "../styles";
import ProposalDiff from "../components/ProposalDiff";
import type { DiffRow } from "../components/ProposalDiff";
import { hhmm } from "../lib/inbox";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Shape of one entry in the SSE answer event's proposals[] (server contract).
// GET /threads/{id} never sends a token, so it is optional here.
export type ServerProposal = {
  id: string;
  token?: string | null;
  operation?: string | null;
  payload?: { operation: string; rows: DiffRow[] } | null;
  expires_at?: string | null;
  status?: string | null;
};

export type Proposal = {
  id: string;
  token: string | null;
  operation: string | null;
  payload: { operation: string; rows: DiffRow[] } | null;
  expiresAt: Date | null;
  rejectedByStop?: boolean;
  // Live status joined by GET /threads/{id}; undefined for the in-view turn.
  liveStatus?: LiveStatus;
};

export type LiveStatus =
  | "pending"
  | "confirmed"
  | "rejected"
  | "expired"
  | "superseded"
  | "missing";

export function toProposal(p: ServerProposal): Proposal {
  const ms =
    typeof p.expires_at === "string" && p.expires_at !== ""
      ? Date.parse(p.expires_at)
      : NaN;
  return {
    id: p.id,
    token: p.token ?? null,
    operation: p.operation ?? null,
    payload: p.payload ?? null,
    expiresAt: Number.isNaN(ms) ? null : new Date(ms),
  };
}

// ---------------------------------------------------------------------------
// Proposal token custody (D-17). The token lives only in this tab's
// sessionStorage, keyed by proposal id. Every access is guarded: storage may be
// disabled. Tokens are never rendered, logged or put in a URL.
// ---------------------------------------------------------------------------

const TOKEN_PREFIX = "monai.proposalToken.";

export function saveProposalToken(id: string, token: string): void {
  try {
    sessionStorage.setItem(TOKEN_PREFIX + id, token);
  } catch {
    // ignore (e.g. storage disabled)
  }
}

export function readProposalToken(id: string): string | null {
  try {
    return sessionStorage.getItem(TOKEN_PREFIX + id);
  } catch {
    return null;
  }
}

export function clearProposalToken(id: string): void {
  try {
    sessionStorage.removeItem(TOKEN_PREFIX + id);
  } catch {
    // ignore (e.g. storage disabled)
  }
}

// ---------------------------------------------------------------------------
// ProposalCard — inline card with before→after diff + Approve/Reject + expiry
// (D-01, D-02, D-03, D-10). Rehydration decision table: 36-UI-SPEC section 7.
// ---------------------------------------------------------------------------

/** POST the confirm call; shared by the card and the plan bar. No React state. */
export async function confirmProposal(
  id: string,
  token: string | null
): Promise<{ ok: true } | { ok: false; text: string }> {
  try {
    const r = await fetch(`/api/proposals/${id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (r.ok) return { ok: true };
    const d = await r.json().catch(() => ({}));
    if (r.status === 410) return { ok: false, text: "Expired — ask again to redo this" };
    return { ok: false, text: d.detail || `Error ${r.status}` };
  } catch (e: unknown) {
    return { ok: false, text: e instanceof Error ? e.message : "Network error" };
  }
}

export default function ProposalCard({
  proposal,
  onApplied,
  onRejected,
  liveStatus,
  inCancelledMessage,
  locked,
  externalError,
  step,
}: {
  proposal: Proposal;
  onApplied: () => void;
  onRejected: () => void;
  liveStatus?: LiveStatus;
  inCancelledMessage?: boolean;
  /** Plan bar is running Approve all: disable both buttons. */
  locked?: boolean;
  /** Error from a plan-bar apply of this card. */
  externalError?: string | null;
  /** 1-based position in a multi-step plan. */
  step?: number;
}) {
  const [status, setStatus] = useState<"pending" | "applied" | "rejected">(
    "pending"
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(new Date());
  // undefined = storage not read yet (it is only read in an effect, never
  // during render); null = read and absent.
  const [stored, setStored] = useState<string | null | undefined>(undefined);

  // Tick every 10 s to update expiry display
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (proposal.token === null) setStored(readProposalToken(proposal.id));
  }, [proposal.id, proposal.token]);

  const token = proposal.token ?? stored ?? null;
  const tokenChecked = proposal.token !== null || stored !== undefined;

  const expiresAt = proposal.expiresAt;
  const timeExpired = expiresAt !== null && now > expiresAt;
  const rows = proposal.payload?.rows ?? [];
  const unapprovableReason: string | null =
    rows.length === 0
      ? "Nothing to review: this proposal has no details, so it can't be approved. Reject it and ask again."
      : expiresAt === null
      ? "No expiry came with this proposal, so it can't be approved. Reject it and ask again."
      : null;

  // Decision table, first match wins (36-UI-SPEC section 7).
  const live = liveStatus ?? proposal.liveStatus;
  const stopCopy = !!proposal.rejectedByStop || !!inCancelledMessage;
  type View = "missing" | "applied" | "rejected" | "expired" | "pending";
  const view: View =
    live === "missing" || live === "superseded"
      ? "missing"
      : status === "applied" || live === "confirmed"
      ? "applied"
      : status === "rejected" || live === "rejected" || proposal.rejectedByStop
      ? "rejected"
      : live === "expired"
      ? "expired"
      : "pending";
  const expired = view === "expired" || (view === "pending" && timeExpired);
  const terminal = view !== "pending" || timeExpired;

  // The single-use token has no further purpose once the card is terminal.
  useEffect(() => {
    if (terminal) clearProposalToken(proposal.id);
  }, [terminal, proposal.id]);

  const pending = view === "pending";
  const readOnly = pending && !expired && tokenChecked && token === null;
  const noticeId = `unapprovable-${proposal.id}`;
  const rejectDisabled = busy || !!locked || !pending || expired;
  const approveDisabled = rejectDisabled || unapprovableReason !== null || !token;
  const remMs = expiresAt ? expiresAt.getTime() - now.getTime() : 0;

  const cardStyle: React.CSSProperties = {
    background: tokens.color.card,
    border: `1px solid ${
      view === "applied"
        ? tokens.color.green
        : view === "rejected" || view === "missing"
        ? tokens.color.border2
        : "#cfe0d6"
    }`,
    borderLeft: `3px solid ${
      view === "rejected"
        ? tokens.color.terracotta
        : view === "missing"
        ? tokens.color.border2
        : tokens.color.green
    }`,
    borderRadius: 14,
    padding: "18px 20px",
    marginTop: 16,
    opacity: expired && pending ? 0.6 : 1,
  };

  async function handleApprove() {
    setBusy(true);
    setError(null);
    try {
      const r = await confirmProposal(proposal.id, token);
      if (r.ok) {
        setStatus("applied");
        clearProposalToken(proposal.id);
        onApplied();
      } else {
        setError(r.text);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/proposals/${proposal.id}/reject`, {
        method: "POST",
      });
      if (r.ok) {
        setStatus("rejected");
        clearProposalToken(proposal.id);
        onRejected();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || `Error ${r.status}`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  const small: React.CSSProperties = {
    color: tokens.color.muted3,
    fontSize: 14,
    lineHeight: 1.5,
  };

  if (view === "missing") {
    return (
      <div style={cardStyle}>
        <div style={small}>This proposal is no longer available.</div>
      </div>
    );
  }

  const expiryLine =
    !expired && expiresAt ? (
      <span
        style={{ marginLeft: "auto", fontSize: 12, color: tokens.color.muted3 }}
      >
        expires {hhmm(expiresAt.getTime())} · in{" "}
        {remMs < 60000 ? "under 1" : Math.floor(remMs / 60000)} min
      </span>
    ) : null;

  return (
    <div style={cardStyle}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: ".1em",
          textTransform: "uppercase",
          color: tokens.color.green,
          fontWeight: 700,
          marginBottom: 10,
        }}
      >
        {step ? `${step}. ` : ""}Proposed {(proposal.operation ?? "write").replace(/_/g, " ")}
      </div>

      {rows.length > 0 && <ProposalDiff rows={rows} dimColor={tokens.color.muted3} />}

      {pending && !readOnly && unapprovableReason && (
        <div id={noticeId} style={{ ...small, marginTop: 8 }}>
          {unapprovableReason}
        </div>
      )}
      {expired && (
        <div style={{ ...small, marginTop: 10 }}>
          Expired — ask again to redo this
        </div>
      )}
      {view === "applied" && (
        <div style={{ color: tokens.color.green, fontSize: 14, marginTop: 10 }}>
          Applied successfully.
        </div>
      )}
      {view === "rejected" && (
        <div style={{ ...small, marginTop: 10 }}>
          {stopCopy
            ? "Rejected — the run was stopped. No changes made."
            : "Rejected — no changes made."}
        </div>
      )}
      {(error ?? externalError) && (
        <div
          style={{ color: tokens.color.terracottaText, fontSize: 12, marginTop: 8 }}
        >
          {error ?? externalError}
        </div>
      )}

      {readOnly && (
        <>
          <div style={{ ...small, marginTop: 10 }}>
            This chat can no longer approve this change. Review and approve it in
            the Inbox.
          </div>
          <div
            style={{
              display: "flex",
              gap: 10,
              marginTop: 16,
              alignItems: "center",
            }}
          >
            <Link
              href="/inbox"
              data-testid="proposal-open-inbox"
              style={{
                ...btnGhost,
                color: tokens.color.ink,
                textDecoration: "none",
                minHeight: 36,
                padding: "8px 16px",
                display: "inline-flex",
                alignItems: "center",
              }}
            >
              Open in Inbox
            </Link>
            {expiryLine}
          </div>
        </>
      )}

      {pending && !readOnly && tokenChecked && !expired && (
        <div
          style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}
        >
          <button
            style={{
              ...btn,
              opacity: approveDisabled ? 0.5 : 1,
              cursor: approveDisabled ? "not-allowed" : "pointer",
            }}
            onClick={handleApprove}
            disabled={approveDisabled}
            aria-describedby={unapprovableReason ? noticeId : undefined}
          >
            {busy ? "…" : "Approve"}
          </button>
          <button
            style={{
              ...btnGhost,
              cursor: rejectDisabled ? "not-allowed" : "pointer",
            }}
            onClick={handleReject}
            disabled={rejectDisabled}
          >
            {busy ? "…" : "Reject"}
          </button>
          {expiryLine}
        </div>
      )}
    </div>
  );
}
