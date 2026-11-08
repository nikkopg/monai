"use client";

// Closed positions (quick 261107-nq6): a position sold to exactly zero leaves
// one record here (ticker, platform, realized P&L in IDR, close date). Its
// holding and events are gone; the sale's cash stays in Records. A record can
// be corrected (PUT) or deleted (DELETE); both are audited server-side.

import { useState } from "react";

import { tokens, card, input, btn } from "../styles";
import { extractDetail } from "../lib/api";

export type ClosedPosition = {
  id: number;
  ticker: string;
  platform_id: number | null;
  platform_name: string | null;
  realized_pnl: number;
  close_date: string;
};

const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(n));
const pnlColor = (n: number) =>
  n >= 0 ? tokens.color.green : tokens.color.terracotta;

const textBtn: React.CSSProperties = {
  background: "transparent",
  border: "none",
  padding: "4px 8px",
  fontSize: 13,
  cursor: "pointer",
  color: tokens.color.muted,
};

export default function ClosedPositions({
  rows,
  load,
}: {
  rows: ClosedPosition[];
  load: () => void;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [pnl, setPnl] = useState("");
  const [date, setDate] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (rows.length === 0) return null;

  async function call(r: ClosedPosition, verb: string, req: () => Promise<Response>) {
    setError(null);
    try {
      const res = await req();
      if (res.ok) {
        setEditingId(null);
        load();
      } else {
        setError(`Couldn't ${verb} ${r.ticker}: ${await extractDetail(res)}`);
      }
    } catch (e) {
      setError(
        `Couldn't ${verb} ${r.ticker}: ${e instanceof Error ? e.message : "Network error"}`
      );
    }
  }

  const save = (r: ClosedPosition) =>
    call(r, "save", () =>
      fetch(`/api/closed-positions/${r.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ realized_pnl: parseFloat(pnl), close_date: date }),
      })
    );

  const remove = (r: ClosedPosition) => {
    if (
      !confirm(
        `Delete the closed position ${r.ticker}? Its realized P&L leaves the total. The sale's cash record stays in Records.`
      )
    )
      return;
    return call(r, "delete", () =>
      fetch(`/api/closed-positions/${r.id}`, { method: "DELETE" })
    );
  };

  return (
    <div data-testid="closed-positions" style={{ ...card, marginTop: 24 }}>
      <h2 style={{ fontSize: 16, margin: "0 0 12px" }}>Closed positions</h2>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", color: tokens.color.muted }}>
            <th>Ticker</th>
            <th>Platform</th>
            <th style={{ textAlign: "right" }}>Realized P&amp;L (IDR)</th>
            <th style={{ textAlign: "right" }}>Closed</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) =>
            editingId === r.id ? (
              <tr key={r.id}>
                <td>{r.ticker}</td>
                <td>{r.platform_name ?? "Deleted platform"}</td>
                <td style={{ textAlign: "right" }}>
                  <input
                    aria-label={`Realized P&L for ${r.ticker}`}
                    style={{ ...input, width: 140 }}
                    type="number"
                    step="any"
                    value={pnl}
                    onChange={(e) => setPnl(e.target.value)}
                  />
                </td>
                <td style={{ textAlign: "right" }}>
                  <input
                    aria-label={`Close date for ${r.ticker}`}
                    style={{ ...input, width: 150 }}
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button
                    style={{ ...btn, padding: "4px 12px" }}
                    aria-label={`Save ${r.ticker}`}
                    disabled={!Number.isFinite(parseFloat(pnl)) || !date}
                    onClick={() => save(r)}
                  >
                    Save
                  </button>
                  <button
                    style={textBtn}
                    aria-label={`Cancel editing ${r.ticker}`}
                    onClick={() => {
                      setEditingId(null);
                      setError(null);
                    }}
                  >
                    Cancel
                  </button>
                </td>
              </tr>
            ) : (
              <tr key={r.id}>
                <td>{r.ticker}</td>
                <td>{r.platform_name ?? "Deleted platform"}</td>
                <td style={{ textAlign: "right", color: pnlColor(r.realized_pnl) }}>
                  {fmtSigned(r.realized_pnl)}
                </td>
                <td style={{ textAlign: "right" }}>{r.close_date}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button
                    style={textBtn}
                    aria-label={`Edit ${r.ticker}`}
                    onClick={() => {
                      setEditingId(r.id);
                      setPnl(String(r.realized_pnl));
                      setDate(r.close_date);
                      setError(null);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    style={{ ...textBtn, color: tokens.color.terracottaText }}
                    aria-label={`Delete ${r.ticker}`}
                    onClick={() => remove(r)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            )
          )}
        </tbody>
      </table>
      {error && (
        <p role="alert" style={{ color: tokens.color.terracottaText, fontSize: 13, margin: "8px 0 0" }}>
          {error}
        </p>
      )}
    </div>
  );
}
