import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 18 Plan 01 — Balance adjustment entry point (ACCT-02).
//
// Route-mocked per cashflow-crud.spec.ts convention: intercept GET
// /api/cashflow/summary so the "Cash" account row carries a known
// current_balance, then mock POST /api/accounts/{id}/adjust-balance for the
// success + 422 cases. No shared fixture file — self-contained per-file
// mocking is the established convention (no fixtures directory exists).
// ---------------------------------------------------------------------------

function summaryFixture() {
  return {
    totals: { income: 5_000_000, expense: 2_000_000, net: 3_000_000 },
    by_category: [],
    accounts: [
      { id: 1, name: "Cash", current_balance: 1_000_000, period_net: 0 },
    ],
    trend: [],
  };
}

async function mockDashboard(page: Page, onSummaryFetch?: () => void) {
  await page.route("**/api/cashflow/summary**", async (route) => {
    onSummaryFetch?.();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summaryFixture()),
    });
  });
  await page.route("**/api/transactions?limit=10", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
}

test.describe("balance adjustment (ACCT-02)", () => {
  test("submitting a target balance POSTs {target_balance} and refetches the summary", async ({
    page,
  }) => {
    let summaryFetchCount = 0;
    await mockDashboard(page, () => summaryFetchCount++);

    let postedBody: unknown = null;
    await page.route("**/api/accounts/*/adjust-balance", async (route) => {
      postedBody = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ transaction_id: 1, amount: "500000" }),
      });
    });

    await page.goto("/cashflow");
    await expect(page.getByText("Accounts", { exact: true }).first()).toBeVisible();

    const cashRow = page.locator("tr", { hasText: "Cash" });
    await expect.poll(() => summaryFetchCount).toBeGreaterThan(0);
    const summaryFetchCountAfterLoad = summaryFetchCount;

    await cashRow.getByText("Adjust balance", { exact: true }).click();
    await expect(page.getByText("Adjust balance — Cash")).toBeVisible();

    const modal = page.locator("form").filter({ hasText: "Save adjustment" });
    const targetInput = modal.locator("input[type='number']");

    // No change yet -> muted, disabled submit.
    await expect(
      page.getByText("No change — target equals current balance.")
    ).toBeVisible();
    await expect(modal.getByRole("button", { name: "Save adjustment" })).toBeDisabled();

    // Positive delta.
    await targetInput.fill("1500000");
    await expect(page.getByText("Adjustment: +Rp 500,000")).toBeVisible();

    // Negative delta (U+2212 minus, not hyphen).
    await targetInput.fill("800000");
    await expect(page.getByText("Adjustment: −Rp 200,000")).toBeVisible();

    // Back to a positive delta and submit.
    await targetInput.fill("1500000");
    await expect(page.getByText("Adjustment: +Rp 500,000")).toBeVisible();
    await modal.getByRole("button", { name: "Save adjustment" }).click();

    await expect.poll(() => postedBody).toEqual({ target_balance: 1500000 });
    await expect
      .poll(() => summaryFetchCount)
      .toBeGreaterThan(summaryFetchCountAfterLoad);
  });

  test("a 422 renders the standard error copy and keeps the modal open", async ({
    page,
  }) => {
    await mockDashboard(page);

    await page.route("**/api/accounts/*/adjust-balance", async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "some backend message" }),
      });
    });

    await page.goto("/cashflow");
    await expect(page.getByText("Accounts", { exact: true }).first()).toBeVisible();

    const cashRow = page.locator("tr", { hasText: "Cash" });
    await cashRow.getByText("Adjust balance", { exact: true }).click();
    await expect(page.getByText("Adjust balance — Cash")).toBeVisible();

    const modal = page.locator("form").filter({ hasText: "Save adjustment" });
    const targetInput = modal.locator("input[type='number']");
    await targetInput.fill("1500000");
    await modal.getByRole("button", { name: "Save adjustment" }).click();

    await expect(
      page.getByText(
        "Couldn't save adjustment: some backend message. Nothing was changed."
      )
    ).toBeVisible();
    // Modal stays open.
    await expect(page.getByText("Adjust balance — Cash")).toBeVisible();
  });
});
