"use client";

// ---------------------------------------------------------------------------
// InboxCard — one Inbox proposal card per 33-UI-SPEC section 3. Every action
// goes through the Next proxy, which attaches the approver key on the
// allowlisted routes only. The page owns each card's `phase`; this component
// owns only transient UI state (busy, error, discard confirm, row windowing,
// copy feedback). All backend text renders as JSX text nodes, never as markup.
// ---------------------------------------------------------------------------

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ProposalDiff from "../components/ProposalDiff";
import TransferLine from "../components/TransferLine";
import { extractDetail, fmtPlain } from "../lib/api";
import { rateChip } from "../lib/bond";
import { INBOX_SURFACE_HEADER } from "../lib/approverAllowlist";
import {
  ALL_SKIPPED_MSG,
  NETWORK_FAIL_MSG,
  approveLabel,
  approvedFooter,
  assumptionLines,
  cardTitle,
  duplicateChipText,
  fmtAbsolute,
  fmtRowDate,
  fmtSigned,
  hhmm,
  invariantBadge,
  isLocked,
  isUuid,
  KIND_LABEL,
  mapActionResponse,
  mergeSkip,
  pendingStatus,
  recordsHref,
  proposalFlagText,
  relativeAge,
  rowProvenance,
  skipAriaLabel,
  sourceLabel,
  sourceLine,
  transactionFlagText,
  uploadMeta,
  visibleRowIndices,
  type CardPhase,
  type DuplicateFlag,
  type HeldCard,
  type InboxAccount,
  type ProposalRow,
} from "../lib/inbox";
import { fmtAmountSigned } from "../lib/money";
import { btn, btnGhost, card as cardStyle, dangerBtn, input, tokens } from "../styles";

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
  categories: string[];
  /** Accounts by id, to name what edits and balance adjustments touch; empty until loaded. */
  accounts: ReadonlyMap<number, InboxAccount>;
};

const c = tokens.color;
const text = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

const smallBtn: React.CSSProperties = {
  ...btnGhost,
  fontSize: "var(--fs-body, 14px)",
  padding: "4px 12px",
  minHeight: 32,
};

const chip: React.CSSProperties = {
  fontSize: "var(--fs-xs, 12px)",
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

const greenChip: React.CSSProperties = { ...chip, color: c.ink, background: c.tintGreen };
const TONE = { green: greenChip, warm: warmChip, neutral: neutralChip };
const sentenceStyle: React.CSSProperties = { fontSize: "var(--fs-body, 14px)", color: c.muted3 };

const cell: React.CSSProperties = {
  fontSize: "var(--fs-body, 14px)",
  color: c.ink,
  padding: "12px 8px",
  borderTop: `1px solid ${c.borderInner}`,
  verticalAlign: "top",
};
const th: React.CSSProperties = {
  fontSize: "var(--fs-xs, 12px)",
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
      <ul style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3, listStyle: "none", margin: "4px 0 0", padding: 0 }}>
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

