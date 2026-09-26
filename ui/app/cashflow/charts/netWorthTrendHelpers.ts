// Pure presentation logic for the net-worth trend card (Phase 23 Plan 01,
// extended by Phase 23.1 Plan 03). No React, no imports: every rule here is
// asserted by a plain-node script instead of a browser test, so the honesty
// rules (D-04..D-13, then 23.1's D-01/D-02) that drive what this card renders
// can be pinned in about a second. Implements: D-02/D-03 (range constant),
// D-04 (pre-ledger trim), D-05 (gap-honest plot, no interpolation), D-07
// (single reason map, unknown-code fallback), D-09/D-10 (tooltip text), D-11
// (each half's own honest flag), D-13 (newest-point as-of line). Phase 23.1:
// D-01 (dashed at-cost investment stretch, split from market-value stretch),
// D-02 (seam month between the two), the tooltip "(at cost)" suffix. The
// under-chart caption helpers (gap captions, the drift and at-cost
// explanations) were deleted after the NWH-03 reword left them unmounted
// (23.2 D-07).
//
// Self-check: node --experimental-strip-types
//   ui/app/cashflow/charts/netWorthTrendHelpers.check.mjs

// --- Types -------------------------------------------------------------

export type LiquidHalf = {
  total: number | null;
  by_account: Record<string, number> | null;
  honest: boolean;
  gap_reason: string | null;
  // 23.1: absent from Phase 22/23 payloads and fixtures, so treat undefined
  // like null. "ledger_plus_corrections" before the account's own adjustment
  // anchor; null on/after (today's existing live-anchored behavior).
  valuation_basis?: string | null;
};

export type InvestmentHalf = {
  total: number | null;
  by_position: Record<string, number> | null;
  honest: boolean;
  gap_reason: string | null;
  valuation_basis: string | null;
  as_of_date: string | null;
};

export type NetWorthRow = {
  month: string; // "YYYY-MM"
  total: number | null;
  honest: boolean;
  gap_reason: string | null;
  liquid: LiquidHalf;
  investment: InvestmentHalf;
};

export type Range = "1Y" | "3Y" | "All";

export type Mode = "total" | "split";

export type PlotPoint = {
  month: string;
  total: number | null;
  liquidTotal: number | null;
  investmentTotal: number | null;
  // 23.1 D-01/D-05: total/investment split by the investment half's basis.
  // Exactly one of the AtCost/Market pair is non-null on any honest row.
  totalAtCost: number | null;
  totalMarket: number | null;
  investmentAtCost: number | null;
  investmentMarket: number | null;
  row: NetWorthRow;
};

// --- Constants -----------------------------------------------------------

export const RANGE_MONTHS: Record<Range, number> = { "1Y": 12, "3Y": 36, All: 600 };

// D-07: single reason map, every code the backend can emit, sentences verbatim
// from 23-UI-SPEC.md's Gap Reason Map.
export const REASON_SENTENCES: Record<string, string> = {
  pre_ledger: "before the ledger existed for these accounts",
  no_opening_anchor: "liquid accounts have no opening balance anchor for these months",
  no_closing_anchor: "liquid accounts have no closing balance anchor for these months",
  no_investment_tracking_before_launch: "investment tracking hadn't started yet",
  synthetic_opening_only:
    "only a synthetic opening balance exists for the investment side, not a verified one",
  fx_unavailable: "the historical FX rate could not be verified for these months",
  unknown_event_type:
    "a portfolio event of an unrecognized type blocks reconstruction for these months",
  negative_running_quantity:
    "the replayed position quantity went negative, which can't be honest",
  no_snapshot_for_month: "no daily portfolio snapshot exists for this month",
  snapshot_missing_position: "the snapshot is missing a position that should be held",
  parity_mismatch: "the liquid and investment totals didn't reconcile for this month",
};

// --- Formatters ------------------------------------------------------------

export function fmtExact(n: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(n));
}

