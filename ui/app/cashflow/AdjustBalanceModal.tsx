"use client";

import { useState } from "react";

import { card, input, btn, label, tokens } from "../styles";
import { extractDetail, fmtPlain } from "../lib/api";
import type { Account } from "./AccountManager";

// ---------------------------------------------------------------------------
// AdjustBalanceModal — ACCT-02 balance-adjustment entry point (D-01/D-02/D-07).
// Single "Target balance" input with a live, presentation-only signed-delta
// preview (target - account.current_balance). Submits exactly
// { target_balance } to POST /api/accounts/{id}/adjust-balance — the
// authoritative delta is recomputed server-side from a fresh unfiltered SUM
// (apply_add_balance_adjustment). Mirrors HoldingModal's overlay shell +
// Cancel/Submit row; no ConfirmDialog second step (D-07 rejects it).
// ---------------------------------------------------------------------------

type Props = {
  account: Account;
  onClose: () => void;
  onChanged: () => void;
};

export default function AdjustBalanceModal({ account, onClose, onChanged }: Props) {
  // Pre-filled with the current balance so the initial state is delta===0
  // (submit disabled, "No change" copy) until the user actually edits it.
  const [target, setTarget] = useState(String(account.current_balance));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WR-03: parse ONCE and gate on validity. A cleared field must not preview a
  // full balance wipe with submit enabled (an empty target is NaN → invalid,
  // not "0"), and the same parsed value feeds both preview and payload.
  const parsed = target.trim() === "" ? NaN : parseFloat(target);
  const delta = Number.isNaN(parsed) ? 0 : parsed - account.current_balance;
  const canSubmit = !saving && !Number.isNaN(parsed) && delta !== 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      // WR-09: adjust posts to account.id directly. If that account was deleted
      // between mount and submit, apply_add_balance_adjustment computes a delta
      // against an empty SUM and writes to an account named "Unknown". Closing
      // this needs a backend `db.get(Account, id) is None → ValueError` guard
      // (the T-14-07 pattern) — out of Phase 18's UI-only scope.
      const r = await fetch(`/api/accounts/${account.id}/adjust-balance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_balance: parsed }),
      });
      if (r.ok) {
        onChanged();
        onClose();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save adjustment: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save adjustment: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,17,21,0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={saving ? undefined : onClose}
    >
      <div
        style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>
          Adjust balance — {account.name}
        </h2>
        <form onSubmit={handleSubmit}>
          <div>
            <label style={label}>Target balance</label>
            <input
              style={input}
              type="number"
              step="any"
              required
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </div>

          <p
            style={{
              fontSize: 13,
              marginTop: 10,
              color:
                delta > 0
                  ? tokens.color.green
                  : delta < 0
                  ? tokens.color.terracotta
                  : tokens.color.muted,
            }}
          >
            {delta === 0
              ? "No change — target equals current balance."
              : delta > 0
              ? `Adjustment: +Rp ${fmtPlain(delta)}`
              : `Adjustment: −Rp ${fmtPlain(Math.abs(delta))}`}
          </p>

          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={saving ? undefined : onClose}
              style={{
                background: "transparent",
                color: "#8b8474",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: saving ? "default" : "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={!canSubmit}>
              {saving ? "Saving…" : "Save adjustment"}
            </button>
            {error && (
              <span style={{ color: "#b5503f", fontSize: 12 }}>{error}</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
