import { test, expect, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";

// D-11: these pages run with real chart data under the CSP header; any
// securitypolicyviolation fails the test.
test.beforeEach(async ({ page }) => {
  await watchCsp(page);
});
test.afterEach(async ({ page }) => {
  expect(await cspViolations(page)).toEqual([]);
});

// ---------------------------------------------------------------------------
// Phase 4 Plan 04 — Cashflow dashboard render + period-refetch spec.
//
// Mirrors smoke.spec.ts / settings.spec.ts conventions: navigate, assert
// visible text/role queries. GET /api/cashflow/summary is intercepted with a
// fixture response so the spec is deterministic regardless of whether a real
// backend + seeded DB are running in this sandbox (mirrors settings.spec.ts's
// "must render even if the backend call fails/is absent" approach, but here
// we assert the populated-data path since that's the behavior under test).
// ---------------------------------------------------------------------------

function summaryFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    totals: { income: 5_000_000, expense: 2_000_000, net: 3_000_000 },
    by_category: [
      {
        id: 1,
        name: "Food & Drinks",
        color: "#d8b26a",
        icon: null,
        total: 1_200_000, // pii-ok synthetic
        children: [
          { id: 11, name: "Groceries", color: "#d8b26a", icon: null, total: 700_000 }, // pii-ok synthetic
          { id: 12, name: "Restaurants", color: "#d8b26a", icon: null, total: 500_000 }, // pii-ok synthetic
        ],
      },
      { id: 2, name: "Transport", color: "#8fae9c", icon: null, total: 500_000, children: [] }, // pii-ok synthetic
      { id: 3, name: "Shopping", color: "#b5503f", icon: null, total: 300_000, children: [] }, // pii-ok synthetic
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

// Records `period` and the "start_date..end_date" of every summary request. A
// request whose range is in `byRange` gets that body; any other gets `body`.
async function mockSummary(
  page: Page,
  body: unknown = summaryFixture(),
  byRange: Record<string, unknown> = {}
) {
  const periods: string[] = [];
  const ranges: string[] = [];
  await page.route("**/api/cashflow/summary**", async (route) => {
    const url = new URL(route.request().url());
    const range = `${url.searchParams.get("start_date")}..${url.searchParams.get("end_date")}`;
    periods.push(url.searchParams.get("period") || "");
    ranges.push(range);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(byRange[range] ?? body),
    });
  });
  return { periods, ranges };
}

const cashflowCard = (page: Page) => page.getByRole("region", { name: "Cashflow", exact: true });

test.describe("/cashflow dashboard", () => {
  test("renders the page heading and the three summary figure captions", async ({
    page,
  }) => {
    await mockSummary(page);
    await page.goto("/cashflow");

    await expect(
      page.getByRole("heading", { name: "Cashflow" })
    ).toBeVisible();
    const card = cashflowCard(page);
    await expect(card.getByText("Income", { exact: true })).toBeVisible();
    await expect(card.getByText("Expenses", { exact: true })).toBeVisible();
    await expect(card.getByText("Net saved", { exact: true })).toBeVisible();
  });

  test("renders at least one chart svg", async ({ page }) => {
    await mockSummary(page);
    await page.goto("/cashflow");

    await expect(cashflowCard(page).locator("svg").first()).toBeVisible();
  });

  test("the period buttons issue custom-range requests for the window and the one before", async ({
    page,
  }) => {
    await page.clock.setFixedTime(new Date(2026, 10, 11, 12));
    const { periods, ranges } = await mockSummary(page);
    await page.goto("/cashflow");

    const month = cashflowCard(page).getByRole("button", { name: "Month", exact: true });
    await expect(month).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => ranges).toContain("2026-11-01..2026-11-11");
    expect(ranges).toContain("2026-10-01..2026-10-11");
    expect(new Set(periods)).toEqual(new Set(["custom"]));

    await cashflowCard(page).getByRole("button", { name: "Year", exact: true }).click();

    await expect.poll(() => ranges).toContain("2026-01-01..2026-11-11");
    expect(ranges).toContain("2025-01-01..2025-11-11");
  });
});

