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

const coinHolding = {
  ...usdHolding,
  id: 13,
  ticker: "ZZCOIN",
  quantity: 1000,
  avg_cost: 350,
  current_price: 481.49,
  current_value: 481490,
  unrealized_pnl: 131490,
  usd_avg_cost: 0.0175,
  usd_current_price: 0.024074643857,
  usd_current_value: 24.07,
  usd_unrealized_pnl: 6.57,
};

// A USD position with no rate: every usd_ value is null.
const noRateHolding = {
  ...usdHolding,
  id: 14,
  ticker: "ZZNORATE",
  usd_avg_cost: null,
  usd_current_price: null,
  usd_current_value: null,
  usd_unrealized_pnl: null,
  usd_rate: null,
  usd_rate_date: null,
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

async function mockInvestmentsPage(page: Page, holdings: unknown[]) {
  await page.route("**/api/investments/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        groups: [
          { platform_id: 1, platform_name: "ZZ Exchange", kind: "crypto app", subtotal: 1512000, holdings },
        ],
        asset_type_groups: [],
        total_value: 1512000,
        total_unrealized_pnl: 797000,
        total_realized_pnl: 215000,
        as_of: "2026-01-02",
      }),
    });
  });
  await page.route("**/api/investments/history**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ points: [] }) });
  });
  await page.route("**/api/platforms", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "ZZ Exchange", kind: "crypto app" }]),
    });
  });
  await page.route("**/api/closed-positions**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

// The row is the innermost div holding the exact ticker text.
function row(page: Page, ticker: string) {
  return page.locator("div").filter({ has: page.getByText(ticker, { exact: true }) }).last();
}

// A cell's two lines: the figure on top, the IDR text underneath.
function lines(page: Page, ticker: string, column: number) {
  const cell = row(page, ticker).locator("> span").nth(column);
  return { top: cell.locator("> span").nth(0), under: cell.locator("> span").nth(1), cell };
}

// Platform page columns: Asset, Units, Avg cost, Price, Value, Realized, Unrealized.
const P = { avg: 2, price: 3, value: 4, realized: 5, unrealized: 6 };
// Investments page columns: Asset, Units, Price, Value, Return.
const I = { price: 2, value: 3, ret: 4 };

test.describe("USD positions on the platform page", () => {
  test("a USD row reads in USD first with the IDR figure underneath", async ({ page }) => {
    await mockPlatformPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments/1");
    await expect(row(page, "ZZUSD")).toBeVisible();

    const avg = lines(page, "ZZUSD", P.avg);
    await expect(avg.top).toHaveText("3.00 USD");
    await expect(avg.under).toHaveText("47,000 IDR");
    await expect(avg.under).not.toHaveAttribute("title", /.+/);

    const price = lines(page, "ZZUSD", P.price);
    await expect(price.top).toHaveText("5.00 USD");
    await expect(price.under).toHaveText("100,000 IDR");
    await expect(price.under).toHaveAttribute("title", RATE_TITLE);

    const value = lines(page, "ZZUSD", P.value);
    await expect(value.top).toHaveText("75.00 USD");
    await expect(value.under).toHaveText("1,500,000 IDR");
    await expect(value.under).toHaveAttribute("title", RATE_TITLE);

    // Realized stays IDR only.
    await expect(row(page, "ZZUSD").locator("> span").nth(P.realized)).toHaveText("+215,000");

    const un = lines(page, "ZZUSD", P.unrealized);
    await expect(un.top).toHaveText("+30.00 USD");
    await expect(un.under).toHaveText("+795,000 IDR");
  });

  test("small USD prices keep their digits to 8 significant figures", async ({ page }) => {
    await mockPlatformPage(page, [coinHolding]);
    await page.goto("/investments/1");
    await expect(lines(page, "ZZCOIN", P.avg).top).toHaveText("0.0175 USD");
    await expect(lines(page, "ZZCOIN", P.price).top).toHaveText("0.024074644 USD");
  });

  test("a USD row with no rate shows IDR and a note; an IDR row is unchanged", async ({ page }) => {
    await mockPlatformPage(page, [noRateHolding, idrHolding]);
    await page.goto("/investments/1");

    const nr = row(page, "ZZNORATE");
    await expect(nr.getByText("No USD rate, shown in IDR")).toBeVisible();
    await expect(nr.locator("> span").nth(P.avg)).toHaveText("47,000");
    await expect(nr.locator("> span").nth(P.price)).toHaveText("100,000");
    await expect(nr.locator("> span").nth(P.value)).toHaveText("1,500,000");
    await expect(nr.locator("> span").nth(P.unrealized)).toHaveText("+795,000");

    const idr = row(page, "ZZIDR");
    await expect(idr.getByText("No USD rate")).toHaveCount(0);
    await expect(idr.locator("> span").nth(P.avg)).toHaveText("1,000");
    await expect(idr.locator("> span").nth(P.price)).toHaveText("1,200");
    await expect(idr.locator("> span").nth(P.value)).toHaveText("12,000");
    await expect(idr.locator("> span").nth(P.unrealized)).toHaveText("+2,000");
  });
});

test.describe("USD positions on the Investments page", () => {
  test("a USD row shows price, value and return in USD over IDR", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, noRateHolding, idrHolding]);
    await page.goto("/investments");
    await expect(row(page, "ZZUSD")).toBeVisible();

    const price = lines(page, "ZZUSD", I.price);
    await expect(price.top).toHaveText("5.00 USD");
    await expect(price.under).toHaveText("100,000 IDR");
    await expect(price.under).toHaveAttribute("title", RATE_TITLE);

    const value = lines(page, "ZZUSD", I.value);
    await expect(value.top).toHaveText("75.00 USD");
    await expect(value.under).toHaveText("1,500,000 IDR");
    await expect(value.under).toHaveAttribute("title", RATE_TITLE);

    const ret = lines(page, "ZZUSD", I.ret);
    await expect(ret.top).toHaveText("+66.7% USD");
    await expect(ret.under).toHaveText("+112.8% IDR");

    // No rate: IDR as today, plus the note.
    const nr = row(page, "ZZNORATE");
    await expect(nr.getByText("No USD rate, shown in IDR")).toBeVisible();
    await expect(nr.locator("> span").nth(I.price)).toHaveText("100,000");
    await expect(nr.locator("> span").nth(I.value)).toHaveText("1,500,000");
    await expect(nr.locator("> span").nth(I.ret)).toHaveText("+112.8%");

    // IDR row unchanged.
    const idr = row(page, "ZZIDR");
    await expect(idr.locator("> span").nth(I.price)).toHaveText("1,200");
    await expect(idr.locator("> span").nth(I.value)).toHaveText("12,000");
    await expect(idr.locator("> span").nth(I.ret)).toHaveText("+20.0%");
  });
});