export function monthLabel(month: string): string {
  const d = new Date(`${month}-01`);
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

export function asOfLabel(isoDate: string): string {
  const d = new Date(isoDate);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

// --- Reason mapping ----------------------------------------------------

export function reasonSentence(code: string | null): string {
  if (code === null) return "data could not be verified for these months";
  const sentence = REASON_SENTENCES[code];
  return sentence !== undefined
    ? sentence
    : `data could not be verified for these months (${code})`;
}

// D-06: engine-level codes, liquid first then investment (never the composed
// both_halves_gapped code, which says nothing useful to a user). Falls back to
// the composed gap_reason only when both halves are individually honest but
// the row still isn't (Phase 22 D-08 soft gap, e.g. parity_mismatch).
export function rowGapCodes(row: NetWorthRow): string[] {
  const codes: string[] = [];
  if (row.liquid.gap_reason) codes.push(row.liquid.gap_reason);
  if (row.investment.gap_reason) codes.push(row.investment.gap_reason);
  if (codes.length === 0 && row.gap_reason) codes.push(row.gap_reason);
  return codes;
}

// --- Range / trim --------------------------------------------------------

// D-04: drop leading pre_ledger rows; keep everything from the first other row
// on. Rows made entirely of pre_ledger months come back unchanged.
export function trimPreLedger(rows: NetWorthRow[]): NetWorthRow[] {
  const firstRealIdx = rows.findIndex((r) => r.liquid.gap_reason !== "pre_ledger");
  return firstRealIdx === -1 ? rows : rows.slice(firstRealIdx);
}

export function visibleRows(rows: NetWorthRow[], range: Range): NetWorthRow[] {
  return range === "All" ? trimPreLedger(rows) : rows;
}

// --- Plot points -----------------------------------------------------------

// D-05/D-11: each series is gated on its own honest flag. No carry-forward, no
// interpolation, and a dishonest half with a non-null total still plots null.
export function toPlotPoints(rows: NetWorthRow[]): PlotPoint[] {
  return rows.map((row) => {
    const atCost = row.investment.valuation_basis === "deposits";
    return {
      month: row.month,
      total: row.honest ? row.total : null,
      liquidTotal: row.liquid.honest ? row.liquid.total : null,
      investmentTotal: row.investment.honest ? row.investment.total : null,
      totalAtCost: row.honest && atCost ? row.total : null,
      totalMarket: row.honest && !atCost ? row.total : null,
      investmentAtCost: row.investment.honest && atCost ? row.investment.total : null,
      investmentMarket: row.investment.honest && !atCost ? row.investment.total : null,
      row,
    };
  });
}

// --- Basis seam / anchor months (23.1 D-01/D-02) ----------------------------

// WR-05: the month right after the LAST row matching `isOldBasis` (rows are
// contiguous months), whether or not that month is honest. Keying off "first
// later honest row" instead would drift forward every month a post-boundary
// month gaps. null when no row has the old basis, or it runs to the last row.
function monthAfterLast(rows: NetWorthRow[], isOldBasis: (r: NetWorthRow) => boolean): string | null {
  let lastIdx = -1;
  rows.forEach((r, i) => {
    if (isOldBasis(r)) lastIdx = i;
  });
  return lastIdx === -1 || lastIdx === rows.length - 1 ? null : rows[lastIdx + 1].month;
}

// D-02: first month (full, untrimmed rows) after the investment half's
// at-cost (deposits) stretch. null when there's no deposits-basis row to
// seam from.
export function seamMonth(rows: NetWorthRow[]): string | null {
  return monthAfterLast(rows, (r) => r.investment.valuation_basis === "deposits");
}

// --- Tooltip -----------------------------------------------------------

// D-09/D-10: exact month + value, "No data — reason" for a gapped half, and
// the investment as-of line on the newest honest point (D-13). The CTA never
// appears in tooltip text.
export function tooltipLines(row: NetWorthRow, mode: Mode, isNewest: boolean): string[] {
  const lines: string[] = [monthLabel(row.month)];

  if (mode === "total") {
    if (row.honest && row.total !== null) {
      // 23.1 Tooltip Delta: at-cost months get a suffix, market-value months
      // (including pre-23.1 payloads with no basis field) are unaffected.
      const suffix = row.investment.valuation_basis === "deposits" ? " (at cost)" : "";
      lines.push(`${fmtExact(row.total)}${suffix}`);
    } else {
      const codes = rowGapCodes(row);
      const text =
        codes.length > 0 ? codes.map((c) => reasonSentence(c)).join("; ") : reasonSentence(null);
      lines.push(`No data — ${text}`);
    }
  } else {
    if (row.liquid.honest && row.liquid.total !== null) {
      lines.push(`Liquid: ${fmtExact(row.liquid.total)}`);
    } else {
      lines.push(`Liquid: No data — ${reasonSentence(row.liquid.gap_reason)}`);
    }
    if (row.investment.honest && row.investment.total !== null) {
      const suffix = row.investment.valuation_basis === "deposits" ? " (at cost)" : "";
      lines.push(`Investment: ${fmtExact(row.investment.total)}${suffix}`);
    } else {
      lines.push(`Investment: No data — ${reasonSentence(row.investment.gap_reason)}`);
    }
  }

  if (isNewest && row.investment.honest && row.investment.as_of_date !== null) {
    lines.push(`Investments as of ${asOfLabel(row.investment.as_of_date)}`);
  }

  return lines;
}
