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

async function mockSummary(page: Page, body: unknown = summaryFixture()) {
  const requestedPeriods: string[] = [];
  await page.route("**/api/cashflow/summary**", async (route) => {
    const url = new URL(route.request().url());
    const period = url.searchParams.get("period") || "";
    requestedPeriods.push(period);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
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

// ---------------------------------------------------------------------------
// UAT gap 2: the Spending by category legend must stay inside its card. All
// names and amounts below are synthetic.
// ---------------------------------------------------------------------------
const layoutCategories = [
  ["Telecommunications", 12_345_678],
  ["Transportation", 9_876_543],
  ["Entertainment", 7_654_321],
  ["Bills & Utilities", 987_654],
  ["Health & Fitness", 456_789],
  ["Food & Drinks", 234_567],
  ["Shopping", 123_456],
].map(([name, total], i) => ({
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

test.describe("Spending by category card layout", () => {
  // 1100: two-column grid, narrow card -> legend stacked below the donut.
  // 420: single column, narrow card -> stacked. 920: single column, wide
  // card (mid-band, clear of the ~1035px grid breakpoint) -> legend beside
  // the 150px donut (150 + 22 gap = 172). 1440: max-width cap, the layout
  // most desktops get -> side-by-side with a ~209px legend. 320: below the
  // 340px floor, where only the narrowed page gutters keep amounts inside.
  const cases: [number, "stacked" | "side-by-side"][] = [
    [1100, "stacked"],
    [420, "stacked"],
    [320, "stacked"],
    [920, "side-by-side"],
    [1440, "side-by-side"],
  ];
  for (const [width, layout] of cases) {
    test(`legend amounts stay inside the card at ${width}px (${layout})`, async ({ page }) => {
      await mockSummary(page, layoutSummary);
      await page.route("**/api/net-worth**", (route) => route.fulfill({ json: layoutNetWorth }));
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/cashflow");
      const card = page.getByText("Spending by category", { exact: true }).locator("xpath=..");
      await expect(card.getByText("12,345,678")).toBeVisible(); // pii-ok: mocked fixture
      const m = await card.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const left = r.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
        const right = r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
        const amounts = Array.from(el.querySelectorAll("span")).filter((s) => /\d/.test(s.textContent ?? ""));
        const names = Array.from(el.querySelectorAll("span[title]"));
        return {
          left,
          right,
          count: amounts.length,
          amountRights: amounts.map((s) => s.getBoundingClientRect().right),
          legendLeft: amounts[0]?.parentElement?.parentElement?.getBoundingClientRect().left ?? NaN,
          // Lines each name occupies (distinct rect tops; an ellipsis adds a
          // rect on the same line). A mid-word split shows as 2+.
          names: names.map((s) => {
            const range = document.createRange();
            range.selectNodeContents(s);
            const lines = new Set(Array.from(range.getClientRects(), (q) => Math.round(q.top))).size;
            return { text: s.textContent, title: s.getAttribute("title"), lines };
          }),
        };
      });
      expect(m.count).toBe(layoutCategories.length);
      for (const right of m.amountRights) expect(right).toBeLessThanOrEqual(m.right + 0.5);
      // Every name keeps its full text in the tooltip; single words never split.
      expect(m.names.map((n) => n.title)).toEqual(layoutCategories.map((c) => c.name));
      for (const n of m.names) {
        expect(n.text).toBe(n.title);
        if (!n.text?.includes(" ")) expect(n.lines, n.text ?? "").toBe(1);
      }
      if (layout === "stacked") {
        expect(Math.abs(m.legendLeft - m.left)).toBeLessThanOrEqual(1);
      } else {
        expect(m.legendLeft - m.left).toBeGreaterThanOrEqual(171);
      }
    });
  }
});
