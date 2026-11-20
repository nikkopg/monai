import { test, expect, type Locator, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";
import { ids, mockInbox, NOW, proposal, transferProposal, txRow } from "./inbox-fixtures";
import { desktopSpot, sizeHistogram, smallText, type DesktopSpot } from "./support/type-scale";

// 375px checks from the 2026-11-15 other-pages audit, route-mocked, synthetic
// values only (261115-oax). A fixed overlay is 375 wide and, with the floating
// dock replacing the icon rail below 561px (261115-s37), `main` leaves cards
// about 325px, so these assert on geometry: nothing crosses its card, amounts
// stay on one line, inputs stay readable.

test.use({ viewport: { width: 375, height: 812 }, contextOptions: { reducedMotion: "reduce" } });

test.beforeEach(async ({ page }) => {
  // Registered first = lowest priority: nothing reaches a backend through the proxy.
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "not mocked" } }));
  await watchCsp(page);
});
test.afterEach(async ({ page }) => {
  expect(await cspViolations(page)).toEqual([]);
});

// ---------------------------------------------------------------------------
// Geometry helpers. Each runs in the page and returns plain data.
// ---------------------------------------------------------------------------

type Box = { x: number; y: number; width: number; height: number };

// Strict axis-aligned rectangle intersection (touching edges do not overlap).
function overlaps(a: Box, b: Box) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

// Every descendant element and non-blank text node whose box leaves the root's
// border box. Skips zero-size boxes, .sr-only, and anything inside a descendant
// that clips horizontally (it cannot paint past its clipper; the clipper itself
// is still checked).
function crossings(loc: Locator): Promise<string[]> {
  return loc.evaluate((root) => {
    const box = root.getBoundingClientRect();
    const out: string[] = [];
    const clipped = (el: Element | null) => {
      for (; el && el !== root; el = el.parentElement) {
        if (getComputedStyle(el).overflowX !== "visible") return true;
      }
      return false;
    };
    const check = (name: string, r: DOMRect) => {
      if (r.width === 0 && r.height === 0) return;
      if (r.left < box.left - 0.5 || r.right > box.right + 0.5)
        out.push(`${name} [${Math.round(r.left)}, ${Math.round(r.right)}] vs card [${Math.round(box.left)}, ${Math.round(box.right)}]`);
    };
    for (const el of Array.from(root.querySelectorAll("*"))) {
      if (el.closest(".sr-only")) continue;
      if (clipped(el.parentElement)) continue;
      check(`${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 30)}"`, el.getBoundingClientRect());
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = (n.textContent ?? "").trim();
      const p = n.parentElement;
      if (!text || !p || p.closest(".sr-only") || clipped(p)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      check(`#text "${text.slice(0, 30)}"`, range.getBoundingClientRect());
    }
    return out;
  });
}

// Distinct rounded line tops of an element's contents (Range technique from cashflow-dashboard.spec.ts).
function lineCount(loc: Locator): Promise<number> {
  return loc.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return new Set(Array.from(range.getClientRects()).filter((r) => r.width > 0).map((r) => Math.round(r.top))).size;
  });
}

// Digit-bearing text nodes that wrap onto more than one line.
function digitTextOneLine(loc: Locator): Promise<string[]> {
  return loc.evaluate((root) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.textContent ?? "";
      if (!/\d/.test(text)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      const tops = new Set(Array.from(range.getClientRects()).filter((r) => r.width > 0).map((r) => Math.round(r.top)));
      if (tops.size > 1) out.push(text.trim());
    }
    return out;
  });
}

// Boxes of every rendered (non-zero) direct child of each matching element.
function childBoxes(loc: Locator): Promise<{ row: number; i: number; box: Box }[]> {
  return loc.evaluateAll((rows) =>
    rows.flatMap((row, r) =>
      Array.from(row.children).flatMap((c, i) => {
        const b = c.getBoundingClientRect();
        return b.width > 0 && b.height > 0 ? [{ row: r, i, box: { x: b.x, y: b.y, width: b.width, height: b.height } }] : [];
      }),
    ),
  );
}

async function noCellOverlap(loc: Locator) {
  const cells = await childBoxes(loc);
  const clashes: string[] = [];
  for (const a of cells)
    for (const b of cells)
      if (a.row === b.row && a.i < b.i && overlaps(a.box, b.box)) clashes.push(`row ${a.row}: child ${a.i + 1} overlaps child ${b.i + 1}`);
  expect(clashes).toEqual([]);
}

// ---------------------------------------------------------------------------
// Mocks (Task 3 and Task 6 reuse these).
// ---------------------------------------------------------------------------

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function mockPlatform(page: Page) {
  const idr = {
    id: 21,
    ticker: "ZZIDR",
    currency: "IDR",
    asset_type: "idx_stock",
    quantity: 12345, // pii-ok synthetic
    avg_cost: 8765, // pii-ok synthetic
    current_price: 9876, // pii-ok synthetic
    current_value: 1234567890, // pii-ok synthetic
    unrealized_pnl: 123456789, // pii-ok synthetic
    realized_pnl: -12345678, // pii-ok synthetic
    platform_id: 7,
    coingecko_id: null,
    price_source: "manual",
    price_fetched_at: "2026-01-02T00:00:00Z",
    is_stale: false,
  };
  const coin = {
    ...idr,
    id: 22,
    ticker: "ZZCOIN",
    currency: "USD",
    asset_type: "crypto",
    quantity: 12345.12345678, // pii-ok synthetic
    avg_cost: 397000, // pii-ok synthetic
    current_price: 397234, // pii-ok synthetic
    current_value: 1234567890, // pii-ok synthetic
    unrealized_pnl: 123456789, // pii-ok synthetic
    usd_avg_cost: 0.024074644, // pii-ok synthetic
    usd_current_price: 0.024074645, // pii-ok synthetic
    usd_current_value: 74822.24, // pii-ok synthetic
    usd_unrealized_pnl: 7482.22, // pii-ok synthetic
    usd_rate: 16500, // pii-ok synthetic
    usd_rate_date: "2026-01-02",
  };
  await page.route("**/api/platforms/*/detail", (r) =>
    r.fulfill(
      json({
        platform_id: 7,
        platform_name: "ZZ Exchange",
        kind: "crypto app",
        subtotal: 1234567890, // pii-ok synthetic
        closed_realized_pnl: 0,
        holdings: [idr, coin],
      }),
    ),
  );
  await page.route("**/api/portfolio-events*", (r) =>
    r.fulfill(
      json([
        {
          id: 501,
          date: "2026-07-20T10:00:00Z",
          ticker: "ZZCOIN",
          event_type: "buy",
          quantity: 12345.12345678, // pii-ok synthetic
          price: 0.024074644, // pii-ok synthetic
          transaction_id: null,
          cash_amount: null,
          currency: "USD",
          fee: 0.12345678, // pii-ok synthetic
          fee_kind: "coin",
        },
        {
          id: 502,
          date: "2026-06-15T10:00:00Z",
          ticker: "ZZCOIN",
          event_type: "sell",
          quantity: 1234.5, // pii-ok synthetic
          price: 0.024074644, // pii-ok synthetic
          transaction_id: null,
          cash_amount: null,
          currency: "USD",
        },
      ]),
    ),
  );
  await page.route("**/api/platforms", (r) => r.fulfill(json([{ id: 7, name: "ZZ Exchange", kind: "crypto app" }])));
}

