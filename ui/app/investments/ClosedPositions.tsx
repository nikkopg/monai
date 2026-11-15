"use client";

// Closed positions (quick 261107-nq6): a position sold to exactly zero leaves
// one record here (ticker, platform, realized P&L in IDR, close date). Its
// holding and events are gone; the sale's cash stays in Records. A record can
// be corrected (PUT) or deleted (DELETE); both are audited server-side.
// Rendered inside the Holdings card's Closed view (no card or title of its
// own), grouped under one row per platform; closed records carry no asset type.

import { useState } from "react";

import { tokens, input, btn } from "../styles";
import { extractDetail } from "../lib/api";
import RowMenu from "../components/RowMenu";
import { columnHeader, groupRow } from "./sectionStyles";

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
  color: tokens.color.muted3,
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

  if (rows.length === 0) {
    return <p style={{ fontSize: 14, color: tokens.color.muted3, margin: 0 }}>No closed positions yet.</p>;
  }

  // One group per platform, in first-seen order; the group row carries the realized sum.
  const groups = new Map<string, ClosedPosition[]>();
  for (const r of rows) {
    const k = r.platform_name ?? "Deleted platform";
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }

  return (
    <div data-testid="closed-positions">
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left" }}>
            <th style={columnHeader}>Asset</th>
            <th style={{ ...columnHeader, textAlign: "right" }}>Closed</th>
            <th style={{ ...columnHeader, textAlign: "right" }}>Realized P&amp;L (IDR)</th>
            <th style={columnHeader} />
          </tr>
        </thead>
        <tbody>
          {Array.from(groups).map(([name, list]) => {
            const sum = list.reduce((a, r) => a + r.realized_pnl, 0);
            const cell = { ...groupRow, padding: "6px 8px" };
            return [
              <tr key={`g-${name}`}>
                <td colSpan={2} style={cell}>
                  {name}
                </td>
                <td style={{ ...cell, textAlign: "right", color: pnlColor(sum) }}>{fmtSigned(sum)}</td>
                <td style={cell} />
              </tr>,
              ...list.map((r) =>
                editingId === r.id ? (
                  <tr key={r.id}>
                    <td>{r.ticker}</td>
                    <td style={{ textAlign: "right" }}>
                      <input
                        aria-label={`Close date for ${r.ticker}`}
                        style={{ ...input, width: 150 }}
                        type="date"
                        value={date}
                        onChange={(e) => setDate(e.target.value)}
                      />
                    </td>
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
                    <td style={{ textAlign: "right" }}>{r.close_date}</td>
                    <td style={{ textAlign: "right", color: pnlColor(r.realized_pnl) }}>
                      {fmtSigned(r.realized_pnl)}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <RowMenu
                        label={`Closed position options: ${r.ticker}`}
                        items={[
                          {
                            label: "Edit",
                            onSelect: () => {
                              setEditingId(r.id);
                              setPnl(String(r.realized_pnl));
                              setDate(r.close_date);
                              setError(null);
                            },
                          },
                          {
                            label: "Delete",
                            destructive: true,
                            onSelect: () => remove(r),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                )
              ),
            ];
          })}
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
