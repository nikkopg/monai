import { test, expect, type Page } from "@playwright/test";

import {
  couponPreview,
  fmtDayMonth,
  fmtDayMonthYear,
  rateChip,
  termsBody,
  termsFromInfo,
  termsValid,
  type BondTermsInput,
} from "../app/lib/bond";

// ---------------------------------------------------------------------------
// Quick 261117-rw1 (SBN bonds), T6: the bond fields on the buy form and the holding
// override modal. Route-mocked, synthetic data only (series ZZBOND, accounts
// Bank Synth / Bank Other / Bank Two). Pure logic first, then the browser.
// ---------------------------------------------------------------------------

const terms = (over: Partial<BondTermsInput> = {}): BondTermsInput => ({
  rate: "6.25",
  floating: false,
  payDay: "15",
  maturity: "2029-11-15",
  taxPct: "10",
  couponAccountId: "11",
  ...over,
});

test.describe("bond logic (261117-rw1)", () => {
  test("couponPreview matches the backend vectors", () => {
    expect(couponPreview(12_000_000, 6, 10)).toEqual({ gross: 60000, tax: 6000, net: 54000 });
    expect(couponPreview(25_000_000, 6.25, 10)).toEqual({ gross: 130208, tax: 13021, net: 117187 });
    expect(couponPreview(1_000_032, 6.25, 10)).toEqual({ gross: 5209, tax: 521, net: 4688 });
    expect(couponPreview(1_000_000, 6.45, 15)).toEqual({ gross: 5375, tax: 806, net: 4569 });
  });

  test("couponPreview is null for out-of-range input", () => {
    expect(couponPreview(0, 6, 10)).toBeNull();
    expect(couponPreview(-5, 6, 10)).toBeNull();
    expect(couponPreview(NaN, 6, 10)).toBeNull();
    expect(couponPreview(1_000_000, 0, 10)).toBeNull();
    expect(couponPreview(1_000_000, 100, 10)).toBeNull();
    expect(couponPreview(1_000_000, 6, -1)).toBeNull();
    expect(couponPreview(1_000_000, 6, 100)).toBeNull();
    expect(couponPreview(1_000_000, 6, 0)).toEqual({ gross: 5000, tax: 0, net: 5000 });
  });

  test("termsValid rejects bad terms", () => {
    expect(termsValid(terms())).toBe(true);
    expect(termsValid(terms({ payDay: "0" }))).toBe(false);
    expect(termsValid(terms({ payDay: "29" }))).toBe(false);
    expect(termsValid(terms({ payDay: "1.5" }))).toBe(false);
    expect(termsValid(terms({ rate: "6.255" }))).toBe(false);
    expect(termsValid(terms({ rate: "0" }))).toBe(false);
    expect(termsValid(terms({ rate: "100" }))).toBe(false);
    expect(termsValid(terms({ rate: "" }))).toBe(false);
    expect(termsValid(terms({ taxPct: "100" }))).toBe(false);
    expect(termsValid(terms({ taxPct: "0" }))).toBe(true);
    expect(termsValid(terms({ maturity: "" }))).toBe(false);
    expect(termsValid(terms({ couponAccountId: "" }))).toBe(false);
  });

  test("termsBody maps strings to the API object", () => {
    expect(termsBody(terms({ floating: true }))).toEqual({
      rate: 6.25,
      floating: true,
      pay_day: 15,
      maturity_date: "2029-11-15",
      tax_pct: 10,
      coupon_account_id: 11,
    });
  });

  test("termsFromInfo prefills a saved bond and tolerates a missing one", () => {
    expect(
      termsFromInfo({
        rate: 6,
        floating: true,
        pay_day: 10,
        maturity_date: "2028-03-10",
        tax_pct: 10,
        coupon_account_id: 13,
        coupon_account_name: "Bank Two",
        gross: null,
        tax: null,
        net: null,
        next_coupon_date: null,
        upcoming: [],
      })
    ).toEqual({ rate: "6", floating: true, payDay: "10", maturity: "2028-03-10", taxPct: "10", couponAccountId: "13" });
    expect(termsFromInfo(null).rate).toBe("");
  });

  test("chip and date text", () => {
    expect(rateChip(6, false)).toBe("6.00% fixed");
    expect(rateChip(6.25, true)).toBe("6.25% floating");
    expect(fmtDayMonth("2026-12-15")).toBe("15 Dec");
    expect(fmtDayMonthYear("2029-11-15")).toBe("15 Nov 2029");
  });
});