// ===========================================================================
// P1 — platform page
// ===========================================================================

test.describe("P1 platform page (261115-oax)", () => {
  test("P1: rows stack inside the card, stats share one box, desktop keeps the table", async ({ page }) => {
    await mockPlatform(page);
    await page.goto("/investments/7");
    await expect(page.getByText("Subtotal", { exact: true })).toBeVisible();

    // Stats: one box no taller than 200px, nothing crossing, each value one line.
    const stats = page.getByText("Subtotal", { exact: true }).locator("../..");
    expect((await stats.boundingBox())!.height).toBeLessThanOrEqual(200);
    expect(await crossings(stats)).toEqual([]);
    for (const v of await stats.locator("> div > :last-child").all()) expect(await lineCount(v)).toBe(1);

    // PnL tab.
    const card = page.locator(".plat-table");
    expect(await crossings(card)).toEqual([]);
    await noCellOverlap(page.locator(".plat-row"));
    expect(await digitTextOneLine(card)).toEqual([]);

    // Buy & Sell tab.
    await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();
    await expect(page.getByText(/^fee /)).toHaveCount(1);
    expect(await crossings(card)).toEqual([]);
    await noCellOverlap(page.locator(".plat-ev"));
    expect(await digitTextOneLine(card)).toEqual([]);
    for (const b of await page.getByRole("button", { name: /^Event options/ }).all()) {
      const bb = (await b.boundingBox())!;
      const cb = (await card.boundingBox())!;
      expect(bb.x).toBeGreaterThanOrEqual(cb.x);
      expect(bb.x + bb.width).toBeLessThanOrEqual(cb.x + cb.width + 0.5);
    }

    // Desktop keeps the 7-column table; the stacked sub-line stays hidden.
    await page.getByRole("button", { name: "PnL", exact: true }).click();
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.getByText("Avg cost", { exact: true })).toBeVisible();
    for (const s of await page.locator(".plat-sub").all()) await expect(s).toBeHidden();
  });
});

// ===========================================================================
// P2 — Records
// ===========================================================================

const DAY = "2026-11-10T12:00:00Z";
const tx = (o: Record<string, unknown>) => ({
  date: DAY,
  category: null,
  merchant: null,
  notes: null,
  is_transfer: false,
  transfer_pair_id: null,
  ...o,
});

async function mockRecords(page: Page) {
  const get = (body: unknown) => (route: import("@playwright/test").Route) =>
    route.request().method() === "GET" ? route.fulfill(json(body)) : route.fallback();
  await page.route(
    "**/api/accounts",
    get([
      { id: 1, name: "ZZ Bank", type: "liquid", currency: "IDR" },
      { id: 2, name: "ZZ Dollar", type: "liquid", currency: "USD" },
    ]),
  );
  await page.route("**/api/categories", get([{ id: 1, name: "ZZ Groceries", is_system: false, children: [] }]));
  await page.route(
    "**/api/transactions?*",
    get([
      tx({ id: 101, amount: -1234567890, category: "ZZ Groceries", merchant: "ZZ Grocery Market", account_id: 1 }), // pii-ok synthetic
      // degraded transfer leg: its sibling is absent
      tx({ id: 103, amount: -5000, category: "ZZ Adjustment", account_id: 1, is_transfer: true, transfer_pair_id: 999 }), // pii-ok synthetic
      // cross-currency pair: USD leg out, IDR leg in
      tx({
        id: 601, amount: -1234.56, currency: "USD", category: "Transfer", account_id: 2, is_transfer: true, // pii-ok synthetic
        transfer_pair_id: 888, amount_idr: -20370000, fx_rate: 16500, fx_rate_date: "2026-11-09", // pii-ok synthetic
      }),
      tx({ id: 602, amount: 20370000, category: "Transfer", account_id: 1, is_transfer: true, transfer_pair_id: 888 }), // pii-ok synthetic
    ]),
  );
}

test.describe("P2 records (261115-oax)", () => {
  test("P2: rows, filters and padding fit at 375", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();

    const card = page.locator("section:not(.tab-in)").filter({ has: page.getByPlaceholder("Search merchant or notes…") });
    expect(await card.evaluate((el) => getComputedStyle(el).paddingLeft)).toBe("18px");
    expect(await crossings(card)).toEqual([]);

    // Rows: the one `div` that directly holds the checkbox cell.
    const rows = card.locator("div:has(> span > input[type=checkbox])");
    await expect(rows).toHaveCount(3);
    for (const row of await rows.all()) {
      const meta = row.locator("> span").nth(2).locator("> span").last();
      const amount = row.locator("> div").first();
      expect((await meta.boundingBox())!.width).toBeGreaterThanOrEqual(150);
      expect(await digitTextOneLine(amount)).toEqual([]);
      if ((await amount.locator("> span").count()) === 0) {
        expect(await lineCount(meta)).toBeLessThanOrEqual(2);
        expect(await lineCount(amount)).toBe(1);
      }
    }

    // Filters.
    for (const s of await card.locator("select").all()) expect((await s.boundingBox())!.width).toBeGreaterThanOrEqual(150);
    const min = (await card.getByPlaceholder("Min amount").boundingBox())!;
    const max = (await card.getByPlaceholder("Max amount").boundingBox())!;
    expect(Math.round(min.y)).toBe(Math.round(max.y));
    const cb = (await card.boundingBox())!;
    expect(max.x + max.width).toBeLessThanOrEqual(cb.x + cb.width);
  });
});

// ===========================================================================
// P3 — modals
// ===========================================================================

