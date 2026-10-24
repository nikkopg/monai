"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, btn, btnGhost } from "../styles";
import {
  announce,
  cardState,
  cardStatus,
  countdownText,
  isLastMinute,
  SENT_NOTE,
  type ExtCall,
} from "./extLabels";

// ---------------------------------------------------------------------------
// ExtApprovalCard (41-UI-SPEC B2/B3, D-13, D-16, D-26). The one control between
// the model and an outbound call: it shows the server, the tool, the server-built
// destination and the exact arguments, then Deny (first, default focus) and Allow
// once. Every state is rendered from the ext_calls row; every server string is a
// React text node (no raw-HTML prop, no markdown). Timers are setInterval only.
// ---------------------------------------------------------------------------

const eyebrow: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: ".12em",
  color: tokens.color.muted3,
};
const blockLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: tokens.color.muted3 };
const caption: React.CSSProperties = { fontSize: 12, color: tokens.color.muted3 };
const body14: React.CSSProperties = { fontSize: 14, lineHeight: 1.5, color: tokens.color.ink, margin: 0 };
const action: React.CSSProperties = { fontSize: 14, padding: "8px 16px", minHeight: 36, fontFamily: "inherit" };
const pre: React.CSSProperties = {
  margin: 0,
  padding: "8px 16px",
  background: tokens.color.inputBg,
  border: `1px solid ${tokens.color.border2}`,
  borderRadius: tokens.radius.sm,
  color: tokens.color.ink,
  fontSize: 14,
  lineHeight: 1.5,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  maxHeight: 240,
  overflow: "auto",
};

async function detailOf(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}));
  return typeof d?.detail === "string" ? d.detail : `HTTP ${r.status}`;
}

