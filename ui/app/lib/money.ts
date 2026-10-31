// The one formatter for liquid money (Phase 44, D-12). The IDR branch reproduces
// the old Cashflow page formatters exactly (en-US on Math.round, no symbol); USD
// shows two decimals and a trailing code. lib/inbox.ts fmtMoney, lib/api.ts
// fmtPlain and the investment-page formatters stay separate on purpose: other
// pages pin their output.
import { fmtRowDate } from "./inbox";

const plain = new Intl.NumberFormat("en-US");
const plainSigned = new Intl.NumberFormat("en-US", { signDisplay: "always" });
const usd = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdSigned = new Intl.NumberFormat("en-US", {
  signDisplay: "always",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const rateFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

// A missing amount must look missing, never a believable 0.
const missing = (v: unknown): v is null | undefined =>
  v === null || v === undefined || !Number.isFinite(v);

/** "1,234,568" for IDR or no currency; "1,234.50 USD" for USD; "—" when missing. */
export function fmtAmount(v: number | null | undefined, ccy?: string | null): string {
  if (missing(v)) return "—";
  return ccy === "USD" ? `${usd.format(v)} USD` : plain.format(Math.round(v));
}

/** Same as fmtAmount with an explicit sign: "+12.30 USD", "-0". */
export function fmtAmountSigned(v: number | null | undefined, ccy?: string | null): string {
  if (missing(v)) return "—";
  return ccy === "USD" ? `${usdSigned.format(v)} USD` : plainSigned.format(Math.round(v));
}

/** Native tooltip text for a converted row; undefined (no title) when rate or date is missing. */
export function rateHover(
  rate: number | null | undefined,
  isoDate: string | null | undefined
): string | undefined {
  if (missing(rate) || !isoDate) return undefined;
  return `1 USD = ${rateFmt.format(rate)} IDR · rate of ${fmtRowDate(isoDate)}`;
}

/**
 * Sum rows in rupiah (D-17). Never adds a native non-IDR amount: a USD row counts
 * only through its amount_idr, and with none it is tallied in `unconverted`.
 */
export function sumIdr(
  rows: { amount: number; currency?: string | null; amount_idr?: number | null }[]
): { total: number; unconverted: number } {
  let total = 0;
  let unconverted = 0;
  for (const r of rows) {
    if (!r.currency || r.currency === "IDR") total += r.amount_idr ?? r.amount;
    else if (typeof r.amount_idr === "number" && Number.isFinite(r.amount_idr)) total += r.amount_idr;
    else unconverted += 1;
  }
  return { total, unconverted };
}
