// SBN bond helpers (quick 261117-rw1). Pure TypeScript, no React.
//
// The coupon preview here is DISPLAY ONLY. The stored amount on a proposal comes
// from backend/bonds.py coupon_amounts; this file repeats the same rule in
// integer basis points so the form and the server agree to the rupiah:
//   gross = round_half_up(nominal x rate / 100 / 12)
//   tax   = round_half_up(gross x tax% / 100)
//   net   = gross - tax

// Mirrors the `bond` dict on a summary holding row. Dates are ISO strings, money
// is a number, and every computed key is null when the terms are incomplete.
export type BondInfo = {
  rate: number | null;
  floating: boolean | null;
  pay_day: number | null;
  maturity_date: string | null;
  tax_pct: number | null;
  coupon_account_id: number | null;
  coupon_account_name: string | null;
  gross: number | null;
  tax: number | null;
  net: number | null;
  next_coupon_date: string | null;
  upcoming: string[];
};

// Form-side terms: everything the owner types is a string until termsBody.
export type BondTermsInput = {
  rate: string;
  floating: boolean;
  payDay: string;
  maturity: string;
  taxPct: string;
  couponAccountId: string;
};

export const EMPTY_TERMS: BondTermsInput = {
  rate: "",
  floating: false,
  payDay: "",
  maturity: "",
  taxPct: "10",
  couponAccountId: "",
};

// Half-up on a non-negative integer ratio: floor((2n + d) / 2d).
const halfUp = (n: number, d: number) => Math.floor((2 * n + d) / (2 * d));

export function couponPreview(
  nominal: number,
  rate: number,
  taxPct: number
): { gross: number; tax: number; net: number } | null {
  if (!(nominal > 0) || !(rate > 0 && rate < 100) || !(taxPct >= 0 && taxPct < 100)) {
    return null;
  }
  const rb = Math.round(rate * 100);
  const tb = Math.round(taxPct * 100);
  const gross = halfUp(nominal * rb, 120000);
  const tax = halfUp(gross * tb, 10000);
  return { gross, tax, net: gross - tax };
}

const DECIMAL_2 = /^\d+(\.\d{1,2})?$/;

export function termsValid(t: BondTermsInput): boolean {
  const rate = parseFloat(t.rate);
  const tax = parseFloat(t.taxPct);
  const day = Number(t.payDay);
  return (
    DECIMAL_2.test(t.rate) &&
    rate > 0 &&
    rate < 100 &&
    DECIMAL_2.test(t.taxPct) &&
    tax >= 0 &&
    tax < 100 &&
    /^\d+$/.test(t.payDay) &&
    day >= 1 &&
    day <= 28 &&
    /^\d{4}-\d{2}-\d{2}$/.test(t.maturity) &&
    /^\d+$/.test(t.couponAccountId)
  );
}

// The `bond` object funded-buy, POST /holdings and PUT /holdings accept.
export function termsBody(t: BondTermsInput) {
  return {
    rate: parseFloat(t.rate),
    floating: t.floating,
    pay_day: parseInt(t.payDay, 10),
    maturity_date: t.maturity,
    tax_pct: parseFloat(t.taxPct),
    coupon_account_id: parseInt(t.couponAccountId, 10),
  };
}

// The form state a saved bond prefills (the override modal's edit path).
export function termsFromInfo(b: BondInfo | null | undefined): BondTermsInput {
  if (!b || b.rate == null) return EMPTY_TERMS;
  return {
    rate: String(b.rate),
    floating: b.floating === true,
    payDay: b.pay_day == null ? "" : String(b.pay_day),
    maturity: b.maturity_date ?? "",
    taxPct: b.tax_pct == null ? "10" : String(b.tax_pct),
    couponAccountId: b.coupon_account_id == null ? "" : String(b.coupon_account_id),
  };
}

export const rateChip = (rate: number, floating: boolean) =>
  `${rate.toFixed(2)}% ${floating ? "floating" : "fixed"}`;

// Built from the date parts (never new Date(iso), which reads the string as UTC
// and can land on the previous day). A fixed month list keeps September "Sep":
// newer ICU renders en-GB as "Sept".
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const parts = (iso: string) => /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);

export const fmtDayMonth = (iso: string) => {
  const m = parts(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : iso;
};
export const fmtDayMonthYear = (iso: string) => {
  const m = parts(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : iso;
};

// Coupons received for one ticker: dividend events, oldest first. The amount is
// the event's cash_amount, else price x quantity (a coupon is quantity 1).
export type CouponEvent = {
  date: string;
  ticker: string;
  event_type: string;
  quantity: number;
  price: number;
  cash_amount: number | null;
};
export function receivedCoupons(events: CouponEvent[], ticker: string) {
  return events
    .filter((e) => e.ticker === ticker && e.event_type === "dividend")
    .map((e) => ({ date: e.date, amount: e.cash_amount ?? e.price * e.quantity }))
    .sort((a, b) => a.date.localeCompare(b.date));
}
