import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 16 Plan 01 (Wave 0) — platform-crud.spec.ts (PLAT-02).
// PlatformManager now lives on Settings (#platforms), reached from the
// Investments Holdings menu (quick 261115-bi5).
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

// The cards above Platforms fill in after their fetches; slow (and synthetic)
// replies make the page grow after load, as it does live, so the hash jump
// can only land if the page scrolls once its data is in.
async function mockSlowCards(page: Page) {
  const slow = (body: unknown) => async (route: import("@playwright/test").Route) => {
    await new Promise((r) => setTimeout(r, 600));
    await route.fulfill({ json: body as object });
  };
  const cat = (id: number) => ({
    id, name: `ZZTest Category ${id}`, parent_id: null, kind: "expense", color: null,
    effective_color: null, icon: null, is_system: false, tx_count: 0, children: [],
  });
  const acct = (id: number) => ({ id, name: `ZZTest Account ${id}`, current_balance: 0, type: "liquid" });
  await page.route("**/api/categories*", slow(Array.from({ length: 40 }, (_, i) => cat(i + 1))));
  await page.route("**/api/cashflow/summary**", slow({ accounts: [1, 2, 3, 4].map(acct) }));
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

    await page.goto("/settings");
    await expect(page.locator("#platforms").getByRole("heading", { name: "Platforms" })).toBeVisible();
    await page.getByRole("button", { name: "Add platform", exact: true }).click();
    await page.getByPlaceholder("Platform name").fill("IBKR");
    await page.getByPlaceholder("e.g. brokerage, crypto app").fill("brokerage");
    await page
      .locator("form")
      .getByRole("button", { name: "Add platform", exact: true })
      .click();

    await expect.poll(() => postedBody?.name).toBe("IBKR");
    await expect.poll(() => postedBody?.kind).toBe("brokerage");
    await expect.poll(() => postedBody?.currency).toBe("IDR");
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

    await page.goto("/settings");
    // Pin the row by stable position, not by name text: clicking Edit swaps the
    // name text node for an <input value="Binance">, and Playwright's hasText
    // ignores input values, so a hasText:"Binance" locator would resolve to 0
    // rows after the first click. Binance is id:1 (first row of the Platforms
    // section) in mockInvestments.
    const binanceRow = page.locator("#platforms tbody tr").first();
    await page
      .getByRole("button", { name: "Platform options: Binance", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
    await binanceRow.locator("input").first().fill("Binance Global");
    await binanceRow.getByPlaceholder("e.g. brokerage, crypto app").fill("exchange");
    await binanceRow
      .getByRole("button", { name: "Save platform", exact: true })
      .click();

    await expect.poll(() => putBody?.name).toBe("Binance Global");
    await expect.poll(() => putBody?.kind).toBe("exchange");
    await expect.poll(() => putBody?.currency).toBe("IDR");
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

    await page.goto("/settings");
    await page
      .getByRole("button", { name: "Platform options: Binance", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
    await expect(
      page.getByText("Delete this platform? This can't be undone.")
    ).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page.getByText(/holdings use this platform/)).toBeVisible();
    await page.getByRole("button", { name: "Reassign & delete" }).click();

    await expect.poll(() => reassignCalled).toBe(true);
  });

  test("Settings lists platforms in the Platforms section", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/settings");
    const section = page.locator("#platforms");
    await expect(section.getByRole("heading", { name: "Platforms" })).toBeVisible();
    // The name cell also holds the kind, so match the row, not an exact text.
    await expect(section.locator("tbody tr").filter({ hasText: "Binance" })).toBeVisible();
    await expect(section.locator("tbody tr").filter({ hasText: "Stockbit" })).toBeVisible();
  });

  test("Investments ⋯ Manage platforms opens Settings at Platforms", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await mockSlowCards(page);
    await mockInvestments(page);
    await page.goto("/investments");
    await page.getByRole("button", { name: "Holdings options", exact: true }).click();
    await page.getByRole("menuitem", { name: "Manage platforms", exact: true }).click();
    await expect(page).toHaveURL(/\/settings#platforms$/);
    // Only judge the scroll once the slow cards above have filled in.
    await expect(page.getByText("ZZTest Account 4").first()).toBeAttached();
    await expect(page.getByText("ZZTest Category 40").first()).toBeAttached();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect(page.locator("#platforms").getByRole("heading", { name: "Platforms" })).toBeInViewport();
  });

  test("Settings #platforms deep link scrolls the Platforms section into view", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await mockSlowCards(page);
    await mockInvestments(page);
    await page.goto("/settings#platforms");
    // Only judge the scroll once the slow cards above have filled in.
    await expect(page.getByText("ZZTest Account 4").first()).toBeAttached();
    await expect(page.getByText("ZZTest Category 40").first()).toBeAttached();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect(page.locator("#platforms").getByRole("heading", { name: "Platforms" })).toBeInViewport();
  });
});