// ---------------------------------------------------------------------------
// Browser
// ---------------------------------------------------------------------------

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const ACCOUNTS = [
  { id: 11, name: "Bank Synth", type: "liquid", currency: "IDR" },
  { id: 12, name: "Bank Other", type: "liquid", currency: "USD" },
  { id: 13, name: "Bank Two", type: "liquid", currency: "IDR" },
  { id: 14, name: "Broker Synth", type: "investment", currency: "IDR" },
];

test.use({ timezoneId: "Asia/Jakarta" });

test.beforeEach(async ({ page }) => {
  // Registered first = lowest priority: nothing reaches a backend through the proxy.
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "not mocked" } }));
  await page.route("**/api/accounts", (r) => r.fulfill(json(ACCOUNTS)));
});

async function openBuyForm(page: Page, onBuy?: (b: Record<string, unknown>) => void) {
  await page.route("**/api/platforms", (r) => r.fulfill(json([{ id: 5, name: "Synth Broker", kind: "bond app" }])));
  await page.route("**/api/platforms/*/detail", (r) =>
    r.fulfill(json({ platform_id: 5, platform_name: "Synth Broker", kind: "bond app", subtotal: 0, holdings: [] })),
  );
  await page.route("**/api/portfolio-events*", (r) => r.fulfill(json([])));
  await page.route("**/api/portfolio-events/funded-buy", async (r) => {
    onBuy?.(r.request().postDataJSON());
    await r.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ transaction_id: 1, portfolio_event_id: 2 }) });
  });
  await page.goto("/investments/5");
  await expect(page.getByRole("heading", { name: "Synth Broker" })).toBeVisible();
  await page.getByRole("button", { name: "Buy & Sell", exact: true }).click();
  await page.getByRole("button", { name: "+ Log event", exact: true }).click();
  await page.locator('label:text-is("Asset type") + select').selectOption({ label: "Bond (SBN)" });
}

const fundingSelect = (page: Page) => page.locator('label:text-is("Investment liquid account") + select');
const nominalInput = (page: Page) => page.locator('label:text-is("Nominal (IDR)") + input');
const preview = (page: Page) => page.getByTestId("bond-preview");

