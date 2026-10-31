import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 44 UAT — USD accounts in the UI, against mocked synthetic data (ZZ44).
// Covers the display half of the owner UAT: USD-first amounts with an "≈ IDR"
// line and rate hover, the IDR-only daily net, the loading state, 375px fit,
// and a long name beside the currency chip. Backend refusals and storage are
// covered by backend/tests/test_currency_enforcement.py.
// ---------------------------------------------------------------------------

const LONG_NAME = "ZZ44 Synthetic Dollar Savings Account 01"; // 40 chars, pii-ok synthetic

function isoAt(daysAgo: number): string {
  const d = new Date();
  d.setUTCHours(10, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString();
}

function summaryFixture() {
  return {
    totals: { income: 1_000_000, expense: 400_000, net: 600_000 },
    by_category: [],
    accounts: [
      { id: 1, name: "ZZ44 Cash", type: "liquid", currency: "IDR", current_balance: 2_500_000, period_net: 100_000 },
      {
        id: 2, name: LONG_NAME, type: "liquid", currency: "USD",
        native_balance: -1_234_567.89, current_balance: -20_123_456_789, // pii-ok synthetic
        fx_rate: 16_300, fx_as_of: "2026-10-30", fx_stale: false, period_net: 0,
      },
    ],
    trend: [],
  };
}

function accountsFixture() {
  return [
    { id: 1, name: "ZZ44 Cash", currency: "IDR" },
    { id: 2, name: LONG_NAME, currency: "USD" },
  ];
}

// One day with an IDR expense and a USD expense: the daily net must add only
// the IDR value of the USD row (-25,000 + -163,000 = -188,000).
function transactionsFixture() {
  return [
    {
      id: 4401, date: isoAt(0), amount: -25_000, currency: "IDR", category: "Food & Drinks",
      merchant: "ZZ44 Warung", account_id: 1, notes: null, is_transfer: false, transfer_pair_id: null,
    },
    {
      id: 4402, date: isoAt(0), amount: -10, currency: "USD", amount_idr: -163_000,
      fx_rate: 16_300, fx_rate_date: "2026-10-30", category: "Shopping",
      merchant: "ZZ44 Store", account_id: 2, notes: null, is_transfer: false, transfer_pair_id: null,
    },
    {
      id: 4403, date: isoAt(1), amount: -1_234_567.89, currency: "USD", amount_idr: -20_123_456_789, // pii-ok synthetic
      fx_rate: 16_300, fx_rate_date: "2026-10-29", category: "Shopping",
      merchant: "ZZ44 Big", account_id: 2, notes: null, is_transfer: false, transfer_pair_id: null,
    },
  ];
}

async function json(page: Page, glob: string, body: unknown, delayMs = 0) {
  await page.route(glob, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function mockAll(page: Page, delayMs = 0) {
  await json(page, "**/api/cashflow/summary**", summaryFixture(), delayMs);
  const liquid = summaryFixture().accounts;
  await json(page, "**/api/net-worth", {
    total: 0, liquid_total: 0, investment_total: 0, liquid_accounts: liquid,
    investment_groups: [], accounts_covered: liquid.length, accounts_total: liquid.length,
  }, delayMs);
  await json(page, "**/api/accounts", accountsFixture());
  await json(page, "**/api/categories", []);
  await json(page, "**/api/transactions*", transactionsFixture(), delayMs);
}

async function noHorizontalScroll(page: Page) {
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll).toBeLessThanOrEqual(client);
}

test.describe("Phase 44 — USD accounts", () => {
  test("Cashflow shows the USD balance first, ≈ IDR second, rate on hover", async ({ page }) => {
    await mockAll(page);
    await page.goto("/cashflow");
    const usd = page.getByText("-1,234,567.89 USD").first();
    await expect(usd).toBeVisible();
    const cell = usd.locator("..");
    await expect(cell).toContainText("≈ -20,123,456,789"); // pii-ok synthetic
    await expect(cell).toHaveAttribute("title", "1 USD = 16,300 IDR · rate of 30 Oct 2026");
    // IDR account unchanged: plain en-US, no code.
    await expect(page.getByText("2,500,000", { exact: true }).first()).toBeVisible();
  });

  test("Records shows USD rows natively and an IDR-only daily net", async ({ page }) => {
    await mockAll(page);
    await page.goto("/records");
    await expect(page.getByText("-10.00 USD")).toBeVisible();
    await expect(page.getByText("≈ -163,000")).toBeVisible();
    await expect(page.locator('[title="1 USD = 16,300 IDR · rate of 30 Oct 2026"]')).toBeVisible();
    await expect(page.getByText("-25,000", { exact: true })).toBeVisible();
    await expect(page.getByText("-188,000").first()).toBeVisible();
  });

  test("Settings shows the currency chip", async ({ page }) => {
    await mockAll(page);
    await page.goto("/settings");
    const row = page.locator("tr", { hasText: LONG_NAME });
    await expect(row.getByText("USD", { exact: true })).toBeVisible();
  });

  test("loading state renders no USD value or notice from stale state", async ({ page }) => {
    await mockAll(page, 2_000);
    await page.goto("/records");
    await expect(page.getByText("Loading your records…")).toBeVisible();
    await expect(page.getByText(/USD|≈/)).toHaveCount(0);

    await page.goto("/cashflow");
    await expect(page.getByRole("heading", { name: "Cashflow" })).toBeVisible();
    await expect(page.getByText(/ USD|≈|unconverted|stale/)).toHaveCount(0);
    await expect(page.getByText("-1,234,567.89 USD").first()).toBeVisible({ timeout: 10_000 });
  });

  test("375px: a large USD amount and its ≈ IDR line fit without horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await mockAll(page);
    await page.goto("/cashflow");
    await expect(page.getByText("-1,234,567.89 USD").first()).toBeVisible();
    await noHorizontalScroll(page);
    await page.goto("/records");
    await expect(page.getByText("-1,234,567.89 USD")).toBeVisible();
    await noHorizontalScroll(page);
  });

  test("a ~40-character name wraps; the currency chip stays visible and unshrunk", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await mockAll(page);
    await page.goto("/settings");
    const shortChip = page.locator("tr", { hasText: "ZZ44 Cash" }).getByText("IDR", { exact: true });
    const longChip = page.locator("tr", { hasText: LONG_NAME }).getByText("USD", { exact: true });
    await expect(longChip).toBeVisible();
    const chip = await longChip.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { scroll: el.scrollWidth, client: el.clientWidth, right: r.right, vw: window.innerWidth, h: r.height };
    });
    const ref = (await shortChip.boundingBox())!;
    expect(chip.scroll).toBeLessThanOrEqual(chip.client); // text not clipped
    expect(chip.right).toBeLessThanOrEqual(chip.vw); // on screen
    expect(chip.h).toBeLessThanOrEqual(ref.height + 1); // single line, same as a short-name chip
    await noHorizontalScroll(page);
  });
});
