import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 18 Plan 03 — RED e2e spec for funded buy/sell (XFER-03, D-05/D-06/D-07).
//
// Route-mocked per platform-detail.spec.ts / investment-transfer.spec.ts
// convention — no live backend. Locks the 18-UI-SPEC.md Surface 3 copy +
// endpoint contract that 18-03 (HoldingModal.tsx funding selector + the
// platform-detail "+ Log event" trigger) must implement to turn these tests
// GREEN. RED now: the funding selector and the "+ Log event" trigger on the
// Buy & Sell tab do not exist yet.
//
// HoldingModal's Ticker/Asset type/Platform/Event type/Quantity/Price fields
// use unassociated <label> siblings (existing file convention, unchanged by
// this plan) — locate them via the `label:text-is(...) + input|select` CSS
// adjacent-sibling combinator rather than getByLabel.
// ---------------------------------------------------------------------------

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));

function platformDetailFixture() {
  return {
    platform_id: 5,
    platform_name: "Bibit",
    kind: "mutual fund app",
    subtotal: 6000000,
    holdings: [],
  };
}

function platformsFixture() {
  return [{ id: 5, name: "Bibit", kind: "mutual fund app" }];
}

function accountsFixture() {
  return [
    { id: 1, name: "BCA", type: "liquid", currency: "IDR" },
    { id: 2, name: "Cash Wallet", type: "liquid", currency: "IDR" },
    { id: 3, name: "Bibit", type: "investment", currency: "IDR" },
  ];
}

async function mockPlatformDetail(page: Page) {
  await page.route("**/api/platforms/*/detail", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(platformDetailFixture()),
    });
  });
}

async function mockPlatformsList(page: Page) {
  await page.route("**/api/platforms", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(platformsFixture()),
    });
  });
}

async function mockAccounts(page: Page) {
  await page.route("**/api/accounts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accountsFixture()),
    });
  });
}

// GET (Buy & Sell tab load) returns an empty event list; POST (the unfunded
// escape hatch submit) is captured via `onPost`.
async function mockPortfolioEvents(
  page: Page,
  onPost?: (body: Record<string, unknown>) => void
) {
  await page.route("**/api/portfolio-events*", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      onPost?.(req.postDataJSON());
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
}

async function mockFundedBuy(page: Page, onPost: (body: Record<string, unknown>) => void) {
  await page.route("**/api/portfolio-events/funded-buy", async (route) => {
    onPost(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }),
    });
  });
}

async function mockFundedSell(page: Page, onPost: (body: Record<string, unknown>) => void) {
  await page.route("**/api/portfolio-events/funded-sell", async (route) => {
    onPost(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }),
    });
  });
}

async function openFundedModal(page: Page) {
  await page.goto("/investments/5");
  await expect(page.getByRole("heading", { name: "Bibit" })).toBeVisible();
  await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();
  await page.getByRole("button", { name: "+ Log event", exact: true }).click();
}

function fundingSelect(page: Page) {
  return page.locator('label:text-is("Funding account") + select');
}
function cashAmountInput(page: Page) {
  return page.locator('label:text-is("Cash amount (IDR)") + input');
}
function eventTypeSelect(page: Page) {
  return page.locator('label:text-is("Event type") + select');
}
function quantityInput(page: Page) {
  return page.locator('label:text-is("Quantity") + input');
}
function priceInput(page: Page) {
  return page.locator('label:text-is("Price per unit (IDR)") + input');
}

test.describe("funded buy/sell (XFER-03)", () => {
  test("Test A: funded Buy routes to /api/portfolio-events/funded-buy with the full funded body", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    let captured: Record<string, unknown> | null = null;
    await mockFundedBuy(page, (body) => (captured = body));

    await openFundedModal(page);

    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");

    await expect(page.getByText("Debits BCA Rp 60,000, +2 ETH")).toBeVisible();

    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();

    await expect.poll(() => captured !== null).toBeTruthy();
    expect(captured).toMatchObject({
      source_account_name: "BCA",
      platform_id: 5,
      ticker: "ETH",
      quantity: 2,
      price: 30000,
      cash_amount: 60000,
    });
  });

  test("Test B: cash_amount defaults to quantity x price and an edited value is posted", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    let captured: Record<string, unknown> | null = null;
    await mockFundedBuy(page, (body) => (captured = body));

    await openFundedModal(page);

    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");

    await expect(cashAmountInput(page)).toHaveValue("60000");

    await cashAmountInput(page).fill("65000");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();

    await expect.poll(() => captured !== null).toBeTruthy();
    expect((captured as unknown as Record<string, unknown>).cash_amount).toBe(65000);
  });

  test("Test C: funded Sell routes to /api/portfolio-events/funded-sell", async ({ page }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    let captured: Record<string, unknown> | null = null;
    await mockFundedSell(page, (body) => (captured = body));

    await openFundedModal(page);

    await eventTypeSelect(page).selectOption({ label: "Sell" });
    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");

    await expect(page.getByText("Credits BCA Rp 60,000, −2 ETH")).toBeVisible();

    await page.getByRole("button", { name: "Log funded Sell", exact: true }).click();

    await expect.poll(() => captured !== null).toBeTruthy();
    expect(captured).toMatchObject({
      source_account_name: "BCA",
      platform_id: 5,
      ticker: "ETH",
      quantity: 2,
      price: 30000,
      cash_amount: 60000,
    });
  });

  test("Test D: leaving Funding account on none still POSTs the unfunded /api/portfolio-events path", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);

    let unfundedCaptured: Record<string, unknown> | null = null;
    await mockPortfolioEvents(page, (body) => (unfundedCaptured = body));

    let fundedBuyCalled = false;
    let fundedSellCalled = false;
    await page.route("**/api/portfolio-events/funded-buy", async (route) => {
      fundedBuyCalled = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });
    await page.route("**/api/portfolio-events/funded-sell", async (route) => {
      fundedSellCalled = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });

    await openFundedModal(page);

    await expect(fundingSelect(page)).toHaveValue("");
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");

    await page.getByRole("button", { name: "Log event", exact: true }).click();

    await expect.poll(() => unfundedCaptured !== null).toBeTruthy();
    expect(unfundedCaptured).toMatchObject({
      ticker: "ETH",
      quantity: 2,
      price: 30000,
      platform_id: 5,
    });
    expect(fundedBuyCalled).toBe(false);
    expect(fundedSellCalled).toBe(false);
  });
});
