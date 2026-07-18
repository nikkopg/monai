"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";
import type { PlatformOption, HoldingRow } from "./page";

// ---------------------------------------------------------------------------
// HoldingOverrideModal — D-03 direct override escape hatch. Sets a holding's
// position directly, bypassing the event ledger. Visually de-emphasized (a
// muted italic warning caption above the fields); reachable via the small
// "Add holding directly" text-link, not an equal-weight CTA. Dual-mode via
// `editingHolding == null`: create -> POST /api/holdings, edit -> PUT
// /api/holdings/{id}. Currency is fixed IDR (D-07), shown read-only.
// ---------------------------------------------------------------------------

type Props = {
  editingHolding: HoldingRow | null;
  platforms: PlatformOption[];
  onClose: () => void;
  onSaved: () => void;
};

const ASSET_TYPES = ["crypto", "idx_stock", "mutual_fund", "other"] as const;

export default function HoldingOverrideModal({
  editingHolding,
  platforms,
  onClose,
  onSaved,
}: Props) {
  const isEdit = editingHolding != null;

  const [ticker, setTicker] = useState(editingHolding?.ticker ?? "");
  const [assetType, setAssetType] = useState<string>(
    editingHolding?.asset_type ?? "crypto"
  );
  // Platform is required (no more "(unassigned)"): editing keeps the
  // holding's existing platform; creating defaults to the first platform.
  const [platformId, setPlatformId] = useState<string>(
    editingHolding?.platform_id != null
      ? String(editingHolding.platform_id)
      : platforms.length > 0
      ? String(platforms[0].id)
      : ""
  );
  const [quantity, setQuantity] = useState(
    editingHolding ? String(editingHolding.quantity) : ""
  );
  const [avgCost, setAvgCost] = useState(
    editingHolding ? String(editingHolding.avg_cost) : ""
  );
  const [purchaseDate, setPurchaseDate] = useState("");
  const [coingeckoId, setCoingeckoId] = useState(
    editingHolding?.coingecko_id ?? ""
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        ticker: ticker.trim(),
        quantity: parseFloat(quantity),
        avg_cost: parseFloat(avgCost),
        asset_type: assetType,
        platform_id: parseInt(platformId, 10),
        currency: "IDR",
        coingecko_id: coingeckoId.trim() || null,
      };
      if (purchaseDate) body.purchase_date = purchaseDate;

      const url = isEdit
        ? `/api/holdings/${editingHolding!.id}`
        : "/api/holdings";
      const method = isEdit ? "PUT" : "POST";

      const r = await fetch(url, {
        method,
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
        setError(`Couldn't save holding: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save holding: ${
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
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px" }}>
          {isEdit ? "Save holding" : "Add holding directly"}
        </h2>
        <p
          style={{
            ...label,
            fontStyle: "italic",
            marginBottom: 16,
          }}
        >
          This directly sets the holding&apos;s position, bypassing the event
          ledger. Prefer &quot;Log event&quot; for a normal buy/sell.
        </p>
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
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: "#b5503f" }}>
                  Add a platform first
                </p>
              )}
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
              <label style={label}>Avg cost (IDR)</label>
              <input
                style={input}
                type="number"
                step="any"
                required
                value={avgCost}
                onChange={(e) => setAvgCost(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Purchase date</label>
              <input
                style={input}
                type="date"
                value={purchaseDate}
                onChange={(e) => setPurchaseDate(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Currency</label>
              <input style={input} value="IDR" readOnly disabled />
            </div>
            {assetType === "crypto" && (
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={label}>CoinGecko id (optional)</label>
                <input
                  style={input}
                  value={coingeckoId}
                  placeholder="bittensor"
                  onChange={(e) => setCoingeckoId(e.target.value)}
                />
                <p style={{ ...label, fontSize: 11, marginTop: 4 }}>
                  Disambiguates tickers that map to multiple coins (e.g. TAO). Find
                  the coin&apos;s API id on{" "}
                  <a
                    href="https://www.coingecko.com"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    coingecko.com
                  </a>{" "}
                  — the URL slug, e.g. <code>bittensor</code>. Leave blank to use
                  the default ticker mapping.
                </p>
              </div>
            )}
          </div>

          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                color: "#8b8474",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={saving || platforms.length === 0}>
              {saving ? "Saving…" : isEdit ? "Save holding" : "Add holding directly"}
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
