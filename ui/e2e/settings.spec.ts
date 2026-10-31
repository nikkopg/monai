import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 3 Plan 03 — Settings page render spec.
//
// This spec MUST fail (RED) against the 03-01 placeholder (`ui/app/settings/
// page.tsx` today renders only "Settings controls load here."). It asserts
// the full three-card contract defined in 03-UI-SPEC.md:
//   - three card section titles: "LLM Provider & Model", "API Keys",
//     "Preferences"
//   - three Save buttons with exact labels: "Save Provider", "Save Keys",
//     "Save Preferences"
//   - a provider <select> offering ollama / claude / openai
//   - a price data source <select> offering coingecko / yfinance / manual
//   - the masked-key helper text "Leave blank to keep the current key."
//
// These are frontend-only render assertions — no backend interaction is
// required. The page must render its cards even if GET /api/settings fails
// (no backend is guaranteed to be running in this sandbox).
// ---------------------------------------------------------------------------

test.describe("/settings page", () => {
  test("renders the three card section titles", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByText("LLM Provider & Model", { exact: true })
    ).toBeVisible();
    await expect(page.getByText("API Keys", { exact: true })).toBeVisible();
    await expect(page.getByText("Preferences", { exact: true })).toBeVisible();
  });

  test("renders the three Save buttons with exact labels", async ({
    page,
  }) => {
    await page.goto("/settings");
    await expect(
      page.getByRole("button", { name: "Save Provider", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Save Keys", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Save Preferences", exact: true })
    ).toBeVisible();
  });

  test("provider segmented control offers ollama, claude, openai", async ({
    page,
  }) => {
    await page.goto("/settings");
    // v1.1: provider is a segmented control (3 buttons), not a <select>.
    for (const p of ["ollama", "claude", "openai"]) {
      await expect(
        page.getByRole("button", { name: p, exact: true })
      ).toBeVisible();
    }
  });

  test("price data source select offers coingecko, yfinance, manual", async ({
    page,
  }) => {
    await page.goto("/settings");
    const priceSourceSelect = page.locator("select").filter({
      has: page.locator("option[value='coingecko']"),
    });
    await expect(priceSourceSelect).toHaveCount(1);
    const values = await priceSourceSelect.locator("option").evaluateAll(
      (opts) => opts.map((o) => (o as HTMLOptionElement).value)
    );
    expect(values).toEqual(["coingecko", "yfinance", "manual"]);
  });

  test("shows the masked-key helper text", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByText("Leave blank to keep the current key.")
    ).toBeVisible();
  });

  // quick 261011-mgj: every row action sits behind a ⋯ menu. Synthetic data,
  // every route this test touches is mocked and non-GETs fail, so nothing can
  // reach the live backend; nothing is clicked through to a destructive action.
  test("row options menus list the same actions as before", async ({ page }) => {
    const node = (id: number, name: string, is_system: boolean) => ({
      id, name, parent_id: null, kind: "expense", color: null, effective_color: null,
      icon: null, is_system, tx_count: 0, children: [],
    });
    const accounts = [
      { id: 1, name: "ZZTest Cash", current_balance: 0, type: "liquid" },
      { id: 2, name: "ZZTest Card", current_balance: 0, type: "credit" },
    ];
    const cats = [node(1, "ZZTest Food", false), node(2, "ZZTest System", true)];
    const mock = async (pg: Page, glob: string, body: unknown) =>
      pg.route(glob, (route) =>
        route.request().method() === "GET"
          ? route.fulfill({ json: body as object })
          : route.fulfill({ status: 500, json: { detail: "blocked in test" } })
      );
    await mock(page, "**/api/categories*", cats);
    await mock(page, "**/api/cashflow/summary**", { accounts });
    await page.goto("/settings");

    const items = page.getByRole("menuitem");
    const open = (name: string) =>
      page.getByRole("button", { name, exact: true }).click();

    await open(`Category options: ${cats[0].name}`);
    await expect(items).toHaveText(["Add subcategory", "Edit", "Merge into…", "Delete"]);
    await page.keyboard.press("Escape");

    await open(`Category options: ${cats[1].name}`);
    const del = page.getByRole("menuitem", { name: "Delete", exact: true });
    await expect(del).toHaveAttribute("aria-disabled", "true");
    await expect(del).toHaveAttribute("title", "System category — can't be deleted.");
    await page.keyboard.press("Escape");

    await open(`Account options: ${accounts[0].name}`);
    await expect(items).toHaveText(["Edit", "Adjust balance", "Delete"]);
    await page.keyboard.press("Escape");

    await open(`Account options: ${accounts[1].name}`);
    await expect(items).toHaveText(["Edit", "Delete"]);
  });
});

