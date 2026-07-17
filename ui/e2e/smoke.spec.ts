import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 3 smoke test — the project's first frontend test.
//
// This spec MUST fail (RED) until Task 3/4 build the Nav + four routes. It
// verifies:
//   (a) each of /chat, /cashflow, /investments, /settings renders a unique,
//       identifying piece of text with no 404 / blank screen
//   (b) the shared nav bar shows exactly four links: Chat, Cashflow,
//       Investments, Settings — on every page
//   (c) clicking a nav link performs a client-side transition (no full
//       document reload) — proven via a window sentinel that survives
//       navigation
//   (d) the active nav link is visually highlighted (v1.1 "paper" redesign:
//       a dark ink pill background) while the others are not
// ---------------------------------------------------------------------------

const NAV_LABELS = ["Chat", "Cashflow", "Investments", "Settings"] as const;

async function getNavLinks(page: Page) {
  return page.locator("nav a, header a").filter({ hasText: /^(Chat|Cashflow|Investments|Settings)$/ });
}

test.describe("route rendering", () => {
  test("/chat renders the ask box", async ({ page }) => {
    const res = await page.goto("/chat");
    expect(res?.status()).toBeLessThan(400);
    await expect(page.getByText("Ask about your finances")).toBeVisible();
  });

  test("/cashflow renders the recent transactions section", async ({ page }) => {
    const res = await page.goto("/cashflow");
    expect(res?.status()).toBeLessThan(400);
    await expect(page.getByText("Recent transactions")).toBeVisible();
  });

  test("/investments renders the Investments heading", async ({ page }) => {
    const res = await page.goto("/investments");
    expect(res?.status()).toBeLessThan(400);
    await expect(
      page.getByRole("heading", { name: "Investments" })
    ).toBeVisible();
  });

  test("/settings renders a Settings heading", async ({ page }) => {
    const res = await page.goto("/settings");
    expect(res?.status()).toBeLessThan(400);
    await expect(
      page.getByRole("heading", { name: "Settings" })
    ).toBeVisible();
  });
});

test.describe("shared nav bar", () => {
  for (const route of ["/chat", "/cashflow", "/investments", "/settings"]) {
    test(`shows exactly four nav links on ${route}`, async ({ page }) => {
      await page.goto(route);
      const links = await getNavLinks(page);
      await expect(links).toHaveCount(4);
      const texts = await links.allTextContents();
      for (const label of NAV_LABELS) {
        expect(texts).toContain(label);
      }
    });
  }
});

test.describe("client-side navigation", () => {
  test("clicking Cashflow from Chat navigates without a full reload", async ({
    page,
  }) => {
    await page.goto("/chat");

    // Sentinel: set a value on window; a full document reload would wipe it.
    await page.evaluate(() => {
      (window as unknown as { __navProbe: boolean }).__navProbe = true;
    });

    const links = await getNavLinks(page);
    await links.filter({ hasText: "Cashflow" }).click();

    await expect(page).toHaveURL(/\/cashflow$/);
    const sentinel = await page.evaluate(
      () => (window as unknown as { __navProbe?: boolean }).__navProbe
    );
    expect(sentinel).toBe(true);
  });

  test("active nav link is highlighted after navigating to /cashflow", async ({
    page,
  }) => {
    await page.goto("/chat");
    const links = await getNavLinks(page);
    await links.filter({ hasText: "Cashflow" }).click();
    await expect(page).toHaveURL(/\/cashflow$/);

    // v1.1: active link carries the dark ink pill (#23201b == rgb(35, 32, 27)).
    // toHaveCSS auto-retries so it settles past the .2s background transition.
    const cashflowLink = links.filter({ hasText: "Cashflow" });
    await expect(cashflowLink).toHaveCSS("background-color", "rgb(35, 32, 27)");

    for (const label of ["Chat", "Investments", "Settings"]) {
      // Inactive links have no pill (transparent background).
      await expect(links.filter({ hasText: label })).not.toHaveCSS(
        "background-color",
        "rgb(35, 32, 27)"
      );
    }
  });
});
