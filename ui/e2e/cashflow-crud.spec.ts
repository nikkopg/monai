import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 4 Plan 05 — Cashflow CRUD spec (CASH-04/05/06/07/08).
//
// Mirrors smoke.spec.ts / cashflow-dashboard.spec.ts conventions: intercept
// backend calls with route mocks so the spec is deterministic regardless of
// whether a live backend + seeded DB are available in this sandbox. Each
// test asserts the UI opens the right modal/dialog and issues the correct
// request — a full DB round-trip is exercised in the manual verification
// pass (04-05-PLAN.md <verification>).
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

function txFixture() {
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
    },
  ];
}

async function mockDashboard(page: Page) {
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
      body: JSON.stringify(txFixture()),
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
  await page.route("**/api/categories/*/affected-count", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ category: "Food & Drinks", affected_count: 3 }),
    });
  });
}

test.describe("transaction create/edit/delete", () => {
  test("Add transaction opens the modal and posts to /api/transactions", async ({
    page,
  }) => {
    await mockDashboard(page);
    let createCalled = false;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        createCalled = true;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 999,
            date: "2026-07-05T10:00:00Z",
            amount: -10000,
            category: "Transport",
            merchant: null,
            account_id: 1,
            notes: null,
            is_transfer: false,
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/cashflow");
    await page.getByRole("button", { name: "Add transaction", exact: true }).click();
    await expect(page.getByText("Add transaction").first()).toBeVisible();

    await page.getByPlaceholder("-25000").fill("-10000");
    await page
      .locator("form")
      .filter({ hasText: "Add transaction" })
      .getByRole("button", { name: "Add transaction", exact: true })
      .click();

    await expect.poll(() => createCalled).toBe(true);
  });

  test("row Edit action opens the modal pre-filled and PUTs the update", async ({
    page,
  }) => {
    await mockDashboard(page);
    let putCalled = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], amount: -30000 }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/cashflow");
    await page.getByText("Edit", { exact: true }).first().click();
    await expect(page.getByText("Edit transaction")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();

    await page.getByRole("button", { name: "Save changes" }).click();
    await expect.poll(() => putCalled).toBe(true);
  });

  test("row Delete action opens ConfirmDialog and DELETEs on confirm", async ({
    page,
  }) => {
    await mockDashboard(page);
    let deleteCalled = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "deleted" }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/cashflow");
    // Row-level actions are <span role="button">; the transactions-table
    // Delete link is the first such span on the page.
    await page.getByText("Delete", { exact: true }).first().click();
    await expect(
      page.getByText("Delete this transaction? This can't be undone.")
    ).toBeVisible();
    // The ConfirmDialog's confirm is a real <button> — scope to the tag to
    // avoid matching the row-level "Delete" spans still in the DOM.
    await page.locator("button").filter({ hasText: "Delete" }).click();

    await expect.poll(() => deleteCalled).toBe(true);
  });
});

test.describe("account reassign-then-delete", () => {
  test("delete on an account with transactions surfaces the reassign select (422 path)", async ({
    page,
  }) => {
    await mockDashboard(page);
    let reassignCalled = false;
    // Trailing "*" is required — Playwright's glob match on the base pattern
    // alone does not match when a query string (?reassign_to=...) is present.
    await page.route("**/api/accounts/1*", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      if (req.method() === "DELETE" && !url.searchParams.has("reassign_to")) {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              message: "3 transactions use this account",
              affected_count: 3,
            },
          }),
        });
        return;
      }
      if (req.method() === "DELETE" && url.searchParams.has("reassign_to")) {
        reassignCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "deleted", reassigned: true }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/cashflow");
    await expect(page.getByText("Accounts", { exact: true }).first()).toBeVisible();

    // The AccountManager section is the one whose "Cash" row has a Delete
    // action (the dashboard per-account balances table above it has no
    // actions column) — scope to the row containing "Delete" to disambiguate.
    const cashRow = page
      .locator("tr", { hasText: "Cash" })
      .filter({ hasText: "Delete" });
    await cashRow.getByText("Delete", { exact: true }).click();
    await expect(
      page.getByText("Delete this account? This can't be undone.")
    ).toBeVisible();
    // Row-level actions are <span role="button">; the ConfirmDialog's
    // confirm/cancel are real <button> elements — scope to the tag to avoid
    // matching the row-level "Delete" spans still in the DOM behind the modal.
    await page.locator("button").filter({ hasText: "Delete" }).click();

    // 422 path swaps in the reassign copy + destination select.
    await expect(
      page.getByText(/transactions use this account/)
    ).toBeVisible();
    await page.getByRole("button", { name: "Reassign & delete" }).click();

    await expect.poll(() => reassignCalled).toBe(true);
  });
});

test.describe("category rename/merge", () => {
  test("rename updates the category name with no confirm dialog", async ({
    page,
  }) => {
    await mockDashboard(page);
    let renameCalled = false;
    await page.route("**/api/categories/rename", async (route) => {
      renameCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          old_name: "Transport",
          new_name: "Travel",
          affected_count: 3,
        }),
      });
    });

    await page.goto("/cashflow");
    await expect(page.getByText("Categories", { exact: true })).toBeVisible();

    const transportRow = page.locator("tr", { hasText: "Transport" });
    await transportRow.getByText("Rename", { exact: true }).click();
    await page.locator("input[value='Transport']").fill("Travel");
    await page.getByRole("button", { name: "Rename category" }).click();

    await expect.poll(() => renameCalled).toBe(true);
  });

  test("merge shows the ConfirmDialog with affected_count before posting", async ({
    page,
  }) => {
    await mockDashboard(page);
    let mergeCalled = false;
    await page.route("**/api/categories/merge", async (route) => {
      mergeCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          from_name: "Food & Drinks",
          into_name: "Transport",
          affected_count: 3,
        }),
      });
    });

    await page.goto("/cashflow");
    const foodRow = page.locator("tr", { hasText: "Food & Drinks" });
    await foodRow.getByText("Merge into…", { exact: true }).click();
    await page.getByRole("button", { name: "Merge categories" }).click();

    await expect(
      page.getByText(/transactions will be updated\. This can't be undone\./)
    ).toBeVisible();
    await page.getByRole("button", { name: "Merge", exact: true }).click();

    await expect.poll(() => mergeCalled).toBe(true);
  });
});

test.describe("CSV upload", () => {
  test("uploading a file shows the Parsed/Inserted/Skipped result line", async ({
    page,
  }) => {
    await mockDashboard(page);
    await page.route("**/api/import", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          parsed: 10,
          inserted: 8,
          skipped: 2,
          currency: "IDR",
        }),
      });
    });

    await page.goto("/cashflow");
    await expect(page.getByText("Import CSV", { exact: true })).toBeVisible();

    await page.setInputFiles("input[type='file']", {
      name: "wallet-export.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("date,amount\n2026-07-01,-25000\n"),
    });
    await page.getByRole("button", { name: "Upload CSV" }).click();

    await expect(page.getByText(/Parsed 10.*Inserted 8.*Skipped 2/)).toBeVisible();
  });
});
