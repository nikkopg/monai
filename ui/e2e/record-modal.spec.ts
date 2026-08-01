import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 16 Plan 01 (Wave 0) — record-modal.spec.ts (REC-04).
//
// Pins the Expense/Income/Transfer segmented-control contract for
// TransactionModal.tsx BEFORE it is built (Wave 1, Plan 02). Route-mocked,
// no live backend — mirrors cashflow-crud.spec.ts's fixture + route-mock
// idiom and modal-open navigation verbatim. Every scenario asserts a request
// BODY or endpoint, never just a UI toggle, so it is a real RED->GREEN
// signal for Wave 1.
//
// Expected to run RED against today's code (no segmented control, no
// currency field, no Transfer branch, no "Save & add another", no edit-leg
// lock yet) — that is the intended Wave 0 baseline (16-01-PLAN.md).
// ---------------------------------------------------------------------------

function summaryFixture() {
  return {
    totals: { income: 5_000_000, expense: 2_000_000, net: 3_000_000 },
    by_category: [
      ["Food & Drinks", 1_200_000],
      ["Transport", 500_000],
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
  };
}

function txFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return [
    {
      id: 101,
      date: "2026-07-01T10:00:00Z",
      amount: -25000,
      category: "Food & Drinks",
      merchant: "warung sate",
      account_id: 1,
      notes: null,
      is_transfer: false,
      ...overrides,
    },
  ];
}

async function mockDashboard(page: Page, txOverrides: Partial<Record<string, unknown>> = {}) {
  await page.route("**/api/cashflow/summary**", async (route) => {
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
      body: JSON.stringify(txFixture(txOverrides)),
    });
  });
  await page.route("**/api/categories", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ categories: ["Food & Drinks", "Transport"] }),
    });
  });
}

async function openCreateModal(page: Page) {
  await page.goto("/cashflow");
  await page.getByRole("button", { name: "+ Add transaction", exact: true }).click();
  await expect(page.getByText("Add transaction").first()).toBeVisible();
}

async function openEditModal(page: Page) {
  await page.goto("/cashflow");
  await page.getByText("Edit", { exact: true }).first().click();
  await expect(page.getByText("Edit transaction")).toBeVisible();
}

test.describe("record-modal — Expense/Income segment (REC-04)", () => {
  test("default segment is Expense, options render Expense/Income/Transfer in order", async ({
    page,
  }) => {
    await mockDashboard(page);
    await openCreateModal(page);

    const form = page.locator("form").filter({ hasText: "Add transaction" });
    const segmentButtons = form.getByRole("button", {
      name: /^(Expense|Income|Transfer)$/,
    });
    await expect(segmentButtons).toHaveCount(3);
    await expect(segmentButtons.nth(0)).toHaveText("Expense");
    await expect(segmentButtons.nth(1)).toHaveText("Income");
    await expect(segmentButtons.nth(2)).toHaveText("Transfer");
    // Active segment carries fontWeight 600 per UI-SPEC's active-segment style.
    await expect(segmentButtons.nth(0)).toHaveCSS("font-weight", "600");
  });

  test("Expense posts a negative signed amount and currency IDR", async ({ page }) => {
    await mockDashboard(page);
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Expense", exact: true }).click();
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form
      .getByRole("button", { name: "Add transaction", exact: true })
      .click();

    await expect.poll(() => postedBody?.amount).toBe(-25000);
    await expect.poll(() => postedBody?.currency).toBe("IDR");
  });

  test("Income posts a positive signed amount", async ({ page }) => {
    await mockDashboard(page);
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999, amount: 25000 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Income", exact: true }).click();
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form
      .getByRole("button", { name: "Add transaction", exact: true })
      .click();

    await expect.poll(() => postedBody?.amount).toBe(25000);
  });

  test("Save & add another keeps the modal open and resets amount/category/notes", async ({
    page,
  }) => {
    await mockDashboard(page);
    let postCount = 0;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postCount += 1;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form.getByPlaceholder("warung sate").fill("some notes");
    await form
      .getByRole("button", { name: "Save & add another", exact: true })
      .click();

    await expect.poll(() => postCount).toBe(1);
    // Modal heading still visible -> modal did not close.
    await expect(page.getByText("Add transaction").first()).toBeVisible();
    await expect(form.getByLabel("Amount", { exact: true })).toHaveValue("");
    await expect(form.getByPlaceholder("warung sate")).toHaveValue("");
  });

  test("editing a non-transfer negative-amount row reverse-maps to Expense + absolute magnitude, saves via PUT", async ({
    page,
  }) => {
    await mockDashboard(page, { amount: -25000, is_transfer: false });
    let putCalled = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], amount: -25000 }),
        });
        return;
      }
      await route.fallback();
    });

    await openEditModal(page);
    const form = page.locator("form").filter({ hasText: "Save changes" });
    await expect(form.getByRole("button", { name: "Expense", exact: true })).toHaveCSS(
      "font-weight",
      "600"
    );
    await expect(form.getByLabel("Amount", { exact: true })).toHaveValue("25000");

    await form.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect.poll(() => putCalled).toBe(true);
  });
});