// ---------------------------------------------------------------------------
// The Cashflow card: pills, in-card chart, stepper, change badges and spend bar.
// Synthetic figures; the browser clock is fixed to local noon on 11 Nov 2026.
// ---------------------------------------------------------------------------
const totals = (income: number, expense: number) => ({ income, expense, net: income - expense });
const rangeBodies = {
  "2026-11-01..2026-11-11": summaryFixture({ totals: totals(9_500_000, 4_210_000) }), // pii-ok synthetic
  "2026-10-01..2026-10-11": summaryFixture({ totals: totals(8_500_000, 4_600_000) }), // pii-ok synthetic
  "2026-10-01..2026-10-31": summaryFixture({ totals: totals(8_000_000, 5_200_000) }), // pii-ok synthetic
  "2026-09-01..2026-09-30": summaryFixture({ totals: totals(10_000_000, 4_000_000) }), // pii-ok synthetic
};
// Every other window of the Jun..Nov month frame, so the chart has six bars.
const frameBodies = {
  ...rangeBodies,
  "2026-06-01..2026-06-30": summaryFixture({ totals: totals(7_000_000, 3_000_000) }), // pii-ok synthetic
  "2026-07-01..2026-07-31": summaryFixture({ totals: totals(7_500_000, 3_500_000) }), // pii-ok synthetic
  "2026-08-01..2026-08-31": summaryFixture({ totals: totals(8_200_000, 3_900_000) }), // pii-ok synthetic
};

const GREEN = "rgb(47, 111, 79)";
const BAD = "rgb(166, 70, 54)";

