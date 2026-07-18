import { test, expect, type Page } from "@playwright/test";

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

async function mockSummary(page: Page) {
  const requestedPeriods: string[] = [];
  await page.route("**/api/cashflow/summary**", async (route) => {
    const url = new URL(route.request().url());
    const period = url.searchParams.get("period") || "";
    requestedPeriods.push(period);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summaryFixture()),
    });
  });
  return requestedPeriods;
}

test.describe("/cashflow dashboard", () => {
  test("renders the page heading and the three summary figure captions", async ({
    page,
  }) => {
    await mockSummary(page);
    await page.goto("/cashflow");

    await expect(
      page.getByRole("heading", { name: "Cashflow" })
    ).toBeVisible();
    // Stat-card captions are <div>s; scope to div so the trend legend's
    // <span>Income/Expenses don't trip strict mode.
    await expect(
      page.locator("div").filter({ hasText: /^Income$/ })
    ).toBeVisible();
    await expect(
      page.locator("div").filter({ hasText: /^Expenses$/ })
    ).toBeVisible();
    await expect(
      page.locator("div").filter({ hasText: /^Net saved$/ })
    ).toBeVisible();
  });

  test("renders at least one chart svg", async ({ page }) => {
    await mockSummary(page);
    await page.goto("/cashflow");

    await expect(page.getByText("Spending by category")).toBeVisible();
    const chartsRow = page
      .getByText("Spending by category")
      .locator("xpath=ancestor::main");
    await expect(chartsRow.locator("svg").first()).toBeVisible();
  });

  test("clicking a different period pill issues a new summary request", async ({
    page,
  }) => {
    const requestedPeriods = await mockSummary(page);
    await page.goto("/cashflow");

    // Wait for the initial load (default period).
    await expect(
      page.locator("div").filter({ hasText: /^Income$/ })
    ).toBeVisible();
    expect(requestedPeriods).toContain("this_month");

    await page.getByRole("button", { name: "Year", exact: true }).click();

    await expect
      .poll(() => requestedPeriods.includes("this_year"))
      .toBe(true);
  });
});
