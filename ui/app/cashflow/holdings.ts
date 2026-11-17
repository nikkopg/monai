// Pure row, centre and share helpers for the Cashflow page's Holdings card
// (HoldingsCard.tsx). No React or recharts here, so the Playwright logic spec
// can import it the way period-card-logic imports periodCard.ts.
//
// Every string the card shows (amount, subline, share, tooltip, centre) is built
// here. A missing figure is "—" with a reason, never 0, and a USD account shows
// its own native balance rather than a converted-and-back figure. The main-view
// totals are the server's, never re-summed client-side.
import { fmtRowDate } from "../lib/inbox";
import { fmtAmount, rateHover } from "../lib/money";

// ---------------------------------------------------------------------------
// Types (moved from page.tsx)
// ---------------------------------------------------------------------------

export type AccountBalance = {
  id: number;
  name: string;
  type: string;
  // Phase 43 payload: a USD row carries its native balance and rate; current_balance
  // (the IDR value) is null when no rate is within range.
  current_balance: number | null;
  period_net: number | null;
  currency?: string;
  native_balance?: number;
  fx_rate?: number | null;
  fx_as_of?: string | null;
  fx_stale?: boolean;
  fx_note?: string | null;
  period_net_unconverted?: boolean;
};

// Decimal fields can arrive as JSON strings, so they are coerced with toNum.
export type InvestmentGroup = {
  platform_id: number;
  platform_name: string;
  kind: string;
  subtotal: number | string;
  holdings: { asset_type: string | null; current_value: number | string | null }[];
};

export type HoldingsData = {
  total: number;
  liquid_total: number;
  investment_total: number;
  liquid_accounts: AccountBalance[];
  investment_groups: InvestmentGroup[];
};

export type Drill = "liquid" | "investment";
export type Ccy = "IDR" | "USD";

export type HoldingRow = {
  key: string;
  name: string;
  sub?: string;
  stale?: string;
  value: number | null; // IDR; drives the slice and the share
  amount: string;
  title?: string;
  negative: boolean;
  share: string;
  color: string;
  drill?: Drill;
  href?: string;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GREENS = ["#2f6f4f", "#5a8f73", "#8fae9c", "#b9cdbf", "#c8c1b5"];
export const GOLDS = ["#d8b26a", "#c9973f", "#a8674a", "#e3c891", "#8a6a3f"];

export const NO_RATE_IDR =
  "IDR value unavailable: no USD→IDR rate, so this account is left out of the total";
export const NO_RATE_USD = "USD value unavailable: no USD→IDR rate to convert with";

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** Centre-of-donut figure: "10.1M", "5.3K USD", "850", "346.15 USD", "—". */
export function fmtShort(n: number | null | undefined, ccy: Ccy): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000) return compact.format(n) + (ccy === "USD" ? " USD" : "");
  return fmtAmount(n, ccy);
}

// Null-preserving: Number(null) would be 0.
function toNum(v: unknown): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// ---------------------------------------------------------------------------
// Row builders
// ---------------------------------------------------------------------------

type Seed = Omit<HoldingRow, "color" | "share"> & { color?: string };

// Sorts (highest first, missing last), colours and computes shares.
// ponytail: negative or missing values get no slice and share "—", so shares
// cover only the positive balances.
function finish(seeds: Seed[], palette: string[], sort: boolean): HoldingRow[] {
  const list = sort
    ? [...seeds].sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity))
    : seeds;
  const positive = list.reduce((t, s) => t + (s.value != null && s.value > 0 ? s.value : 0), 0);
  return list.map((s, i) => ({
    ...s,
    color: s.color ?? palette[i % palette.length],
    share: s.value != null && s.value > 0 ? `${Math.round((s.value / positive) * 100)}%` : "—",
  }));
}

/** Liquid then Investment, from the server's totals. */
export function mainRows(d: Omit<HoldingsData, "total">): HoldingRow[] {
  return finish(
    [
      {
        key: "liquid",
        name: "Liquid",
        sub: plural(d.liquid_accounts.length, "account", "accounts"),
        value: d.liquid_total,
        amount: fmtAmount(d.liquid_total, "IDR"),
        negative: d.liquid_total < 0,
        color: GREENS[0],
        drill: "liquid",
      },
      {
        key: "investment",
        name: "Investment",
        sub: plural(d.investment_groups.length, "platform", "platforms"),
        value: d.investment_total,
        amount: fmtAmount(d.investment_total, "IDR"),
        negative: d.investment_total < 0,
        color: GOLDS[0],
        drill: "investment",
      },
    ],
    GREENS,
    false
  );
}

/**
 * Liquid accounts in IDR or USD. The slice value is always the IDR value, so the
 * donut and shares never change with the toggle. A row's subline is its other
 * currency, only when its main figure is a conversion. The centre covers the
 * accounts that have an IDR value (the donut's set); in USD it is null without a rate.
 */
