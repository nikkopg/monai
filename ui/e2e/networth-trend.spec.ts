import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 23 Plan 02 — net worth trend card render + gap/range/split/hover/error
// coverage.
//
// Every API call the cashflow page makes (/api/cashflow/summary, /api/net-worth,
// /api/cashflow/networth-history) is intercepted, so this spec is deterministic
// and never reads the live DB.
//
// <!-- planner-discipline-allow: api/net-worth -->
// This spec legitimately mocks the hero's endpoint (the card only renders
// inside page.tsx's summary-gated fragment, and the hero sits above it). The
// Task 1 negative gate on `api/net-worth` applies only to
// NetWorthTrendChart.tsx, which never calls that endpoint itself.
//
// Hover assertions run in headless Chromium, where requestAnimationFrame
// fires normally. The automated browser pane used elsewhere in this project
// is different: it reports `visibilityState: "hidden"` and never fires rAF.
// The live human check in plan 23-03 covers that environment.
// ---------------------------------------------------------------------------

// --- Fixture builder (mirrors plan 23-01's row() builder; no app import) ---

function nwRow(
  month: string,
  opts: {
    liquid?: Partial<{
      total: number;
      by_account: Record<string, number> | null;
      honest: boolean;
      gap_reason: string | null;
      valuation_basis: string | null;
    }>;
    investment?: Partial<{
      total: number;
      by_position: Record<string, number> | null;
      honest: boolean;
      gap_reason: string | null;
      valuation_basis: string | null;
      as_of_date: string | null;
    }>;
    total?: number;
    honest?: boolean;
    gap?: string | null;
  } = {}
) {
  const liquid = {
    total: null as number | null,
    by_account: null as Record<string, number> | null,
    honest: false,
    gap_reason: null as string | null,
    valuation_basis: null as string | null,
    ...opts.liquid,
  };
  if (liquid.honest && liquid.by_account === null) liquid.by_account = {};

  const investment = {
    total: null as number | null,
    by_position: null as Record<string, number> | null,
    honest: false,
    gap_reason: null as string | null,
    valuation_basis: null as string | null,
    as_of_date: null as string | null,
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

type NwRow = ReturnType<typeof nwRow>;

function monthRange(startYear: number, startMonth: number, count: number): string[] {
  const out: string[] = [];
  let y = startYear;
  let m = startMonth;
  for (let i = 0; i < count; i++) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m++;
    if (m > 12) {
      m = 1;
      y++;
    }
  }
  return out;
}

// today1Y: the 12-month 2025-10..2026-09 live-shaped rows from the plan
// 23-01 interfaces block. 2026-09 is honest (total 109999999.3, as_of
// 2026-09-20).
const BOTH_GAPPED_MONTHS = [
  "2025-10", "2025-11", "2025-12",
  "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
];

function today1Y(): NwRow[] {
  return [
    ...BOTH_GAPPED_MONTHS.map((m) =>
      nwRow(m, {
        liquid: { gap_reason: "no_opening_anchor" },
        investment: { gap_reason: "no_investment_tracking_before_launch" },
        gap: "both_halves_gapped",
      })
    ),
    nwRow("2026-07", {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { total: 41234567.49, honest: true, as_of_date: "2026-07-31" },
      gap: "liquid_half_gapped",
    }),
    nwRow("2026-08", {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { total: 45678901.23, honest: true, as_of_date: "2026-08-29" },
      gap: "liquid_half_gapped",
    }),
    nwRow("2026-09", {
      liquid: { total: 61234567.19, honest: true },
      investment: { total: 48765432.11, honest: true, as_of_date: "2026-09-20" },
      total: 109999999.3,
      honest: true,
    }),
  ];
}

// allGapped1Y: today1Y with 2026-09 also both-halves gapped.
function allGapped1Y(): NwRow[] {
  const base = today1Y();
  return [
    ...base.slice(0, 11),
    nwRow("2026-09", {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { gap_reason: "no_snapshot_for_month" },
      gap: "both_halves_gapped",
    }),
  ];
}

// threeYear: 24 both-gapped rows 2023-10..2025-09 followed by today1Y.
function threeYear(): NwRow[] {
  const extra = monthRange(2023, 10, 24).map((m) =>
    nwRow(m, {
      liquid: { gap_reason: "no_opening_anchor" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    })
  );
  return [...extra, ...today1Y()];
}

// allRange: three pre_ledger rows 2020-01..2020-03 followed by today1Y.
function allRange(): NwRow[] {
  const preLedger = ["2020-01", "2020-02", "2020-03"].map((m) =>
    nwRow(m, {
      liquid: { gap_reason: "pre_ledger" },
      investment: { gap_reason: "no_investment_tracking_before_launch" },
      gap: "both_halves_gapped",
    })
  );
  return [...preLedger, ...today1Y()];
}

// archival1Y: the live-shaped post-23.1 1Y fixture (plan 23.1-03's interfaces
// table, synthetic values). 2025-10..2026-05 carry an at-cost ("deposits")
// investment basis with values well under the 2026-06 pinned step so the seam
// stays the only jump; 2026-07 onward are honest snapshot months. Liquid
// stays "ledger_plus_corrections" throughout except the newest live-anchored
// row.
const ARCHIVAL_EARLY_MONTHS = [
  "2025-10", "2025-11", "2025-12",
  "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
];

function archival1Y(): NwRow[] {
  const early = ARCHIVAL_EARLY_MONTHS.map((m, i) => {
    const liquid = 40000000 + i * 7000000;
    const investment = 10000000 + i * 3000000;
    return nwRow(m, {
      liquid: { total: liquid, honest: true, valuation_basis: "ledger_plus_corrections" },
      investment: { total: investment, honest: true, valuation_basis: "deposits" },
      total: liquid + investment,
      honest: true,
    });
  });
  return [
    ...early,
    nwRow("2026-06", {
      liquid: { total: 52000000, honest: true, valuation_basis: "ledger_plus_corrections" },
      investment: { total: 58000000, honest: true, valuation_basis: "deposits" },
      total: 110000000,
      honest: true,
    }),
    nwRow("2026-07", {
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
    nwRow("2026-08", {
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
    nwRow("2026-09", {
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
}

// summaryFixture, copied from cashflow-dashboard.spec.ts — the new card only
// renders inside page.tsx's summary-gated fragment.
function summaryFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    totals: { income: 5_000_000, expense: 2_000_000, net: 3_000_000 },
    by_category: [
      ["Food & Drinks", 1_200_000],
      ["Transport", 500_000],
      ["Shopping", 300_000],
    ],
    accounts: [
      { id: 1, name: "Cash", current_balance: 4_000_000, period_net: 1_500_000 },
      { id: 2, name: "Bank", current_balance: 8_000_000, period_net: 1_500_000 },
    ],
    trend: [
      { month: "2026-02", income: 4_000_000, expense: 2_000_000, net: 2_000_000 },
      { month: "2026-03", income: 4_500_000, expense: 2_200_000, net: 2_300_000 },
      { month: "2026-04", income: 4_800_000, expense: 2_100_000, net: 2_700_000 },
      { month: "2026-05", income: 5_100_000, expense: 1_900_000, net: 3_200_000 },
      { month: "2026-06", income: 4_900_000, expense: 2_050_000, net: 2_850_000 },
      { month: "2026-07", income: 5_000_000, expense: 2_000_000, net: 3_000_000 },
    ],
    ...overrides,
  };
}

function netWorthFixture() {
  return {
    total: 110345678,
    liquid_total: 61234567,
    investment_total: 49111111,
    liquid_accounts: [],
    investment_groups: [],
    accounts_covered: 0,
    accounts_total: 0,
  };
}

type HistoryFn = (
  months: string
) => { status: number; rows: NwRow[]; liquid_drift_estimate?: number };

function defaultHistory(months: string): { status: number; rows: NwRow[] } {
  if (months === "12") return { status: 200, rows: today1Y() };
  if (months === "36") return { status: 200, rows: threeYear() };
  if (months === "600") return { status: 200, rows: allRange() };
  return { status: 200, rows: [] };
}

async function mockPage(page: Page, history: HistoryFn = defaultHistory) {
  const requestedMonths: string[] = [];

  await page.route("**/api/cashflow/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summaryFixture()),
    });
  });

  await page.route("**/api/net-worth", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(netWorthFixture()),
    });
  });

  await page.route("**/api/cashflow/networth-history**", async (route) => {
    const url = new URL(route.request().url());
    const months = url.searchParams.get("months") ?? "";
    requestedMonths.push(months);
    const { status, rows, liquid_drift_estimate } = history(months);
    if (status === 200) {
      const body: Record<string, unknown> = { rows, honest_months: [], gap_summary: {} };
      // Only present when the fixture opts in, so Phase 23 tests keep
      // receiving exactly today's envelope (no liquid_drift_estimate key).
      if (liquid_drift_estimate !== undefined) body.liquid_drift_estimate = liquid_drift_estimate;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    } else {
      await route.fulfill({ status });
    }
  });

  return requestedMonths;
}

test.describe("net worth trend card", () => {
  test("renders one honest dot and no caption text under the chart", async ({
    page,
  }) => {
    const requestedMonths = await mockPage(page);
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region).toBeVisible();

    await expect(
      region.getByRole("button", { name: "1Y", exact: true })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      region.getByRole("button", { name: "Total", exact: true })
    ).toHaveAttribute("aria-pressed", "true");

    await expect(region.locator("g.recharts-line")).toHaveCount(1);
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(1);

    await expect(region).not.toContainText("not shown:");
    await expect(region).not.toContainText("the figure above uses live prices");

    expect(requestedMonths[0]).toBe("12");
  });

  test("zero honest months still renders the card with no caption text", async ({
    page,
  }) => {
    await mockPage(page, (months) =>
      months === "12" ? { status: 200, rows: allGapped1Y() } : defaultHistory(months)
    );
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region).toBeVisible();
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(0);
    await expect(region).not.toContainText("not shown:");
    await expect(region).not.toContainText("Investments valued at");
  });

  test("range pills fetch 36 and 600, All trims pre-ledger months, and a loaded range is served from cache", async ({
    page,
  }) => {
    const requestedMonths = await mockPage(page);
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    // Wait for the 1Y dot before recording the baseline request count.
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(1);
    const initialTwelveCount = requestedMonths.filter((m) => m === "12").length;

    await region.getByRole("button", { name: "3Y", exact: true }).click();
    await expect.poll(() => requestedMonths.includes("36")).toBe(true);
    await expect(region).not.toContainText("not shown:");

    await region.getByRole("button", { name: "All", exact: true }).click();
    await expect.poll(() => requestedMonths.includes("600")).toBe(true);
    await expect(region).not.toContainText("not shown:");
    await expect(region).not.toContainText("Jan 2020");
    await expect(region).not.toContainText("before the ledger existed");

    await region.getByRole("button", { name: "1Y", exact: true }).click();
    // Cache proof (D-03) without relying on networkidle, which can be flaky
    // under the Next dev server's hot-reload socket: the loading placeholder
    // never reappears and no new "12" request is issued.
    await expect(region.getByText("Loading net worth history…")).toHaveCount(0);
    const finalTwelveCount = requestedMonths.filter((m) => m === "12").length;
    expect(finalTwelveCount).toBe(initialTwelveCount);
    await expect(
      region.getByRole("button", { name: "1Y", exact: true })
    ).toHaveAttribute("aria-pressed", "true");

    await region.getByRole("button", { name: "All", exact: true }).click();
    await expect(
      region.getByRole("button", { name: "All", exact: true })
    ).toHaveAttribute("aria-pressed", "true");
    await region.getByRole("button", { name: "1Y", exact: true }).click();
    await expect(
      region.getByRole("button", { name: "1Y", exact: true })
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("Split draws liquid and investment as two independently honest lines", async ({
    page,
  }) => {
    const requestedMonths = await mockPage(page);
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(1);
    const historyRequestsBefore = requestedMonths.length;

    await region.getByRole("button", { name: "Split", exact: true }).click();
    // liquid shows only Sep, investment shows Jul, Aug and Sep (D-11).
    await expect(region.locator("g.recharts-line")).toHaveCount(2);
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(4);

    await expect(region.getByText("Liquid", { exact: true })).toBeVisible();
    await expect(region.getByText("Investment", { exact: true })).toBeVisible();

    await region.getByRole("button", { name: "Total", exact: true }).click();
    await expect(region.locator("g.recharts-line")).toHaveCount(1);
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(1);
    await expect(region.getByText("Liquid", { exact: true })).toHaveCount(0);
    await expect(region.getByText("Investment", { exact: true })).toHaveCount(0);

    // No new history request was made by the mode switches.
    expect(requestedMonths.length).toBe(historyRequestsBefore);
  });

  test("hover shows the exact month and value, and No data with the reason on a gapped month", async ({
    page,
  }) => {
    await mockPage(page);
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region.locator("circle.recharts-line-dot")).toHaveCount(1);

    const tooltip = region.locator(".recharts-tooltip-wrapper");

    // Honest point.
    await region.locator("circle.recharts-line-dot").first().hover();
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("Sep 2026");
    await expect(tooltip).toContainText("109,999,999");
    await expect(tooltip).toContainText("Investments as of Sep 20, 2026");

    // Gapped month: hover the middle of the chart surface. With 12 points
    // this lands on Mar or Apr 2026, and both are gapped.
    //
    // The toBeVisible assertion below is load-bearing. recharts hides the
    // tooltip wrapper with `visibility: hidden` when the filtered payload is
    // empty, so this assertion fails if `filterNull={false}` is ever removed
    // from the chart's <Tooltip>.
    const surface = region.locator("svg.recharts-surface").first();
    const box = await surface.boundingBox();
    if (!box) throw new Error("chart surface has no bounding box");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText(
      "No data — liquid accounts have no opening balance anchor for these months"
    );
  });

  test("a failed history fetch shows the error copy inside the card", async ({
    page,
  }) => {
    await mockPage(page, () => ({ status: 500, rows: [] }));
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region).toContainText(
      "Couldn't load net worth history — check the backend is running and reload the page."
    );
    await expect(
      region.getByRole("button", { name: "3Y", exact: true })
    ).toBeVisible();
  });

  test("archival history: dashed at-cost stretch and seam marker, no captions", async ({
    page,
  }) => {
    const requestedMonths = await mockPage(page, (m) =>
      m === "12"
        ? { status: 200, rows: archival1Y(), liquid_drift_estimate: 8000000 }
        : defaultHistory(m)
    );
    await page.goto("/cashflow");

    const region = page.getByRole("region", { name: "Net worth trend", exact: true });
    await expect(region).toBeVisible();

    // Total mode: market Line + one dashed at-cost Line.
    await expect(region.locator("g.recharts-line")).toHaveCount(2);
    await expect(
      region.locator('path.recharts-line-curve[stroke-dasharray="5 5"]')
    ).toHaveCount(1);

    await expect(region.locator(".recharts-reference-line")).toHaveCount(1);
    await expect(region).toContainText("Market value →");

    await expect(region).not.toContainText("may be overstated");
    await expect(region).not.toContainText("money deposited");
    await expect(region).not.toContainText("not shown:");
    await expect(region).not.toContainText("the figure above uses live prices");

    // Hover the leftmost (Oct 2025, at-cost) point via the surface-hover
    // technique, not `circle.recharts-line-dot.first()`: with two Lines, DOM
    // order — not chart order — decides which dot comes first.
    const tooltip = region.locator(".recharts-tooltip-wrapper");
    const surface = region.locator("svg.recharts-surface").first();
    const box = await surface.boundingBox();
    if (!box) throw new Error("chart surface has no bounding box");
    await page.mouse.move(box.x + 8, box.y + box.height / 2);
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("Oct 2025");
    await expect(tooltip).toContainText("(at cost)");

    // Split mode: liquid + investment-market + investment-at-cost.
    const historyRequestsBefore = requestedMonths.length;
    await region.getByRole("button", { name: "Split", exact: true }).click();
    await expect(region.locator("g.recharts-line")).toHaveCount(3);
    await expect(
      region.locator('path.recharts-line-curve[stroke-dasharray="5 5"]')
    ).toHaveCount(1);
    await expect(region.getByText("Liquid", { exact: true })).toBeVisible();
    await expect(region.getByText("Investment", { exact: true })).toBeVisible();
    await expect(region.locator(".recharts-reference-line")).toHaveCount(1);

    // The mode switch reused the cached rows — no new history request.
    expect(requestedMonths.length).toBe(historyRequestsBefore);
  });
});