test.describe("Cashflow card", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(new Date(2026, 10, 11, 12));
  });

  // The change badge sitting right after a row's label word.
  const badge = (page: Page, label: string) =>
    cashflowCard(page).getByText(label, { exact: true }).locator("xpath=..").locator("span[title]");

  test("renders the figures, badges, bar and stepper", async ({ page }) => {
    await mockSummary(page, summaryFixture(), rangeBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);

    await expect(card.getByText("9,500,000", { exact: true })).toBeVisible();
    await expect(card.getByText("4,210,000", { exact: true })).toBeVisible();
    await expect(card.getByText("+5,290,000", { exact: true })).toBeVisible();

    const income = badge(page, "Income");
    const expenses = badge(page, "Expenses");
    const net = badge(page, "Net saved");
    await expect(income).toHaveText("+12%");
    await expect(expenses).toHaveText("−8%");
    await expect(net).toHaveText("+36%");
    for (const b of [income, expenses, net]) await expect(b).toHaveCSS("color", GREEN);
    await expect(income).toHaveAttribute("title", "Up 12% vs 1–11 Oct (8,500,000)");
    await expect(expenses).toHaveAttribute("title", "Down 8% vs 1–11 Oct (4,600,000)");
    await expect(net).toHaveAttribute("title", "Up 36% vs 1–11 Oct (3,900,000)");
    await expect(income.locator("i")).toHaveCSS("border-bottom-width", "6px");
    await expect(expenses.locator("i")).toHaveCSS("border-top-width", "6px");
    await expect(net.locator("i")).toHaveCSS("border-bottom-width", "6px");

    await expect(card.getByRole("img", { name: "Spent 44% of income" })).toBeVisible();
    await expect(card.getByText("56% kept", { exact: true })).toBeVisible();

    await expect(card.getByText("Nov 2026", { exact: true })).toBeVisible();
    await expect(card.getByText("1–11 Nov · vs 1–11 Oct", { exact: true })).toBeVisible();
    await expect(card.getByRole("button", { name: "Next month" })).toBeDisabled();

    // The card holds the only period picker on the page.
    const pills = /^(Week|Month|Year)$/;
    await expect(page.getByRole("button", { name: pills })).toHaveCount(3);
    await expect(card.getByRole("button", { name: pills })).toHaveCount(3);
  });

  test("the stepper moves to the previous month and back", async ({ page }) => {
    const { ranges } = await mockSummary(page, summaryFixture(), rangeBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByText("Nov 2026", { exact: true })).toBeVisible();

    await card.getByRole("button", { name: "Previous month" }).click();
    await expect.poll(() => ranges).toContain("2026-10-01..2026-10-31");
    expect(ranges).toContain("2026-09-01..2026-09-30");
    await expect(card.getByText("Oct 2026", { exact: true })).toBeVisible();
    await expect(card.getByText("1–31 Oct · vs 1–30 Sep", { exact: true })).toBeVisible();
    await expect(card.getByText("8,000,000", { exact: true })).toBeVisible();

    await expect(badge(page, "Income")).toHaveText("−20%");
    await expect(badge(page, "Expenses")).toHaveText("+30%");
    await expect(badge(page, "Net saved")).toHaveText("−53%");
    for (const label of ["Income", "Expenses", "Net saved"]) {
      await expect(badge(page, label)).toHaveCSS("color", BAD);
    }
    await expect(badge(page, "Income").locator("i")).toHaveCSS("border-top-width", "6px");
    await expect(badge(page, "Expenses").locator("i")).toHaveCSS("border-bottom-width", "6px");
    await expect(card.getByRole("img", { name: "Spent 65% of income" })).toBeVisible();
    await expect(card.getByText("35% kept", { exact: true })).toBeVisible();
    await expect(card.getByRole("button", { name: "Next month" })).toBeEnabled();

    await card.getByRole("button", { name: "Next month" }).click();
    await expect(card.getByText("Nov 2026", { exact: true })).toBeVisible();
    await expect(card.getByText("9,500,000", { exact: true })).toBeVisible();
    await expect(card.getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  test("a period with no income hides the spend bar", async ({ page }) => {
    await mockSummary(page, summaryFixture(), {
      ...rangeBodies,
      "2026-11-01..2026-11-11": summaryFixture({ totals: { income: 0, expense: 1_000_000, net: -1_000_000 } }), // pii-ok synthetic
    });
    await page.goto("/cashflow");
    const card = cashflowCard(page);

    await expect(card.getByText("1,000,000", { exact: true }).first()).toBeVisible();
    await expect(card.getByRole("img", { name: /Spent/ })).toHaveCount(0);
    await expect(card.getByText(/kept/)).toHaveCount(0);
    await expect(badge(page, "Income")).toHaveText("−100%");
    await expect(badge(page, "Income")).toHaveCSS("color", BAD);
  });

  test("the chart sits in the card between the stepper and the Income row", async ({ page }) => {
    const { ranges } = await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    const group = card.getByRole("group", { name: "Cash flow by month" });
    await expect(group.getByRole("button")).toHaveText(["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"]);
    for (const r of [
      "2026-06-01..2026-06-30", "2026-07-01..2026-07-31", "2026-08-01..2026-08-31",
      "2026-09-01..2026-09-30", "2026-10-01..2026-10-31", "2026-11-01..2026-11-11",
    ]) expect(ranges).toContain(r);

    const title = await card.getByText("Nov 2026", { exact: true }).boundingBox();
    const chart = await group.locator("xpath=..").locator(".recharts-wrapper").boundingBox();
    const income = await card.getByText("Income", { exact: true }).boundingBox();
    expect(chart!.y).toBeGreaterThanOrEqual(title!.y + title!.height);
    expect(chart!.y + chart!.height).toBeLessThanOrEqual(income!.y);
    expect(chart!.height).toBeLessThanOrEqual(90);
    // the old separate card is gone and the card holds the only period pills
    await expect(page.getByText("Cash flow, last 6 months")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^(Week|Month|Year)$/ })).toHaveCount(3);
  });

  test("the pills switch the chart between weeks, months and years", async ({ page }) => {
    const { ranges } = await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);

    await card.getByRole("button", { name: "Week", exact: true }).click();
    await expect(card.getByRole("group", { name: "Cash flow by week" }).getByRole("button")).toHaveText([
      "5 Oct", "12 Oct", "19 Oct", "26 Oct", "2 Nov", "9 Nov",
    ]);
    expect(ranges).toContain("2026-10-05..2026-10-11");
    expect(ranges).toContain("2026-11-02..2026-11-08");

    await card.getByRole("button", { name: "Year", exact: true }).click();
    await expect(card.getByRole("group", { name: "Cash flow by year" }).getByRole("button")).toHaveText([
      "2021", "2022", "2023", "2024", "2025", "2026",
    ]);
    expect(ranges).toContain("2021-01-01..2021-12-31");
    expect(ranges).toContain("2025-01-01..2025-12-31");
  });

  test("request cost: seven ranges per load, none for a step inside the frame", async ({ page }) => {
    const { ranges } = await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByRole("group", { name: "Cash flow by month" })).toBeVisible();
    expect(new Set(ranges).size).toBe(7);
    expect(ranges).toContain("2026-10-01..2026-10-11");

    const before = ranges.length;
    await card.getByRole("button", { name: "Previous month" }).click();
    await expect(card.getByText("Oct 2026", { exact: true })).toBeVisible();
    await expect(card.getByText("8,000,000", { exact: true })).toBeVisible();
    expect(ranges.length).toBe(before);
  });

  test("a failed window shows a note, never a zero bar", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.route("**/api/cashflow/summary**", (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("start_date") === "2026-07-01" && url.searchParams.get("end_date") === "2026-07-31") {
        return route.fulfill({ status: 500, body: "boom" });
      }
      return route.fallback();
    });
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByText("Couldn't load the chart.")).toBeVisible();
    await expect(card.getByRole("group", { name: /Cash flow by/ })).toHaveCount(0);
    await expect(card.getByText("9,500,000", { exact: true })).toBeVisible();
  });

  // ---- the selected period -------------------------------------------------
  const bars = (page: Page) => cashflowCard(page).locator('path.recharts-rectangle[name="Income"], path.recharts-rectangle[name="Expenses"]');
  const labelBtn = (page: Page, name: string) =>
    cashflowCard(page).getByRole("group", { name: /Cash flow by/ }).getByRole("button", { name, exact: true });
  const opacities = (page: Page) => bars(page).evaluateAll((els) => els.map((e) => e.getAttribute("fill-opacity")));
  const areaX = (page: Page) =>
    cashflowCard(page).locator(".recharts-reference-area-rect").evaluate((e) => Number(e.getAttribute("x")));

  test("the selected period is highlighted and ‹ › move the highlight", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByRole("group", { name: "Cash flow by month" })).toBeVisible();

    await expect(labelBtn(page, "Nov 2026")).toHaveAttribute("aria-pressed", "true");
    await expect(labelBtn(page, "Nov 2026")).toHaveCSS("font-weight", "700");
    for (const m of ["Jun", "Jul", "Aug", "Sep", "Oct"]) {
      await expect(labelBtn(page, `${m} 2026`)).toHaveAttribute("aria-pressed", "false");
      await expect(labelBtn(page, `${m} 2026`)).toHaveCSS("font-weight", "400");
    }
    const ops = await opacities(page);
    expect(ops.filter((o) => o === "1")).toHaveLength(2);
    expect(ops.filter((o) => o === "0.35")).toHaveLength(10);
    await expect(card.locator(".recharts-reference-area-rect")).toHaveCount(1);
    await expect(card.locator(".recharts-reference-area-rect")).toHaveAttribute("fill", "#f0ece3");

    const before = await areaX(page);
    await card.getByRole("button", { name: "Previous month" }).click();
    await expect(labelBtn(page, "Oct 2026")).toHaveAttribute("aria-pressed", "true");
    await expect(labelBtn(page, "Nov 2026")).toHaveAttribute("aria-pressed", "false");
    await expect(card.locator('path.recharts-rectangle[name="Income"][offset="-1"]')).toHaveAttribute("fill-opacity", "1");
    expect(await areaX(page)).toBeLessThan(before);

    await card.getByRole("button", { name: "Next month" }).click();
    await expect(labelBtn(page, "Nov 2026")).toHaveAttribute("aria-pressed", "true");
  });

  test("clicking a bar selects its period", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByText("Nov 2026", { exact: true })).toBeVisible();

    await card.locator('path.recharts-rectangle[name="Income"][offset="-2"]').click({ position: { x: 9, y: 4 } }); // clear of the net dot
    await expect(card.getByText("1–30 Sep · vs 1–31 Aug", { exact: true })).toBeVisible();
    await expect(card.getByText("10,000,000", { exact: true })).toBeVisible(); // pii-ok synthetic
    await expect(labelBtn(page, "Sep 2026")).toHaveAttribute("aria-pressed", "true");
    await expect(card.getByRole("button", { name: "Next month" })).toBeEnabled();
  });

  test("Enter and Space on a label button select its period", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByText("Nov 2026", { exact: true })).toBeVisible();

    await labelBtn(page, "Aug 2026").focus();
    await page.keyboard.press("Enter");
    await expect(card.getByText("Aug 2026", { exact: true })).toBeVisible();
    await expect(labelBtn(page, "Aug 2026")).toHaveAttribute("aria-pressed", "true");

    await labelBtn(page, "Jul 2026").focus();
    await page.keyboard.press("Space");
    await expect(card.getByText("Jul 2026", { exact: true })).toBeVisible();
    await expect(labelBtn(page, "Jul 2026")).toHaveAttribute("aria-pressed", "true");
  });

  test("hovering a bar shows the exact figures", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await expect(card.getByRole("group", { name: "Cash flow by month" })).toBeVisible();
    await card.locator('path.recharts-rectangle[name="Income"][offset="0"]').hover({ position: { x: 9, y: 4 } }); // clear of the net dot
    await expect(page.getByText("Income 9,500,000", { exact: true })).toBeVisible();
    await expect(page.getByText("Expenses 4,210,000", { exact: true })).toBeVisible();
    await expect(page.getByText("Net +5,290,000", { exact: true })).toBeVisible();
  });

  test("a year with no history is not drawn", async ({ page }) => {
    const empty = summaryFixture({ totals: totals(0, 0) });
    await mockSummary(page, summaryFixture(), {
      "2021-01-01..2021-12-31": empty,
      "2022-01-01..2022-12-31": empty,
      "2023-01-01..2023-12-31": empty,
      "2024-01-01..2024-12-31": empty,
    });
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    await card.getByRole("button", { name: "Year", exact: true }).click();
    const group = card.getByRole("group", { name: "Cash flow by year" });
    await expect(group.getByRole("button")).toHaveText(["2025", "2026"]);
  });

  test("net worth spans the whole top row on a wide window", async ({ page }) => {
    await mockSummary(page, summaryFixture(), frameBodies);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/cashflow");
    const nw = await page.getByRole("region", { name: "Net worth trend" }).boundingBox();
    const row = await page.locator(".cf-lower").boundingBox();
    expect(nw!.width).toBeGreaterThanOrEqual(row!.width * 0.9);
  });

  test("the period pills are the shared Pills markup", async ({ page }) => {
    const { ranges } = await mockSummary(page, summaryFixture(), rangeBodies);
    await page.goto("/cashflow");
    const mine = cashflowCard(page).getByRole("button", { name: /^(Week|Month|Year)$/ });
    const theirs = page
      .getByRole("region", { name: "Net worth trend" })
      .getByRole("button", { name: "1Y", exact: true });

    for (const b of [mine.first(), theirs]) {
      await expect(b).toHaveAttribute("type", "button");
      await expect(b).toHaveAttribute("aria-pressed", /true|false/);
      await expect(b).toHaveCSS("border-radius", "999px");
      const parent = b.locator("xpath=..");
      expect(await parent.evaluate((el) => el.tagName)).toBe("DIV");
      await expect(parent).toHaveCSS("display", "flex");
      await expect(parent).toHaveCSS("border-radius", "999px");
    }

    const [week, month, year] = ["Week", "Month", "Year"].map((n) =>
      cashflowCard(page).getByRole("button", { name: n, exact: true })
    );
    await expect(month).toHaveAttribute("aria-pressed", "true");
    await expect(week).toHaveAttribute("aria-pressed", "false");
    await expect(year).toHaveAttribute("aria-pressed", "false");

    await week.click();
    await expect(week).toHaveAttribute("aria-pressed", "true");
    await expect(month).toHaveAttribute("aria-pressed", "false");
    await expect.poll(() => ranges).toContain("2026-11-09..2026-11-11");
    expect(ranges).toContain("2026-11-02..2026-11-04");
  });
});

