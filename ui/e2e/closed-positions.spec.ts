import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Quick 261107-nq6 — closed-position records on the Investments page.
// Route-mocked, no live backend. All values are synthetic. Every non-GET route
// is fulfilled here, so nothing reaches a real backend.
// ---------------------------------------------------------------------------

type Row = {
  id: number;
  ticker: string;
  platform_id: number | null;
  platform_name: string | null;
  realized_pnl: number;
  close_date: string;
};

const rowsFixture = (): Row[] => [
  { id: 1, ticker: "ZZ1", platform_id: 1, platform_name: "Plat A", realized_pnl: 125000, close_date: "2026-03-04" },
  { id: 2, ticker: "ZZ2", platform_id: 1, platform_name: "Plat A", realized_pnl: -40000, close_date: "2026-04-10" },
];

async function mockPage(page: Page, rows: Row[]) {
  await page.route("**/api/investments/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        groups: [],
        asset_type_groups: [],
        total_value: 0,
        total_unrealized_pnl: 0,
        total_realized_pnl: 0,
        as_of: "2026-11-01",
      }),
    });
  });
  await page.route("**/api/investments/history**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ points: [] }) });
  });
  await page.route("**/api/platforms", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "Plat A", kind: "brokerage" }]),
    });
  });
  let current = rows;
  await page.route("**/api/closed-positions**", async (route) => {
    const req = route.request();
    const m = req.url().match(/closed-positions\/(\d+)/);
    if (req.method() === "PUT" && m) {
      const body = req.postDataJSON();
      current = current.map((r) => (r.id === Number(m[1]) ? { ...r, ...body } : r));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current.find((r) => r.id === Number(m[1]))),
      });
      return;
    }
    if (req.method() === "DELETE" && m) {
      current = current.filter((r) => r.id !== Number(m[1]));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "deleted", id: Number(m[1]) }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
  });
}

test.describe("closed positions list", () => {
  test("renders ticker, platform and signed realized value", async ({ page }) => {
    await mockPage(page, rowsFixture());
    await page.goto("/investments");
    const list = page.getByTestId("closed-positions");
    await expect(list).toBeVisible();
    await expect(list.getByText("ZZ1", { exact: true })).toBeVisible();
    await expect(list.getByText("Plat A", { exact: true })).toHaveCount(2);
    await expect(list.getByText("+125,000", { exact: true })).toBeVisible();
    await expect(list.getByText("-40,000", { exact: true })).toBeVisible();
  });

  test("renders nothing when there are no closed positions", async ({ page }) => {
    await mockPage(page, []);
    await page.goto("/investments");
    await expect(page.getByText("Platforms", { exact: true })).toBeVisible();
    await expect(page.getByTestId("closed-positions")).toHaveCount(0);
  });

  test("Edit sends PUT with realized_pnl and close_date, then reloads", async ({ page }) => {
    await mockPage(page, rowsFixture());
    let put: { url: string; body: Record<string, unknown> } | null = null;
    page.on("request", (req) => {
      if (req.method() === "PUT" && req.url().includes("/api/closed-positions/")) {
        put = { url: req.url(), body: req.postDataJSON() };
      }
    });
    await page.goto("/investments");
    await page.getByRole("button", { name: "Edit ZZ1" }).click();
    await page.getByLabel("Realized P&L for ZZ1").fill("99000");
    await page.getByLabel("Close date for ZZ1").fill("2026-03-05");
    await page.getByRole("button", { name: "Save ZZ1" }).click();

    await expect.poll(() => put !== null).toBeTruthy();
    expect(put!.url).toMatch(/\/api\/closed-positions\/1$/);
    expect(put!.body).toEqual({ realized_pnl: 99000, close_date: "2026-03-05" });
    // The list reloaded from the (mutated) mock.
    await expect(page.getByText("+99,000", { exact: true })).toBeVisible();
    await expect(page.getByText("2026-03-05", { exact: true })).toBeVisible();
  });

  test("Edit shows the backend error inline and keeps the row", async ({ page }) => {
    await mockPage(page, rowsFixture());
    await page.route("**/api/closed-positions/1", async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ detail: "some backend message" }),
        });
        return;
      }
      await route.fallback();
    });
    await page.goto("/investments");
    await page.getByRole("button", { name: "Edit ZZ1" }).click();
    await page.getByLabel("Realized P&L for ZZ1").fill("1");
    await page.getByRole("button", { name: "Save ZZ1" }).click();
    await expect(page.getByText(/some backend message/)).toBeVisible();
  });

  test("Delete confirms, sends DELETE, and reloads", async ({ page }) => {
    await mockPage(page, rowsFixture());
    let deleted = false;
    page.on("request", (req) => {
      if (req.method() === "DELETE" && req.url().endsWith("/api/closed-positions/2")) deleted = true;
    });
    let message = "";
    page.on("dialog", async (d) => {
      message = d.message();
      await d.accept();
    });
    await page.goto("/investments");
    await page.getByRole("button", { name: "Delete ZZ2" }).click();

    await expect.poll(() => deleted).toBeTruthy();
    expect(message).toMatch(/realized P&L leaves the total/i);
    expect(message).toMatch(/cash record stays/i);
    await expect(page.getByText("ZZ2", { exact: true })).toHaveCount(0);
    await expect(page.getByText("ZZ1", { exact: true })).toBeVisible();
  });

  test("Delete does nothing when the confirm is dismissed", async ({ page }) => {
    await mockPage(page, rowsFixture());
    let deleted = false;
    page.on("request", (req) => {
      if (req.method() === "DELETE") deleted = true;
    });
    page.on("dialog", (d) => d.dismiss());
    await page.goto("/investments");
    await page.getByRole("button", { name: "Delete ZZ2" }).click();
    await expect(page.getByText("ZZ2", { exact: true })).toBeVisible();
    expect(deleted).toBe(false);
  });
});