// The investments page with one worst-case crypto row (8-dp quantity, 9-digit
// USD price) next to an IDR row. Task 6 reuses it.
async function mockInvestments(page: Page) {
  const base = {
    id: 21,
    ticker: "ZZIDR",
    currency: "IDR",
    asset_type: "idx_stock",
    quantity: 12345, // pii-ok synthetic
    avg_cost: 8765, // pii-ok synthetic
    current_price: 9876, // pii-ok synthetic
    current_value: 1234567890, // pii-ok synthetic
    unrealized_pnl: 123456789, // pii-ok synthetic
    realized_pnl: -12345678, // pii-ok synthetic
    platform_id: 7,
    coingecko_id: null,
    price_source: "manual",
    price_fetched_at: "2026-01-02T00:00:00Z",
    is_stale: false,
  };
  const coin = {
    ...base,
    id: 22,
    ticker: "ZZCOIN",
    currency: "USD",
    asset_type: "crypto",
    quantity: 12345.12345678, // pii-ok synthetic
    avg_cost: 397000, // pii-ok synthetic
    current_price: 397234, // pii-ok synthetic
    current_value: 1234567890, // pii-ok synthetic
    unrealized_pnl: 123456789, // pii-ok synthetic
    usd_avg_cost: 0.024074644, // pii-ok synthetic
    usd_current_price: 0.024074645, // pii-ok synthetic
    usd_current_value: 74822.24, // pii-ok synthetic
    usd_unrealized_pnl: 7482.22, // pii-ok synthetic
    usd_rate: 16500, // pii-ok synthetic
    usd_rate_date: "2026-01-02",
  };
  await page.route("**/api/investments/summary**", (r) =>
    r.fulfill(
      json({
        groups: [{ platform_id: 7, platform_name: "ZZ Exchange", kind: "crypto app", subtotal: 2469135780, holdings: [base, coin] }], // pii-ok synthetic
        asset_type_groups: [
          { asset_type: "idx_stock", total_value: 1234567890 }, // pii-ok synthetic
          { asset_type: "crypto", total_value: 1234567890 }, // pii-ok synthetic
        ],
        total_value: 2469135780, // pii-ok synthetic
        total_unrealized_pnl: 246913578, // pii-ok synthetic
        total_realized_pnl: -24691356, // pii-ok synthetic
        as_of: "2026-01-02",
      }),
    ),
  );
  await page.route("**/api/investments/history**", (r) => r.fulfill(json({ points: [] })));
  await page.route("**/api/platforms", (r) => r.fulfill(json([{ id: 7, name: "ZZ Exchange", kind: "crypto app" }])));
  await page.route("**/api/closed-positions**", (r) => r.fulfill(json([])));
}

// Text-like inputs narrower than 120px, as "name: width" so a failure names them.
function narrowInputs(dialog: Locator): Promise<string[]> {
  return dialog.evaluate((root) =>
    Array.from(root.querySelectorAll<HTMLElement>("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea"))
      .filter((el) => el.getBoundingClientRect().width > 0)
      .filter((el) => el.getBoundingClientRect().width < 120)
      .map((el) => `${el.id || el.getAttribute("placeholder") || el.tagName}: ${Math.round(el.getBoundingClientRect().width)}`),
  );
}

// Every currency chip sits on the same rounded top as the input before it. Returns the chip count.
async function chipsShareTop(dialog: Locator): Promise<number> {
  const chips = await dialog.locator("input + [aria-label*=urrency]").all();
  for (const chip of chips) {
    const input = chip.locator("xpath=preceding-sibling::input[1]");
    expect(Math.round((await chip.boundingBox())!.y)).toBe(Math.round((await input.boundingBox())!.y));
  }
  return chips.length;
}

async function dialogFits(dialog: Locator, expectChips: boolean) {
  await expect(dialog).toBeVisible();
  expect(await narrowInputs(dialog)).toEqual([]);
  expect(await crossings(dialog)).toEqual([]);
  const chips = await chipsShareTop(dialog);
  if (expectChips) expect(chips).toBeGreaterThan(0);
}

test.describe("P3 modals (261115-oax)", () => {
  test("P3: Add transaction (Expense and cross-currency Transfer) fits at 375", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await page.getByRole("button", { name: "+ Add record", exact: true }).click();
    const dialog = page.getByRole("heading", { name: "Add transaction" }).locator("..");
    await dialogFits(dialog, true);

    await page.getByRole("button", { name: "Transfer", exact: true }).click();
    await page.getByLabel("From account", { exact: true }).selectOption({ label: "ZZ Dollar" });
    await page.getByLabel("To account", { exact: true }).selectOption({ label: "ZZ Bank" });
    await expect(page.getByLabel("Amount received (IDR)", { exact: true })).toBeVisible();
    await dialogFits(dialog, true);
  });

  test("P3: Log event (HoldingModal) fits at 375", async ({ page }) => {
    await mockPlatform(page);
    await page.route("**/api/accounts", (r) => r.fulfill(json([{ id: 1, name: "ZZ Bank", type: "liquid", currency: "IDR" }])));
    await page.goto("/investments/7");
    await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();
    await page.getByRole("button", { name: "+ Log event", exact: true }).click();
    // Picking a funding account shows the cash-amount row and the currency chips.
    await page.locator('label:text-is("Investment liquid account") + select').selectOption({ label: "ZZ Bank" });
    await dialogFits(page.getByRole("heading", { name: "Log event" }).locator(".."), true);
  });

  test("P3: Add holding directly (HoldingOverrideModal) fits at 375", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    await page.getByRole("button", { name: "Holdings options", exact: true }).click();
    await page.getByRole("menuitem", { name: "Add holding directly", exact: true }).click();
    await dialogFits(page.getByRole("heading", { name: "Add holding directly" }).locator(".."), false);
  });

  test("P3: an Inbox proposal card fits at 375", async ({ page }) => {
    await mockInbox(page, {
      list: [
        proposal({
          id: ids.a,
          payload: {
            operation: "add_transaction",
            rows: [txRow({ after: { amount: "-1234567890.00", merchant: "ZZ Merchant With A Long Name" } })], // pii-ok synthetic
          },
        }),
        transferProposal({ id: ids.b }),
      ],
    });
    await page.clock.setFixedTime(NOW);
    await page.goto("/inbox");
    const cards = page.getByRole("article");
    await expect(cards).toHaveCount(2);
    for (const card of await cards.all()) expect(await crossings(card)).toEqual([]);
  });
});