/** Scheduled coupon: the net amount, one sentence on how it was worked out, and Edit amount. */
function CouponBody({
  after,
  editable,
  editing,
  draft,
  blocked,
  saving,
  onEdit,
  onDraft,
  onSave,
  onCancel,
}: {
  after: Record<string, unknown>;
  editable: boolean;
  editing: boolean;
  draft: string;
  blocked: boolean;
  saving: boolean;
  onEdit: () => void;
  onDraft: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const amount = Number(after.amount);
  const expected = Number(after.gross) - Number(after.tax);
  const rate = Number(after.rate);
  const sentence =
    `${Number.isFinite(rate) ? rateChip(rate, after.floating === true) : "Coupon"} on ${fmtPlain(Number(after.nominal))}, ` +
    `after ${text(after.tax_pct)}% tax. Records income on ${text(after.account)} and a coupon on ${text(after.ticker)}.`;
  return (
    <div>
      <div
        data-testid="inbox-coupon-amount"
        style={{ fontFamily: tokens.font.serif, fontSize: 28, color: c.ink, fontVariantNumeric: "tabular-nums", overflowWrap: "anywhere" }}
      >
        +{fmtPlain(amount)} to {text(after.account)}
      </div>
      <p style={{ ...sentenceStyle, margin: "4px 0 0" }}>{sentence}</p>
      {Number.isFinite(expected) && expected !== amount && (
        <p style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3, margin: "4px 0 0" }}>Expected {fmtPlain(expected)}</p>
      )}
      {editable &&
        (editing ? (
          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              aria-label="Coupon amount"
              style={{ ...input, width: 160, ...gated(blocked) }}
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
            />
            <button type="button" style={{ ...smallBtn, ...gated(blocked) }} aria-disabled={blocked} onClick={onSave}>
              {saving ? "…" : "Save"}
            </button>
            <button type="button" style={smallBtn} onClick={onCancel}>
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" style={{ ...smallBtn, marginTop: 12 }} onClick={onEdit}>
            Edit amount
          </button>
        ))}
    </div>
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
  categories,
  accounts,
}: Props) {
  const p = card.proposal;
  const id = p.id;
  const rows = p.payload.rows ?? [];
  const op = p.operation;
  const live = card.phase === "live";
  const locked = isLocked(p);
  const skippedCount = rows.filter((r) => r.skip === true).length;
  // Skips the owner chose; a default skip (261121-kwu) is not a choice to protect on Reject.
  const chosenSkips = rows.filter((r) => r.skip === true && !r.skip_default).length;
  const allSkipped = op === "add_transaction" && rows.length > 0 && skippedCount === rows.length;

  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFallback, setCopyFallback] = useState(false);
  const [editAmount, setEditAmount] = useState(false);
  const [amountDraft, setAmountDraft] = useState("");

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
      // Rows skipped by default are only skipped in this view until saved (261121-kwu).
      for (let i = 0; i < rows.length; i++) {
        if (!rows[i].skip_default) continue;
        const s = await fetch(`/api/proposals/${id}/rows/${i}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...INBOX_SURFACE_HEADER },
          body: JSON.stringify({ skip: true }),
        });
        if (!s.ok) return fail(s);
      }
      const r = await fetch(`/api/proposals/${id}/approve`, {
        method: "POST",
        headers: INBOX_SURFACE_HEADER,
      });
      if (!r.ok) return fail(r);
      focusStatus.current = true;
      onSettle(id, "approved");
      announce("Proposal approved: " + approveLabel(op, rows));
    });
  }

  async function reject() {
    if (blocked) return;
    if (chosenSkips >= 1 && !confirmDiscard) {
      setConfirmDiscard(true);
      return;
    }
    setConfirmDiscard(false);
    await act("reject", async () => {
      const r = await fetch(`/api/proposals/${id}/reject`, {
        method: "POST",
        headers: INBOX_SURFACE_HEADER,
      });
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
        headers: { "Content-Type": "application/json", ...INBOX_SURFACE_HEADER },
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

  async function setCategory(i: number, value: string | null) {
    if (blocked) return;
    await act(i, async () => {
      const r = await fetch(`/api/proposals/${id}/rows/${i}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...INBOX_SURFACE_HEADER },
        body: JSON.stringify({ category: value }),
      });
      if (!r.ok) return fail(r);
      // The UI only sends names from the server's own list (or null), so the sent value is what is stored.
      onRows(
        id,
        rows.map((row, k) => {
          if (k !== i) return row;
          const { category_suggested: _drop, ...rest } = row; // the server drops it too
          return { ...rest, after: { ...row.after, category: value } };
        })
      );
      announce(`Row ${i + 1} category set to ${value ?? "Uncategorized"}.`);
    });
  }

  async function saveAmount() {
    const n = Number(amountDraft);
    if (blocked || amountDraft.trim() === "" || !Number.isFinite(n) || n <= 0) return;
    await act(0, async () => {
      const r = await fetch(`/api/proposals/${id}/rows/0`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...INBOX_SURFACE_HEADER },
        body: JSON.stringify({ amount: n }),
      });
      if (!r.ok) return fail(r);
      onRows(id, rows.map((row, k) => (k === 0 ? { ...row, after: { ...row.after, amount: String(n) } } : row)));
      setEditAmount(false);
      announce(`Coupon amount set to ${fmtPlain(n)}.`);
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
    // A way to see what was just written (261121-kwu); undo is still Records' row menu.
    status = (
      <>
        {"✓ Approved · " + hhmm(card.settledAt ?? nowMs) + " · "}
        <Link href={recordsHref(p, accounts)} style={{ color: c.green, textDecoration: "underline" }}>
          View in Records
        </Link>
      </>
    );
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

  const upload = uploadMeta(p);
  const badge = upload && invariantBadge(upload, rows.length, text(rows[0]?.after?.currency));
  const code = typeof p.code === "string" && p.code !== "" ? p.code : null;
  const blockedDescribedBy = offline ? offlineBannerId : undefined;

  const transfer = rows[0]?.after as
    | { leg_a?: Record<string, unknown>; leg_b?: Record<string, unknown> }
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
          <span style={neutralChip}>{sourceLabel(p.channel)}</span>
        </div>
        <span
          id={`inbox-status-${id}`}
          ref={statusRef}
          tabIndex={-1}
          style={{ fontSize: "var(--fs-xs, 12px)", fontWeight: 600, color: statusColor }}
        >
          {status}
        </span>
      </div>
      <div style={{ marginTop: 4, fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>
        Proposed {relativeAge(Date.parse(p.created_at), nowMs)}
      </div>

      {/* upload provenance: before the rows, so the trust statement is read first (D-23) */}
      {upload && badge && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>File</span>
          <span
            data-testid="inbox-upload-file"
            style={{ fontSize: "var(--fs-body, 14px)", fontWeight: 600, color: c.ink, overflowWrap: "anywhere" }}
          >
            {text(upload.filename)}
          </span>
          <span style={{ ...sentenceStyle, fontVariantNumeric: "tabular-nums" }}>
            {" · "}
            {KIND_LABEL[upload.kind] ?? text(upload.kind)} · {rows.length} rows
          </span>
          <span data-testid="inbox-invariant-badge" style={TONE[badge.tone]}>
            {badge.text}
          </span>
          <span style={sentenceStyle}>{badge.sentence}</span>
          {assumptionLines(upload).length > 0 && (
            <>
              <span style={warmChip}>Format assumed</span>
              {assumptionLines(upload).map((line, k) => (
                <span key={k} style={sentenceStyle}>{line}</span>
              ))}
            </>
          )}
        </div>
      )}

      {/* MCP code */}
      {live && p.channel === "mcp" && code && (
        <>
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>Code</span>
            <code
              ref={codeRef}
              tabIndex={0}
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                fontSize: "var(--fs-body, 14px)",
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
              <span style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>Select the code and press Ctrl+C</span>
            )}
          </div>
          <p style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3, margin: "8px 0 0" }}>
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
                  const prov = rowProvenance(row);
                  const src = sourceLine(row);
                  return [
                    <tr key={`r${i}`} className="inbox-row">
                      <td className="inbox-c-num" style={{ ...cell, color: tone }}>{i + 1}</td>
                      <td className="inbox-c-date" style={{ ...cell, color: tone }}>{fmtRowDate(a.date)}</td>
                      <td className="inbox-c-merchant" style={{ ...cell, color: tone }}>
                        {skipped && <span style={{ ...neutralChip, marginRight: 8 }}>Skipped</span>}
                        <span style={struck}>{text(a.merchant) || "–"}</span>
                        {text(a.notes) !== "" && (
                          <div style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>{text(a.notes)}</div>
                        )}
                      </td>
                      <td className="inbox-c-account" style={{ ...cell, color: tone }}>{text(a.account)}</td>
                      <td className="inbox-c-category" style={{ ...cell, color: text(a.category) ? tone : c.muted3 }}>
                        {live ? (
                          <>
                          <select
                            style={{ ...input, padding: "4px 8px", width: "auto", color: "inherit", ...gated(blocked) }}
                            aria-label={`Category for row ${i + 1}: ${text(a.merchant) || "no merchant"}`}
                            aria-disabled={blocked}
                            aria-describedby={
                              [row.category_suggested === true ? `inbox-sugg-${id}-${i}` : undefined, blockedDescribedBy]
                                .filter(Boolean)
                                .join(" ") || undefined
                            }
                            value={text(a.category)}
                            onChange={(e) => void setCategory(i, e.target.value || null)}
                          >
                            <option value="">Uncategorized</option>
                            {[...categories, ...(text(a.category) && !categories.includes(text(a.category)) ? [text(a.category)] : [])].map((n) => (
                              <option key={n} value={n}>{n}</option>
                            ))}
                          </select>
                          {row.category_suggested === true && (
                            <span
                              id={`inbox-sugg-${id}-${i}`}
                              style={{ ...neutralChip, marginLeft: 8 }}
                              title="Picked from past transactions at this merchant. Approving keeps it."
                            >
                              Suggested
                            </span>
                          )}
                          </>
                        ) : (
                          text(a.category) || "Uncategorized"
                        )}
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
                        {text(a.currency) === "USD" ? fmtAmountSigned(Number(a.amount), "USD") : fmtSigned(a.amount)}
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
                    (flags.length > 0 || prov.length > 0) && (
                      <tr key={`f${i}`} className="inbox-flag-row">
                        <td colSpan={7} style={{ padding: "0 8px 12px" }}>
                          {flags.length > 0 && <DuplicateFlags flags={flags} selfId={id} onPageIds={onPageIds} />}
                          {row.skip_default && row.skip && (
                            <div style={{ marginTop: 4, fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>
                              Skipped by default because it matches an existing record. Include it if it&apos;s new.
                            </div>
                          )}
                          {prov.map((item, k) => (
                            <div key={k} style={{ marginTop: 4 }}>
                              <span style={warmChip}>{item.chip}</span>{" "}
                              <span style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>{item.line}</span>
                            </div>
                          ))}
                          {src && (
                            <div style={{ marginTop: 4, fontSize: "var(--fs-xs, 12px)", color: c.muted3, overflowWrap: "anywhere" }}>
                              {src}
                            </div>
                          )}
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
                  <span style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>
                    {rows.length - visibleRowIndices(rows, false).length} rows hidden
                  </span>
                )}
              </div>
            )}
          </>
        ) : op === "add_transfer" ? (
          <>
            <TransferLine legA={transfer?.leg_a} legB={transfer?.leg_b} showRate />
            {flagsOf(rows[0]).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <DuplicateFlags flags={flagsOf(rows[0])} selfId={id} onPageIds={onPageIds} />
              </div>
            )}
          </>
        ) : op === "add_balance_adjustment" ? (
          <BalanceLine row={rows[0]} accounts={accounts} />
        ) : op === "add_coupon" ? (
          <CouponBody
            after={rows[0]?.after ?? {}}
            editable={live}
            editing={editAmount}
            draft={amountDraft}
            blocked={blocked}
            saving={busy === 0}
            onEdit={() => {
              setAmountDraft(text(rows[0]?.after?.amount));
              setEditAmount(true);
            }}
            onDraft={setAmountDraft}
            onSave={() => void saveAmount()}
            onCancel={() => setEditAmount(false)}
          />
        ) : (
          <>
            {p.channel === "schedule" && op === "add_funded_sell" && (
              <p style={{ ...sentenceStyle, margin: "0 0 12px" }}>
                Matured {fmtRowDate(rows[0]?.after?.date)}: sells {text(rows[0]?.after?.ticker)} at face value into{" "}
                {text(rows[0]?.after?.source_account_name)}. Record any coupon for it first; a closed bond takes no
                more coupons.
              </p>
            )}
            {(op === "edit_transaction" || op === "delete_transaction") && (
              <TargetLine before={rows[0]?.before} accounts={accounts} />
            )}
            <ProposalDiff
              rows={rows.map(({ duplicates: _d, skip: _s, ...diffRow }) => diffRow)}
              dimColor={tokens.color.muted3}
            />
          </>
        )}
      </div>

      {/* footer */}
      {live && (
        <div
          className="inbox-footer"
          // Say what a slow approve or reject is doing (261121-m17), not a bare "…".
          aria-busy={busy === "approve" || busy === "reject" || undefined}
          style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
          onKeyDown={(e) => {
            if (confirmDiscard && e.key === "Escape") setConfirmDiscard(false);
          }}
        >
          {confirmDiscard ? (
            <>
              <span style={{ fontSize: "var(--fs-body, 14px)", color: c.ink }}>
                Discard this proposal and your skip choices on {chosenSkips}{" "}
                {chosenSkips === 1 ? "row" : "rows"}?
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
                {busy === "approve" ? "Applying…" : allSkipped ? "Nothing left to add" : approveLabel(op, rows)}
              </button>
              {allSkipped && (
                <span id={`inbox-allskipped-${id}`} style={{ fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>
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
                {busy === "reject" ? "Rejecting…" : "Reject and discard"}
              </button>
              <span style={{ marginLeft: "auto", fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>
                {pendingStatus(expiresMs, nowMs)}
              </span>
            </>
          )}
        </div>
      )}
      {card.phase === "approved" && (
        <div style={{ marginTop: 16, fontSize: "var(--fs-xs, 12px)", color: c.muted3 }}>{approvedFooter(op, rows)}</div>
      )}

      {error && (
        <p role="alert" style={{ fontSize: "var(--fs-xs, 12px)", color: c.terracotta, margin: "8px 0 0" }}>
          {error}
        </p>
      )}
    </article>
  );
}

// The transaction an edit or delete changes, so the diff is never judged blind
// (261121-kwu): `before` is the whole row (backend _tx_to_dict).
function TargetLine({
  before,
  accounts,
}: {
  before: Record<string, unknown> | null | undefined;
  accounts: ReadonlyMap<number, InboxAccount>;
}) {
  if (!before) return null;
  const acc = accounts.get(Number(before.account_id));
  const parts = [
    fmtRowDate(before.date),
    text(before.merchant) || null,
    acc ? acc.name : before.account_id != null ? `account #${text(before.account_id)}` : null,
    `${fmtSigned(before.amount)}${before.currency && before.currency !== "IDR" ? ` ${text(before.currency)}` : ""}`,
  ].filter(Boolean);
  return (
    <p style={{ fontSize: "var(--fs-body, 14px)", color: c.ink, margin: "0 0 10px" }}>
      <span style={{ color: c.muted3 }}>Transaction: </span>
      {parts.join(" · ")}
    </p>
  );
}

// A balance adjustment overwrites an account's balance: name the account and
// show what it is now and how much moves (261121-kwu). Ids only as a fallback.
function BalanceLine({
  row,
  accounts,
}: {
  row: ProposalRow | undefined;
  accounts: ReadonlyMap<number, InboxAccount>;
}) {
  const acc = accounts.get(Number(row?.account_id));
  const target = Number(row?.target_balance);
  const now = acc?.current_balance;
  const known = acc != null && now != null && Number.isFinite(target);
  return (
    <div style={{ fontSize: "var(--fs-body, 14px)", color: c.ink }}>
      <div>
        Set {acc ? acc.name : `account #${text(row?.account_id)}`} balance to {fmtAbsolute(row?.target_balance)}
        {acc && acc.currency !== "IDR" ? ` ${acc.currency}` : ""}
      </div>
      {known && (
        <div style={{ marginTop: 4, color: c.muted3, fontSize: "var(--fs-xs, 12px)" }}>
          Now {fmtAbsolute(now)} · change {fmtSigned(target - (now as number))}
        </div>
      )}
    </div>
  );
}
