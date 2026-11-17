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

// Built from the date parts, never new Date(iso), which reads the string as UTC
// and can land on the previous day (fmtRowDate in inbox.ts is the model).
function dayParts(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

const dayMonth = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const dayMonthYear = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export const fmtDayMonth = (iso: string) => {
  const d = dayParts(iso);
  return d ? dayMonth.format(d) : iso;
};
export const fmtDayMonthYear = (iso: string) => {
  const d = dayParts(iso);
  return d ? dayMonthYear.format(d) : iso;
};