// The Settings page's API: categories with a system parent, one account, one platform, LLM settings.
async function mockSettings(page: Page) {
  const cat = (id: number, name: string, o: Record<string, unknown> = {}) => ({
    id, name, parent_id: null, kind: "expense", color: null, effective_color: null,
    icon: null, is_system: false, tx_count: 3, children: [], ...o,
  });
  const get = (body: unknown) => (route: import("@playwright/test").Route) =>
    route.request().method() === "GET" ? route.fulfill(json(body)) : route.fallback();
  await page.route(
    "**/api/categories",
    get([
      cat(1, "ZZ Adjustment", { is_system: true, tx_count: 12, children: [cat(3, "ZZ Child", { parent_id: 1 })] }),
      cat(2, "ZZ Groceries"),
    ]),
  );
  await page.route(
    "**/api/cashflow/summary**",
    get({ accounts: [{ id: 1, name: "ZZ Bank", type: "liquid", currency: "IDR", current_balance: 1234567890 }] }), // pii-ok synthetic
  );
  await page.route("**/api/platforms", get([{ id: 7, name: "ZZ Exchange", kind: "crypto app" }]));
  await page.route(
    "**/api/settings",
    get({
      llm_provider: "ollama", llm_model: "zz-model", anthropic_api_key_masked: "", openai_api_key_masked: "",
      base_currency: "IDR", price_data_source: "coingecko",
    }),
  );
}

// ===========================================================================
// P4 — Settings
// ===========================================================================

test.describe("P4 settings (261115-oax)", () => {
  test("P4: nothing in Settings crosses its card", async ({ page }) => {
    await mockSettings(page);
    await page.goto("/settings");
    const row = page.locator(".cat-row").filter({ hasText: "ZZ Adjustment" }).first();
    await expect(row).toBeVisible();

    // Every bordered card on the page.
    const cards = page.locator(".tab-in > *");
    let checked = 0;
    for (const c of await cards.all()) {
      if ((await c.evaluate((el) => getComputedStyle(el).borderTopWidth)) === "0px") continue;
      checked++;
      expect(await crossings(c)).toEqual([]);
    }
    expect(checked).toBeGreaterThan(3);

    // Provider control: "openai" is inside its card.
    const openai = (await page.getByRole("button", { name: "openai", exact: true }).boundingBox())!;
    const providerCard = (await page.getByText("LLM Provider & Model", { exact: true }).locator("..").boundingBox())!;
    expect(openai.x + openai.width).toBeLessThanOrEqual(providerCard.x + providerCard.width);

    // System row: the menu button sits on the name's line, the note below it.
    const name = (await row.getByText("ZZ Adjustment", { exact: true }).boundingBox())!;
    const menu = (await row.getByRole("button", { name: /^Category options/ }).boundingBox())!;
    const note = (await row.getByText("System category — can't be deleted.").boundingBox())!;
    const menuMid = menu.y + menu.height / 2;
    expect(menuMid).toBeGreaterThan(name.y);
    expect(menuMid).toBeLessThan(name.y + name.height);
    expect(note.y).toBeGreaterThanOrEqual(name.y + name.height);

    // The expand arrow is 13px (--fs-xs on phones).
    expect(await row.locator("span[role=button]").evaluate((el) => getComputedStyle(el).fontSize)).toBe("13px");
  });
});

// ===========================================================================
// P5 — chat composer
// ===========================================================================

test.describe("P5 chat (261115-oax)", () => {
  test("P5: the composer text box has room at 375", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Ask monai a question" });
    await expect(box).toBeVisible();
    const b = (await box.boundingBox())!;
    expect(b.width).toBeGreaterThanOrEqual(200);
    for (const name of ["Attach a file", "Ask"]) {
      const btn = page.getByRole("button", { name, exact: true });
      const r = (await btn.boundingBox())!;
      expect(r.y).toBeGreaterThanOrEqual(b.y + b.height);
      expect(r.x).toBeGreaterThanOrEqual(b.x);
      expect(r.x + r.width).toBeLessThanOrEqual(b.x + b.width + 0.5);
      expect(r.height).toBeGreaterThanOrEqual(40);
    }
  });
});

// ===========================================================================
// P6 — Investments cards
// ===========================================================================

test.describe("P6 investments (261115-oax)", () => {
  test("P6: Investments cards are tight and nothing crosses at 375", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    const holdings = page.locator('section[aria-labelledby="holdings-title"]');
    const alloc = page.locator('section[aria-labelledby="allocation-title"]');
    await expect(holdings.getByText("ZZCOIN").first()).toBeAttached();
    for (const card of [holdings, alloc]) {
      expect(await card.evaluate((el) => getComputedStyle(el).paddingLeft)).toBe("18px");
      expect(await crossings(card)).toEqual([]);
    }
    const total = alloc.getByText("Total", { exact: true });
    expect(await total.evaluate((el) => getComputedStyle(el).fontSize)).toBe("13px"); // --fs-xs on phones (261116-s7w)
  });
});

// ===========================================================================
// D1 — floating phone dock (261115-s37)
// ===========================================================================

