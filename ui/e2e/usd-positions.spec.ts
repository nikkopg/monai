import { test, expect, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";

test.beforeEach(async ({ page }) => {
  await watchCsp(page);
});
test.afterEach(async ({ page }) => {
  expect(await cspViolations(page)).toEqual([]);
});

// Quick 261108-d2c — USD positions show in USD with the IDR figure underneath.
// Route-mocked, synthetic values only. The backend computes the usd_* fields;
// the UI only formats them.

const RATE_TITLE = "1 USD = 20,000 IDR · rate of 2 Jan 2026";

const usdHolding = {
  id: 11,
  ticker: "ZZUSD",
  currency: "USD",
  asset_type: "crypto",
  quantity: 15,
  avg_cost: 47000,
  current_price: 100000,
  current_value: 1500000,
  unrealized_pnl: 795000,
  realized_pnl: 215000,
  usd_avg_cost: 3,
  usd_current_price: 5,
  usd_current_value: 75,
  usd_unrealized_pnl: 30,
  usd_rate: 20000,
  usd_rate_date: "2026-01-02",
  platform_id: 1,
  coingecko_id: null,
  price_source: "manual",
  price_fetched_at: "2026-01-02T00:00:00Z",
  is_stale: false,
};

const coinHolding = {
  ...usdHolding,
  id: 13,
  ticker: "ZZCOIN",
  quantity: 1000,
  avg_cost: 350,
  current_price: 481.49,
  current_value: 481490,
  unrealized_pnl: 131490,
  usd_avg_cost: 0.0175,
  usd_current_price: 0.024074643857,
  usd_current_value: 24.07,
  usd_unrealized_pnl: 6.57,
};

// A USD position with no rate: every usd_ value is null.
const noRateHolding = {
  ...usdHolding,
  id: 14,
  ticker: "ZZNORATE",
  usd_avg_cost: null,
  usd_current_price: null,
  usd_current_value: null,
  usd_unrealized_pnl: null,
  usd_rate: null,
  usd_rate_date: null,
};

const idrHolding = {
  id: 12,
  ticker: "ZZIDR",
  currency: "IDR",
  asset_type: "stock",
  quantity: 10,
  avg_cost: 1000,
  current_price: 1200,
  current_value: 12000,
  unrealized_pnl: 2000,
  realized_pnl: 0,
  platform_id: 1,
  coingecko_id: null,
  price_source: "manual",
  price_fetched_at: "2026-01-02T00:00:00Z",
  is_stale: false,
};

async function mockPlatformPage(page: Page, holdings: unknown[]) {
  await page.route("**/api/platforms/*/detail", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        platform_id: 1,
        platform_name: "ZZ Exchange",
        kind: "crypto app",
        subtotal: 1512000,
        holdings,
      }),
    });
  });
  await page.route("**/api/portfolio-events*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

async function mockInvestmentsPage(page: Page, holdings: unknown[]) {
  await page.route("**/api/investments/summary**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        groups: [
          { platform_id: 1, platform_name: "ZZ Exchange", kind: "crypto app", subtotal: 1512000, holdings },
        ],
        asset_type_groups: [
          { asset_type: "gold", total_value: 12000 },
          { asset_type: "mutual_fund", total_value: 12000 },
          { asset_type: "idx_stock", total_value: 6000 },
          { asset_type: "other", total_value: 3000 },
          { asset_type: "crypto", total_value: 1500000 },
        ],
        total_value: 1512000,
        total_unrealized_pnl: 797000,
        total_realized_pnl: 215000,
        as_of: "2026-01-02",
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
      body: JSON.stringify([{ id: 1, name: "ZZ Exchange", kind: "crypto app" }]),
    });
  });
  await page.route("**/api/closed-positions**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

// The row is the innermost div holding the exact ticker text.
function row(page: Page, ticker: string) {
  return page.locator("div").filter({ has: page.getByText(ticker, { exact: true }) }).last();
}

// A cell's two lines: the figure on top, the IDR text underneath.
function lines(page: Page, ticker: string, column: number) {
  const cell = row(page, ticker).locator("> span").nth(column);
  return { top: cell.locator("> span").nth(0), under: cell.locator("> span").nth(1), cell };
}

type Box = { x: number; y: number; width: number; height: number };
// Strict axis-aligned rectangle intersection (touching edges do not overlap).
function overlaps(a: Box, b: Box) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

// The four boxes a holdings row is judged by: Value, Return, staleness line, ticker.
async function rowBoxes(page: Page, t: string) {
  const [value, ret, stale, ticker] = await Promise.all([
    lines(page, t, I.value).cell.boundingBox(),
    lines(page, t, I.ret).cell.boundingBox(),
    row(page, t).getByText(/^Price as of/).boundingBox(),
    row(page, t).getByText(t, { exact: true }).boundingBox(),
  ]);
  return { value: value!, ret: ret!, stale: stale!, ticker: ticker! };
}

// Platform page columns: Asset, Units, Avg cost, Price, Value, Realized, Unrealized.
const P = { avg: 2, price: 3, value: 4, realized: 5, unrealized: 6 };
// Investments page columns: Asset, Units, Price, Value, Return.
const I = { price: 2, value: 3, ret: 4 };

test.describe("USD positions on the platform page", () => {
  test("a USD row reads in USD first with the IDR figure underneath", async ({ page }) => {
    await mockPlatformPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments/1");
    await expect(row(page, "ZZUSD")).toBeVisible();

    const avg = lines(page, "ZZUSD", P.avg);
    await expect(avg.top).toHaveText("3.00 USD");
    await expect(avg.under).toHaveText("47,000 IDR");
    await expect(avg.under).not.toHaveAttribute("title", /.+/);

    const price = lines(page, "ZZUSD", P.price);
    await expect(price.top).toHaveText("5.00 USD");
    await expect(price.under).toHaveText("100,000 IDR");
    await expect(price.under).toHaveAttribute("title", RATE_TITLE);
    await expect(price.under).toHaveCSS("color", "rgb(111, 104, 87)");
    await expect(price.under).toHaveCSS("font-size", "12px");
    await expect(row(page, "ZZIDR").getByText("ZZID", { exact: true })).toHaveCSS("color", "rgb(35, 32, 27)");

    const value = lines(page, "ZZUSD", P.value);
    await expect(value.top).toHaveText("75.00 USD");
    await expect(value.under).toHaveText("1,500,000 IDR");
    await expect(value.under).toHaveAttribute("title", RATE_TITLE);

    // Realized stays IDR only.
    await expect(row(page, "ZZUSD").locator("> span").nth(P.realized)).toHaveText("+215,000");

    const un = lines(page, "ZZUSD", P.unrealized);
    await expect(un.top).toHaveText("+30.00 USD");
    await expect(un.under).toHaveText("+795,000 IDR");
  });

  test("small USD prices keep their digits to 8 significant figures", async ({ page }) => {
    await mockPlatformPage(page, [coinHolding]);
    await page.goto("/investments/1");
    await expect(lines(page, "ZZCOIN", P.avg).top).toHaveText("0.0175 USD");
    await expect(lines(page, "ZZCOIN", P.price).top).toHaveText("0.024074644 USD");
  });

  test("a USD row with no rate shows IDR and a note; an IDR row is unchanged", async ({ page }) => {
    await mockPlatformPage(page, [noRateHolding, idrHolding]);
    await page.goto("/investments/1");

    const nr = row(page, "ZZNORATE");
    await expect(nr.getByText("No USD rate, shown in IDR")).toBeVisible();
    await expect(nr.locator("> span").nth(P.avg)).toHaveText("47,000");
    await expect(nr.locator("> span").nth(P.price)).toHaveText("100,000");
    await expect(nr.locator("> span").nth(P.value)).toHaveText("1,500,000");
    await expect(nr.locator("> span").nth(P.unrealized)).toHaveText("+795,000");

    const idr = row(page, "ZZIDR");
    await expect(idr.getByText("No USD rate")).toHaveCount(0);
    await expect(idr.locator("> span").nth(P.avg)).toHaveText("1,000");
    await expect(idr.locator("> span").nth(P.price)).toHaveText("1,200");
    await expect(idr.locator("> span").nth(P.value)).toHaveText("12,000");
    await expect(idr.locator("> span").nth(P.unrealized)).toHaveText("+2,000");
  });
});

test.describe("USD positions on the Investments page", () => {
  test("a USD row shows price, value and return in USD over IDR", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, noRateHolding, idrHolding]);
    await page.goto("/investments");
    await expect(row(page, "ZZUSD")).toBeVisible();

    // GOLDS[0..4] from ui/app/cashflow/holdings.ts in largest-first order, as on the
    // Cashflow Holdings card. Crypto is the biggest group but comes fifth in the payload.
    // Scoped to Allocation: the Holdings group rows say "Crypto" too.
    const alloc = page.getByRole("region", { name: "Allocation" });
    await alloc.getByRole("group", { name: "Allocation grouping" }).getByRole("button", { name: "Asset type" }).click();
    const swatch = (label: string) =>
      alloc.getByText(label, { exact: true }).locator("xpath=preceding-sibling::span[1]");
    const golds: [string, string][] = [
      ["Crypto", "rgb(216, 178, 106)"],
      ["Gold", "rgb(201, 151, 63)"],
      ["Mutual funds", "rgb(168, 103, 74)"],
      ["Stocks", "rgb(227, 200, 145)"],
      ["Other", "rgb(138, 106, 63)"],
    ];
    for (const [label, rgb] of golds) {
      await expect(swatch(label)).toHaveCSS("background-color", rgb);
      await expect(swatch(label)).not.toHaveCSS("background-color", "rgb(181, 80, 63)");
    }

    const price = lines(page, "ZZUSD", I.price);
    await expect(price.top).toHaveText("5.00 USD");
    await expect(price.under).toHaveText("100,000 IDR");
    await expect(price.under).toHaveAttribute("title", RATE_TITLE);
    await expect(price.under).toHaveCSS("color", "rgb(111, 104, 87)");
    await expect(price.under).toHaveCSS("font-size", "12px");
    await expect(page.getByText("Asset", { exact: true }).first()).toHaveCSS("color", "rgb(111, 104, 87)");
    await expect(row(page, "ZZIDR").getByText("ZZID", { exact: true })).toHaveCSS("color", "rgb(35, 32, 27)");
    await expect(row(page, "ZZNORATE").getByText("ZZNO", { exact: true })).toHaveCSS("color", "rgb(255, 255, 255)");

    const value = lines(page, "ZZUSD", I.value);
    await expect(value.top).toHaveText("75.00 USD");
    await expect(value.under).toHaveText("1,500,000 IDR");
    await expect(value.under).toHaveAttribute("title", RATE_TITLE);

    const ret = lines(page, "ZZUSD", I.ret);
    await expect(ret.top).toHaveText("+66.7% USD");
    await expect(ret.under).toHaveText("+112.8% IDR");

    // No rate: IDR as today, plus the note.
    const nr = row(page, "ZZNORATE");
    await expect(nr.getByText("No USD rate, shown in IDR")).toBeVisible();
    await expect(nr.locator("> span").nth(I.price)).toHaveText("100,000");
    await expect(nr.locator("> span").nth(I.value)).toHaveText("1,500,000");
    await expect(nr.locator("> span").nth(I.ret)).toHaveText("+112.8%");

    // IDR row unchanged.
    const idr = row(page, "ZZIDR");
    await expect(idr.locator("> span").nth(I.price)).toHaveText("1,200");
    await expect(idr.locator("> span").nth(I.value)).toHaveText("12,000");
    await expect(idr.locator("> span").nth(I.ret)).toHaveText("+20.0%");
  });

  test("375px: holdings keep Value, Return and ⋯ on screen; Units × Price moves under the row", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await mockInvestmentsPage(page, [usdHolding, noRateHolding, idrHolding]);
    await page.goto("/investments");
    await expect(row(page, "ZZUSD")).toBeVisible();
    await expect(lines(page, "ZZUSD", I.value).cell).toBeVisible();
    await expect(page.getByText("Units", { exact: true })).toBeHidden();
    await expect(row(page, "ZZIDR").getByText("10 × 1,200", { exact: true })).toBeVisible();

    const open = (await page.getByRole("link", { name: "Open ZZ Exchange", exact: true }).boundingBox())!;
    expect(open.x).toBeGreaterThanOrEqual(0);
    expect(open.x + open.width).toBeLessThanOrEqual(375);

    // The text lives in RollingNumber's sr-only span (261115-dvn); measure the hero div around it.
    const total = page.getByText("1,512,000", { exact: true }).first().locator("xpath=ancestor::div[1]");
    expect(await total.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);

    const overflowing = await page.evaluate(() =>
      Array.from(document.querySelectorAll("main *"))
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > window.innerWidth + 1;
        })
        .map((el) => `${el.tagName} ${(el.textContent ?? "").slice(0, 20)}`)
    );
    expect(overflowing).toEqual([]);

    // The column header row is gone; each row stacks instead.
    await expect(page.getByText("Return", { exact: true })).toBeHidden();
    for (const t of ["ZZUSD", "ZZIDR"]) {
      const { value, ret, stale, ticker } = await rowBoxes(page, t);
      expect(ret.x - (value.x + value.width)).toBeGreaterThanOrEqual(8);
      expect(overlaps(value, stale)).toBe(false);
      expect(overlaps(value, ret)).toBe(false);
      for (const b of [value, ret]) {
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width).toBeLessThanOrEqual(375);
      }
      expect(ticker.width).toBeGreaterThanOrEqual(120);
    }
  });

  test("1440px: each holdings row stays on one line", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments");
    await expect(page.getByText("Return", { exact: true })).toBeVisible();
    for (const t of ["ZZUSD", "ZZIDR"]) {
      const { value, ret, ticker } = await rowBoxes(page, t);
      expect(Math.abs(value.y - ret.y)).toBeLessThanOrEqual(2);
      expect(value.y).toBeLessThan(ticker.y + ticker.height);
    }
  });

  test("loading skeleton: hero line draws, bones pulse, reduced motion stops both, the page replaces it (261115-hfb)", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**/api/investments/summary**", async (route) => {
      await gate;
      await route.fallback();
    });
    await page.goto("/investments");
    const skel = page.getByRole("status", { name: "Loading your portfolio" });
    await expect(skel).toBeVisible();
    await expect(skel).toHaveAttribute("aria-busy", "true");
    await expect(skel.locator(".draw-line")).toHaveCount(1);
    const names = () =>
      skel.evaluate((el) => [
        getComputedStyle(el.querySelector(".bone")!).animationName,
        getComputedStyle(el.querySelector(".draw-line path")!).animationName,
      ]);
    expect(await names()).toEqual(["breathe", "draw"]);
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await names()).toEqual(["none", "none"]);
    release();
    await expect(skel).toHaveCount(0);
    await expect(row(page, "ZZUSD")).toBeVisible();
  });

  test("1024 and 780: holdings rows fit the card, not the viewport (261115-e3k)", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    for (const { width, height, mid } of [
      { width: 1024, height: 800, mid: true },
      { width: 780, height: 900, mid: false },
    ]) {
      // Resize BEFORE goto: resizing a loaded page across 560px measures the nav mid-transition.
      await page.setViewportSize({ width, height });
      await page.goto("/investments");
      await expect(row(page, "ZZUSD")).toBeVisible();
      const card = (await page.getByRole("region", { name: "Holdings", exact: true }).boundingBox())!;
      const inside = (b: Box) => {
        expect(b.x).toBeGreaterThanOrEqual(card.x);
        expect(b.x + b.width).toBeLessThanOrEqual(card.x + card.width);
      };

      await expect(page.getByText("Units", { exact: true })).toBeHidden();
      if (mid) await expect(page.getByText("Return", { exact: true })).toBeVisible();
      else await expect(page.getByText("Return", { exact: true })).toBeHidden();
      await expect(row(page, "ZZIDR").getByText("10 × 1,200", { exact: true })).toBeVisible();

      for (const t of ["ZZUSD", "ZZIDR"]) {
        const { value, ret, stale, ticker } = await rowBoxes(page, t);
        const menu = (await page.getByRole("button", { name: "Holding options: " + t, exact: true }).boundingBox())!;
        expect(overlaps(value, ret)).toBe(false);
        expect(overlaps(value, stale)).toBe(false);
        expect(overlaps(ret, stale)).toBe(false);
        for (const b of [value, ret, stale, menu]) inside(b);
        if (mid) {
          expect(Math.abs(value.y - ret.y)).toBeLessThanOrEqual(2);
          expect(value.y).toBeLessThan(ticker.y + ticker.height);
        } else {
          expect(value.y).toBeGreaterThanOrEqual(stale.y + stale.height - 1);
        }
      }

      const group = page
        .locator("div")
        .filter({ has: page.getByRole("link", { name: "Open ZZ Exchange", exact: true }) })
        .last();
      const name = (await group.locator("> span").nth(0).boundingBox())!;
      const subtotal = (await group.locator("> span").nth(1).boundingBox())!;
      expect(overlaps(name, subtotal)).toBe(false);
      inside(subtotal);
    }
  });

  test("hero shows unrealized and realized P&L once; legend labels stay on one line", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments");
    await expect(page.getByText("+797,000", { exact: true })).toBeVisible();
    await expect(page.getByText("+215,000", { exact: true })).toBeVisible();
    const hero = page.getByRole("region", { name: "Portfolio value" });
    await expect(hero.getByText(/^Realized/)).toBeVisible();
    await expect(page.getByText("Unrealized P&L", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Realized P&L", { exact: true })).toHaveCount(0);
    await expect(page.getByText(/[\u25B2\u25BC]/)).toHaveCount(0);
    const alloc = page.getByRole("region", { name: "Allocation" });
    await alloc.getByRole("group", { name: "Allocation grouping" }).getByRole("button", { name: "Asset type" }).click();
    const box = await alloc.getByText("Mutual funds", { exact: true }).boundingBox();
    expect(box!.height).toBeLessThan(20);
  });

  test("headline figures roll like Cashflow; lists stay static (261115-dvn)", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments");
    const hero = page.getByRole("region", { name: "Portfolio value" });
    const alloc = page.getByRole("region", { name: "Allocation" });
    await expect(hero.locator(".roll > .sr-only")).toHaveText(["1,512,000", "+797,000", "+215,000"]);
    await expect(alloc.locator(".roll > .sr-only")).toHaveText(["1.5M"]);
    await expect(page.locator(".roll")).toHaveCount(4);
  });

  test("hero holds the history chart, its pills and the price footer", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, { ...idrHolding, is_stale: true }]);
    await page.route("**/api/investments/history**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          points: [
            { date: "2026-01-01", total_market_value: 1000000, total_pnl: 0 },
            { date: "2026-01-02", total_market_value: 1100000, total_pnl: 50000 },
            { date: "2026-01-03", total_market_value: 1512000, total_pnl: 797000 },
          ],
        }),
      });
    });
    await page.goto("/investments");
    const hero = page.getByRole("region", { name: "Portfolio value" });
    await expect(hero).toHaveCSS("background-color", "rgb(35, 32, 27)");
    await expect(hero.getByText("Total value", { exact: true })).toBeVisible();
    await expect(hero.getByRole("button", { name: "Refresh prices" })).toBeVisible();
    for (const name of ["1M", "3M", "All", "Value", "P&L"]) {
      await expect(hero.getByRole("button", { name, exact: true })).toBeVisible();
    }
    await expect(hero.getByRole("button", { name: "3M", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(hero.getByRole("button", { name: "Value", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(hero.locator(".recharts-line-curve")).toHaveCount(1);
    await expect(hero.locator(".recharts-line-curve")).toHaveAttribute("stroke", "#9fdcb6");
    await expect(hero.getByText(/^Unrealized/)).toBeVisible();
    await expect(hero.getByText(/^Realized/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Portfolio history" })).toHaveCount(0);

    const strip = page.getByText(/^USD positions converted at 1 USD = 20,000 IDR/);
    await expect(strip).toBeVisible();
    await expect(strip).toContainText("1 price is stale");
  });

  test("1440 puts Allocation at a third beside the hero; 375 stacks it below", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    const hero = page.getByRole("region", { name: "Portfolio value" });
    const alloc = page.getByRole("region", { name: "Allocation" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/investments");
    await expect(hero).toBeVisible();
    const h = (await hero.boundingBox())!;
    const a = (await alloc.boundingBox())!;
    expect(h.width / a.width).toBeGreaterThan(1.8);
    expect(h.width / a.width).toBeLessThan(2.2);
    expect(Math.abs(h.y - a.y)).toBeLessThanOrEqual(1);

    await page.setViewportSize({ width: 375, height: 812 });
    await expect(hero).toBeVisible();
    const h2 = (await hero.boundingBox())!;
    const a2 = (await alloc.boundingBox())!;
    expect(a2.y).toBeGreaterThanOrEqual(h2.y + h2.height);
  });

  test("the donut sits inside the Allocation card with the legend below it", async ({ page }) => {
    for (const vp of [
      { width: 1440, height: 900 },
      { width: 375, height: 812 },
    ]) {
      await mockInvestmentsPage(page, [usdHolding, idrHolding]);
      // Size before goto so ResponsiveContainer measures the real width.
      await page.setViewportSize(vp);
      await page.goto("/investments");
      const alloc = page.getByRole("region", { name: "Allocation" });
      const svg = alloc.locator("svg.recharts-surface").first();
      await expect(svg).toBeVisible();
      const c = (await alloc.boundingBox())!;
      const s = (await svg.boundingBox())!;
      expect(s.x).toBeGreaterThanOrEqual(c.x);
      expect(s.y).toBeGreaterThanOrEqual(c.y);
      expect(s.x + s.width).toBeLessThanOrEqual(c.x + c.width);
      expect(s.y + s.height).toBeLessThanOrEqual(c.y + c.height);
      expect(s.height).toBeLessThanOrEqual(220);

      const total = alloc.getByText("Total", { exact: true });
      await expect(total).toBeVisible();
      const t = (await total.boundingBox())!;
      const cx = t.x + t.width / 2;
      const cy = t.y + t.height / 2;
      expect(cx).toBeGreaterThanOrEqual(s.x);
      expect(cx).toBeLessThanOrEqual(s.x + s.width);
      expect(cy).toBeGreaterThanOrEqual(s.y);
      expect(cy).toBeLessThanOrEqual(s.y + s.height);
      await expect(total.locator("xpath=following-sibling::*[1]")).toHaveText("1.5M");

      await alloc.getByRole("group", { name: "Allocation grouping" }).getByRole("button", { name: "Asset type" }).click();
      const label = (await alloc.getByText("Mutual funds", { exact: true }).boundingBox())!;
      expect(label.y).toBeGreaterThanOrEqual(s.y + s.height);
    }
  });

  test("controls are at least 32px tall", async ({ page }) => {
    await mockInvestmentsPage(page, [usdHolding, idrHolding]);
    await page.goto("/investments");
    await expect(row(page, "ZZUSD")).toBeVisible();
    const controls = [
      ...["Refresh prices", "1M", "All", "Value", "P&L", "Open", "Closed", "+ Log event", "Holdings options", "Holding options: ZZUSD"].map(
        (name) => page.getByRole("button", { name, exact: true })
      ),
      page.getByRole("link", { name: "Open ZZ Exchange", exact: true }),
      // Both the Allocation and the Holdings grouping groups carry these.
      ...(await page.getByRole("button", { name: "Asset type", exact: true }).all()),
      ...(await page.getByRole("button", { name: "Platform", exact: true }).all()),
    ];
    for (const c of controls) {
      expect((await c.boundingBox())!.height).toBeGreaterThanOrEqual(32);
    }
  });

  test.describe("one Holdings card", () => {
    const holdings = (page: Page) => page.getByRole("region", { name: "Holdings" });
    const group = (page: Page, label: string) => page.getByRole("group", { name: label });

    test("one Holdings card groups rows under platform rows", async ({ page }) => {
      await mockInvestmentsPage(page, [usdHolding, idrHolding]);
      await page.goto("/investments");
      await expect(holdings(page)).toHaveCount(1);
      await expect(holdings(page).getByText("2 positions", { exact: true })).toBeVisible();
      await expect(holdings(page).getByText("1,512,000", { exact: true })).toBeVisible();
      await expect(holdings(page).getByRole("link", { name: "Open ZZ Exchange" })).toHaveAttribute("href", "/investments/1");
      await expect(row(page, "ZZUSD")).toBeVisible();
      await expect(row(page, "ZZIDR")).toBeVisible();
      await expect(page.getByRole("button", { name: "Holding options: ZZUSD", exact: true })).toBeVisible();
      await expect(page.getByText("Return", { exact: true })).toHaveCount(1);
    });

    test("the grouping pill is shared with Allocation", async ({ page }) => {
      await mockInvestmentsPage(page, [usdHolding, idrHolding]);
      await page.goto("/investments");
      const pressed = (label: string, name: string) =>
        group(page, label).getByRole("button", { name, exact: true });
      await expect(pressed("Holdings grouping", "Platform")).toHaveAttribute("aria-pressed", "true");
      await expect(pressed("Allocation grouping", "Platform")).toHaveAttribute("aria-pressed", "true");

      await pressed("Holdings grouping", "Asset type").click();
      await expect(pressed("Allocation grouping", "Asset type")).toHaveAttribute("aria-pressed", "true");
      await expect(holdings(page).getByText("Crypto", { exact: true })).toBeVisible();
      await expect(holdings(page).getByRole("link", { name: "Open ZZ Exchange" })).toHaveCount(0);
      await expect(row(page, "ZZUSD")).toContainText("ZZ Exchange");

      await pressed("Allocation grouping", "Platform").click();
      await expect(pressed("Holdings grouping", "Platform")).toHaveAttribute("aria-pressed", "true");
      await expect(holdings(page).getByRole("link", { name: "Open ZZ Exchange" })).toBeVisible();
    });

    test("Open/Closed switch", async ({ page }) => {
      await mockInvestmentsPage(page, [usdHolding, idrHolding]);
      await page.goto("/investments");
      await expect(row(page, "ZZUSD")).toBeVisible();
      await group(page, "Holdings view").getByRole("button", { name: "Closed", exact: true }).click();
      await expect(page.getByText("No closed positions yet.")).toBeVisible();
      await expect(page.getByText("Return", { exact: true })).toHaveCount(0);
      await expect(group(page, "Holdings grouping")).toHaveCount(0);
      await group(page, "Holdings view").getByRole("button", { name: "Open", exact: true }).click();
      await expect(row(page, "ZZUSD")).toBeVisible();
    });

    test("the menu holds Add holding directly", async ({ page }) => {
      await mockInvestmentsPage(page, [usdHolding, idrHolding]);
      await page.goto("/investments");
      await page.getByRole("button", { name: "Holdings options", exact: true }).click();
      await page.getByRole("menuitem", { name: "Add holding directly", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Add holding directly" })).toBeVisible();
    });
  });
});
