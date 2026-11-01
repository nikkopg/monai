import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 18 Plan 02 — RED e2e spec for the "Deposit cash" liquid->investment
// transfer entry point (XFER-02, D-03/D-04/D-07).
//
// Route-mocked per platform-detail.spec.ts's mockPlatformDetail/
// mockPortfolioEvents convention — no live backend. Locks the 18-UI-SPEC.md
// copy + endpoint contract that 18-02 Task 2 (DepositCashModal.tsx +
// investments/[platformId]/page.tsx) must implement to turn these tests
// GREEN. RED now: the "Deposit cash" entry point does not exist yet.
// ---------------------------------------------------------------------------

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));

function platformDetailFixture() {
  return {
    platform_id: 1,
    platform_name: "Bibit",
    kind: "mutual fund app",
    subtotal: 6000000,
    holdings: [],
  };
}

function portfolioEventsFixture() {
  return [];
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

async function mockPortfolioEvents(page: Page) {
  await page.route("**/api/portfolio-events*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(portfolioEventsFixture()),
    });
  });
}

async function mockAccounts(page: Page, accounts: unknown[] = accountsFixture()) {
  await page.route("**/api/accounts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accounts),
    });
  });
}

const usdCashDetail = () => ({
  ...platformDetailFixture(),
  holdings: [
    {
      id: 9,
      ticker: "CASH",
      asset_type: "cash",
      currency: "USD",
      quantity: 100,
      avg_cost: 0,
      current_price: null,
      current_value: 1631000,
      unrealized_pnl: null,
      realized_pnl: 0,
    },
  ],
});

test.describe("Deposit across currencies (45-05, D-05 D-07 D-10)", () => {
  async function openDeposit(page: Page) {
    await mockPortfolioEvents(page);
    await page.route("**/api/platforms/*/detail", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(usdCashDetail()) });
    });
    await mockAccounts(page, [
      { id: 1, name: "ZZ45 Bank", type: "liquid", currency: "IDR" },
      { id: 2, name: "ZZ45 Wallet", type: "liquid", currency: "USD" },
    ]);
    await page.goto("/investments/1");
    await page.getByRole("button", { name: "Deposit cash", exact: true }).click();
    await expect(page.getByLabel("From account")).toBeVisible();
  }

  test("cross-currency deposit asks for the credited amount", async ({ page }) => {
    await openDeposit(page);
    const bodies: Record<string, unknown>[] = [];
    await page.route("**/api/transactions/investment-transfer", async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }) });
    });

    await page.getByLabel("From account").selectOption({ label: "ZZ45 Bank" });
    await expect(page.getByLabel("Currency", { exact: true })).toHaveText("IDR");
    await page.getByLabel("Amount", { exact: true }).fill("1631000");
    await page.getByLabel("Amount credited (USD)", { exact: true }).fill("100");
    await expect(page.getByLabel("Credited currency")).toHaveText("USD");
    // Neither amount is computed from the other.
    await expect(
      page.getByText("Moves Rp 1,631,000 from ZZ45 Bank, crediting 100.00 USD to Bibit.")
    ).toBeVisible();

    await page.getByRole("button", { name: "Deposit cash", exact: true }).last().click();
    await expect.poll(() => bodies.length).toBe(1);
    expect(bodies[0]).toMatchObject({
      from_account: "ZZ45 Bank",
      platform_id: 1,
      amount: 1631000,
      event_amount: 100,
      event_currency: "USD",
    });
    expect(bodies[0]).not.toHaveProperty("currency");
  });

  test("switching to a same-currency account hides the second row and drops it from the body", async ({ page }) => {
    await openDeposit(page);
    const bodies: Record<string, unknown>[] = [];
    await page.route("**/api/transactions/investment-transfer", async (route) => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }) });
    });

    await page.getByLabel("From account").selectOption({ label: "ZZ45 Bank" });
    await page.getByLabel("Amount credited (USD)", { exact: true }).fill("100");
    await page.getByLabel("From account").selectOption({ label: "ZZ45 Wallet" });
    // Back across: the second field starts empty again and Submit needs it.
    await page.getByLabel("From account").selectOption({ label: "ZZ45 Bank" });
    await expect(page.getByLabel("Amount credited (USD)", { exact: true })).toHaveValue("");
    await page.getByLabel("Amount", { exact: true }).fill("1631000");
    await expect(page.getByRole("button", { name: "Deposit cash", exact: true }).last()).toBeDisabled();
    await page.getByLabel("From account").selectOption({ label: "ZZ45 Wallet" });
    await expect(page.getByLabel("Currency", { exact: true })).toHaveText("USD");
    await expect(page.getByLabel(/Amount credited/)).toHaveCount(0);
    await page.getByLabel("Amount", { exact: true }).fill("12.5");
    await expect(page.getByText("Moves 12.50 USD from ZZ45 Wallet into Bibit.")).toBeVisible();

    await page.getByRole("button", { name: "Deposit cash", exact: true }).last().click();
    await expect.poll(() => bodies.length).toBe(1);
    expect(bodies[0]).toMatchObject({ from_account: "ZZ45 Wallet", amount: 12.5 });
    expect(bodies[0]).not.toHaveProperty("event_amount");
    expect(bodies[0]).not.toHaveProperty("event_currency");
    expect(bodies[0]).not.toHaveProperty("currency");
  });

  test("422 is shown verbatim", async ({ page }) => {
    await openDeposit(page);
    await page.route("**/api/transactions/investment-transfer", async (route) => {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "event currency USD does not match holding currency IDR (one currency per position)" }) });
    });
    await page.getByLabel("From account").selectOption({ label: "ZZ45 Bank" });
    await page.getByLabel("Amount", { exact: true }).fill("1631000");
    await page.getByLabel("Amount credited (USD)", { exact: true }).fill("100");
    await page.getByRole("button", { name: "Deposit cash", exact: true }).last().click();
    await expect(
      page.getByText("Couldn't deposit cash: event currency USD does not match holding currency IDR (one currency per position). Nothing was changed.")
    ).toBeVisible();
  });
});

