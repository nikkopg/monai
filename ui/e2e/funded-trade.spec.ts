import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 18 Plan 03 — RED e2e spec for funded buy/sell (XFER-03, D-05/D-06/D-07).
//
// Route-mocked per platform-detail.spec.ts
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

function platformDetailFixture(holdings: unknown[] = []) {
  return {
    platform_id: 5,
    platform_name: "Bibit",
    kind: "mutual fund app",
    subtotal: 6000000,
    holdings,
  };
}

// A held position in a given currency (ZZ45 = synthetic).
const heldFixture = (ticker: string, currency: string) => ({
  id: 7,
  ticker,
  currency,
  asset_type: "stock",
  quantity: 3,
  avg_cost: 10,
  current_price: null,
  current_value: null,
  unrealized_pnl: null,
  realized_pnl: 0,
});

function platformsFixture() {
  return [{ id: 5, name: "Bibit", kind: "mutual fund app" }];
}

function accountsFixture() {
  return [
    { id: 1, name: "BCA", type: "liquid", currency: "IDR" },
    { id: 2, name: "Cash Wallet", type: "liquid", currency: "IDR" },
    { id: 3, name: "Bibit", type: "investment", currency: "IDR" },
    { id: 4, name: "ZZ45 Wallet", type: "liquid", currency: "USD" },
  ];
}

async function mockPlatformDetail(page: Page, holdings: unknown[] = []) {
  await page.route("**/api/platforms/*/detail", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(platformDetailFixture(holdings)),
    });
  });
}

