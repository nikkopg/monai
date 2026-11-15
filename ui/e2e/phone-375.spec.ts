import { test, expect, type Locator, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";
import { ids, mockInbox, NOW, proposal, transferProposal, txRow } from "./inbox-fixtures";

// 375px checks from the 2026-11-15 other-pages audit, route-mocked, synthetic
// values only (261115-oax). A fixed overlay is 375 wide and `main` leaves cards
// about 238px, so these assert on geometry: nothing crosses its card, amounts
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
      tx({ id: 101, amount: -12345678, category: "ZZ Groceries", merchant: "ZZ Grocery Market", account_id: 1 }), // pii-ok synthetic
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
    expect(await card.evaluate((el) => getComputedStyle(el).paddingLeft)).toBe("16px");
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

// ===========================================================================
// P4 — Settings
// ===========================================================================

test.describe("P4 settings (261115-oax)", () => {
  test("P4: nothing in Settings crosses its card", async ({ page }) => {
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

    // The expand arrow is 12px.
    expect(await row.locator("span[role=button]").evaluate((el) => getComputedStyle(el).fontSize)).toBe("12px");
  });
});