test.describe("Deposit cash (XFER-02)", () => {
  test("submits a liquid-only transfer and refetches platform detail on success", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await mockAccounts(page);

    let detailFetchCount = 0;
    await page.route("**/api/platforms/*/detail", async (route) => {
      detailFetchCount++;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(platformDetailFixture()),
      });
    });

    let capturedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions/investment-transfer", async (route) => {
      capturedBody = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }),
      });
    });

    await page.goto("/investments/1");
    await expect(page.getByRole("heading", { name: "Bibit" })).toBeVisible();

    await page.getByRole("button", { name: "Deposit cash", exact: true }).click();

    const fromAccountSelect = page.getByLabel("From account");
    await expect(fromAccountSelect).toBeVisible();
    expect(await fromAccountSelect.evaluate((el) => el.tagName)).toBe("SELECT");
    await expect(fromAccountSelect.locator("option")).toHaveText(["BCA", "Cash Wallet"]);

    await fromAccountSelect.selectOption({ label: "BCA" });
    await page.getByLabel("Amount").fill("500000");

    await expect(
      page.getByText("Moves Rp 500,000 from BCA into Bibit.")
    ).toBeVisible();

    const detailFetchBefore = detailFetchCount;
    await page.getByRole("button", { name: "Deposit cash", exact: true }).last().click();

    await expect
      .poll(() => capturedBody !== null)
      .toBeTruthy();
    expect(capturedBody).toMatchObject({
      from_account: "BCA",
      platform_id: 1,
      amount: 500000,
    });
    // 45-05 D-10: the account decides the currency; nothing is sent or picked.
    expect(capturedBody).not.toHaveProperty("currency");
    await expect(page.locator("#deposit-cash-currency")).toHaveCount(0);

    await expect
      .poll(() => detailFetchCount)
      .toBeGreaterThan(detailFetchBefore);
  });

  test("shows the standard error copy and keeps the modal open on 422", async ({ page }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await mockAccounts(page);

    await page.route("**/api/transactions/investment-transfer", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "some backend message" }),
      });
    });

    await page.goto("/investments/1");
    await page.getByRole("button", { name: "Deposit cash", exact: true }).click();

    await page.getByLabel("From account").selectOption({ label: "BCA" });
    await page.getByLabel("Amount").fill("500000");
    await page.getByRole("button", { name: "Deposit cash", exact: true }).last().click();

    await expect(
      page.getByText("Couldn't deposit cash: some backend message. Nothing was changed.")
    ).toBeVisible();
    await expect(page.getByLabel("From account")).toBeVisible();
  });

  test("shows the empty-state copy and disables submit with zero liquid accounts", async ({
    page,
  }) => {
    await mockPlatformDetail(page);
    await mockPortfolioEvents(page);
    await mockAccounts(page, [
      { id: 3, name: "Bibit", type: "investment", currency: "IDR" },
    ]);

    await page.goto("/investments/1");
    await page.getByRole("button", { name: "Deposit cash", exact: true }).click();

    await expect(
      page.getByText(
        "No liquid accounts yet — add one in Cashflow before depositing cash."
      )
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Deposit cash", exact: true }).last()
    ).toBeDisabled();
  });
});