async function mockPlatformsList(page: Page, list: unknown[] = platformsFixture()) {
  await page.route("**/api/platforms", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(list),
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

// GET (Buy & Sell tab load) returns an empty event list; POST (the
// dividend-only /api/portfolio-events submit) is captured via `onPost`.
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
  return page.locator('label:text-is("Investment liquid account") + select');
}
function cashAmountInput(page: Page, ccy = "IDR") {
  return page.getByLabel(`Cash amount (${ccy})`, { exact: true });
}
function eventTypeSelect(page: Page) {
  return page.locator('label:text-is("Event type") + select');
}
function quantityInput(page: Page) {
  return page.locator('label:text-is("Quantity") + input');
}
function priceInput(page: Page, ccy = "IDR") {
  return page.getByLabel(`Price per unit (${ccy})`, { exact: true });
}

// Lock the timezone so the CR-02 date regression is deterministic regardless
// of the runner machine's TZ (WIB / UTC+7 is where the day-early bug bites).
test.use({ timezoneId: "Asia/Jakarta" });

test.describe("funded buy/sell (XFER-03)", () => {
  test("Test A: funded Buy routes to /api/portfolio-events/funded-buy with the full funded body", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    const posted: Record<string, unknown>[] = [];
    await mockFundedBuy(page, (body) => posted.push(body));

    // CR-02 regression: freeze the clock at 02:00 Asia/Jakarta. Pre-fix, the
    // submit did new Date("...T02:00").toISOString().slice(0,10) which shifts
    // to the PREVIOUS UTC day (2026-08-16); the fix slices the local value so
    // date must be exactly 2026-08-17.
    await page.clock.install({ time: new Date("2026-08-17T02:00:00+07:00") });

    await openFundedModal(page);

    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");

    await expect(page.getByText("Debits BCA Rp 60,000, +2 ETH")).toBeVisible();

    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();

    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({
      source_account_name: "BCA",
      platform_id: 5,
      ticker: "ETH",
      quantity: 2,
      price: 30000,
      cash_amount: 60000,
      // fields CR-02 / WR-10 depend on — previously unasserted, which is why
      // the day-early date shipped green:
      date: "2026-08-17",
      // 45-05: an IDR account and a new position; the cash currency is derived
      // by the backend, the event currency comes from the select's default.
      event_currency: "IDR",
      asset_type: "crypto",
    });
    expect(posted[0]).not.toHaveProperty("cash_currency");
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

  test("Test D: Buy and Sell cannot be submitted without an Investment liquid account", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);

    let portfolioEventsPosted = false;
    await mockPortfolioEvents(page, () => (portfolioEventsPosted = true));
    let fundedCaptured: Record<string, unknown> | null = null;
    await mockFundedBuy(page, (body) => (fundedCaptured = body));
    let fundedSellCalled = false;
    await mockFundedSell(page, () => (fundedSellCalled = true));

    await openFundedModal(page);

    await expect(fundingSelect(page)).toHaveValue("");
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    // No account yet, so the price names no currency (it used to claim IDR).
    await expect(priceInput(page)).toHaveCount(0);
    await page.getByLabel("Price per unit", { exact: true }).fill("30000");

    // No account chosen: the submit button is disabled for Buy and for Sell.
    const submit = page.locator('form button[type="submit"]');
    await expect(submit).toBeDisabled();
    await eventTypeSelect(page).selectOption({ label: "Sell" });
    await expect(submit).toBeDisabled();
    await eventTypeSelect(page).selectOption({ label: "Buy" });
    expect(portfolioEventsPosted).toBe(false);
    expect(fundedCaptured).toBeNull();
    expect(fundedSellCalled).toBe(false);

    // Choosing an account enables it and posts to the funded route only.
    await fundingSelect(page).selectOption({ label: "BCA" });
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect.poll(() => fundedCaptured !== null).toBeTruthy();
    expect(fundedCaptured).toMatchObject({ source_account_name: "BCA", ticker: "ETH" });
    expect(portfolioEventsPosted).toBe(false);
  });

  test("Sell on a held ticker shows the exact quantity held", async ({ page }) => {
    await mockPlatformDetail(page, [heldFixture("ZZ45X", "IDR")]);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    await openFundedModal(page);

    await eventTypeSelect(page).selectOption({ label: "Sell" });
    await page.getByPlaceholder("BBCA").fill("ZZ45X");
    await expect(page.getByText("Held: 3", { exact: true })).toBeVisible();
    // A buy, or a ticker that is not held, shows no hint.
    await eventTypeSelect(page).selectOption({ label: "Buy" });
    await expect(page.getByText(/^Held:/)).toHaveCount(0);
  });

  test("with no liquid accounts the form points to Settings or Add holding", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await page.route("**/api/accounts", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ id: 3, name: "Bibit", type: "investment", currency: "IDR" }]),
      });
    });
    await mockPortfolioEvents(page);

    await openFundedModal(page);

    await expect(
      page.getByText(/add a liquid account in Settings, or use Add holding directly/i)
    ).toBeVisible();
    await eventTypeSelect(page).selectOption({ label: "Dividend" });
    await expect(page.getByText(/add a liquid account in Settings/i)).toHaveCount(0);
  });

  test("Test E: keeps the modal open and shows the standard error copy on a funded-buy 422", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    await page.route("**/api/portfolio-events/funded-buy", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "some backend message" }),
      });
    });

    await openFundedModal(page);

    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ETH");
    await quantityInput(page).fill("2");
    await priceInput(page).fill("30000");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();

    await expect(
      page.getByText(
        "Couldn't log funded buy: some backend message. Nothing was changed."
      )
    ).toBeVisible();
    // modal stays mounted (funding select still visible)
    await expect(fundingSelect(page)).toBeVisible();
  });

  test("Test F: selecting Dividend drops a chosen funding account and posts the unfunded path (WR-01)", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);

    let unfundedCaptured: Record<string, unknown> | null = null;
    await mockPortfolioEvents(page, (body) => (unfundedCaptured = body));

    let fundedBuyCalled = false;
    await page.route("**/api/portfolio-events/funded-buy", async (route) => {
      fundedBuyCalled = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });

    await openFundedModal(page);

    // Pick a funding account first, THEN switch to Dividend — the selection
    // must be dropped (not silently ignored into an unfunded write).
    await fundingSelect(page).selectOption({ label: "BCA" });
    await eventTypeSelect(page).selectOption({ label: "Dividend" });
    await expect(fundingSelect(page)).toHaveValue("");
    await expect(fundingSelect(page)).toBeDisabled();

    await page.getByPlaceholder("BBCA").fill("ETH");
    // The dividend path keeps its own "(IDR)" label.
    await page.getByLabel("Dividend amount (IDR)", { exact: true }).fill("500");

    await page.getByRole("button", { name: "Log event", exact: true }).click();

    await expect.poll(() => unfundedCaptured !== null).toBeTruthy();
    expect(unfundedCaptured).toMatchObject({
      ticker: "ETH",
      event_type: "dividend",
      platform_id: 5,
    });
    expect(fundedBuyCalled).toBe(false);
  });

  test("funded buy from a USD account", async ({ page }) => {
    await mockPlatformDetail(page, [heldFixture("ZZ45X", "USD")]);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);
    const posted: Record<string, unknown>[] = [];
    await mockFundedBuy(page, (body) => posted.push(body));

    await openFundedModal(page);
    await fundingSelect(page).selectOption({ label: "ZZ45 Wallet" });
    await page.getByPlaceholder("BBCA").fill("ZZ45X");

    await expect(cashAmountInput(page, "USD")).toBeVisible();
    await expect(page.getByLabel("Cash currency")).toHaveText("USD");
    await expect(priceInput(page, "USD")).toBeVisible();
    await expect(page.getByLabel("Position currency")).toHaveText("USD");
    expect(await page.getByLabel("Position currency").evaluate((el) => el.tagName)).toBe("SPAN");

    await quantityInput(page).fill("1");
    await priceInput(page, "USD").fill("12.5");
    await expect(cashAmountInput(page, "USD")).toHaveValue("12.5");
    await expect(page.getByText("Debits ZZ45 Wallet 12.50 USD, +1 ZZ45X")).toBeVisible();

    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ source_account_name: "ZZ45 Wallet", ticker: "ZZ45X", cash_amount: 12.5 });
    expect(posted[0]).not.toHaveProperty("cash_currency");
    expect(posted[0]).not.toHaveProperty("event_currency");
  });

  test("funded sell into a USD account credits dollars", async ({ page }) => {
    await mockPlatformDetail(page, [heldFixture("ZZ45X", "USD")]);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    await openFundedModal(page);
    await eventTypeSelect(page).selectOption({ label: "Sell" });
    await fundingSelect(page).selectOption({ label: "ZZ45 Wallet" });
    await page.getByPlaceholder("BBCA").fill("ZZ45X");
    await quantityInput(page).fill("2");
    await priceInput(page, "USD").fill("5");
    await expect(page.getByText("Credits ZZ45 Wallet 10.00 USD, −2 ZZ45X")).toBeVisible();
  });

  test("new position offers a position currency", async ({ page }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);
    const posted: Record<string, unknown>[] = [];
    await mockFundedBuy(page, (body) => posted.push(body));

    await openFundedModal(page);
    await fundingSelect(page).selectOption({ label: "ZZ45 Wallet" });
    await page.getByPlaceholder("BBCA").fill("ZZ45N");

    const pos = page.getByLabel("Position currency");
    expect(await pos.evaluate((el) => el.tagName)).toBe("SELECT");
    await expect(pos.locator("option")).toHaveText(["IDR", "USD"]);
    await expect(pos).toHaveValue("USD"); // defaults to the funding account's currency

    await pos.selectOption("IDR");
    await expect(priceInput(page, "IDR")).toBeVisible();
    await pos.selectOption("USD");
    await quantityInput(page).fill("1");
    await priceInput(page, "USD").fill("4");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ ticker: "ZZ45N", event_currency: "USD" });
    expect(posted[0]).not.toHaveProperty("cash_currency");
  });

  test("a new ticker on a USD platform starts in USD; a held IDR ticker keeps its chip", async ({ page }) => {
    await mockPlatformDetail(page, [heldFixture("ZZ45I", "IDR")]);
    await mockPlatformsList(page, [{ id: 5, name: "Bibit", kind: "mutual fund app", currency: "USD" }]);
    await mockAccounts(page);
    await mockPortfolioEvents(page);
    const posted: Record<string, unknown>[] = [];
    await mockFundedBuy(page, (body) => posted.push(body));

    await openFundedModal(page);
    await fundingSelect(page).selectOption({ label: "BCA" }); // an IDR account
    await page.getByPlaceholder("BBCA").fill("ZZ45N");
    const pos = page.getByLabel("Position currency");
    expect(await pos.evaluate((el) => el.tagName)).toBe("SELECT");
    await expect(pos).toHaveValue("USD"); // the platform's, not the account's
    await expect(priceInput(page, "USD")).toBeVisible();

    await pos.selectOption("IDR");
    await quantityInput(page).fill("1");
    await priceInput(page, "IDR").fill("100");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ ticker: "ZZ45N", event_currency: "IDR" });

    // A ticker already held on the platform keeps its own currency.
    await page.getByPlaceholder("BBCA").fill("ZZ45I");
    expect(await page.getByLabel("Position currency").evaluate((el) => el.tagName)).toBe("SPAN");
    await expect(page.getByLabel("Position currency")).toHaveText("IDR");
  });

  test("no auto-fill across currencies", async ({ page }) => {
    await mockPlatformDetail(page, [heldFixture("ZZ45X", "USD"), heldFixture("ZZ45I", "IDR")]);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);

    await openFundedModal(page);
    await fundingSelect(page).selectOption({ label: "BCA" });
    await page.getByPlaceholder("BBCA").fill("ZZ45X");
    await quantityInput(page).fill("2");
    await priceInput(page, "USD").fill("12.5");
    // IDR account, USD position: a USD price is never copied into the IDR cash field.
    await expect(cashAmountInput(page, "IDR")).toHaveValue("");

    // IDR position: still fills quantity x price while untouched.
    await page.getByPlaceholder("BBCA").fill("ZZ45I");
    await priceInput(page, "IDR").fill("100");
    await expect(cashAmountInput(page, "IDR")).toHaveValue("200");

    // Switching to a USD position clears the value the modal filled itself.
    await page.getByPlaceholder("BBCA").fill("ZZ45X");
    await expect(cashAmountInput(page, "IDR")).toHaveValue("");
  });

  test("422 one-currency-per-position refusal is shown verbatim", async ({ page }) => {
    await mockPlatformDetail(page);
    await mockPlatformsList(page);
    await mockAccounts(page);
    await mockPortfolioEvents(page);
    await page.route("**/api/portfolio-events/funded-buy", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "event currency USD does not match holding currency IDR (one currency per position)" }),
      });
    });

    await openFundedModal(page);
    await fundingSelect(page).selectOption({ label: "ZZ45 Wallet" });
    await page.getByPlaceholder("BBCA").fill("ZZ45N");
    await quantityInput(page).fill("1");
    await priceInput(page, "USD").fill("4");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect(
      page.getByText("Couldn't log funded buy: event currency USD does not match holding currency IDR (one currency per position). Nothing was changed.")
    ).toBeVisible();
  });
});
