// Assert-based self-check for netWorthTrendHelpers.ts (Phase 23 Plan 01, RED step).
// Run: node --experimental-strip-types ui/app/cashflow/charts/netWorthTrendHelpers.check.mjs
// Repeat with TZ=America/Los_Angeles to pin the UTC-label rule.
//
// No test framework, no console-log-only assertions — this uses the strict assert
// module so a failed check exits non-zero. The explicit ".ts" extension on the
// import below is required: bare specifiers fail under --experimental-strip-types.
import assert from "node:assert/strict";
import {
  RANGE_MONTHS,
  REASON_SENTENCES,
  fmtExact,
  monthLabel,
  asOfLabel,
  reasonSentence,
  rowGapCodes,
  trimPreLedger,
  visibleRows,
  toPlotPoints,
  tooltipLines,
  seamMonth,
} from "./netWorthTrendHelpers.ts";

// --- Fixture builder -------------------------------------------------------
// row(month, { liquid, investment, total, honest, gap }) returns a row shaped
// exactly like backend/schemas.py NetWorthHistoryRowOut (L361-408), filling in
// defaults for any field not passed. Honest halves default by_account/by_position
// to {}; dishonest halves default to null (matches the live API).
function row(month, opts = {}) {
  const liquid = {
    total: null,
    by_account: null,
    honest: false,
    gap_reason: null,
    ...opts.liquid,
  };
  if (liquid.honest && liquid.by_account === null) liquid.by_account = {};

  const investment = {
    total: null,
    by_position: null,
    honest: false,
    gap_reason: null,
    valuation_basis: null,
    as_of_date: null,
    ...opts.investment,
  };
  if (investment.honest && investment.by_position === null) investment.by_position = {};

  return {
    month,
    total: opts.total !== undefined ? opts.total : null,
    honest: opts.honest !== undefined ? opts.honest : false,
    gap_reason: opts.gap !== undefined ? opts.gap : null,
    liquid,
    investment,
  };
}

// --- Fixtures (from the plan's interfaces block, synthetic values) -----

// today1Y: the 12 rows 2025-10..2026-09 shaped like a live months=12 response.
const BOTH_GAPPED_MONTHS = [
  "2025-10", "2025-11", "2025-12",
  "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
];
const today1Y = [
  ...BOTH_GAPPED_MONTHS.map((m) =>
    row(m, {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    })
  ),
  row("2026-07", {
    liquid: { gap_reason: "no_opening_anchor" },
    investment: { total: 41234567.49, honest: true, as_of_date: "2026-07-31" },
    gap: "liquid_half_gapped",
  }),
  row("2026-08", {
    liquid: { gap_reason: "no_opening_anchor" },
    investment: { total: 45678901.23, honest: true, as_of_date: "2026-08-29" },
    gap: "liquid_half_gapped",
  }),
  row("2026-09", {
    liquid: { total: 61234567.19, honest: true },
    investment: { total: 48765432.11, honest: true, as_of_date: "2026-09-20" },
    total: 109999999.3,
    honest: true,
  }),
];

// withPreLedger: three pre_ledger rows 2020-01..2020-03, then today1Y (15 rows).
const PRE_LEDGER_MONTHS = ["2020-01", "2020-02", "2020-03"];
const preLedgerRows = PRE_LEDGER_MONTHS.map((m) =>
  row(m, {
    liquid: { gap_reason: "pre_ledger" },
    investment: { gap_reason: "no_investment_tracking_before_launch" },
    gap: "both_halves_gapped",
  })
);
const withPreLedger = [...preLedgerRows, ...today1Y];

// --- 1. D-03: range constant ------------------------------------------------
assert.deepEqual(RANGE_MONTHS, { "1Y": 12, "3Y": 36, All: 600 });

