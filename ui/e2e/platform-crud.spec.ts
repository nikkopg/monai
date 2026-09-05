import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 16 Plan 01 (Wave 0) — platform-crud.spec.ts (PLAT-02).
//
// Structural mirror of cashflow-crud.spec.ts's "account reassign-then-delete"
// test — route-mocked, no live backend. Pins CRUD parity for PlatformManager:
// add (name + kind), edit (name AND kind — the D-08 gap), delete-with-reassign
// (structural copy, unchanged code, asserted for parity only).
//
// Expected RED against current code for the edit-kind scenario (PlatformManager
// edit row only sends `name` today) — turns GREEN in Wave 1 (Plan 03).
// ---------------------------------------------------------------------------

function platformsFixture() {
  return [
    { id: 1, name: "Binance", kind: "crypto app" },
    { id: 2, name: "Stockbit", kind: "brokerage" },
  ];
}

async function mockInvestments(page: Page) {
  await page.route("**/api/investments/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        groups: [],
        asset_type_groups: [],
        total_value: 0,
        total_unrealized_pnl: 0,
      }),
    });
  });
  await page.route("**/api/investments/history**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ points: [] }),
    });
  });
  await page.route("**/api/platforms", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(platformsFixture()),
    });
  });
}

test.describe("platform CRUD parity (PLAT-02)", () => {
  test("Add a platform posts name and kind to POST /api/platforms", async ({
    page,
  }) => {
    await mockInvestments(page);
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/platforms", async (route) => {
      if (route.request().method() === "POST") {
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ id: 3, name: "IBKR", kind: "brokerage" }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/investments");
    await expect(page.getByText("Platforms", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Add platform", exact: true }).click();
    await page.getByPlaceholder("Platform name").fill("IBKR");
    await page.getByPlaceholder("e.g. brokerage, crypto app").fill("brokerage");
    await page
      .locator("form")
      .getByRole("button", { name: "Add platform", exact: true })
      .click();

    await expect.poll(() => postedBody?.name).toBe("IBKR");
    await expect.poll(() => postedBody?.kind).toBe("brokerage");
  });

  test("Edit updates both name and kind via PUT /api/platforms/{id}", async ({
    page,
  }) => {
    await mockInvestments(page);
    let putBody: Record<string, unknown> | null = null;
    await page.route("**/api/platforms/1", async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: 1, name: "Binance Global", kind: "exchange" }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/investments");
    // Pin the row by stable position, not by name text: clicking Edit swaps the
    // name text node for an <input value="Binance">, and Playwright's hasText
    // ignores input values, so a hasText:"Binance" locator would resolve to 0
    // rows after the first click. Binance is id:1 (first row of the Platforms
    // section) in mockInvestments.
    const binanceRow = page
      .locator("section")
      .filter({ hasText: "Platforms" })
      .locator("tbody tr")
      .first();
    await binanceRow.getByText("Edit", { exact: true }).click();
    await binanceRow.locator("input").first().fill("Binance Global");
    await binanceRow.getByPlaceholder("e.g. brokerage, crypto app").fill("exchange");
    await binanceRow
      .getByRole("button", { name: "Save platform", exact: true })
      .click();

    await expect.poll(() => putBody?.name).toBe("Binance Global");
    await expect.poll(() => putBody?.kind).toBe("exchange");
  });

  test("Delete on a platform with holdings surfaces the reassign select (422 path)", async ({
    page,
  }) => {
    await mockInvestments(page);
    let reassignCalled = false;
    await page.route("**/api/platforms/1*", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      if (req.method() === "DELETE" && !url.searchParams.has("reassign_to")) {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            detail: { message: "3 holdings use this platform", affected_count: 3 },
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

    await page.goto("/investments");
    const binanceRow = page
      .locator("tr", { hasText: "Binance" })
      .filter({ hasText: "Delete" });
    await binanceRow.getByText("Delete", { exact: true }).click();
    await expect(
      page.getByText("Delete this platform? This can't be undone.")
    ).toBeVisible();
    await page.locator("button").filter({ hasText: "Delete" }).click();

    await expect(page.getByText(/holdings use this platform/)).toBeVisible();
    await page.getByRole("button", { name: "Reassign & delete" }).click();

    await expect.poll(() => reassignCalled).toBe(true);
  });
});
