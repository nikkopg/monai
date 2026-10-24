"use client";

import Link from "next/link";

import { tokens } from "../styles";
import { cardSentence, cardTrustLine } from "./attachLabels";

// ---------------------------------------------------------------------------
// UploadCard (39-UI-SPEC section 5): the chat card for a proposal with channel
// "upload". No Approve, Reject, token, countdown or diff; the owner decides in
// the Inbox. A decided proposal drops the link (no dead "Review").
// ---------------------------------------------------------------------------

export type UploadMeta = {
  id: string;
  filename: string;
  kind: string;
  row_count: number;
  invariant: string | null;
  opening?: string | null;
  closing?: string | null;
  llm_read: boolean;
  flagged_count: number;
  assumptions?: string[];
};

export default function UploadCard({
  proposal,
  status,
}: {
  proposal: { id: string; payload?: { attachment?: UploadMeta } | null };
  status?: string;
}) {
  const meta = proposal.payload?.attachment;
  if (!meta) return null;
  const s = cardSentence(meta.row_count, meta.flagged_count, status);
  const trust = cardTrustLine(status, meta);
  const sentenceId = `${proposal.id}-sentence`;
  return (
    <article
      data-testid="upload-card"
      aria-labelledby={sentenceId}
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border}`,
        borderLeft: `3px solid ${tokens.color.border2}`,
        borderRadius: 14,
        padding: "18px 20px",
        marginTop: 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", color: tokens.color.muted3 }}>
        Upload
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{meta.filename}</div>
      <div
        id={sentenceId}
        style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.4, color: tokens.color.ink, fontVariantNumeric: "tabular-nums" }}
      >
        {s.lead}
        {s.linked ? (
          <Link
            href={"/inbox#proposal-" + proposal.id}
            data-testid="upload-card-link"
            className="coarse-tap"
            aria-label={"Review in Inbox: " + meta.filename}
            style={{ color: tokens.color.ink, textDecoration: "underline", textUnderlineOffset: 4, display: "inline-block", padding: "6px 0" }}
          >
            {s.tail}
            <span aria-hidden="true"> ›</span>
          </Link>
        ) : (
          s.tail
        )}
      </div>
      {trust && <div style={{ fontSize: 14, lineHeight: 1.5, color: tokens.color.muted3 }}>{trust}</div>}
    </article>
  );
}