// --- 2. D-04: pre-ledger trim ------------------------------------------------
{
  const trimmed = trimPreLedger(withPreLedger);
  assert.equal(trimmed.length, 12);
  assert.equal(trimmed[0].month, "2025-10");

  assert.deepEqual(visibleRows(withPreLedger, "All"), trimPreLedger(withPreLedger));
  assert.equal(visibleRows(withPreLedger, "1Y").length, 15);
  assert.equal(visibleRows(withPreLedger, "3Y").length, 15);

  const onlyPreLedger = preLedgerRows;
  assert.equal(trimPreLedger(onlyPreLedger).length, onlyPreLedger.length);

  const preLedgerAfterReal = [
    row("2025-01", {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    }),
    row("2025-02", {
      liquid: { gap_reason: "pre_ledger" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    }),
  ];
  assert.equal(trimPreLedger(preLedgerAfterReal).length, 2);
}

// --- 3. D-05/D-11: gap-honest plot points, no interpolation -----------------
{
  const points = toPlotPoints(today1Y);
  for (let i = 0; i <= 10; i++) assert.equal(points[i].total, null);
  assert.equal(points[11].total, 109999999.3);

  for (let i = 0; i <= 10; i++) assert.equal(points[i].liquidTotal, null);
  assert.equal(points[11].liquidTotal, 61234567.19);

  for (let i = 0; i <= 8; i++) assert.equal(points[i].investmentTotal, null);
  assert.equal(points[9].investmentTotal, 41234567.49);
  assert.equal(points[10].investmentTotal, 45678901.23);
  assert.equal(points[11].investmentTotal, 48765432.11);

  points.forEach((p, i) => {
    assert.equal(p.month, today1Y[i].month);
    assert.equal(p.row, today1Y[i]);
  });

  const carryTest = [
    row("2026-01", { liquid: { total: 100, honest: true }, investment: { total: 100, honest: true }, total: 100, honest: true }),
    row("2026-02", {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    }),
    row("2026-03", { liquid: { total: 300, honest: true }, investment: { total: 300, honest: true }, total: 300, honest: true }),
  ];
  assert.deepEqual(toPlotPoints(carryTest).map((p) => p.total), [100, null, 300]);

  const dishonestNonNull = [
    row("2026-01", {
      liquid: { total: 500, honest: false, gap_reason: "no_opening_anchor" },
      investment: { total: 500, honest: false, gap_reason: "fx_unavailable" },
      total: null,
      honest: false,
      gap: "both_halves_gapped",
    }),
  ];
  const dp = toPlotPoints(dishonestNonNull);
  assert.equal(dp[0].liquidTotal, null);
  assert.equal(dp[0].investmentTotal, null);
}

// --- 4. D-07: single reason map, unknown/null fallback ----------------------
{
  const EXPECTED_REASONS = {
    pre_ledger: "before the ledger existed for these accounts",
    no_opening_anchor: "liquid accounts have no opening balance anchor for these months",
    no_closing_anchor: "liquid accounts have no closing balance anchor for these months",
    no_investment_tracking_before_launch: "investment tracking hadn't started yet",
    synthetic_opening_only: "only a synthetic opening balance exists for the investment side, not a verified one",
    fx_unavailable: "the historical FX rate could not be verified for these months",
    unknown_event_type: "a portfolio event of an unrecognized type blocks reconstruction for these months",
    negative_running_quantity: "the replayed position quantity went negative, which can't be honest",
    no_snapshot_for_month: "no daily portfolio snapshot exists for this month",
    snapshot_missing_position: "the snapshot is missing a position that should be held",
    parity_mismatch: "the liquid and investment totals didn't reconcile for this month",
  };
  assert.equal(Object.keys(REASON_SENTENCES).length, 11);
  for (const [code, sentence] of Object.entries(EXPECTED_REASONS)) {
    assert.ok(code in REASON_SENTENCES, `missing reason code: ${code}`);
    assert.equal(reasonSentence(code), sentence);
  }
  assert.equal(reasonSentence("brand_new_code"), "data could not be verified for these months (brand_new_code)");
  assert.equal(reasonSentence(null), "data could not be verified for these months");
}

// --- 9. D-09/D-10: tooltip text ----------------------------------------------
{
  const sep = today1Y[11];
  const jul = today1Y[9];
  const octBoth = today1Y[0];

  assert.deepEqual(tooltipLines(sep, "total", true), [
    "Sep 2026",
    "109,999,999",
    "Investments as of Sep 20, 2026",
  ]);
  assert.deepEqual(tooltipLines(sep, "split", true), [
    "Sep 2026",
    "Liquid: 61,234,567",
    "Investment: 48,765,432",
    "Investments as of Sep 20, 2026",
  ]);
  assert.deepEqual(tooltipLines(jul, "total", false), [
    "Jul 2026",
    "No data — liquid accounts have no opening balance anchor for these months",
  ]);
  assert.deepEqual(tooltipLines(jul, "split", false), [
    "Jul 2026",
    "Liquid: No data — liquid accounts have no opening balance anchor for these months",
    "Investment: 41,234,567",
  ]);
  assert.deepEqual(tooltipLines(octBoth, "total", false), [
    "Oct 2025",
    "No data — liquid accounts have no opening balance anchor for these months; investment tracking hadn't started yet",
  ]);

  const allTooltipOutputs = [
    ...tooltipLines(sep, "total", true),
    ...tooltipLines(sep, "split", true),
    ...tooltipLines(jul, "total", false),
    ...tooltipLines(jul, "split", false),
    ...tooltipLines(octBoth, "total", false),
  ];
  assert.ok(!allTooltipOutputs.some((line) => line.includes("Add a back-dated")));

  // rowGapCodes: liquid first, then investment; empty when both honest; falls
  // back to the composed code (parity_mismatch) when both halves are null.
  assert.deepEqual(rowGapCodes(octBoth), ["no_opening_anchor", "no_investment_tracking_before_launch"]);
  assert.deepEqual(rowGapCodes(jul), ["no_opening_anchor"]);
  assert.deepEqual(rowGapCodes(sep), []);
  assert.deepEqual(
    rowGapCodes({
      month: "2026-09",
      total: null,
      honest: false,
      gap_reason: "parity_mismatch",
      liquid: { total: 100, by_account: {}, honest: true, gap_reason: null },
      investment: { total: 100, by_position: {}, honest: true, gap_reason: null, valuation_basis: null, as_of_date: null },
    }),
    ["parity_mismatch"]
  );
}

// --- 11. Labels: UTC-stable formatting ---------------------------------------
assert.equal(monthLabel("2026-09"), "Sep 2026");
assert.equal(monthLabel("2025-10"), "Oct 2025");
assert.equal(asOfLabel("2026-09-20"), "Sep 20, 2026");
assert.equal(fmtExact(-750000), "-750,000");

// --- 12. Phase 23.1: basis split, seam month and tooltip suffix ------------
// archival1Y: the live-shaped post-23.1 1Y fixture (synthetic values). Months before 2026-07 carry the investment
// half "at cost" (deposits basis, the old Investements running balance);
// 2026-07 onward are honest snapshot months. Liquid stays
// "ledger_plus_corrections" throughout except the newest (live-anchored) row.
const ARCHIVAL_EARLY_MONTHS = [
  "2025-10", "2025-11", "2025-12",
  "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
];
const archivalEarlyRows = ARCHIVAL_EARLY_MONTHS.map((m, i) => {
  const liquid = 40000000 + i * 7000000;
  const investment = 10000000 + i * 3000000;
  return row(m, {
    liquid: { total: liquid, honest: true, valuation_basis: "ledger_plus_corrections" },
    investment: { total: investment, honest: true, valuation_basis: "deposits" },
    total: liquid + investment,
    honest: true,
  });
});
const archival1Y = [
  ...archivalEarlyRows,
  row("2026-06", {
    liquid: { total: 52000000, honest: true, valuation_basis: "ledger_plus_corrections" },
    investment: { total: 58000000, honest: true, valuation_basis: "deposits" },
    total: 110000000,
    honest: true,
  }),
  row("2026-07", {
    liquid: { total: 60500000, honest: true, valuation_basis: "ledger_plus_corrections" },
    investment: {
      total: 41234567.49,
      honest: true,
      valuation_basis: "snapshot",
      as_of_date: "2026-07-31",
    },
    total: 101734567.49,
    honest: true,
  }),
  row("2026-08", {
    liquid: { total: 63456789.12, honest: true, valuation_basis: "ledger_plus_corrections" },
    investment: {
      total: 45678901.23,
      honest: true,
      valuation_basis: "snapshot",
      as_of_date: "2026-08-29",
    },
    total: 109135690.35,
    honest: true,
  }),
  row("2026-09", {
    liquid: { total: 61234567.19, honest: true, valuation_basis: null },
    investment: {
      total: 48765432.11,
      honest: true,
      valuation_basis: "snapshot",
      as_of_date: "2026-09-20",
    },
    total: 109999999.3,
    honest: true,
  }),
];

// --- 12c. seamMonth -------------------------------------------------------
assert.equal(seamMonth(archival1Y), "2026-07");
assert.equal(seamMonth(today1Y), null);

// --- 12f. toPlotPoints basis split -----------------------------------------
{
  const points = toPlotPoints(archival1Y);
  for (let i = 0; i <= 8; i++) {
    assert.notEqual(points[i].totalAtCost, null);
    assert.notEqual(points[i].investmentAtCost, null);
    assert.equal(points[i].totalMarket, null);
    assert.equal(points[i].investmentMarket, null);
  }
  for (let i = 9; i <= 11; i++) {
    assert.equal(points[i].totalAtCost, null);
    assert.equal(points[i].investmentAtCost, null);
    assert.notEqual(points[i].totalMarket, null);
    assert.notEqual(points[i].investmentMarket, null);
  }
  points.forEach((p) => assert.notEqual(p.liquidTotal, null));
  points.forEach((p, i) => {
    assert.equal(p.total, archival1Y[i].total);
    assert.equal(p.investmentTotal, archival1Y[i].investment.total);
  });

  const todayPoints = toPlotPoints(today1Y);
  todayPoints.forEach((p) => {
    assert.equal(p.totalAtCost, null);
    assert.equal(p.investmentAtCost, null);
  });
  for (let i = 0; i <= 10; i++) assert.equal(todayPoints[i].totalMarket, null);
  assert.equal(todayPoints[11].totalMarket, 109999999.3);
}

// --- 12g. tooltipLines "(at cost)" suffix ----------------------------------
{
  const jun = archival1Y[8];
  const jul = archival1Y[9];
  assert.deepEqual(tooltipLines(jun, "total", false), ["Jun 2026", "110,000,000 (at cost)"]);
  assert.deepEqual(tooltipLines(jun, "split", false), [
    "Jun 2026",
    "Liquid: 52,000,000",
    "Investment: 58,000,000 (at cost)",
  ]);
  assert.deepEqual(tooltipLines(jul, "total", false), ["Jul 2026", "101,734,567"]);
}

console.log("netWorthTrendHelpers: all checks passed");
