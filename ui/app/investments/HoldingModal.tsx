"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";
import type { PlatformOption } from "./page";

// ---------------------------------------------------------------------------
// HoldingModal — buy/sell/dividend event entry (D-01, primary INV-01 path).
// Mirrors TransactionModal's overlay+card shell. POSTs /api/portfolio-events
// through the Next.js proxy (which injects the API key server-side); the
// position recompute happens server-side (05-RESEARCH Pattern 2). On success
// calls onSaved() (parent refetches the summary) then onClose().
// ---------------------------------------------------------------------------

type Props = {
  platforms: PlatformOption[];
  onClose: () => void;
  onSaved: () => void;
};

const ASSET_TYPES = ["crypto", "idx_stock", "mutual_fund", "other"] as const;

// datetime-local value from a Date using LOCAL wall-clock components (verbatim
// from TransactionModal — avoids the toISOString() UTC shift).
function toLocalDatetimeInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

export default function HoldingModal({ platforms, onClose, onSaved }: Props) {
  const [ticker, setTicker] = useState("");
  const [assetType, setAssetType] = useState<string>("crypto");
  // Platform is required (no more "(unassigned)") — default to the first
  // platform when any exist.
  const [platformId, setPlatformId] = useState<string>(
    platforms.length > 0 ? String(platforms[0].id) : ""
  );
  const [eventType, setEventType] = useState<"buy" | "sell" | "dividend">("buy");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [date, setDate] = useState(toLocalDatetimeInputValue(new Date()));

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDividend = eventType === "dividend";

  // When switching to Dividend, default quantity to 1 (still editable) so the
  // form keeps the same field set (quantity=1, price=amount convention).
  function onEventTypeChange(next: "buy" | "sell" | "dividend") {
    setEventType(next);
    if (next === "dividend" && !quantity) setQuantity("1");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // Event date is a plain date (backend column is DATE) — send YYYY-MM-DD.
      const body: Record<string, unknown> = {
        ticker: ticker.trim(),
        event_type: eventType,
        quantity: parseFloat(quantity),
        price: parseFloat(price),
        date: new Date(date).toISOString().slice(0, 10),
        asset_type: assetType,
        platform_id: parseInt(platformId, 10),
      };
      const r = await fetch("/api/portfolio-events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
        setError(`Couldn't log event: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't log event: ${
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
        style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>
          Log event
        </h2>
        <form onSubmit={handleSubmit}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div>
              <label style={label}>Ticker</label>
              <input
                style={input}
                required
                value={ticker}
                placeholder="BBCA"
                onChange={(e) => setTicker(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Asset type</label>
              <select
                style={input}
                value={assetType}
                onChange={(e) => setAssetType(e.target.value)}
              >
                {ASSET_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={label}>Platform</label>
              <select
                style={input}
                required
                value={platformId}
                onChange={(e) => setPlatformId(e.target.value)}
              >
                {platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              {platforms.length === 0 && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: "#f87171" }}>
                  Add a platform first
                </p>
              )}
            </div>
            <div>
              <label style={label}>Event type</label>
              <select
                style={input}
                value={eventType}
                onChange={(e) =>
                  onEventTypeChange(e.target.value as "buy" | "sell" | "dividend")
                }
              >
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
                <option value="dividend">Dividend</option>
              </select>
            </div>
            <div>
              <label style={label}>Quantity</label>
              <input
                style={input}
                type="number"
                step="any"
                required
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>
                {isDividend ? "Dividend amount (IDR)" : "Price per unit (IDR)"}
              </label>
              <input
                style={input}
                type="number"
                step="any"
                required
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Date</label>
              <input
                style={input}
                type="datetime-local"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
          </div>

          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                color: "#9aa0a6",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={saving || platforms.length === 0}>
              {saving ? "Saving…" : "Log event"}
            </button>
            {error && (
              <span style={{ color: "#f87171", fontSize: 12 }}>{error}</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