test.describe("bond buy form (261117-rw1)", () => {
  test("bond mode relabels, hides price and fee, and offers only IDR liquid accounts", async ({ page }) => {
    await openBuyForm(page);
    await fundingSelect(page).selectOption({ label: "Bank Synth" });

    await expect(page.locator('label:text-is("Series")')).toBeVisible();
    await expect(page.locator('label:text-is("Ticker")')).toHaveCount(0);
    await expect(nominalInput(page)).toBeVisible();
    await expect(page.locator('label:text-is("Quantity")')).toHaveCount(0);
    await expect(page.locator("#holding-price")).toHaveCount(0);
    await expect(page.locator("#holding-fee")).toHaveCount(0);
    await expect(page.getByLabel("Position currency")).toHaveCount(0);

    await expect(fundingSelect(page).locator("option")).toHaveText(["Choose an account", "Bank Synth", "Bank Two"]);
    await expect(page.getByLabel("Coupons go to")).toHaveValue("11");
    await expect(page.getByLabel("Tax %", { exact: true })).toHaveValue("10");

    // Another asset type brings the normal form back.
    await page.locator('label:text-is("Asset type") + select').selectOption({ label: "Crypto" });
    await expect(page.locator("#holding-price")).toBeVisible();
    await expect(page.getByTestId("bond-preview")).toHaveCount(0);
  });

  test("the preview updates live and Floating shows the reset note", async ({ page }) => {
    await openBuyForm(page);
    await nominalInput(page).fill("12000000");
    await page.getByLabel("Rate % p.a.").fill("6.00");
    await expect(preview(page)).toContainText("Gross / month60,000");
    await expect(preview(page)).toContainText("Tax 10%−6,000");
    await expect(preview(page)).toContainText("You receive / month54,000");

    await nominalInput(page).fill("25000000");
    await page.getByLabel("Rate % p.a.").fill("6.25");
    await expect(preview(page)).toContainText("Gross / month130,208");
    await expect(preview(page)).toContainText("Tax 10%−13,021");
    await expect(preview(page)).toContainText("You receive / month117,187");

    const note = page.getByText("Edit the rate when it resets; coupons after that use the new rate.");
    await expect(note).toHaveCount(0);
    await page.getByRole("button", { name: "Floating", exact: true }).click();
    await expect(note).toBeVisible();

    await page.getByLabel("Rate % p.a.").fill("");
    await expect(preview(page)).toContainText("You receive / month—");
  });

  test("submit waits for valid terms, then posts a face-value funded buy with the bond object", async ({ page }) => {
    const posted: Record<string, unknown>[] = [];
    await openBuyForm(page, (b) => posted.push(b));
    const submit = page.getByRole("button", { name: "Log funded Buy", exact: true });

    await page.getByPlaceholder("ORI099").fill("ZZBOND");
    await fundingSelect(page).selectOption({ label: "Bank Synth" });
    await nominalInput(page).fill("25000000");
    await expect(submit).toBeDisabled();

    await page.getByLabel("Rate % p.a.").fill("6.25");
    await page.getByLabel("Pay day").fill("15");
    await page.getByLabel("Maturity").fill("2029-11-15");
    await expect(submit).toBeEnabled();

    await page.getByLabel("Pay day").fill("29");
    await expect(submit).toBeDisabled();
    await page.getByLabel("Pay day").fill("15");

    await submit.click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({
      source_account_name: "Bank Synth",
      platform_id: 5,
      ticker: "ZZBOND",
      quantity: 25000000,
      price: 1,
      cash_amount: 25000000,
      event_currency: "IDR",
      asset_type: "bond",
      bond: {
        rate: 6.25,
        floating: false,
        pay_day: 15,
        maturity_date: "2029-11-15",
        tax_pct: 10,
        coupon_account_id: 11,
      },
    });
    expect(posted[0]).not.toHaveProperty("fee");
    expect(posted[0]).not.toHaveProperty("fee_kind");
    expect(posted[0]).not.toHaveProperty("cash_currency");
  });

  test("picking another coupon account changes coupon_account_id, and it stops following the funding account", async ({ page }) => {
    const posted: Record<string, unknown>[] = [];
    await openBuyForm(page, (b) => posted.push(b));
    await page.getByPlaceholder("ORI099").fill("ZZBOND");
    await fundingSelect(page).selectOption({ label: "Bank Synth" });
    await nominalInput(page).fill("12000000");
    await page.getByLabel("Rate % p.a.").fill("6");
    await page.getByLabel("Pay day").fill("10");
    await page.getByLabel("Maturity").fill("2028-03-10");
    await page.getByRole("button", { name: "Floating", exact: true }).click();

    await page.getByLabel("Coupons go to").selectOption({ label: "Bank Two" });
    await fundingSelect(page).selectOption({ label: "Bank Two" });
    await fundingSelect(page).selectOption({ label: "Bank Synth" });
    await expect(page.getByLabel("Coupons go to")).toHaveValue("13");

    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0].bond).toMatchObject({ floating: true, pay_day: 10, coupon_account_id: 13 });
  });

  test("a non-bond funded buy is unchanged: no bond key, price and fee still sent", async ({ page }) => {
    const posted: Record<string, unknown>[] = [];
    await openBuyForm(page, (b) => posted.push(b));
    await page.locator('label:text-is("Asset type") + select').selectOption({ label: "Crypto" });
    await fundingSelect(page).selectOption({ label: "Bank Synth" });
    await page.getByPlaceholder("BBCA").fill("ZZCOIN");
    await page.locator('label:text-is("Quantity") + input').fill("2");
    await page.locator("#holding-price").fill("30000");
    await page.getByRole("button", { name: "Log funded Buy", exact: true }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ ticker: "ZZCOIN", quantity: 2, price: 30000, asset_type: "crypto" });
    expect(posted[0]).not.toHaveProperty("bond");
  });
});

