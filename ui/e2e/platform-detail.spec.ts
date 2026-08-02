import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 17 Plan 02 — RED e2e spec for Platform detail (PLAT-01).
//
// Route-mocked per platform-crud.spec.ts / cashflow-crud.spec.ts convention —
// no live backend. Locks the 17-UI-SPEC.md copy + endpoint contract that
// 17-05 (ui/app/investments/[platformId]/page.tsx) must implement to turn
// these tests GREEN. RED now: the dynamic route + page do not exist yet.
// ---------------------------------------------------------------------------

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(n));

function platformDetailFixture() {
  return {
    platform_id: 1,
    platform_name: "Binance",
    kind: "crypto app",
    subtotal: 6000000,
    holdings: [
      {
        id: 11,
        ticker: "BTC",
        asset_type: "crypto",
        quantity: 0.01,
        avg_cost: 500000000,
        current_price: 600000000,
        current_value: 6000000,
        unrealized_pnl: 1000000,
        realized_pnl: 200000,
        platform_id: 1,
        coingecko_id: null,
        price_source: "coingecko",
        price_fetched_at: "2026-08-01T00:00:00Z",
        is_stale: false,
      },
    ],
  };
}

function portfolioEventsFixture() {
  return [
    {
      id: 501,
      date: "2026-07-20T10:00:00Z",
      ticker: "BTC",
      event_type: "buy",
      quantity: 0.01,
      price: 600000000,
    },
    {
      id: 502,
      date: "2026-06-15T10:00:00Z",
      ticker: "BTC",
      event_type: "sell",
      quantity: 0.005,
      price: 610000000,
    },
  ];
}

async function mockPlatformDetail(
  page: Page,
  opts?: { status?: number; body?: unknown }
) {
  await page.route("**/api/platforms/*/detail", async (route) => {
    if (opts?.status && opts.status !== 200) {
      await route.fulfill({
        status: opts.status,
        contentType: "application/json",
        body: JSON.stringify(opts.body ?? { detail: "Platform not found" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts?.body ?? platformDetailFixture()),
    });
  });
}

async function mockPortfolioEvents(page: Page) {
  await page.route("**/api/portfolio-events*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(portfolioEventsFixture()),
    });
  });
}

test.describe("Platform detail shell (PLAT-01, D-08)", () => {
  test("shows the back-link, name/kind, and the 3 stat cards", async ({ page }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await page.goto("/investments/1");

    await expect(page.getByRole("link", { name: "← Investments" })).toBeVisible();
    await expect(page.getByText("Platform", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Binance" })).toBeVisible();
    await expect(page.getByText("crypto app", { exact: true })).toBeVisible();

    await expect(page.getByText("Subtotal", { exact: true })).toBeVisible();
    // "Realized"/"Unrealized" also label PnL-table columns (Component 11),
    // which render simultaneously below the stat cards (PnL is the default
    // tab) — scope to .first() to avoid a strict-mode multi-match.
    await expect(page.getByText("Realized", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Unrealized", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(fmtPlain(6000000))).toBeVisible();
  });
});

test.describe("PnL tab (D-05, Component 11)", () => {
  test("is active by default and its table shows the locked headers with realized/unrealized values", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await page.goto("/investments/1");

    for (const header of ["Ticker", "Qty", "Avg cost", "Price", "Value"]) {
      await expect(page.getByText(header, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Realized", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Unrealized", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("BTC", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(fmtSigned(200000))).toBeVisible();
    await expect(page.getByText(fmtSigned(1000000))).toBeVisible();
  });
});

test.describe("Buy & Sell tab (D-05, Component 12)", () => {
  test("clicking Buy & Sell switches to the event table with the locked headers and colored Title-cased Side", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await page.goto("/investments/1");

    await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();

    for (const header of ["Date", "Ticker", "Side", "Qty", "Price"]) {
      await expect(page.getByText(header, { exact: true })).toBeVisible();
    }
    // event_type Title-cased, not the raw lowercase enum value.
    await expect(page.getByText("Buy", { exact: true })).toBeVisible();
    await expect(page.getByText("Sell", { exact: true })).toBeVisible();
  });
});

test.describe("Platform detail states (Component 13)", () => {
  test("a 404 detail response shows 'Platform not found' with the back-link still present", async ({
    page,
  }) => {
    await mockPlatformDetail(page, {
      status: 404,
      body: { detail: "Platform 999 not found" },
    });
    await mockPortfolioEvents(page);
    await page.goto("/investments/999");

    await expect(page.getByText(/Platform not found/)).toBeVisible();
    await expect(page.getByRole("link", { name: "← Investments" })).toBeVisible();
  });
});
