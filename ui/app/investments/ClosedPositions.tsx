"use client";

// Closed positions (quick 261107-nq6): a position sold to exactly zero leaves
// one record here (ticker, platform, realized P&L in IDR, close date). Its
// holding and events are gone; the sale's cash stays in Records.

import { tokens, card } from "../styles";

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

export default function ClosedPositions({ rows }: { rows: ClosedPosition[] }) {
  if (rows.length === 0) return null;
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
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.ticker}</td>
              <td>{r.platform_name ?? "Deleted platform"}</td>
              <td style={{ textAlign: "right", color: pnlColor(r.realized_pnl) }}>
                {fmtSigned(r.realized_pnl)}
              </td>
              <td style={{ textAlign: "right" }}>{r.close_date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
