"use client";

// ---------------------------------------------------------------------------
// InboxCard — one Inbox proposal card per 33-UI-SPEC section 3. Every action
// goes through the Next proxy, which attaches the approver key on the
// allowlisted routes only. The page owns each card's `phase`; this component
// owns only transient UI state (busy, error, discard confirm, row windowing,
// copy feedback). All backend text renders as JSX text nodes, never as markup.
// ---------------------------------------------------------------------------

import { useEffect, useRef, useState } from "react";
import ProposalDiff from "../components/ProposalDiff";
import { extractDetail } from "../lib/api";
import {
  ALL_SKIPPED_MSG,
  NETWORK_FAIL_MSG,
  approveLabel,
  approvedFooter,
  cardTitle,
  duplicateChipText,
  fmtRowDate,
  fmtSigned,
  fmtUnsigned,
  hhmm,
  isLocked,
  isUuid,
  mapActionResponse,
  mergeSkip,
  pendingStatus,
  proposalFlagText,
  relativeAge,
  skipAriaLabel,
  transactionFlagText,
  visibleRowIndices,
  type CardPhase,
  type DuplicateFlag,
  type HeldCard,
  type ProposalRow,
} from "../lib/inbox";
import { btn, btnGhost, card as cardStyle, dangerBtn, tokens } from "../styles";

type Busy = null | "approve" | "reject" | number;

type Props = {
  card: HeldCard;
  nowMs: number;
  offline: boolean;
  offlineBannerId: string;
  onPageIds: ReadonlySet<string>;
  replacementId: string | null;
  onBusy: (id: string, busy: boolean) => void;
  onSettle: (id: string, phase: CardPhase) => void;
  onRows: (id: string, rows: ProposalRow[]) => void;
  announce: (msg: string) => void;
};

const c = tokens.color;
const text = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

const smallBtn: React.CSSProperties = {
  ...btnGhost,
  fontSize: 14,
  padding: "4px 12px",
  minHeight: 32,
};

const chip: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  borderRadius: tokens.radius.pill,
  padding: "4px 12px",
  display: "inline-block",
};
const neutralChip: React.CSSProperties = { ...chip, color: c.muted3, background: c.tintNeutral };
const warmChip: React.CSSProperties = {
  ...chip,
  color: c.ink,
  background: c.tintWarm,
  border: `1px solid ${c.border2}`,
};

const cell: React.CSSProperties = {
  fontSize: 14,
  color: c.ink,
  padding: "12px 8px",
  borderTop: `1px solid ${c.borderInner}`,
  verticalAlign: "top",
};
const th: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 400,
  color: c.muted3,
  textAlign: "left",
  padding: "0 8px 8px",
};

const gated = (blocked: boolean): React.CSSProperties =>
  blocked ? { cursor: "not-allowed", opacity: 0.6 } : {};

