import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 18 Plan 01 — Balance adjustment (ACCT-02), now opened from Settings
// (account options → Adjust balance). The success POST of {target_balance}
// is covered in settings.spec.ts; this file keeps the 422 error path.
// Synthetic data; every request is mocked.
// ---------------------------------------------------------------------------

test.describe("balance adjustment (ACCT-02)", () => {
  test("a 422 renders the standard error copy and keeps the modal open", async ({
    page,
  }) => {
    await page.route("**/api/categories*", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/cashflow/summary**", (route) =>
      route.fulfill({
        json: { accounts: [{ id: 1, name: "Cash", type: "liquid", current_balance: 1_000_000 }] },
      })
    );
    await page.route("**/api/accounts/*/adjust-balance", (route) =>
      route.fulfill({ status: 422, json: { detail: "some backend message" } })
    );

    await page.goto("/settings");
    await page.getByRole("button", { name: "Account options: Cash", exact: true }).click();
    await page.getByRole("menuitem", { name: "Adjust balance", exact: true }).click();
    await expect(page.getByText("Adjust balance — Cash")).toBeVisible();

    const modal = page.locator("form").filter({ hasText: "Save adjustment" });
    await modal.locator("input[type='number']").fill("1500000");
    await modal.getByRole("button", { name: "Save adjustment" }).click();

    await expect(
      page.getByText("Couldn't save adjustment: some backend message. Nothing was changed.")
    ).toBeVisible();
    await expect(page.getByText("Adjust balance — Cash")).toBeVisible();
  });
});
