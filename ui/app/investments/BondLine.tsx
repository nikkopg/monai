"use client";

// SBN bond pieces for the Investments rows and the platform page (quick
// 261117-rw1). BondLine sits INSIDE the ticker cell (never a new child of
// .inv-row / .plat-row, whose phone layout places children by index).

import { tokens, card } from "../styles";
import {
  fmtDayMonth,
  fmtDayMonthYear,
  rateChip,
  receivedCoupons,
  type BondInfo,
  type CouponEvent,
} from "../lib/bond";

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));

const xs = "var(--fs-xs, 12px)";

const chip = (green: boolean): React.CSSProperties => ({
  display: "inline-block",
  fontSize: xs,
  padding: "1px 8px",
  borderRadius: 999,
  background: green ? tokens.color.tintGreen : tokens.color.tintNeutral,
  color: green ? tokens.color.green : tokens.color.muted3,
});

const muted: React.CSSProperties = {
  display: "block",
  fontSize: xs,
  color: tokens.color.muted3,
  whiteSpace: "normal",
};

export function BondLine({ bond }: { bond: BondInfo }) {
  const hasTerms = bond.rate != null;
  return (
    <>
      <span style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 2 }}>
        <span style={chip(false)}>Bond</span>
        {hasTerms && <span style={chip(true)}>{rateChip(bond.rate as number, bond.floating === true)}</span>}
      </span>
      {hasTerms ? (
        <>
          {bond.next_coupon_date && bond.net != null && (
            <span style={muted}>
              {`Next coupon ${fmtDayMonth(bond.next_coupon_date)} · ${fmtPlain(bond.net)}`}
              {bond.coupon_account_name ? ` to ${bond.coupon_account_name}` : ""}
            </span>
          )}
          {bond.maturity_date && <span style={muted}>{`Matures ${fmtDayMonthYear(bond.maturity_date)}`}</span>}
        </>
      ) : (
        <span style={muted}>Add coupon terms with Edit</span>
      )}
    </>
  );
}

export function CouponSchedule({
  ticker,
  bond,
  quantity,
  events,
}: {
  ticker: string;
  bond: BondInfo;
  quantity: number;
  events: CouponEvent[];
}) {
  const received = receivedCoupons(events, ticker);
  const total = received.reduce((s, r) => s + r.amount, 0);
  const rows: { date: string; amount: number; tag: string; due: boolean }[] = [
    ...received.slice(-3).map((r) => ({ date: r.date, amount: r.amount, tag: "received", due: false })),
    ...bond.upcoming.map((d) => ({ date: d, amount: bond.net ?? 0, tag: "due", due: true })),
  ];
  if (bond.maturity_date) {
    rows.push({ date: bond.maturity_date, amount: quantity, tag: "maturity", due: true });
  }
  return (
    <div className="card-tight" style={{ ...card, marginTop: 14 }}>
      <h3 style={{ margin: "0 0 6px", fontSize: "var(--fs-body, 14px)", fontWeight: 600 }}>
        {`Coupon schedule · ${ticker}`}
      </h3>
      <div style={{ fontSize: xs, color: tokens.color.muted3 }}>
        {"Realized from coupons "}
        <b style={{ color: tokens.color.green, fontVariantNumeric: "tabular-nums" }}>
          {`+${fmtPlain(total)}`}
        </b>
        {` (${received.length} paid)`}
      </div>
      <div style={{ marginTop: 12, borderTop: `1px solid ${tokens.color.borderInner}` }}>
        {rows.map((r, i) => (
          <div
            key={`${r.tag}-${r.date}-${i}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              fontSize: "var(--fs-body, 14px)",
              padding: "9px 0",
              borderBottom: i === rows.length - 1 ? 0 : `1px solid ${tokens.color.borderInner}`,
              color: r.due ? tokens.color.muted3 : undefined,
            }}
          >
            <span>{fmtDayMonthYear(r.date)}</span>
            <span style={{ fontVariantNumeric: "tabular-nums", textAlign: "right" }}>
              {`${fmtPlain(r.amount)} · ${r.tag}`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