/** Duplicate chip plus one line per flag, shared by table rows and the transfer line. */
function DuplicateFlags({
  flags,
  selfId,
  onPageIds,
}: {
  flags: DuplicateFlag[];
  selfId: string;
  onPageIds: ReadonlySet<string>;
}) {
  return (
    <>
      <span style={warmChip}>{duplicateChipText(flags.length)}</span>
      <ul style={{ fontSize: 12, color: c.muted3, listStyle: "none", margin: "4px 0 0", padding: 0 }}>
        {flags.map((flag, k) => (
          <li key={k}>
            {flag.kind === "transaction" ? (
              transactionFlagText(flag)
            ) : (
              <>
                {proposalFlagText(flag)}
                {isUuid(flag.id) && onPageIds.has(flag.id) && flag.id !== selfId && (
                  <>
                    {" "}
                    <a href={`#proposal-${flag.id}`} style={{ color: c.ink, textDecoration: "underline" }}>
                      Go to that proposal
                    </a>
                  </>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export default function InboxCard({
  card,
  nowMs,
  offline,
  offlineBannerId,
  onPageIds,
  replacementId,
  onBusy,
  onSettle,
  onRows,
  announce,
}: Props) {
  const p = card.proposal;
  const id = p.id;
  const rows = p.payload.rows ?? [];
  const op = p.operation;
  const live = card.phase === "live";
  const locked = isLocked(p);
  const skippedCount = rows.filter((r) => r.skip === true).length;
  const allSkipped = op === "add_transaction" && rows.length > 0 && skippedCount === rows.length;

  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFallback, setCopyFallback] = useState(false);

  const blocked = offline || busy !== null;

  const statusRef = useRef<HTMLSpanElement>(null);
  const codeRef = useRef<HTMLElement>(null);
  const rejectRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const focusStatus = useRef(false);
  const wasConfirming = useRef(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimer.current !== null) clearTimeout(copyTimer.current);
  }, []);

  // After a local approve or reject, move focus to the status label.
  useEffect(() => {
    if (focusStatus.current && card.phase !== "live") {
      focusStatus.current = false;
      statusRef.current?.focus();
    }
  }, [card.phase]);

  // Two-step discard: focus the safe button on open, return to Reject on close.
  useEffect(() => {
    if (confirmDiscard) {
      wasConfirming.current = true;
      keepRef.current?.focus();
    } else if (wasConfirming.current) {
      wasConfirming.current = false;
      rejectRef.current?.focus();
    }
  }, [confirmDiscard]);

  async function act(kind: Busy, fn: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    onBusy(id, true);
    try {
      await fn();
    } catch {
      setError("Couldn't apply: " + NETWORK_FAIL_MSG);
    } finally {
      setBusy(null);
      onBusy(id, false);
    }
  }

  /** Map a non-2xx response onto a phase and/or an error line. */
  async function fail(r: Response) {
    const o = mapActionResponse(r.status, await extractDetail(r));
    if (o.kind === "phase") {
      onSettle(id, o.phase);
      if (o.message) setError(o.message);
    } else if (o.kind === "error") {
      setError(o.message);
    }
  }

  async function approve() {
    if (blocked || allSkipped) return;
    await act("approve", async () => {
      const r = await fetch(`/api/proposals/${id}/approve`, { method: "POST" });
      if (!r.ok) return fail(r);
      focusStatus.current = true;
      onSettle(id, "approved");
      announce("Proposal approved: " + approveLabel(op, rows));
    });
  }

  async function reject() {
    if (blocked) return;
    if (skippedCount >= 1 && !confirmDiscard) {
      setConfirmDiscard(true);
      return;
    }
    setConfirmDiscard(false);
    await act("reject", async () => {
      const r = await fetch(`/api/proposals/${id}/reject`, { method: "POST" });
      if (!r.ok) return fail(r);
      focusStatus.current = true;
      onSettle(id, "rejected");
      announce("Proposal rejected. Nothing changed.");
    });
  }

  async function skip(i: number) {
    if (blocked) return;
    const next = !(rows[i].skip === true);
    await act(i, async () => {
      const r = await fetch(`/api/proposals/${id}/rows/${i}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skip: next }),
      });
      if (!r.ok) return fail(r);
      let resp: unknown = null;
      try {
        resp = (await r.json())?.payload?.rows;
      } catch {
        // unusable body: fall back to the local flip below
      }
      const merged = Array.isArray(resp)
        ? mergeSkip(rows, resp as ProposalRow[])
        : rows.map((row, k) => (k === i ? { ...row, skip: next } : row));
      onRows(id, merged);
      if (merged.every((row) => row.skip === true)) {
        announce(`Row ${i + 1} skipped. ${ALL_SKIPPED_MSG}`);
      } else {
        const label = approveLabel(op, merged);
        announce(
          `Row ${i + 1} ${next ? "skipped" : "included"}. Approve will ${
            label.charAt(0).toLowerCase() + label.slice(1)
          }`
        );
      }
    });
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopyFallback(false);
      setCopied(true);
      announce("Code copied");
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API missing or rejected
      setCopyFallback(true);
      codeRef.current?.focus();
    }
  }

  // ---- header status ------------------------------------------------------
  const expiresMs = Date.parse(p.expires_at);
  let status: React.ReactNode;
  let statusColor: string = c.muted3;
  if (live) {
    if (busy === "approve") status = "Applying…";
    else if (locked) {
      status = (
        <span style={{ ...chip, color: c.ink, background: c.tintWarm, border: `1px solid ${c.border2}` }}>
          Locked after 5 wrong codes · approve here
        </span>
      );
    } else {
      status = pendingStatus(expiresMs, nowMs);
      statusColor = c.ink;
    }
  } else if (card.phase === "approved") {
    status = "✓ Approved · " + hhmm(card.settledAt ?? nowMs);
    statusColor = c.green;
  } else if (card.phase === "approvedElsewhere") {
    status = "✓ Approved elsewhere";
    statusColor = c.green;
  } else if (card.phase === "rejected") {
    status = "Rejected · nothing changed";
  } else if (card.phase === "rejectedElsewhere") {
    status = "Rejected elsewhere · nothing changed";
  } else if (card.phase === "expired") {
    status = "Expired · ask again to redo this";
  } else if (card.phase === "superseded") {
    status = (
      <>
        Replaced by a newer version
        {replacementId && (
          <>
            {" "}
            <a href={`#proposal-${replacementId}`} style={{ color: c.ink, textDecoration: "underline" }}>
              Go to the new one
            </a>
          </>
        )}
      </>
    );
  } else {
    status = "Decided elsewhere";
  }

  const sourceLabel = p.channel === "mcp" ? "Claude" : p.channel === "chat" ? "monai chat" : p.channel;
  const code = typeof p.code === "string" && p.code !== "" ? p.code : null;
  const blockedDescribedBy = offline ? offlineBannerId : undefined;

  const transfer = rows[0]?.after as
    | { leg_a?: Record<string, unknown>; leg_b?: Record<string, unknown> }
    | undefined;
  const investTransfer = rows[0]?.after as
    | { cash_leg?: Record<string, unknown>; event?: Record<string, unknown> }
    | undefined;
  const flagsOf = (r: ProposalRow | undefined) => r?.duplicates ?? [];

  return (
    <article
      id={`proposal-${id}`}
      aria-labelledby={`inbox-title-${id}`}
      style={{ ...cardStyle, marginBottom: 0 }}
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <h2
            id={`inbox-title-${id}`}
            style={{ fontFamily: tokens.font.serif, fontSize: 20, fontWeight: 400, margin: 0 }}
          >
            {cardTitle(op, rows)}
          </h2>
          <span style={neutralChip}>{sourceLabel}</span>
        </div>
        <span
          id={`inbox-status-${id}`}
          ref={statusRef}
          tabIndex={-1}
          style={{ fontSize: 12, fontWeight: 600, color: statusColor }}
        >
          {status}
        </span>
      </div>
      <div style={{ marginTop: 4, fontSize: 12, color: c.muted3 }}>
        Proposed {relativeAge(Date.parse(p.created_at), nowMs)}
      </div>

      {/* MCP code */}
      {live && p.channel === "mcp" && code && (
        <>
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: c.muted3 }}>Code</span>
            <code
              ref={codeRef}
              tabIndex={0}
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                fontSize: 14,
                fontWeight: 600,
                letterSpacing: ".14em",
                color: c.ink,
                background: c.inputBg,
                border: `1px solid ${c.border2}`,
                borderRadius: tokens.radius.sm,
                padding: "8px 12px",
                userSelect: "all",
              }}
            >
              {code}
            </code>
            <button
              type="button"
              style={smallBtn}
              aria-label="Copy confirm code"
              onClick={() => void copyCode(code)}
            >
              {copied ? "Copied" : "Copy code"}
            </button>
            {copyFallback && (
              <span style={{ fontSize: 12, color: c.muted3 }}>Select the code and press Ctrl+C</span>
            )}
          </div>
          <p style={{ fontSize: 12, color: c.muted3, margin: "8px 0 0" }}>
            Tell Claude this code to approve it there. You don't need it to approve here.
            {locked && " Claude can no longer approve this with the code. You still can."}
          </p>
        </>
      )}

      {/* rows */}
      <div style={{ marginTop: 16 }}>
        {op === "add_transaction" ? (
          <>
            <table id={`inbox-rows-${id}`} className="inbox-table" style={{ borderCollapse: "collapse", width: "100%" }}>
              <caption className="sr-only">Rows in this proposal</caption>
              <thead>
                <tr>
                  <th scope="col" style={th}>#</th>
                  <th scope="col" style={th}>Date</th>
                  <th scope="col" style={th}>Merchant</th>
                  <th scope="col" style={th}>Account</th>
                  <th scope="col" style={th}>Category</th>
                  <th scope="col" style={{ ...th, textAlign: "right" }}>Amount</th>
                  <th scope="col" style={th}>
                    <span className="sr-only">Skip</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleRowIndices(rows, expanded).map((i) => {
                  const row = rows[i];
                  const a = row.after ?? {};
                  const skipped = row.skip === true;
                  const tone = skipped ? c.muted3 : c.ink;
                  const struck: React.CSSProperties = skipped ? { textDecoration: "line-through" } : {};
                  const flags = flagsOf(row);
                  return [
                    <tr key={`r${i}`} className="inbox-row">
                      <td className="inbox-c-num" style={{ ...cell, color: tone }}>{i + 1}</td>
                      <td className="inbox-c-date" style={{ ...cell, color: tone }}>{fmtRowDate(a.date)}</td>
                      <td className="inbox-c-merchant" style={{ ...cell, color: tone }}>
                        {skipped && <span style={{ ...neutralChip, marginRight: 8 }}>Skipped</span>}
                        <span style={struck}>{text(a.merchant) || "—"}</span>
                        {text(a.notes) !== "" && (
                          <div style={{ fontSize: 12, color: c.muted3 }}>{text(a.notes)}</div>
                        )}
                      </td>
                      <td className="inbox-c-account" style={{ ...cell, color: tone }}>{text(a.account)}</td>
                      <td className="inbox-c-category" style={{ ...cell, color: text(a.category) ? tone : c.muted3 }}>
                        {text(a.category) || "Uncategorized"}
                      </td>
                      <td
                        className="inbox-c-amount"
                        style={{
                          ...cell,
                          color: tone,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          ...struck,
                        }}
                      >
                        {fmtSigned(a.amount)}
                      </td>
                      <td className="inbox-c-skip" style={cell}>
                        {live && (
                          <button
                            type="button"
                            style={{ ...smallBtn, minWidth: 72, ...gated(blocked) }}
                            aria-label={skipAriaLabel(i, row)}
                            aria-disabled={blocked}
                            aria-describedby={blockedDescribedBy}
                            onClick={() => void skip(i)}
                          >
                            {busy === i ? "…" : skipped ? "Include" : "Skip"}
                          </button>
                        )}
                      </td>
                    </tr>,
                    flags.length > 0 && (
                      <tr key={`f${i}`} className="inbox-flag-row">
                        <td colSpan={7} style={{ padding: "0 8px 12px" }}>
                          <DuplicateFlags flags={flags} selfId={id} onPageIds={onPageIds} />
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
            {rows.length > 8 && (
              <div style={{ marginTop: 8, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  type="button"
                  style={smallBtn}
                  aria-expanded={expanded}
                  aria-controls={`inbox-rows-${id}`}
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? "Show fewer rows" : `Show all ${rows.length} rows`}
                </button>
                {!expanded && (
                  <span style={{ fontSize: 12, color: c.muted3 }}>
                    {rows.length - visibleRowIndices(rows, false).length} rows hidden
                  </span>
                )}
              </div>
            )}
          </>
        ) : op === "add_transfer" ? (
          <>
            <div style={{ fontSize: 14, color: c.ink }}>
              Transfer {fmtUnsigned(transfer?.leg_a?.amount)} from {text(transfer?.leg_a?.account)} to{" "}
              {text(transfer?.leg_b?.account)} on {fmtRowDate(transfer?.leg_a?.date)}
            </div>
            {flagsOf(rows[0]).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <DuplicateFlags flags={flagsOf(rows[0])} selfId={id} onPageIds={onPageIds} />
              </div>
            )}
          </>
        ) : op === "add_balance_adjustment" ? (
          <div style={{ fontSize: 14, color: c.ink }}>
            Set account #{text(rows[0]?.account_id)} balance to {fmtSigned(rows[0]?.target_balance)}
          </div>
        ) : op === "add_investment_transfer" ? (
          <>
            <div style={{ fontSize: 14, color: c.ink }}>
              Move {fmtUnsigned(investTransfer?.cash_leg?.amount)} {text(investTransfer?.cash_leg?.currency)} from{" "}
              {text(investTransfer?.cash_leg?.account)} to platform #{text(investTransfer?.event?.platform_id)} on{" "}
              {fmtRowDate(investTransfer?.cash_leg?.date)}
            </div>
            {text(investTransfer?.cash_leg?.notes) !== "" && (
              <div style={{ fontSize: 12, color: c.muted3, marginTop: 4 }}>
                {text(investTransfer?.cash_leg?.notes)}
              </div>
            )}
          </>
        ) : (
          <ProposalDiff rows={rows} dimColor={tokens.color.muted3} />
        )}
      </div>

      {/* footer */}
      {live && (
        <div
          className="inbox-footer"
          style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
          onKeyDown={(e) => {
            if (confirmDiscard && e.key === "Escape") setConfirmDiscard(false);
          }}
        >
          {confirmDiscard ? (
            <>
              <span style={{ fontSize: 14, color: c.ink }}>
                Discard this proposal and your skip choices on {skippedCount}{" "}
                {skippedCount === 1 ? "row" : "rows"}?
              </span>
              <button
                type="button"
                style={{ ...dangerBtn, minHeight: 40, ...gated(blocked) }}
                aria-disabled={blocked}
                aria-describedby={blockedDescribedBy}
                onClick={() => void reject()}
              >
                Discard proposal
              </button>
              <button
                type="button"
                ref={keepRef}
                style={{ ...btnGhost, minHeight: 40 }}
                onClick={() => setConfirmDiscard(false)}
              >
                Keep it
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="inbox-approve"
                style={{ ...btn, minHeight: 40, ...gated(blocked || allSkipped) }}
                aria-disabled={blocked || allSkipped}
                aria-describedby={offline ? offlineBannerId : allSkipped ? `inbox-allskipped-${id}` : undefined}
                onClick={() => void approve()}
              >
                <span className="sr-only">Approve: </span>
                {busy === "approve" ? "…" : allSkipped ? "Nothing left to add" : approveLabel(op, rows)}
              </button>
              {allSkipped && (
                <span id={`inbox-allskipped-${id}`} style={{ fontSize: 12, color: c.muted3 }}>
                  {ALL_SKIPPED_MSG}
                </span>
              )}
              <button
                type="button"
                ref={rejectRef}
                style={{ ...btnGhost, minHeight: 40, ...gated(blocked) }}
                aria-disabled={blocked}
                aria-describedby={blockedDescribedBy}
                onClick={() => void reject()}
              >
                {busy === "reject" ? "…" : "Reject and discard"}
              </button>
              <span style={{ marginLeft: "auto", fontSize: 12, color: c.muted3 }}>
                {pendingStatus(expiresMs, nowMs)}
              </span>
            </>
          )}
        </div>
      )}
      {card.phase === "approved" && (
        <div style={{ marginTop: 16, fontSize: 12, color: c.muted3 }}>{approvedFooter(op, rows)}</div>
      )}

      {error && (
        <p role="alert" style={{ fontSize: 12, color: c.terracotta, margin: "8px 0 0" }}>
          {error}
        </p>
      )}
    </article>
  );
}
