import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 4 Plan 05 — Cashflow CRUD spec (CASH-04/05/06/07/08). Only CSV import
// still lives on Cashflow: transaction add/edit/delete moved to Records
// (record-modal.spec.ts, records.spec.ts), accounts and categories to Settings
// (settings.spec.ts, balance-adjust.spec.ts).
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
      { id: 1, name: "Food & Drinks", color: null, icon: null, total: 1_200_000, children: [] }, // pii-ok synthetic
      { id: 2, name: "Transport", color: null, icon: null, total: 500_000, children: [] }, // pii-ok synthetic
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

async function mockDashboard(page: Page) {
  await page.route("**/api/cashflow/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summaryFixture()),
    });
  });
}

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