test.describe("D1 phone dock (261115-s37)", () => {
  const dockOf = (page: Page) => page.getByRole("navigation", { name: "Main" });
  const ACTIVE_BG = "rgb(242, 239, 232)";
  const bg = (loc: Locator) => loc.evaluate((el) => getComputedStyle(el).backgroundColor);

  test("D1: dock geometry, sidebar hidden", async ({ page }) => {
    await page.goto("/cashflow");
    const dock = dockOf(page);
    await expect(dock).toBeVisible();
    await expect(page.locator(".app-sidebar")).toBeHidden();
    const items = [...(await dock.getByRole("link").all()), dock.getByRole("button", { name: "More" })];
    expect(items).toHaveLength(6);
    for (const it of items) {
      const b = (await it.boundingBox())!;
      expect(b.width).toBeGreaterThanOrEqual(44);
      expect(b.height).toBeGreaterThanOrEqual(44);
    }
    const d = (await dock.boundingBox())!;
    expect(Math.abs(d.x + d.width / 2 - 187.5)).toBeLessThanOrEqual(1);
    expect(Math.abs(d.y + d.height - 792)).toBeLessThanOrEqual(1);
  });

  test("D1: the active route is the light circle", async ({ page }) => {
    await page.goto("/cashflow");
    const dock = dockOf(page);
    const names = ["Cashflow", "Records", "Inbox", "Chat", "Investments"];
    for (const name of names) {
      await dock.getByRole("link", { name }).click();
      await expect(page).toHaveURL(new RegExp(`/${name.toLowerCase()}$`));
      const on = dock.getByRole("link", { name });
      await expect(on).toHaveAttribute("aria-current", "page");
      expect(await bg(on)).toBe(ACTIVE_BG);
      await expect(dock.locator("[aria-current]")).toHaveCount(1);
    }
    await dock.getByRole("button", { name: "More" }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(dock.locator("[aria-current]")).toHaveCount(0);
    expect(await bg(dock.getByRole("button", { name: "More" }))).toBe(ACTIVE_BG);
  });

  test("D1: the Inbox link keeps its label and badge", async ({ page }) => {
    await mockInbox(page, { counts: 3 });
    await page.goto("/cashflow");
    const link = dockOf(page).getByRole("link", { name: "Inbox, 3 pending" });
    await expect(link).toBeVisible();
    await expect(link.locator(".dock-badge")).toBeVisible();
    await expect(link.locator(".dock-badge")).toHaveText("3");
  });

  test("D1: the More menu opens, closes and works from the keyboard", async ({ page }) => {
    await page.goto("/cashflow");
    const dock = dockOf(page);
    const more = dock.getByRole("button", { name: "More" });
    const settings = page.getByRole("menuitem", { name: "Settings" });
    await expect(more).toHaveAttribute("aria-haspopup", "menu");
    await expect(more).toHaveAttribute("aria-expanded", "false");

    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("menu")).toBeVisible();
    await expect(settings).toBeFocused();
    const m = (await page.getByRole("menu").boundingBox())!;
    expect(m.y + m.height).toBeLessThanOrEqual((await dock.boundingBox())!.y);

    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await expect(more).toBeFocused();

    await more.click();
    await expect(page.getByRole("menu")).toBeVisible();
    await page.getByRole("heading", { name: "Cashflow", level: 1 }).click();
    await expect(page.getByRole("menu")).toHaveCount(0);

    await more.focus();
    await page.keyboard.press("Enter");
    await expect(settings).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/settings$/);
  });

  test("D1: at 1280 the sidebar is unchanged and the dock is hidden", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/cashflow");
    await expect(dockOf(page)).toBeHidden();
    const side = page.locator(".app-sidebar");
    await expect(side).toBeVisible();
    // CSS width is 236; the box adds 2x18 padding and a 1px border (content-box).
    expect(await side.evaluate((el) => getComputedStyle(el).width)).toBe("236px");
    await expect(page.getByRole("button", { name: "Collapse sidebar" })).toBeVisible();
    await expect(page.getByText("Local-first")).toBeVisible();
    const texts = (await page.locator(".app-sidebar nav a").allTextContents()).map((t) => t.trim());
    expect(texts).toEqual(["Cashflow", "Records", "Inbox", "Chat", "Investments", "Settings"]);
  });
});

// ===========================================================================
// D2 — pages and the Chat composer clear the dock (261115-s37)
// ===========================================================================

test.describe("D2 dock clearance (261115-s37)", () => {
  const dockTop = async (page: Page) =>
    (await page.getByRole("navigation", { name: "Main" }).boundingBox())!.y;
  const toBottom = (page: Page) => page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  // Bottom edge of the last rendered element child of the page root.
  const lastCardBottom = (page: Page) =>
    page.locator("main .tab-in").first().evaluate((root) => {
      const kids = Array.from(root.children).filter((el) => {
        const r = el.getBoundingClientRect();
        return getComputedStyle(el).display !== "none" && r.height > 0;
      });
      return kids[kids.length - 1].getBoundingClientRect().bottom;
    });

  test("D2: the last card on Records ends above the dock", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    await toBottom(page);
    const gap = (await dockTop(page)) - (await lastCardBottom(page));
    console.log(`D2 records gap to dock top: ${gap}`);
    expect(gap).toBeGreaterThanOrEqual(0);
  });

  test("D2: the last card on Investments ends above the dock", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    await expect(page.getByText("ZZCOIN").first()).toBeAttached();
    await toBottom(page);
    const gap = (await dockTop(page)) - (await lastCardBottom(page));
    console.log(`D2 investments gap to dock top: ${gap}`);
    expect(gap).toBeGreaterThanOrEqual(0);
  });

  test("D2: Chat's Ask button sits above the dock, pinned and at the end", async ({ page }) => {
    const TID = "00000000-0000-4000-8000-0000000000d2";
    const filler = "ZZ synthetic filler sentence that pads the message out so the thread is long enough to scroll. ";
    const messages = Array.from({ length: 16 }, (_, i) => ({
      id: `00000000-0000-4000-8000-0000000001${String(i).padStart(2, "0")}`,
      seq: i + 1,
      role: i % 2 === 0 ? "user" : "assistant",
      content: `ZZ synthetic ${i % 2 === 0 ? "question" : "answer"} ${i + 1}. ${filler.repeat(3)}`,
      status: "complete",
      created_at: new Date().toISOString(),
      parts: { steps: [], proposals: [] },
    }));
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (r) => r.fulfill({ json: [] }));
    await page.route(new RegExp(`/api/threads/${TID}$`), (r) =>
      r.fulfill({
        json: { id: TID, title: "ZZ synthetic chat", updated_at: new Date().toISOString(), active_run: null, messages, attachments: [] },
      }),
    );
    await page.goto(`/chat?thread=${TID}`);
    const box = page.getByRole("textbox", { name: "Ask monai a question" });
    const ask = page.getByRole("button", { name: "Ask", exact: true });
    await expect(page.getByText("ZZ synthetic question 1.")).toBeVisible();
    const check = async (where: string) => {
      const top = await dockTop(page);
      const askGap = top - (await ask.boundingBox())!.y - (await ask.boundingBox())!.height;
      const boxGap = top - (await box.boundingBox())!.y - (await box.boundingBox())!.height;
      console.log(`D2 chat ${where}: ask gap ${askGap}, textbox gap ${boxGap}`);
      expect(askGap).toBeGreaterThanOrEqual(0);
      expect(boxGap).toBeGreaterThanOrEqual(0);
    };
    await toBottom(page);
    await check("end");
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(812);
    await page.evaluate(() => window.scrollTo(0, 0));
    await check("pinned");
  });

  test("D2: the Add record modal covers the dock", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await page.getByRole("button", { name: "+ Add record", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Add transaction" })).toBeVisible();
    const d = (await page.getByRole("navigation", { name: "Main" }).boundingBox())!;
    const covered = await page.evaluate(
      ([x, y]) => !document.elementFromPoint(x, y)!.closest(".app-dock"),
      [d.x + d.width / 2, d.y + d.height / 2],
    );
    expect(covered).toBe(true);
  });

  test("D2: a RowMenu that overlaps the dock paints above it", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    // .fade-in (0.3s on the list) is a stacking context while it runs; let it end.
    await page.waitForFunction(() => document.getAnimations().length === 0);
    await toBottom(page);
    // At the end of the page the last row sits above the dock, so scroll back until
    // its button is just over the dock; the menu then opens down across it.
    const opts = page.getByRole("button", { name: /^Record options: / }).last();
    await page.evaluate((dy) => window.scrollBy(0, dy), (await opts.boundingBox())!.y - ((await dockTop(page)) - 30));
    await opts.click();
    const menu = page.locator("[role=menu]");
    await expect(menu).toBeVisible();
    const m = (await menu.boundingBox())!;
    const d = (await page.getByRole("navigation", { name: "Main" }).boundingBox())!;
    expect(overlaps(m, d)).toBe(true);
    const x = Math.max(m.x, d.x) + (Math.min(m.x + m.width, d.x + d.width) - Math.max(m.x, d.x)) / 2;
    const y = Math.max(m.y, d.y) + (Math.min(m.y + m.height, d.y + d.height) - Math.max(m.y, d.y)) / 2;
    expect(await page.evaluate(([px, py]) => !!document.elementFromPoint(px, py)!.closest("[role=menu]"), [x, y])).toBe(true);
  });
});