export function liquidRows(
  accounts: AccountBalance[],
  ccy: Ccy,
  liquidTotal: number
): { rows: HoldingRow[]; centre: number | null } {
  // The only USD rate the page has: a USD row's own fx_rate. IDR rows carry
  // fx_rate 1.0 from the API, so taking any row's rate divided by 1 and showed
  // rupiah labelled as USD.
  const rateAcct = accounts.find((a) => a.currency === "USD" && Number.isFinite(a.fx_rate));
  const rate = rateAcct?.fx_rate ?? null;
  let usdCentre = 0;

  const seeds = accounts.map((a): Seed => {
    const isUsd = (a.currency ?? "IDR") === "USD";
    const idr = a.current_balance;
    const base = {
      key: String(a.id),
      name: a.name,
      value: idr,
      stale: isUsd && a.fx_stale ? `stale, rate of ${fmtRowDate(a.fx_as_of)}` : undefined,
    };
    let shown: number | null;
    let sub: string | undefined;
    let title: string | undefined;
    if (isUsd) {
      if (ccy === "IDR") {
        shown = idr;
        sub = fmtAmount(a.native_balance, "USD");
        title = idr == null ? NO_RATE_IDR : rateHover(a.fx_rate, a.fx_as_of);
      } else {
        shown = a.native_balance ?? null;
      }
      if (idr != null) usdCentre += a.native_balance ?? 0;
    } else if (ccy === "IDR") {
      shown = idr;
    } else if (idr != null && rate != null) {
      shown = idr / rate;
      sub = `${fmtAmount(idr, "IDR")} IDR`;
      title = rateHover(rate, rateAcct!.fx_as_of);
      usdCentre += shown;
    } else {
      shown = null;
      sub = idr != null ? `${fmtAmount(idr, "IDR")} IDR` : undefined;
      title = NO_RATE_USD;
    }
    return {
      ...base,
      sub,
      title,
      amount: fmtAmount(shown, ccy),
      negative: shown != null && shown < 0,
    };
  });

  return {
    rows: finish(seeds, GREENS, true),
    centre: ccy === "IDR" ? liquidTotal : rate == null ? null : usdCentre,
  };
}

// ---------------------------------------------------------------------------
// Investment
// ---------------------------------------------------------------------------

// Category = the EXISTING holdings.asset_type field through a fixed label map
// (HoldingModal's crypto / idx_stock / mutual_fund / other, plus the gold and
// legacy cash values seen in code). Anything else, or null, is "Other". No
// per-ticker guessing and no backend change.
const ASSET_LABELS: Record<string, string> = {
  crypto: "Crypto",
  idx_stock: "Stocks",
  mutual_fund: "Mutual funds",
  gold: "Gold",
  cash: "Cash",
  bond: "Bond (SBN)",
};

export function assetLabel(t: string | null | undefined): string {
  return (t != null && ASSET_LABELS[t]) || "Other";
}

/** One row per platform, from the server's subtotal; rows open /investments/{id}. */
export function platformRows(groups: InvestmentGroup[]): HoldingRow[] {
  return finish(
    groups.map((g): Seed => {
      const value = toNum(g.subtotal);
      const cats = new Set(
        g.holdings
          .filter((h) => {
            const v = toNum(h.current_value);
            return v != null && v !== 0;
          })
          .map((h) => assetLabel(h.asset_type))
      );
      return {
        key: `p${g.platform_id ?? g.platform_name}`,
        name: g.platform_name,
        sub: plural(cats.size, "category", "categories"),
        value,
        amount: fmtAmount(value, "IDR"),
        negative: value != null && value < 0,
        href: Number.isFinite(g.platform_id) ? `/investments/${g.platform_id}` : undefined,
      };
    }),
    GOLDS,
    true
  );
}

/** Holdings summed by asset type across platforms; a null value is skipped, never counted as 0. */
export function categoryRows(groups: InvestmentGroup[]): HoldingRow[] {
  const sums = new Map<string, { value: number; platforms: string[] }>();
  for (const g of groups) {
    for (const h of g.holdings) {
      const v = toNum(h.current_value);
      if (v == null) continue;
      const label = assetLabel(h.asset_type);
      const e = sums.get(label) ?? { value: 0, platforms: [] };
      e.value += v;
      if (!e.platforms.includes(g.platform_name)) e.platforms.push(g.platform_name);
      sums.set(label, e);
    }
  }
  return finish(
    Array.from(sums).map(([name, e]): Seed => ({
      key: name,
      name,
      sub: e.platforms.join(", "),
      value: e.value,
      amount: fmtAmount(e.value, "IDR"),
      negative: e.value < 0,
    })),
    GOLDS,
    true
  );
}