// ---------------------------------------------------------------------------
// Holding override modal
// ---------------------------------------------------------------------------

const bondRow = {
  id: 31,
  ticker: "ZZBOND",
  currency: "IDR",
  asset_type: "bond",
  quantity: 12000000,
  avg_cost: 1,
  current_price: 1,
  current_value: 12000000,
  unrealized_pnl: 0,
  realized_pnl: 0,
  platform_id: 1,
  coingecko_id: null,
  price_source: "face",
  price_fetched_at: null,
  is_stale: false,
  bond: {
    rate: 6,
    floating: false,
    pay_day: 15,
    maturity_date: "2029-11-15",
    tax_pct: 10,
    coupon_account_id: 11,
    coupon_account_name: "Bank Synth",
    gross: 60000,
    tax: 6000,
    net: 54000,
    next_coupon_date: "2026-12-15",
    upcoming: ["2026-12-15", "2027-01-15", "2027-02-15"],
  },
};

async function mockInvestmentsWithBond(page: Page, onPut?: (b: Record<string, unknown>) => void) {
  await page.route("**/api/investments/summary**", (r) =>
    r.fulfill(
      json({
        groups: [{ platform_id: 1, platform_name: "Synth Broker", kind: "bond app", subtotal: 12000000, holdings: [bondRow] }],
        asset_type_groups: [{ asset_type: "bond", total_value: 12000000 }],
        total_value: 12000000,
        total_unrealized_pnl: 0,
        total_realized_pnl: 0,
        as_of: "2026-01-02",
      }),
    ),
  );
  await page.route("**/api/investments/history**", (r) => r.fulfill(json({ points: [] })));
  await page.route("**/api/platforms", (r) => r.fulfill(json([{ id: 1, name: "Synth Broker", kind: "bond app" }])));
  await page.route("**/api/closed-positions**", (r) => r.fulfill(json([])));
  await page.route("**/api/holdings/31", async (r) => {
    onPut?.(r.request().postDataJSON());
    await r.fulfill(json({ id: 31 }));
  });
}

async function openEditBond(page: Page) {
  await page.goto("/investments");
  await page.getByRole("button", { name: "Holding options: ZZBOND", exact: true }).click();
  await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Save holding" })).toBeVisible();
}