// ---------------------------------------------------------------------------
// UAT gap 2: the "Where it went" legend must stay inside its card. All names
// and amounts below are synthetic.
// ---------------------------------------------------------------------------
const layoutCategories = ([
  ["Telecommunications", 12_345_678],
  ["Transportation", 9_876_543],
  ["Entertainment", 7_654_321],
  ["Bills & Utilities", 987_654],
  ["Health & Fitness", 456_789],
  ["Food & Drinks", 234_567],
  ["Shopping", 123_456],
] as [string, number][]).map(([name, total], i) => ({
  id: i + 1,
  name,
  color: ["#4f8", "#48f", "#f84", "#8f4", "#f48", "#84f", "#ff4"][i],
  icon: null,
  total,
  children: [],
}));

const layoutSummary = summaryFixture({ by_category: layoutCategories });

const layoutNetWorth = {
  total: 4_000_000,
  liquid_total: 4_000_000,
  investment_total: 0,
  liquid_accounts: [
    { id: 1, name: "Cash", type: "liquid", current_balance: 4_000_000, period_net: 0 },
  ],
  investment_groups: [],
  accounts_covered: 1,
  accounts_total: 1,
};

test.describe("Cashflow card legend layout", () => {
  // The legend sits beside the 88px donut once the card's content box fits the
  // donut, the 14px gap and the legend's 150px basis (252px), else it drops
  // below. Content widths measured: 1100 -> 281 (beside: three columns of
  // ~300px cards, the legend is far narrower than the old 180px basis), 420 ->
  // 179 and 320 -> 135 (stacked; 320 is below the 340px floor, where only the
  // narrowed page gutters keep amounts inside), 920 -> 451 and 1440 -> 380
  // (beside, the latter the max-width cap most desktops get).
  // Note (Holdings card): the lower row is now two cards, so the widths above
  // (measured with three columns) are larger; the layout assertions below are
  // width-independent and unchanged.
  const cases: [number, "stacked" | "side-by-side"][] = [
    [1100, "side-by-side"],
    [420, "side-by-side"], // the dock gives back the 66px rail, so the legend fits beside the ring (261115-s37)
    [320, "stacked"],
    [920, "side-by-side"],
    [1440, "side-by-side"],
  ];
  const top = [...layoutCategories].sort((a, b) => b.total - a.total);
  const names = [...top.slice(0, 5).map((c) => c.name), "Others"];
  const othersTotal = top.slice(5).reduce((sum, c) => sum + c.total, 0);
  const sum = top.reduce((t, c) => t + c.total, 0);

  for (const [width, layout] of cases) {
    test(`legend stays inside the card at ${width}px (${layout})`, async ({ page }) => {
      await mockSummary(page, layoutSummary);
      await page.route("**/api/net-worth**", (route) => route.fulfill({ json: layoutNetWorth }));
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/cashflow");
      const card = cashflowCard(page);
      const list = card.getByRole("list", { name: "Where it went" });
      await expect(list.getByText("12,345,678")).toBeVisible(); // pii-ok: mocked fixture
      const m = await card.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const left = r.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
        const right = r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
        const ul = el.querySelector('ul[aria-label="Where it went"]')!;
        const rows = Array.from(ul.children).map((li) => Array.from(li.querySelectorAll("span")));
        return {
          left,
          right,
          legendLeft: ul.getBoundingClientRect().left,
          rows: rows.map(([, name, amount, share]) => {
            // Lines the name occupies (distinct rect tops; an ellipsis adds a
            // rect on the same line). A mid-word split shows as 2+.
            const range = document.createRange();
            range.selectNodeContents(name);
            const lines = new Set(Array.from(range.getClientRects(), (q) => Math.round(q.top))).size;
            return {
              text: name.textContent,
              title: name.getAttribute("title"),
              lines,
              amount: amount.textContent,
              amountRight: amount.getBoundingClientRect().right,
              share: share.textContent,
              shareRight: share.getBoundingClientRect().right,
            };
          }),
        };
      });
      expect(m.rows).toHaveLength(6);
      const others = m.rows[5];
      expect(others.title).toBe("Others");
      expect(others.amount).toBe("358,023"); // pii-ok: mocked fixture, 234,567 + 123,456
      expect(others.share).toBe(`${Math.round((othersTotal / sum) * 100)}%`);
      for (const row of m.rows) {
        expect(row.amountRight).toBeLessThanOrEqual(m.right + 0.5);
        expect(row.shareRight).toBeLessThanOrEqual(m.right + 0.5);
        // Every name keeps its full text in the tooltip; single words never split.
        expect(row.text).toBe(row.title);
        if (!row.text?.includes(" ")) expect(row.lines, row.text ?? "").toBe(1);
      }
      expect(m.rows.map((row) => row.title)).toEqual(names);
      if (layout === "stacked") {
        expect(Math.abs(m.legendLeft - m.left)).toBeLessThanOrEqual(1);
      } else {
        expect(m.legendLeft - m.left).toBeGreaterThanOrEqual(88 + 14 - 1);
      }
    });
  }

  test("clicking a slice with subcategories drills in and Back returns", async ({ page }) => {
    await mockSummary(page);
    await page.goto("/cashflow");
    const card = cashflowCard(page);
    const list = card.getByRole("list", { name: "Where it went" });
    await expect(list.getByText("Food & Drinks", { exact: true })).toBeVisible();

    // A plain click can land in the donut hole: the centre of a ring slice's box is often empty.
    await card.locator(".recharts-pie-sector path").first().dispatchEvent("click");
    await expect(card.getByRole("button", { name: "‹ Back" })).toBeVisible();
    await expect(list.getByText("Groceries", { exact: true })).toBeVisible();
    await expect(list.getByText("Restaurants", { exact: true })).toBeVisible();
    await expect(list.getByText("Transport", { exact: true })).toHaveCount(0);

    await card.getByRole("button", { name: "‹ Back" }).click();
    await expect(list.getByText("Transport", { exact: true })).toBeVisible();
    await expect(list.getByText("Groceries", { exact: true })).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Phase 44 plan 03 — USD balances (DISP-01). Mocked, synthetic: ZZ44 names,
// round example rates and dates.
// ---------------------------------------------------------------------------
function netWorthFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    ...layoutNetWorth,
    accounts_total: 2,
    accounts_covered: 2,
    ...overrides,
  };
}