test.describe("record-modal — Transfer segment (REC-04)", () => {
  test("Transfer branch hides Category, shows From/To account selects, POSTs the whitelist body to /api/transactions/transfer", async ({
    page,
  }) => {
    await mockDashboard(page);
    let transferPosted = false;
    let transactionsPosted = false;
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions/transfer", async (route) => {
      if (route.request().method() === "POST") {
        transferPosted = true;
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ status: "ok" }),
        });
        return;
      }
      await route.fallback();
    });
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        transactionsPosted = true;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Transfer", exact: true }).click();

    await expect(form.getByLabel("Category", { exact: true })).toHaveCount(0);
    const fromSelect = form.getByLabel("From account", { exact: true });
    const toSelect = form.getByLabel("To account", { exact: true });
    await expect(fromSelect).toBeVisible();
    await expect(toSelect).toBeVisible();
    await expect(fromSelect.locator("option", { hasText: "Cash" })).toHaveCount(1);
    await expect(fromSelect.locator("option", { hasText: "Bank" })).toHaveCount(1);

    await fromSelect.selectOption({ label: "Cash" });
    await toSelect.selectOption({ label: "Bank" });
    await form.getByLabel("Amount", { exact: true }).fill("50000");
    await form.getByRole("button", { name: "Add transfer", exact: true }).click();

    await expect.poll(() => transferPosted).toBe(true);
    expect(transactionsPosted).toBe(false);
    expect(postedBody).not.toBeNull();
    const keys = Object.keys(postedBody as Record<string, unknown>).sort();
    expect(keys).toEqual(
      ["amount", "currency", "date", "from_account", "notes", "to_account"].sort()
    );
    expect((postedBody as Record<string, unknown>).from_account).toBe("Cash");
    expect((postedBody as Record<string, unknown>).to_account).toBe("Bank");
    expect((postedBody as Record<string, unknown>).amount).toBe(50000);
  });

  test("same-account guard blocks submit with an inline error and issues no request", async ({
    page,
  }) => {
    await mockDashboard(page);
    let transferPosted = false;
    await page.route("**/api/transactions/transfer", async (route) => {
      if (route.request().method() === "POST") transferPosted = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Transfer", exact: true }).click();
    await form.getByLabel("From account", { exact: true }).selectOption({ label: "Cash" });
    await form.getByLabel("To account", { exact: true }).selectOption({ label: "Cash" });
    await form.getByLabel("Amount", { exact: true }).fill("50000");
    await form.getByRole("button", { name: "Add transfer", exact: true }).click();

    await expect(
      page.getByText("From and To accounts must be different.")
    ).toBeVisible();
    expect(transferPosted).toBe(false);
  });

  test("editing a transfer-tinted row locks the segment, keeps legacy Account select, never routes to the pair endpoint", async ({
    page,
  }) => {
    await mockDashboard(page, { is_transfer: true, amount: -25000 });
    let putCalled = false;
    let transferPosted = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture({ is_transfer: true })[0] }),
        });
        return;
      }
      await route.fallback();
    });
    await page.route("**/api/transactions/transfer", async (route) => {
      transferPosted = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });

    await openEditModal(page);
    const form = page.locator("form").filter({ hasText: "Save changes" });

    // Segmented control disabled: clicking Income must not change the active segment.
    const transferSegment = form.getByRole("button", { name: "Transfer", exact: true });
    const incomeSegment = form.getByRole("button", { name: "Income", exact: true });
    await expect(transferSegment).toHaveCSS("font-weight", "600");
    await incomeSegment.click({ force: true });
    await expect(transferSegment).toHaveCSS("font-weight", "600");

    // Legacy single Account select shown, not From/To.
    await expect(form.getByLabel("Account", { exact: true })).toBeVisible();
    await expect(form.getByLabel("From account", { exact: true })).toHaveCount(0);
    await expect(form.getByLabel("To account", { exact: true })).toHaveCount(0);

    await expect(
      page.getByText(
        "This is one leg of a transfer — full pair editing isn't available yet."
      )
    ).toBeVisible();
    await expect(
      form.getByRole("button", { name: "Save & add another", exact: true })
    ).toHaveCount(0);

    await form.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect.poll(() => putCalled).toBe(true);
    expect(transferPosted).toBe(false);
  });
});