test.describe("bond override modal (261117-rw1)", () => {
  test("a new Bond (SBN) holding shows Nominal, avg cost 1 and the bond fields", async ({ page }) => {
    await mockInvestmentsWithBond(page);
    await page.goto("/investments");
    await page.getByRole("button", { name: "Holdings options", exact: true }).click();
    await page.getByRole("menuitem", { name: "Add holding directly", exact: true }).click();
    await page.locator('label:text-is("Asset type") + select').selectOption({ label: "Bond (SBN)" });

    await expect(page.locator('label:text-is("Nominal (IDR)")')).toBeVisible();
    await expect(page.locator('label:text-is("Avg cost (IDR)") + input')).toHaveValue("1");
    await expect(page.getByLabel("Rate % p.a.")).toBeVisible();
    await expect(page.getByLabel("Coupons go to").locator("option")).toHaveText(["Choose an account", "Bank Synth", "Bank Two"]);
    await expect(page.getByRole("button", { name: "Add holding directly", exact: true })).toBeDisabled();
  });

  test("editing a bond prefills from holding.bond and PUTs the full new terms", async ({ page }) => {
    const put: Record<string, unknown>[] = [];
    await mockInvestmentsWithBond(page, (b) => put.push(b));
    await openEditBond(page);

    await expect(page.getByLabel("Rate % p.a.")).toHaveValue("6");
    await expect(page.getByLabel("Pay day")).toHaveValue("15");
    await expect(page.getByLabel("Maturity")).toHaveValue("2029-11-15");
    await expect(page.getByLabel("Coupons go to")).toHaveValue("11");
    await expect(page.getByRole("button", { name: "Fixed", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(preview(page)).toContainText("You receive / month54,000");

    await page.getByLabel("Rate % p.a.").fill("6.25");
    await page.getByRole("button", { name: "Floating", exact: true }).click();
    await page.getByRole("button", { name: "Save holding", exact: true }).click();

    await expect.poll(() => put.length).toBe(1);
    expect(put[0]).toMatchObject({
      ticker: "ZZBOND",
      asset_type: "bond",
      quantity: 12000000,
      bond: {
        rate: 6.25,
        floating: true,
        pay_day: 15,
        maturity_date: "2029-11-15",
        tax_pct: 10,
        coupon_account_id: 11,
      },
    });
  });
});

// ---------------------------------------------------------------------------
// 375px
// ---------------------------------------------------------------------------

test.describe("bond forms at 375 (261115-oax conventions)", () => {
  test.use({ viewport: { width: 375, height: 812 }, contextOptions: { reducedMotion: "reduce" } });

  async function fits(page: Page, heading: string) {
    const dialog = page.getByRole("heading", { name: heading, exact: true }).locator("..");
    await expect(dialog).toBeVisible();
    await expect(page.getByLabel("Rate % p.a.")).toBeVisible();
    const m = await dialog.evaluate((root) => {
      const inputs = Array.from(root.querySelectorAll<HTMLElement>("input:not([type=hidden]), select")).filter(
        (el) => el.getBoundingClientRect().width > 0,
      );
      const grid = root.querySelector<HTMLElement>(".form-grid")!;
      const rootBox = root.getBoundingClientRect();
      return {
        scroll: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        smallFont: inputs.filter((el) => getComputedStyle(el).fontSize !== "16px").map((el) => el.id || el.tagName),
        columns: getComputedStyle(grid).gridTemplateColumns.split(" ").length,
        outside: inputs
          .filter((el) => el.getBoundingClientRect().right > rootBox.right + 0.5)
          .map((el) => el.id || el.tagName),
      };
    });
    expect(m.scroll[0]).toBeLessThanOrEqual(m.scroll[1]);
    expect(m.smallFont).toEqual([]);
    expect(m.columns).toBe(1);
    expect(m.outside).toEqual([]);

    // The card scrolls inside the overlay, so the submit button can be brought on screen.
    const save = dialog.getByRole("button").last();
    await save.scrollIntoViewIfNeeded();
    const box = (await save.boundingBox())!;
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(812);
  }

  test("the Buy modal on a bond fits", async ({ page }) => {
    await openBuyForm(page);
    await fundingSelect(page).selectOption({ label: "Bank Synth" });
    await nominalInput(page).fill("12000000");
    await page.getByLabel("Rate % p.a.").fill("6");
    await page.getByRole("button", { name: "Floating", exact: true }).click();
    await fits(page, "Log event");
  });

  test("the override modal on a bond fits", async ({ page }) => {
    await mockInvestmentsWithBond(page);
    await openEditBond(page);
    await fits(page, "Save holding");
  });
});
