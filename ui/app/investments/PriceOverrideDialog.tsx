"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";
import type { HoldingRow } from "./page";

// ---------------------------------------------------------------------------
// PriceOverrideDialog (INV-04, D-11) — manually set a holding's price. Writes
// price_cache source='manual' via POST /api/prices/override; the newest row
// wins as "current price", so P&L updates immediately on refetch. Mirrors
// ConfirmDialog dimensions (maxWidth 360, padding 24).
// ---------------------------------------------------------------------------

type Props = {
  holding: HoldingRow;
  onClose: () => void;
  onSaved: () => void;
};

const muted = "#8b8474";

export default function PriceOverrideDialog({ holding, onClose, onSaved }: Props) {
  const [price, setPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/prices/override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: holding.ticker, price: parseFloat(price) }),
      });
      if (r.ok) {
        onSaved();
        onClose();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep status-based detail
        }
        setError(`Couldn't set price: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't set price: ${
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
      onClick={onClose}
    >
      <div
        style={{ ...card, maxWidth: 360, width: "100%", padding: 24, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 4px" }}>
          Set price · {holding.ticker}
        </h2>
        <p style={{ fontSize: 12, color: muted, margin: "0 0 16px" }}>
          Current:{" "}
          {holding.current_price != null
            ? new Intl.NumberFormat("en-US").format(holding.current_price)
            : "—"}
          {holding.price_source ? ` · ${holding.price_source}` : ""}
        </p>
        <form onSubmit={handleSubmit}>
          <label style={label}>New price (IDR)</label>
          <input
            style={input}
            type="number"
            step="any"
            required
            autoFocus
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
          <p style={{ fontSize: 11, color: muted, margin: "8px 0 0" }}>
            A manual price is used until the next successful live fetch replaces
            it.
          </p>
          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                color: muted,
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={saving}>
              {saving ? "Saving…" : "Set price"}
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