// ===========================================================================
// S0 — desktop unchanged (261116-s7w)
// ===========================================================================

// Captured at HEAD (f372f33) before any ui/app edit: the 1280 type histogram of
// `main` and the desktop spot values for each page. The phone type scale is
// phone-only, so these must stay green through every task.
const S0: Record<string, { hist: Record<string, number>; spot: DesktopSpot } | undefined> = {
  investments: { hist: {"12px": 30, "13px": 9, "14px": 15, "16px": 3, "17px": 1, "40px": 1, "52px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": {"pad": "22px 24px", "radius": "18px", "mb": "0px"}, "pillH": 32} }, // pii-ok synthetic
  platform: { hist: {"12px": 16, "13px": 3, "14px": 16, "28px": 3, "40px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": null, "pillH": null} }, // pii-ok synthetic
  records: { hist: {"12px": 8, "13px": 5, "14px": 12, "16px": 3, "40px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": {"pad": "22px 24px", "radius": "18px", "mb": "18px"}, "pillH": null} }, // pii-ok synthetic
  inbox: { hist: {"12px": 19, "14px": 17, "20px": 2, "40px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": {"pad": "22px 24px", "radius": "18px", "mb": "0px"}, "pillH": null} }, // pii-ok synthetic
  chat: { hist: {"12px": 7, "14px": 11, "15px": 2, "40px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": null, "pillH": null} }, // pii-ok synthetic
  settings: { hist: {"11px": 1, "12px": 16, "13px": 9, "13.3333px": 1, "14px": 27, "15px": 6, "16px": 4, "40px": 1}, spot: {"framePad": "28px", "panelRadius": "22px", "panelBorder": "1px", "card": {"pad": "22px 24px", "radius": "18px", "mb": "18px"}, "pillH": null} }, // pii-ok synthetic
};

async function expectDesktopUnchanged(page: Page, key: string) {
  await expect(page.locator(".bone")).toHaveCount(0);
  const got = { hist: await sizeHistogram(page.locator("main")), spot: await desktopSpot(page) };
  const want = S0[key];
  if (!want) console.log(`S0CAPTURE ${key} ${JSON.stringify(got)}`);
  expect(got).toEqual(want);
}

async function mockChatEmpty(page: Page) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
}

test.describe("S0 desktop unchanged (261116-s7w)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  test("S0: /investments", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    await expect(page.locator('section[aria-labelledby="holdings-title"]').getByText("ZZCOIN").first()).toBeAttached();
    await expectDesktopUnchanged(page, "investments");
  });

  test("S0: /investments/7", async ({ page }) => {
    await mockPlatform(page);
    await page.goto("/investments/7");
    await expect(page.getByText("Subtotal", { exact: true })).toBeVisible();
    await expectDesktopUnchanged(page, "platform");
  });

  test("S0: /records", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    await expectDesktopUnchanged(page, "records");
  });

  test("S0: /inbox", async ({ page }) => {
    await mockInbox(page, {
      list: [
        proposal({
          id: ids.a,
          payload: { operation: "add_transaction", rows: [txRow({ after: { amount: "-1234567890.00", merchant: "ZZ Merchant With A Long Name" } })] }, // pii-ok synthetic
        }),
        transferProposal({ id: ids.b }),
      ],
    });
    await page.clock.setFixedTime(NOW);
    await page.goto("/inbox");
    await expect(page.getByRole("article")).toHaveCount(2);
    await expectDesktopUnchanged(page, "inbox");
  });

  test("S0: /chat", async ({ page }) => {
    await mockChatEmpty(page);
    await page.goto("/chat");
    await expect(page.getByRole("textbox", { name: "Ask monai a question" })).toBeVisible();
    await expectDesktopUnchanged(page, "chat");
  });

  test("S0: /settings", async ({ page }) => {
    await mockSettings(page);
    await page.goto("/settings");
    await expect(page.locator(".cat-row").filter({ hasText: "ZZ Adjustment" }).first()).toBeVisible();
    await expectDesktopUnchanged(page, "settings");
  });
});

// ===========================================================================
// S1 — phone type scale (261116-s7w); shared checks. Each later task adds its page here.
// ===========================================================================