// Phase 44-01 — AccountManager currency surfaces. Synthetic data; GETs are
// mocked and every non-GET is fulfilled by the test, so nothing reaches the
// live backend through the dev server's proxy.
test.describe("AccountManager currency (Phase 44)", () => {
  const mockSummary = async (pg: Page, accounts: object[]) => {
    await pg.route("**/api/categories*", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: [] })
        : route.fulfill({ status: 500, json: { detail: "blocked in test" } })
    );
    await pg.route("**/api/cashflow/summary**", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { accounts } })
        : route.fulfill({ status: 500, json: { detail: "blocked in test" } })
    );
  };

  test("USD account create and chip", async ({ page }) => {
    await mockSummary(page, [
      { id: 1, name: "ZZ44 Cash", current_balance: 0, type: "liquid", currency: "IDR" },
      { id: 2, name: "ZZ44 Wallet", current_balance: 0, type: "liquid", currency: "USD" },
      { id: 3, name: "ZZ44 Card", current_balance: 0, type: "liquid" },
    ]);
    const posted: unknown[] = [];
    await page.route("**/api/accounts", (route) => {
      if (route.request().method() !== "POST") return route.fulfill({ status: 500, json: { detail: "blocked in test" } });
      posted.push(route.request().postDataJSON());
      return route.fulfill({ status: 201, json: { id: 9, name: "ZZ44 New", type: "liquid", currency: "USD" } });
    });
    await page.goto("/settings");

    const chip = (name: string) =>
      page.locator("tr", { hasText: name }).getByText(/^(IDR|USD)$/);
    await expect(chip("ZZ44 Cash")).toHaveText("IDR");
    await expect(chip("ZZ44 Wallet")).toHaveText("USD");
    await expect(chip("ZZ44 Card")).toHaveText("IDR");

    await page.getByRole("button", { name: "Add account", exact: true }).click();
    const select = page.getByLabel("Account currency");
    expect(
      await select.locator("option").evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value))
    ).toEqual(["IDR", "USD"]);
    await expect(select).toHaveValue("IDR");

    await select.selectOption("USD");
    await page.getByPlaceholder("Account name").fill("ZZ44 New");
    await page.getByRole("button", { name: "Add account", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toEqual({ name: "ZZ44 New", type: "liquid", currency: "USD" });

    await page.getByRole("button", { name: "Add account", exact: true }).click();
    await expect(page.getByLabel("Account currency")).toHaveValue("IDR");
  });
  test("reassign lists same-currency accounts only", async ({ page }) => {
    await mockSummary(page, [
      { id: 1, name: "ZZ44 Cash", current_balance: 0, type: "liquid", currency: "IDR" },
      { id: 2, name: "ZZ44 Bank", current_balance: 0, type: "liquid", currency: "IDR" },
      { id: 3, name: "ZZ44 Card", current_balance: 0, type: "liquid" },
      { id: 4, name: "ZZ44 Wallet", current_balance: 0, type: "liquid", currency: "USD" },
    ]);
    const deletes: string[] = [];
    await page.route(/\/api\/accounts\/\d+/, (route) => {
      const req = route.request();
      if (req.method() !== "DELETE") return route.fulfill({ status: 500, json: { detail: "blocked in test" } });
      deletes.push(req.url());
      return req.url().includes("reassign_to")
        ? route.fulfill({ json: { status: "deleted", reassigned: 3 } })
        : route.fulfill({ status: 422, json: { detail: { message: "3 transactions use this account", affected_count: 3 } } });
    });
    await page.goto("/settings");

    const startDelete = async (name: string) => {
      await page.getByRole("button", { name: `Account options: ${name}`, exact: true }).click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await page.getByRole("button", { name: "Delete account", exact: true }).click();
    };

    // USD account, no other USD account: no select, disabled confirm, Cancel closes.
    await startDelete("ZZ44 Wallet");
    await expect(page.getByText("No other USD account to move these records to.")).toBeVisible();
    await expect(page.getByLabel("Destination account")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reassign & delete", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Reassign & delete", exact: true })).toHaveCount(0);
    expect(deletes.filter((u) => u.includes("reassign_to"))).toEqual([]);

    // IDR account: only IDR accounts (a missing currency counts as IDR), never itself.
    await startDelete("ZZ44 Cash");
    const dest = page.getByLabel("Destination account");
    expect(await dest.locator("option").allTextContents()).toEqual(["ZZ44 Bank", "ZZ44 Card"]);
    const confirm = page.getByRole("button", { name: "Reassign & delete", exact: true });
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect.poll(() => deletes.filter((u) => u.includes("reassign_to=2")).length).toBe(1);
    expect(deletes.find((u) => u.includes("reassign_to"))).toContain("/api/accounts/1?reassign_to=2");
  });
});
