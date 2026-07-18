import { test, expect } from "@playwright/test";

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
});
