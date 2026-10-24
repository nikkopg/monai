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
