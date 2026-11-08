import { test, expect, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";

test.beforeEach(async ({ page }) => {
  await watchCsp(page);
});
test.afterEach(async ({ page }) => {
  expect(await cspViolations(page)).toEqual([]);
});

// Quick 261108-d2c — USD positions show in USD with the IDR figure underneath.
// Route-mocked, synthetic values only. The backend computes the usd_* fields;
// the UI only formats them.

const RATE_TITLE = "1 USD = 20,000 IDR · rate of 2 Jan 2026";

const usdHolding = {
  id: 11,
  ticker: "ZZUSD",
  currency: "USD",
  asset_type: "crypto",
  quantity: 15,
  avg_cost: 47000,
  current_price: 100000,
  current_value: 1500000,
  unrealized_pnl: 795000,
  realized_pnl: 215000,
  usd_avg_cost: 3,
  usd_current_price: 5,
  usd_current_value: 75,
  usd_unrealized_pnl: 30,
  usd_rate: 20000,
  usd_rate_date: "2026-01-02",
  platform_id: 1,
  coingecko_id: null,
  price_source: "manual",
  price_fetched_at: "2026-01-02T00:00:00Z",
  is_stale: false,
};

const idrHolding = {
  id: 12,
  ticker: "ZZIDR",
  currency: "IDR",
  asset_type: "stock",
  quantity: 10,
  avg_cost: 1000,
  current_price: 1200,
  current_value: 12000,
  unrealized_pnl: 2000,
  realized_pnl: 0,
  platform_id: 1,
  coingecko_id: null,
  price_source: "manual",
  price_fetched_at: "2026-01-02T00:00:00Z",
  is_stale: false,
};

async function mockPlatformPage(page: Page, holdings: unknown[]) {
  await page.route("**/api/platforms/*/detail", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        platform_id: 1,
        platform_name: "ZZ Exchange",
        kind: "crypto app",
        subtotal: 1512000,
        holdings,
      }),
    });
  });
  await page.route("**/api/portfolio-events*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

function valueCell(page: Page, ticker: string) {
  // Columns: Asset, Units, Avg cost, Price, Value, Realized, Unrealized.
  return page.locator("div", { hasText: ticker }).last().locator("> span").nth(4);
}

test.describe("USD positions on the platform page", () => {
  test("Value shows USD first with the IDR figure and the rate underneath", async ({ page }) => {
    await mockPlatformPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments/1");

    await expect(page.getByText("75.00 USD")).toBeVisible();
    const idr = page.getByText("1,500,000 IDR");
    await expect(idr).toBeVisible();
    await expect(idr).toHaveAttribute("title", RATE_TITLE);

    // The IDR holding reads as today: plain number, no IDR suffix.
    await expect(valueCell(page, "ZZIDR")).toHaveText("12,000");
  });
});
