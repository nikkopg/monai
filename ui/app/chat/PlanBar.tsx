"use client";

// Plan bar (38 D-16, D-17): one line above two or more proposal cards stating
// the order, plus "Approve all", a client loop over the existing confirm route.
// Each change stays its own confirm with its own single-use token and audit
// row; the loop stops at the first failure. The persisted order is creation
// order (D-14), so the array order is the plan order.

import { useEffect, useState } from "react";
import { clearProposalToken, confirmProposal, readProposalToken } from "./ProposalCard";
import type { Proposal } from "./ProposalCard";
import { btn, tokens } from "../styles";

export default function PlanBar({
  proposals,
  onApplied,
  onFailed,
  onRunning,
}: {
  proposals: Proposal[];
  onApplied: (id: string) => void;
  onFailed: (id: string, text: string) => void;
  onRunning: (running: boolean) => void;
}) {
  const [ready, setReady] = useState(false);
  const [running, setRunning] = useState<number | null>(null); // 1-based index
  const [status, setStatus] = useState("");
  const n = proposals.length;

  // Storage is read only in an effect (hydration); re-check as expiries pass.
  useEffect(() => {
    const check = () =>
      setReady(
        proposals.every(
          (p) =>
            (p.liveStatus === undefined || p.liveStatus === "pending") &&
            !p.rejectedByStop &&
            (p.payload?.rows ?? []).length > 0 &&
            p.expiresAt !== null &&
            p.expiresAt.getTime() > Date.now() &&
            (p.token ?? readProposalToken(p.id)) !== null
        )
      );
    check();
    const t = setInterval(check, 10_000);
    return () => clearInterval(t);
  }, [proposals]);

  if (n < 2) return null;

  async function approveAll() {
    onRunning(true);
    setStatus("");
    let k = 0;
    try {
      for (const p of proposals) {
        setRunning(k + 1);
        const r = await confirmProposal(p.id, p.token ?? readProposalToken(p.id));
        if (!r.ok) {
          onFailed(p.id, r.text);
          setStatus(
            `Applied ${k} of ${n}. Stopped at change ${k + 1}; the rest are still pending.`
          );
          return;
        }
        clearProposalToken(p.id);
        onApplied(p.id);
        k += 1;
      }
      setStatus(`All ${n} changes applied.`);
    } finally {
      setRunning(null);
      onRunning(false);
    }
  }

  return (
    <div
      data-testid="plan-bar"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        marginTop: 16,
        padding: "10px 14px",
        background: tokens.color.panel,
        border: `1px solid ${tokens.color.border2}`,
        borderRadius: tokens.radius.md,
      }}
    >
      <span style={{ fontSize: 14, fontWeight: 600, color: tokens.color.ink }}>
        {n} changes, in this order
      </span>
      <span role="status" style={{ fontSize: 13, color: tokens.color.muted3 }}>
        {status}
      </span>
      {running !== null ? (
        <span style={{ marginLeft: "auto", fontSize: 13, color: tokens.color.muted3 }}>
          Applying {running} of {n}…
        </span>
      ) : (
        ready && (
          <button
            type="button"
            style={{ ...btn, minHeight: 36, marginLeft: "auto" }}
            onClick={approveAll}
          >
            Approve all
          </button>
        )
      )}
    </div>
  );
}