test.describe("S1 phone type scale (261116-s7w)", () => {
  test("S1: shell, Records filters and cards, Investments pills", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();

    // Full-bleed frame: no inset, and the panel has no border, radius or shadow.
    expect(await page.locator(".app-frame").evaluate((el) => getComputedStyle(el).padding)).toBe("0px");
    const panel = await page.locator(".app-panel").evaluate((el) => {
      const cs = getComputedStyle(el);
      return { border: cs.borderTopWidth, radius: cs.borderRadius, shadow: cs.boxShadow };
    });
    expect(panel).toEqual({ border: "0px", radius: "0px", shadow: "none" });

    // iOS must not rescale text.
    expect(
      await page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement) as CSSStyleDeclaration & { webkitTextSizeAdjust?: string };
        return cs.webkitTextSizeAdjust || cs.getPropertyValue("text-size-adjust");
      }),
    ).toBe("100%");

    // Records: every filter control is 16px (iOS does not zoom on focus); card is 18px / 16px.
    const filters = page.locator(".rec-filters");
    const sizes = await filters.locator("input:not([type=checkbox]), select").evaluateAll((els) => els.map((e) => getComputedStyle(e).fontSize));
    expect(sizes.length).toBeGreaterThan(3);
    expect(sizes.filter((px) => px !== "16px")).toEqual([]);
    const card = page.locator("section:not(.tab-in)").filter({ has: page.getByPlaceholder("Search merchant or notes…") });
    expect(await card.evaluate((el) => ({ pad: getComputedStyle(el).paddingLeft, radius: getComputedStyle(el).borderRadius }))).toEqual({
      pad: "18px",
      radius: "16px",
    });

    // Investments: every Pills button is at least 36px tall with 14px text.
    await mockInvestments(page);
    await page.goto("/investments");
    await expect(page.locator('section[aria-labelledby="holdings-title"]').getByText("ZZCOIN").first()).toBeAttached();
    const pills = await page.locator('[role="group"] button[aria-pressed]').evaluateAll((els) =>
      els.map((e) => ({ h: e.getBoundingClientRect().height, fs: getComputedStyle(e).fontSize })),
    );
    expect(pills.length).toBeGreaterThan(0);
    for (const p of pills) {
      expect(p.h).toBeGreaterThanOrEqual(36);
      expect(p.fs).toBe("14px");
    }
  });

  test("S1: Investments phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockInvestments(page);
    await page.goto("/investments");
    const holdings = page.locator('section[aria-labelledby="holdings-title"]');
    await expect(holdings.getByText("ZZCOIN").first()).toBeAttached();
    await expect(page.locator(".bone")).toHaveCount(0);
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    const hero = page.locator('section[aria-label="Portfolio value"] .roll').first();
    expect(await px(hero)).toBe(38);
    const fit = await hero.evaluate((roll) => {
      const tops = new Set(Array.from(roll.querySelectorAll(".roll-digit, .roll-char"), (d) => Math.round(d.getBoundingClientRect().top)));
      const card = roll.closest("section")!;
      const cs = getComputedStyle(card);
      const right = card.getBoundingClientRect().right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
      return { lines: tops.size, over: roll.getBoundingClientRect().right - right };
    });
    expect(fit.lines).toBe(1);
    expect(fit.over).toBeLessThanOrEqual(0.5);
    expect(await px(page.locator("#holdings-title"))).toBe(16);
    expect(await px(page.locator("#allocation-title"))).toBe(16);
    expect(await px(holdings.getByText("ZZCOIN", { exact: true }))).toBeGreaterThanOrEqual(15);
  });

  test("S1: platform page phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockPlatform(page);
    await page.goto("/investments/7");
    await expect(page.getByText("Subtotal", { exact: true })).toBeVisible();
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    expect(await px(page.locator(".plat-row").getByText("ZZCOIN", { exact: true }))).toBeGreaterThanOrEqual(15);
  });

  test("S1: Investments dialogs phone type scale (261116-s7w)", async ({ page }) => {
    await mockPlatform(page);
    await page.route("**/api/accounts", (r) => r.fulfill(json([{ id: 1, name: "ZZ Bank", type: "liquid", currency: "IDR" }])));
    await page.goto("/investments/7");
    await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();
    await page.getByRole("button", { name: "+ Log event", exact: true }).click();
    await page.locator('label:text-is("Investment liquid account") + select').selectOption({ label: "ZZ Bank" });
    const dialog = page.getByRole("heading", { name: "Log event" }).locator("..");
    await expect(dialog).toBeVisible();
    const controls = await dialog
      .locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")
      .evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width > 0).map((e) => getComputedStyle(e).fontSize));
    expect(controls.length).toBeGreaterThan(2);
    expect(controls.filter((s) => s !== "16px")).toEqual([]);
    expect(await smallText(dialog, 13)).toEqual([]);
    // Buttons are body text (--fs-body, 15px on phones).
    expect(await dialog.getByRole("button", { name: "Cancel", exact: true }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(15);
    for (const b of await dialog.locator("button[aria-pressed]").all()) expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(36);
  });

  test("S1: Records phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    await expect(page.locator(".bone")).toHaveCount(0);
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    const card = page.locator("section:not(.tab-in)").filter({ has: page.getByPlaceholder("Search merchant or notes…") });
    expect(await px(card.getByText("ZZ Grocery Market", { exact: true }))).toBeGreaterThanOrEqual(15);
    // Amount cells hold the digits; the meta line may wrap to two lines by design (P2 caps it).
    for (const amt of await card.locator(".rec-amt").all()) expect(await digitTextOneLine(amt)).toEqual([]);
    expect(await crossings(card)).toEqual([]);
  });

  test("S1: Add record dialog phone type scale (261116-s7w)", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await page.getByRole("button", { name: "+ Add record", exact: true }).click();
    const dialog = page.getByRole("heading", { name: "Add transaction" }).locator("..");
    await dialogFits(dialog, true);
    const controls = await dialog
      .locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")
      .evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width > 0).map((e) => getComputedStyle(e).fontSize));
    expect(controls.length).toBeGreaterThan(2);
    expect(controls.filter((s) => s !== "16px")).toEqual([]);
    expect(await smallText(dialog, 13)).toEqual([]);
    for (const name of ["Expense", "Income", "Transfer"]) {
      const b = dialog.getByRole("button", { name, exact: true });
      expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(36);
      expect(await b.evaluate((el) => getComputedStyle(el).fontSize)).toBe("14px");
    }
  });

  test("S1: Inbox phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockInbox(page, {
      list: [
        proposal({
          id: ids.a,
          payload: { operation: "add_transaction", rows: [txRow({ after: { amount: "-1234567890.00", merchant: "ZZ Merchant With A Long Name" } })] }, // pii-ok synthetic
        }),
        transferProposal({ id: ids.b }),
      ],
    });
    await page.clock.setFixedTime(NOW);
    await page.goto("/inbox");
    const cards = page.getByRole("article");
    await expect(cards).toHaveCount(2);
    await expect(page.locator(".bone")).toHaveCount(0);
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    expect(await px(cards.first().getByText("ZZ Merchant With A Long Name").first())).toBeGreaterThanOrEqual(15);
    for (const card of await cards.all()) {
      const controls = await card
        .locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")
        .evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width > 0).map((e) => getComputedStyle(e).fontSize));
      expect(controls.filter((s) => s !== "16px")).toEqual([]);
      expect(await crossings(card)).toEqual([]);
    }
  });

  test("S1: Settings phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockSettings(page);
    await page.goto("/settings");
    await expect(page.locator(".cat-row").filter({ hasText: "ZZ Adjustment" }).first()).toBeVisible();
    await expect(page.locator(".bone")).toHaveCount(0);
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    expect(await px(page.getByText("LLM Provider & Model", { exact: true }))).toBe(16);
    const seg = page.locator(".seg-fill button");
    expect(await seg.count()).toBeGreaterThan(1);
    for (const b of await seg.all()) {
      expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(36);
      expect(await b.evaluate((el) => getComputedStyle(el).fontSize)).toBe("14px");
    }
    const controls = await main
      .locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")
      .evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().width > 0).map((e) => getComputedStyle(e).fontSize));
    expect(controls.length).toBeGreaterThan(2);
    expect(controls.filter((s) => s !== "16px")).toEqual([]);
  });

  test("S1: Chat phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Ask monai a question" });
    await expect(box).toBeVisible();
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(main.locator("h1"))).toBe(24);
    expect(await px(box)).toBe(16);
    expect((await box.boundingBox())!.width).toBeGreaterThanOrEqual(200);
    for (const name of ["Attach a file", "Ask"]) {
      expect((await page.getByRole("button", { name, exact: true }).boundingBox())!.height).toBeGreaterThanOrEqual(40);
    }
  });

  test("S1: Chat thread phone type scale (261116-s7w)", async ({ page }) => {
    const px = (loc: Locator) => loc.first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    const TID = "00000000-0000-4000-8000-0000000000e1";
    const messages = [
      { role: "user", content: "ZZ synthetic question 1." },
      { role: "assistant", content: "ZZ synthetic answer 2 with a short body." },
    ].map((m, i) => ({
      id: `00000000-0000-4000-8000-0000000002${String(i).padStart(2, "0")}`,
      seq: i + 1,
      ...m,
      status: "complete",
      created_at: new Date().toISOString(),
      parts: { steps: [], proposals: [] },
    }));
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (r) => r.fulfill({ json: [] }));
    await page.route(new RegExp(`/api/threads/${TID}$`), (r) =>
      r.fulfill({
        json: { id: TID, title: "ZZ synthetic chat", updated_at: new Date().toISOString(), active_run: null, messages, attachments: [] },
      }),
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("ZZ synthetic question 1.")).toBeVisible();
    const main = page.locator("main");
    expect(await smallText(main, 13)).toEqual([]);
    expect(await px(page.getByText("ZZ synthetic answer 2 with a short body."))).toBeGreaterThanOrEqual(15);
  });
});