export default function ExtApprovalCard({
  threadId,
  call,
  live,
  canTakeFocus,
  onReread,
  onAnnounce,
}: {
  threadId: string;
  call: ExtCall;
  /** Arrived on the live stream in this view (a reloaded card never moves focus). */
  live: boolean;
  canTakeFocus: () => boolean;
  onReread: () => Promise<void>;
  onAnnounce: (text: string) => void;
}) {
  const [busy, setBusy] = useState<"deny" | "allow" | null>(null);
  const [answered, setAnswered] = useState<"approved" | "denied" | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [shown, setShown] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [phase, setPhase] = useState<"none" | "rereading" | "late">("none");
  const denyRef = useRef<HTMLButtonElement>(null);

  // A 200 answer shows at once; the server row wins as soon as it stops saying pending.
  const eff: ExtCall =
    call.approval === "pending" && answered
      ? { ...call, approval: answered, decided_via: "user" }
      : call;
  const state = missing ? "missing" : cardState(eff, busy !== null);
  const pending = state === "pending" || state === "busy";
  const msLeft = Date.parse(call.expires_at) - now;
  const zeroed = pending && msLeft <= 0;
  const disabled = busy !== null || (zeroed && phase !== "late");
  const id = call.id;

  // 1 s tick from expires_at - Date.now(), so a throttled tab self-corrects.
  useEffect(() => {
    if (!pending) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [pending]);

  // Local zero (clock skew): one re-read, then every 5 s until the server says terminal.
  useEffect(() => {
    if (!zeroed) return;
    if (phase === "none") {
      setPhase("rereading");
      onReread().finally(() => setPhase("late"));
      return;
    }
    if (phase !== "late") return;
    const t = setInterval(() => void onReread(), 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zeroed, phase]);

  // Appearance: announce once and, if it is safe, put focus on Deny.
  useEffect(() => {
    if (!live || !pending) return;
    onAnnounce(announce.appeared(call));
    if (canTakeFocus()) denyRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const minuteSaid = useRef(false);
  useEffect(() => {
    if (pending && msLeft > 0 && isLastMinute(msLeft) && !minuteSaid.current) {
      minuteSaid.current = true;
      onAnnounce(announce.oneMinute(call));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, msLeft]);

  const wasPending = useRef(pending);
  useEffect(() => {
    if (wasPending.current && !pending) onAnnounce(cardStatus(state, eff) || announce.terminal(eff));
    wasPending.current = pending;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  async function decide(approve: boolean) {
    setBusy(approve ? "allow" : "deny");
    setError(null);
    setStale(false);
    try {
      const r = await fetch(`/api/threads/${threadId}/ext-calls/${call.id}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ approve }),
      });
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        setAnswered((d?.approval ?? (approve ? "approved" : "denied")) === "approved" ? "approved" : "denied");
      } else if (r.status === 404) {
        setMissing(true);
      } else if (r.status === 409) {
        setStale(true);
        await onReread();
      } else {
        setError(await detailOf(r));
      }
    } catch {
      setError("Network error");
    } finally {
      setBusy(null);
    }
  }

  const status = cardStatus(state, eff);
  const ruleColor =
    pending ? tokens.color.ink : state === "failed" ? tokens.color.terracotta : tokens.color.border2;
  const showDetails = pending || (shown && state !== "missing");

  return (
    <article
      data-testid="ext-approval-card"
      data-call-id={id}
      data-state={state}
      aria-labelledby={`${id}-heading`}
      aria-describedby={showDetails ? `${id}-leaves` : undefined}
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border}`,
        borderLeft: `3px solid ${ruleColor}`,
        borderRadius: 14,
        padding: "18px 20px",
        marginTop: 16,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <div style={eyebrow}>EXTERNAL TOOL REQUEST</div>
      <h3
        id={`${id}-heading`}
        style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.4, color: tokens.color.ink, margin: 0, overflowWrap: "anywhere" }}
      >
        {call.server_slug} wants to run {call.tool}
      </h3>

      {pending && call.reason === "ledger_read" && (
        <p style={{ ...body14, color: tokens.color.muted3 }}>
          You set this tool to Always, but monai asks again after an answer has used your monai data.
        </p>
      )}

      {!pending && status && (
        <div
          style={
            state === "unknown"
              ? { ...body14, background: tokens.color.tintWarm, border: `1px solid ${tokens.color.border2}`, borderRadius: tokens.radius.sm, padding: "8px 12px" }
              : { ...body14, color: state === "failed" ? tokens.color.terracottaText : state === "missing" ? tokens.color.muted3 : tokens.color.ink }
          }
        >
          <p style={{ margin: 0 }}>{status}</p>
          {state === "sent" && <p style={{ margin: 0, color: tokens.color.muted3 }}>{SENT_NOTE}</p>}
        </div>
      )}

      {!pending && state !== "missing" && (
        <div>
          <button
            type="button"
            data-testid="ext-show-args"
            className="coarse-tap"
            aria-expanded={shown}
            aria-controls={`${id}-details`}
            onClick={() => setShown((s) => !s)}
            style={{ ...btnGhost, ...action }}
          >
            {shown ? "Hide arguments" : "Show arguments"}
          </button>
        </div>
      )}

      {showDetails && (
        <div id={`${id}-details`} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <dl style={{ display: "grid", gridTemplateColumns: "96px 1fr", columnGap: 16, rowGap: 12, margin: 0 }}>
            {[
              ["Server", call.server_slug],
              ["Tool", call.tool],
              ["Destination", call.destination],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt style={blockLabel}>{k}</dt>
                <dd style={{ ...body14, overflowWrap: "anywhere" }}>{v}</dd>
              </div>
            ))}
          </dl>

          <div
            id={`${id}-leaves`}
            data-testid="ext-leaves"
            style={{
              ...body14,
              background: call.leaves_machine ? tokens.color.tintWarm : tokens.color.tintNeutral,
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: tokens.radius.sm,
              padding: "12px 16px",
            }}
          >
            {call.leaves_machine ? (
              <>
                <span style={{ fontWeight: 600 }}>This leaves your computer.</span> The arguments below are sent to{" "}
                {call.destination}.
              </>
            ) : (
              <span style={{ fontWeight: 600 }}>Runs on this computer; the server may contact the internet.</span>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={blockLabel}>Arguments (sent exactly as shown)</span>
            <pre
              data-testid="ext-args"
              tabIndex={0}
              role="region"
              aria-label={`Arguments for ${call.tool}`}
              style={pre}
            >
              {JSON.stringify(call.args, null, 2)}
            </pre>
            <span style={caption}>monai sends these arguments and no others. They are not changed after you answer.</span>
          </div>
        </div>
      )}

      {pending && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <button
              ref={denyRef}
              type="button"
              data-testid="ext-deny"
              className="coarse-tap"
              aria-label={`Deny ${call.tool} on ${call.server_slug}`}
              disabled={disabled}
              onClick={() => void decide(false)}
              style={{ ...btnGhost, ...action, opacity: disabled ? 0.6 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
            >
              {busy === "deny" ? "Denying…" : "Deny"}
            </button>
            <button
              type="button"
              data-testid="ext-allow"
              className="coarse-tap"
              aria-label={`Allow once: run ${call.tool} on ${call.server_slug}`}
              disabled={disabled}
              onClick={() => void decide(true)}
              style={{ ...btn, ...action, opacity: disabled ? 0.6 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
            >
              {busy === "allow" ? "Allowing…" : "Allow once"}
            </button>
            <span
              data-testid="ext-countdown"
              style={{
                marginLeft: "auto",
                fontSize: 12,
                fontVariantNumeric: "tabular-nums",
                fontWeight: isLastMinute(msLeft) ? 600 : 400,
                color: isLastMinute(msLeft) ? tokens.color.ink : tokens.color.muted3,
              }}
            >
              {zeroed && phase === "late" ? "Auto-denies shortly" : countdownText(msLeft)}
            </span>
          </div>
        </>
      )}

      {stale && (
        <p style={{ ...body14, color: tokens.color.muted3 }}>That request had already been answered or had expired.</p>
      )}
      {error && (
        <p role="alert" style={{ ...body14, color: tokens.color.terracottaText }}>
          Couldn&apos;t send your answer: {error}. The request is still waiting.
        </p>
      )}
    </article>
  );
}