async function mockNetWorth(page: Page, body: unknown) {
  await page.route("**/api/net-worth", (route) => route.fulfill({ json: body }));
}

const usdWallet = {
  id: 2,
  name: "ZZ44 Wallet",
  type: "liquid",
  currency: "USD",
  native_balance: -12.34,
  current_balance: -200_525,
  fx_rate: 16250,
  fx_as_of: "2026-10-30",
  fx_stale: false,
  fx_note: null,
  period_net: 0,
};

test.describe("USD balances (Phase 44)", () => {
  // The Holdings card replaced the liquid-accounts list: Liquid is one click in,
  // and its IDR view shows each USD account's native balance as the subline.
  const openLiquid = async (page: Page) => {
    await page.goto("/cashflow");
    const card = page.getByRole("region", { name: "Holdings", exact: true });
    await card.getByRole("button", { name: /^Liquid/ }).click();
    return card;
  };

  test("USD balance shows the IDR value, native USD beneath and the rate", async ({ page }) => {
    await mockSummary(page);
    await mockNetWorth(
      page,
      netWorthFixture({
        liquid_accounts: [
          { id: 1, name: "ZZ44 Cash", type: "liquid", current_balance: 4_000_000, period_net: 0 },
          usdWallet,
        ],
      })
    );
    const card = await openLiquid(page);

    const wallet = card.getByText("ZZ44 Wallet", { exact: true }).locator("xpath=../..");
    await expect(wallet.getByText("-12.34 USD", { exact: true })).toBeVisible();
    await expect(wallet.getByText("-200,525", { exact: true })).toHaveAttribute(
      "title",
      "1 USD = 16,250 IDR · rate of 30 Oct 2026"
    );
    // A negative balance has no slice, so no share.
    await expect(wallet.getByText("—", { exact: true })).toBeVisible();

    const cash = card.getByText("ZZ44 Cash", { exact: true }).locator("xpath=../..");
    await expect(cash.getByText("4,000,000", { exact: true })).toBeVisible();
    await expect(cash.locator("[title]")).toHaveCount(1); // only the name's own tooltip
  });

  test("stale rate is a visible label", async ({ page }) => {
    await mockSummary(page);
    await mockNetWorth(
      page,
      netWorthFixture({
        liquid_accounts: [
          { ...usdWallet, fx_stale: true, fx_as_of: "2026-10-27", fx_note: "stale, rate of 2026-10-27" },
        ],
      })
    );
    const card = await openLiquid(page);
    await expect(card.getByText("stale, rate of 27 Oct 2026", { exact: true })).toBeVisible();
  });

  test("missing rate is never 0", async ({ page }) => {
    await mockSummary(page);
    await mockNetWorth(
      page,
      netWorthFixture({
        liquid_accounts: [{ ...usdWallet, current_balance: null, fx_rate: null, fx_as_of: null }],
      })
    );
    const card = await openLiquid(page);
    const wallet = card.getByText("ZZ44 Wallet", { exact: true }).locator("xpath=../..");
    await expect(wallet.getByText("-12.34 USD", { exact: true })).toBeVisible();
    await expect(wallet.getByText("—", { exact: true }).first()).toHaveAttribute(
      "title",
      "IDR value unavailable: no USD→IDR rate, so this account is left out of the total"
    );
    await expect(wallet.getByText("0", { exact: true })).toHaveCount(0);
  });

  test("unconverted notice sits above the cards and keeps the IDR totals", async ({ page }) => {
    await mockSummary(page, summaryFixture({ unconverted_count: 3, unconverted_usd: -12.34 }));
    await mockNetWorth(page, netWorthFixture());
    await page.goto("/cashflow");
    await expect(page.getByText("3 USD rows unconverted (-12.34 USD)", { exact: true })).toBeVisible();
    await expect(page.getByText("5,000,000", { exact: true })).toBeVisible();
    await expect(page.getByText("2,000,000", { exact: true })).toBeVisible();
    await expect(page.getByText("+3,000,000", { exact: true })).toBeVisible();
  });

  test("unconverted notice uses the singular for one row and is absent for zero or missing", async ({
    page,
  }) => {
    await mockSummary(page, summaryFixture({ unconverted_count: 1, unconverted_usd: -12.34 }));
    await mockNetWorth(page, netWorthFixture());
    await page.goto("/cashflow");
    await expect(page.getByText("1 USD row unconverted (-12.34 USD)", { exact: true })).toBeVisible();

    for (const body of [
      summaryFixture({ unconverted_count: 0, unconverted_usd: 0 }),
      summaryFixture(),
    ]) {
      await page.unroute("**/api/cashflow/summary**");
      await mockSummary(page, body);
      await page.reload();
      await expect(page.getByText("Net saved", { exact: true })).toBeVisible();
      await expect(page.getByText(/USD rows? unconverted/)).toHaveCount(0);
    }
  });

  test("net-worth notice shows the server strings and the excluded accounts", async ({ page }) => {
    await mockSummary(page);
    await mockNetWorth(
      page,
      netWorthFixture({
        notice: "1 account(s) left out of the total: no USD->IDR rate within 7 days",
        fx_note: "stale, rate of 2026-10-27",
        fx_excluded: [{ name: "ZZ44 Savings", native_balance: 1234.5, currency: "USD" }],
      })
    );
    await page.goto("/cashflow");
    await expect(
      page.getByText("1 account(s) left out of the total: no USD->IDR rate within 7 days", { exact: true })
    ).toBeVisible();
    await expect(page.getByText("stale, rate of 2026-10-27", { exact: true })).toBeVisible();
    await expect(page.getByText("ZZ44 Savings: 1,234.50 USD", { exact: true })).toBeVisible();
  });

  test("net-worth notice block is absent when there is nothing to say", async ({ page }) => {
    await mockSummary(page);
    await mockNetWorth(page, netWorthFixture({ notice: null, fx_note: null, fx_excluded: [] }));
    await page.goto("/cashflow");
    await expect(page.getByText("Net saved", { exact: true })).toBeVisible();
    await expect(page.getByText(/left out of the total|rate of/)).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// 261115-msv: phone width. Synthetic ZZ names and round example figures only.
// ---------------------------------------------------------------------------
test.describe("phone width, 375px (261115-msv)", () => {
  test.use({ viewport: { width: 375, height: 812 }, contextOptions: { reducedMotion: "reduce" } });

  test.beforeEach(async ({ page }) => {
    // Registered first, so it has the lowest priority: nothing reaches a live backend.
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { detail: "mocked" } }));
    await mockSummary(
      page,
      summaryFixture({
        totals: { income: 23_456_789, expense: 12_345_678, net: 11_111_111 }, // pii-ok synthetic
        unconverted_count: 2,
        unconverted_usd: 1234.56, // pii-ok synthetic
      })
    );
    await mockNetWorth(
      page,
      netWorthFixture({
        total: 1_234_567_890, // pii-ok synthetic
        liquid_total: 734_567_890, // pii-ok synthetic
        investment_total: 500_000_000, // pii-ok synthetic
        liquid_accounts: [
          {
            id: 1,
            name: "ZZ Bank",
            type: "liquid",
            currency: "IDR",
            fx_rate: 1,
            current_balance: 734_567_890, // pii-ok synthetic
            period_net: 0,
          },
        ],
        investment_groups: [
          {
            platform_id: 7,
            platform_name: "ZZ Broker",
            kind: "broker",
            subtotal: 500_000_000, // pii-ok synthetic
            holdings: [{ asset_type: "idx_stock", current_value: 500_000_000 }], // pii-ok synthetic
          },
        ],
      })
    );
    await page.goto("/cashflow");
    await expect(page.getByRole("region", { name: "Holdings", exact: true })).toBeVisible();
  });

  test("F1: cards are at least 236px wide, the Period pills sit inside the Cashflow card, the USD note is at most 2 lines", async ({
    page,
  }) => {
    const card = cashflowCard(page);
    const cardBox = (await card.boundingBox())!;
    const holdingsBox = (await page.getByRole("region", { name: "Holdings", exact: true }).boundingBox())!;
    expect(cardBox.width).toBeGreaterThanOrEqual(236);
    expect(holdingsBox.width).toBeGreaterThanOrEqual(236);

    const pills = (await card.getByRole("group", { name: "Period" }).boundingBox())!;
    expect(pills.x + pills.width).toBeLessThanOrEqual(cardBox.x + cardBox.width);

    const lines = await page.getByText(/USD rows? unconverted/).evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return new Set(Array.from(range.getClientRects(), (q) => Math.round(q.top))).size;
    });
    expect(lines).toBeLessThanOrEqual(2);
  });

  test("F2: every figure stays on one line inside its card", async ({ page }) => {
    const figs = await page.evaluate(() =>
      Array.from(document.querySelectorAll("main .roll")).map((roll) => {
        const tops = new Set(
          Array.from(roll.querySelectorAll(".roll-digit, .roll-char"), (d) => Math.round(d.getBoundingClientRect().top))
        );
        const card = roll.closest(".card-tight")!;
        const r = card.getBoundingClientRect();
        const cs = getComputedStyle(card);
        const right = r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
        return { lines: tops.size, over: roll.getBoundingClientRect().right - right };
      })
    );
    expect(figs.length).toBeGreaterThanOrEqual(5); // hero, Income, Expenses, Net saved, Holdings centre
    for (const f of figs) {
      expect(f.lines).toBe(1);
      expect(f.over).toBeLessThanOrEqual(0.5);
    }
  });

  test("F4: the Holdings card ends at its last row; amount and share share a line", async ({ page }) => {
    const card = page.getByRole("region", { name: "Holdings", exact: true });
    const cardBox = (await card.boundingBox())!;
    const lastBox = (await card.getByRole("button", { name: /^Investment/ }).boundingBox())!;
    const gap = cardBox.y + cardBox.height - (lastBox.y + lastBox.height);
    expect(gap).toBeGreaterThanOrEqual(0);
    expect(gap).toBeLessThanOrEqual(24);

    for (const name of [/^Liquid/, /^Investment/]) {
      const row = card.getByRole("button", { name });
      const b = (await row.locator("b").boundingBox())!;
      const em = (await row.locator("em").boundingBox())!;
      expect(Math.abs(b.y + b.height / 2 - (em.y + em.height / 2))).toBeLessThanOrEqual(2);
    }
  });
});