// ===========================================================================
// Uniform phone pills: on a touch phone every toggle is 36px visible inside
// an equal-height track, and still takes taps 4px above its edge (44px area).
// ===========================================================================

test.describe("Uniform phone pills", () => {
  test.use({ isMobile: true, hasTouch: true });

  const measure = (page: Page) =>
    page.locator(".pill-btn").evaluateAll((els) =>
      els.map((e) => {
        e.scrollIntoView({ block: "center" });
        const b = e.getBoundingClientRect();
        const hit = document.elementFromPoint(b.left + b.width / 2, b.top - 3);
        return {
          h: Math.round(b.height),
          track: Math.round(e.parentElement!.getBoundingClientRect().height),
          fs: getComputedStyle(e).fontSize,
          tap: hit === e,
        };
      }),
    );

  test("Investments and Settings pills share one size", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    await expect(page.locator('section[aria-labelledby="holdings-title"]').getByText("ZZCOIN").first()).toBeAttached();
    const inv = await measure(page);

    await mockSettings(page);
    await page.goto("/settings");
    await expect(page.locator(".cat-row").first()).toBeVisible();
    const set = await measure(page);

    expect(inv.length).toBeGreaterThan(1);
    expect(set.length).toBe(3);
    for (const p of [...inv, ...set]) expect(p).toEqual({ h: 36, track: 44, fs: "14px", tap: true });
  });
});

// ===========================================================================
// antislop audit 001 fixes (261120-r0k). Pass conditions from
// anti-slop/audit-001-2026-11-20.md: text >= 4.5:1 (3:1 at 24px+ or 18.66px
// bold) on the colour it sits on, focus ring >= 3:1 on the ink cards.
// ===========================================================================

// Every visible text node in `main` below its WCAG AA minimum, as readable lines.
const lowContrast = (page: Page) =>
  page.evaluate(() => {
    const parse = (c: string) => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    type C = { r: number; g: number; b: number; a: number };
    const lum = ({ r, g, b }: C) => {
      const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const blend = (fg: C, bg: C): C => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
    });
    const bgOf = (el: Element) => {
      const stack: C[] = [];
      for (let e: Element | null = el; e; e = e.parentElement) {
        const c = parse(getComputedStyle(e).backgroundColor);
        if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; }
      }
      return stack.reverse().reduce((base, c) => blend(c, base), { r: 255, g: 255, b: 255, a: 1 } as C);
    };
    const out: string[] = [];
    for (const el of document.querySelectorAll("main *")) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (!r.width || !r.height || cs.visibility === "hidden" || el.closest('[aria-hidden="true"]')) continue;
      if ((el as HTMLButtonElement).disabled || el.closest(":disabled")) continue; // WCAG exempts inactive controls
      if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim())) continue;
      const fg = parse(cs.color);
      if (!fg) continue;
      const bg = bgOf(el);
      const a = lum(blend(fg, bg)), b = lum(bg);
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const fs = parseFloat(cs.fontSize);
      const need = fs >= 24 || (fs >= 18.66 && +cs.fontWeight >= 700) ? 3 : 4.5;
      if (ratio < need) out.push(`${ratio.toFixed(2)} "${el.textContent!.trim().slice(0, 24)}" ${cs.color}`);
    }
    return out;
  });

test.describe("antislop 001 (261120-r0k)", () => {
  test("T1: Records, Settings and platform text meets AA contrast", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    expect(await lowContrast(page)).toEqual([]);

    await mockSettings(page);
    await page.goto("/settings");
    await expect(page.locator(".cat-row").first()).toBeVisible();
    expect(await lowContrast(page)).toEqual([]);

    await mockPlatform(page);
    await page.goto("/investments/7");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await lowContrast(page)).toEqual([]);
  });

  test("T1: focus ring is at least 3:1 on the dark hero card", async ({ page }) => {
    await mockInvestments(page);
    await page.goto("/investments");
    const pill = page.locator(".hero-pills .pill-btn").first();
    await expect(pill).toBeVisible();
    const ratio = await pill.evaluate((el) => {
      (el as HTMLElement).focus({ focusVisible: true } as FocusOptions);
      const m = getComputedStyle(el).outlineColor.match(/\d+/g)!.map(Number);
      const lum = (r: number, g: number, b: number) =>
        [r, g, b].map((v) => ((v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)))
          .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
      const a = lum(m[0], m[1], m[2]), b = lum(0x23, 0x20, 0x1b);
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    });
    expect(ratio).toBeGreaterThanOrEqual(3);
  });
});
