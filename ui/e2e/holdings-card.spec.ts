import { test, expect, type Page } from "@playwright/test";

import {
  GOLDS,
  GREENS,
  NO_RATE_IDR,
  NO_RATE_USD,
  assetLabel,
  categoryRows,
  fmtShort,
  liquidRows,
  mainRows,
  platformRows,
  type AccountBalance,
  type InvestmentGroup,
} from "../app/overview/holdings";

// ---------------------------------------------------------------------------
// The Cashflow page's Holdings card. Part 1 is browserless logic (holdings.ts);
// part 2 drives the card against mocked routes. Synthetic ZZ names and round
// made-up amounts only; the catch-all 404 route keeps every test off the live backend.
// ---------------------------------------------------------------------------

const acct = (o: Partial<AccountBalance> & Pick<AccountBalance, "id" | "name">): AccountBalance => ({
  type: "liquid",
  current_balance: 0,
  period_net: 0,
  ...o,
});

// Like the real API (backend/tools.py), an IDR row carries fx_rate 1.0; the USD
// rate must never be taken from it.
const ZZ_BANK = acct({ id: 1, name: "ZZ Bank", current_balance: 4_000_000, currency: "IDR", fx_rate: 1 }); // pii-ok synthetic
const ZZ_WALLET = acct({
  id: 2,
  name: "ZZ Wallet",
  currency: "USD",
  native_balance: 100,
  current_balance: 1_625_000, // pii-ok synthetic
  fx_rate: 16_250,
  fx_as_of: "2026-10-30",
});
const ZZ_DOLLAR = acct({
  id: 3,
  name: "ZZ Dollar",
  currency: "USD",
  native_balance: 50,
  current_balance: null,
  fx_rate: null,
  fx_as_of: null,
});
const ACCOUNTS = [ZZ_BANK, ZZ_WALLET, ZZ_DOLLAR];
const RATE_TITLE = "1 USD = 16,250 IDR · rate of 30 Oct 2026";

test.describe("holdings logic", () => {
  test("fmtShort", () => {
    expect(fmtShort(10_125_000, "IDR")).toBe("10.1M"); // pii-ok synthetic
    expect(fmtShort(1_200_000_000, "IDR")).toBe("1.2B"); // pii-ok synthetic
    expect(fmtShort(5_300, "USD")).toBe("5.3K USD");
    expect(fmtShort(346.15, "USD")).toBe("346.15 USD");
    expect(fmtShort(850, "IDR")).toBe("850");
    expect(fmtShort(999_950, "IDR")).toBe("1.0M"); // pii-ok synthetic
    expect(fmtShort(null, "IDR")).toBe("–");
    expect(fmtShort(NaN, "USD")).toBe("–");
  });

  test("liquidRows in IDR", () => {
    const { rows, centre } = liquidRows(ACCOUNTS, "IDR", 5_625_000); // pii-ok synthetic
    expect(rows.map((r) => r.name)).toEqual(["ZZ Bank", "ZZ Wallet", "ZZ Dollar"]);
    const [bank, wallet, dollar] = rows;
    expect(bank).toMatchObject({ amount: "4,000,000", sub: undefined, title: undefined, share: "71%" });
    expect(wallet).toMatchObject({ amount: "1,625,000", sub: "100.00 USD", title: RATE_TITLE, share: "29%" });
    expect(dollar).toMatchObject({ amount: "–", title: NO_RATE_IDR, sub: "50.00 USD", share: "–" });
    expect(rows.map((r) => r.color)).toEqual(GREENS.slice(0, 3));
    expect(centre).toBe(5_625_000);
  });

  test("liquidRows in USD", () => {
    const { rows, centre } = liquidRows(ACCOUNTS, "USD", 5_625_000); // pii-ok synthetic
    const [bank, wallet, dollar] = rows;
    expect(bank).toMatchObject({ amount: "246.15 USD", sub: "4,000,000 IDR", title: RATE_TITLE, share: "71%" });
    // A USD account shows its own balance, not 1,625,000 / 16,250.
    expect(wallet).toMatchObject({ amount: "100.00 USD", sub: undefined, share: "29%" });
    expect(dollar).toMatchObject({ amount: "50.00 USD", share: "–" });
    // Only accounts with an IDR value, the donut's set.
    expect(centre).toBeCloseTo(4_000_000 / 16_250 + 100, 6); // pii-ok synthetic
  });

  test("liquidRows in USD with no rate anywhere", () => {
    const { rows, centre } = liquidRows([ZZ_BANK, ZZ_DOLLAR], "USD", 4_000_000); // pii-ok synthetic
    expect(rows[0]).toMatchObject({ name: "ZZ Bank", amount: "–", title: NO_RATE_USD, sub: "4,000,000 IDR" });
    expect(centre).toBeNull();
  });

  test("a negative balance has no slice share and is flagged", () => {
    const owed = acct({ id: 9, name: "ZZ Owed", currency: "IDR", current_balance: -500_000 }); // pii-ok synthetic
    const { rows } = liquidRows([ZZ_BANK, owed], "IDR", 3_500_000); // pii-ok synthetic
    expect(rows[0]).toMatchObject({ name: "ZZ Bank", share: "100%", negative: false });
    expect(rows[1]).toMatchObject({ name: "ZZ Owed", amount: "-500,000", share: "–", negative: true });
  });

  test("a stale USD row keeps its label in both views", () => {
    const stale = { ...ZZ_WALLET, fx_stale: true, fx_as_of: "2026-10-27" };
    for (const ccy of ["IDR", "USD"] as const) {
      expect(liquidRows([stale], ccy, 1_625_000).rows[0].stale).toBe("stale, rate of 27 Oct 2026"); // pii-ok synthetic
    }
  });

  test("mainRows", () => {
    const groups = [{ platform_id: 1 }, { platform_id: 2 }] as unknown as InvestmentGroup[];
    const [liquid, invest] = mainRows({
      liquid_total: 6_000_000, // pii-ok synthetic
      investment_total: 4_000_000, // pii-ok synthetic
      liquid_accounts: ACCOUNTS,
      investment_groups: groups,
    });
    expect(liquid).toMatchObject({
      name: "Liquid", sub: "3 accounts", amount: "6,000,000", drill: "liquid", color: GREENS[0], share: "60%",
    });
    expect(invest).toMatchObject({
      name: "Investment", sub: "2 platforms", amount: "4,000,000", drill: "investment", color: GOLDS[0], share: "40%",
    });
    const one = mainRows({
      liquid_total: 1, investment_total: 0, liquid_accounts: [ZZ_BANK], investment_groups: groups.slice(0, 1),
    });
    expect(one[0].sub).toBe("1 account");
    expect(one[1]).toMatchObject({ sub: "1 platform", share: "–" });
  });

  test("assetLabel", () => {
    expect(["crypto", "idx_stock", "mutual_fund", "gold", "cash"].map(assetLabel)).toEqual([
      "Crypto", "Stocks", "Mutual funds", "Gold", "Cash",
    ]);
    for (const t of ["other", null, undefined, "zz_unknown"]) expect(assetLabel(t)).toBe("Other");
  });

  const holding = (asset_type: string | null, current_value: number | string | null) => ({ asset_type, current_value });
  const GROUPS_LOGIC: InvestmentGroup[] = [
    {
      platform_id: 7, platform_name: "ZZ Broker", kind: "broker",
      subtotal: "3000000", // a JSON string, as Decimals can arrive
      holdings: [holding("idx_stock", 2_000_000), holding("mutual_fund", 1_000_000)], // pii-ok synthetic
    },
    {
      platform_id: 8, platform_name: "ZZ Coins", kind: "crypto",
      subtotal: 1_500_000, // pii-ok synthetic
      holdings: [holding("crypto", 1_000_000), holding("idx_stock", 500_000), holding("crypto", null)], // pii-ok synthetic
    },
  ];

  test("platformRows", () => {
    const [broker, coins] = platformRows(GROUPS_LOGIC);
    expect(broker).toMatchObject({
      name: "ZZ Broker", amount: "3,000,000", sub: "2 categories", href: "/investments/7", share: "67%", color: GOLDS[0],
    });
    // The null-valued holding is not counted as a category.
    expect(coins).toMatchObject({
      name: "ZZ Coins", amount: "1,500,000", sub: "2 categories", href: "/investments/8", share: "33%", color: GOLDS[1],
    });
    const orphan = platformRows([{ ...GROUPS_LOGIC[0], platform_id: null as unknown as number }]);
    expect(orphan[0].href).toBeUndefined();
  });

  test("categoryRows sums asset types across platforms and skips null values", () => {
    const rows = categoryRows(GROUPS_LOGIC);
    expect(rows.map((r) => [r.name, r.amount, r.sub])).toEqual([
      ["Stocks", "2,500,000", "ZZ Broker, ZZ Coins"],
      ["Mutual funds", "1,000,000", "ZZ Broker"], // ties keep first-seen order
      ["Crypto", "1,000,000", "ZZ Coins"],
    ]);
    expect(rows.every((r) => r.href === undefined && r.drill === undefined)).toBe(true);
    expect(categoryRows([{ ...GROUPS_LOGIC[0], holdings: [holding(null, 100)] }])[0].name).toBe("Other");
  });
});

// ---------------------------------------------------------------------------
// The card, against mocked routes.
// ---------------------------------------------------------------------------

const GROUPS = [
  {
    platform_id: 7,
    platform_name: "ZZ Broker",
    kind: "broker",
    subtotal: 3_000_000, // pii-ok synthetic
    holdings: [
      { asset_type: "idx_stock", current_value: 2_000_000 }, // pii-ok synthetic
      { asset_type: "mutual_fund", current_value: 1_000_000 }, // pii-ok synthetic
    ],
  },
  {
    platform_id: 8,
    platform_name: "ZZ Coins",
    kind: "crypto",
    subtotal: 1_500_000, // pii-ok synthetic
    holdings: [
      { asset_type: "crypto", current_value: 1_000_000 }, // pii-ok synthetic
      { asset_type: "idx_stock", current_value: 500_000 },
    ],
  },
];

const SUMMARY = { totals: { income: 0, expense: 0, net: 0 }, by_category: [], accounts: [], trend: [] };
const NET_WORTH = {
  total: 10_125_000, // pii-ok synthetic
  liquid_total: 5_625_000, // pii-ok synthetic
  investment_total: 4_500_000, // pii-ok synthetic
  liquid_accounts: ACCOUNTS,
  investment_groups: GROUPS,
  accounts_covered: 3,
  accounts_total: 3,
};

async function mockAll(page: Page, netWorth: unknown = NET_WORTH) {
  // Registered first, so it has the lowest priority: nothing reaches the live backend.
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { detail: "mocked" } }));
  await page.route("**/api/cashflow/summary**", (route) => route.fulfill({ json: SUMMARY }));
  await page.route("**/api/net-worth", (route) => route.fulfill({ json: netWorth }));
}

const holdings = (page: Page) => page.getByRole("region", { name: "Holdings", exact: true });
// The donut wrapper (recharts' own svg is also role=img, hence the name filter).
const donut = (page: Page) => holdings(page).getByRole("img", { name: /^(Total|Liquid|Investment) / });

// Clicks the ring at `f` (0..1 clockwise from 12 o'clock), mid-way between the radii.
async function clickRing(page: Page, f: number) {
  const box = (await donut(page).boundingBox())!;
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  const a = 2 * Math.PI * f;
  await page.mouse.click(cx + 64 * Math.sin(a), cy - 64 * Math.cos(a));
}

// Midpoint fraction of slice `i` for the given values.
const mid = (values: number[], i: number) => {
  const sum = values.reduce((t, v) => t + v, 0);
  return (values.slice(0, i).reduce((t, v) => t + v, 0) + values[i] / 2) / sum;
};

test.describe("Holdings card", () => {
  test.use({ contextOptions: { reducedMotion: "reduce" } });

  test.beforeEach(async ({ page }) => {
    await mockAll(page);
    await page.goto("/overview");
    await expect(holdings(page)).toBeVisible();
  });

  test("on a wide window the Holdings and Cashflow cards are the same width, and Holdings is never shorter", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const a = (await page.getByRole("region", { name: "Cashflow", exact: true }).boundingBox())!;
    const b = (await holdings(page).boundingBox())!;
    expect(Math.abs(a.width - b.width)).toBeLessThan(1);
    // Equal when Cashflow is taller than the 520px floor (this fixture has no spend rows).
    expect(b.height).toBeGreaterThanOrEqual(a.height - 1);
  });

  test("main view: two rows, a total in the donut centre", async ({ page }) => {
    const card = holdings(page);
    await expect(card.getByRole("img", { name: "Total 10.1M" })).toBeVisible();
    const liquid = card.getByRole("button", { name: /^Liquid/ });
    const invest = card.getByRole("button", { name: /^Investment/ });
    await expect(liquid).toContainText("3 accounts");
    await expect(liquid).toContainText("5,625,000");
    await expect(liquid).toContainText("56%");
    await expect(invest).toContainText("2 platforms");
    await expect(invest).toContainText("4,500,000");
    await expect(invest).toContainText("44%");
    await expect(page.getByText("Liquid accounts", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Investment platforms", { exact: true })).toHaveCount(0);
  });

  test("Liquid row drills in; IDR and USD views; back returns", async ({ page }) => {
    const card = holdings(page);
    await card.getByRole("button", { name: /^Liquid/ }).click();
    await expect(card.getByRole("button", { name: "‹ Holdings" })).toBeVisible();
    await expect(card.getByRole("img", { name: "Liquid 5.6M" })).toBeVisible();
    await expect(card.getByRole("button", { name: "IDR", exact: true })).toHaveAttribute("aria-pressed", "true");

    await expect(card.getByText("1,625,000", { exact: true })).toHaveAttribute("title", RATE_TITLE);
    await expect(card.getByText("100.00 USD", { exact: true })).toBeVisible();
    await expect(card.getByText("–", { exact: true }).first()).toHaveAttribute("title", NO_RATE_IDR);

    await card.getByRole("button", { name: "USD", exact: true }).click();
    await expect(card.getByText("246.15 USD", { exact: true })).toHaveAttribute("title", RATE_TITLE);
    await expect(card.getByText("4,000,000 IDR", { exact: true })).toBeVisible();
    await expect(card.getByText("50.00 USD", { exact: true })).toBeVisible();
    await expect(card.getByRole("img", { name: "Liquid 346.15 USD" })).toBeVisible();

    await card.getByRole("button", { name: "‹ Holdings" }).click();
    await expect(card.getByRole("img", { name: "Total 10.1M" })).toBeVisible();
    // The pill choice survives drilling out and back in.
    await card.getByRole("button", { name: /^Liquid/ }).click();
    await expect(card.getByRole("button", { name: "USD", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("clicking the Liquid slice drills in; the donut hole does not", async ({ page }) => {
    const card = holdings(page);
    const box = (await donut(page).boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(card.getByRole("button", { name: "‹ Holdings" })).toHaveCount(0);

    await clickRing(page, mid([5_625_000, 4_500_000], 0)); // pii-ok synthetic
    await expect(card.getByRole("button", { name: "‹ Holdings" })).toBeVisible();
    await expect(card.getByRole("img", { name: /^Liquid/ })).toBeVisible();
  });

  test("hovering a row fades the other slices", async ({ page }) => {
    const card = holdings(page);
    await card.getByRole("button", { name: /^Liquid/ }).hover();
    const opacities = await card.locator(".recharts-pie-sector path").evaluateAll((els) =>
      els.map((e) => e.getAttribute("fill-opacity"))
    );
    expect(opacities).toEqual(["1", "0.35"]);
  });

  test("Investment drill: Platform rows, Category rows, the centre never changes", async ({ page }) => {
    const card = holdings(page);
    await card.getByRole("button", { name: /^Investment/ }).click();
    await expect(card.getByRole("button", { name: "‹ Holdings" })).toBeVisible();
    await expect(card.getByRole("img", { name: "Investment 4.5M" })).toBeVisible();
    await expect(card.getByRole("button", { name: "Platform", exact: true })).toHaveAttribute("aria-pressed", "true");
    const broker = card.getByRole("link", { name: /ZZ Broker/ });
    await expect(broker).toContainText("3,000,000");
    await expect(broker).toContainText("2 categories");
    await expect(broker).toContainText("67%");
    await expect(card.getByRole("link", { name: /ZZ Coins/ })).toContainText("33%");

    await card.getByRole("button", { name: "Category", exact: true }).click();
    await expect(card.getByRole("img", { name: "Investment 4.5M" })).toBeVisible();
    await expect(card.getByRole("link")).toHaveCount(0);
    for (const t of ["Stocks", "2,500,000", "ZZ Broker, ZZ Coins", "Crypto", "Mutual funds"]) {
      await expect(card.getByText(t, { exact: true }).first()).toBeVisible();
    }
  });

  test("a platform row opens its page", async ({ page }) => {
    const card = holdings(page);
    await card.getByRole("button", { name: /^Investment/ }).click();
    await card.getByRole("link", { name: /ZZ Broker/ }).click();
    await expect(page).toHaveURL(/\/investments\/7$/);
  });

  test("the Investment slice drills in, then a platform slice opens its page", async ({ page }) => {
    const card = holdings(page);
    await clickRing(page, mid([5_625_000, 4_500_000], 1)); // pii-ok synthetic
    await expect(card.getByRole("img", { name: "Investment 4.5M" })).toBeVisible();
    await clickRing(page, mid([3_000_000, 1_500_000], 1)); // pii-ok synthetic
    await expect(page).toHaveURL(/\/investments\/8$/);
  });

  test("Liquid keeps USD and Investment keeps Category across back and forth", async ({ page }) => {
    const card = holdings(page);
    await card.getByRole("button", { name: /^Liquid/ }).click();
    await card.getByRole("button", { name: "USD", exact: true }).click();
    await card.getByRole("button", { name: "‹ Holdings" }).click();
    await card.getByRole("button", { name: /^Investment/ }).click();
    await card.getByRole("button", { name: "Category", exact: true }).click();
    await card.getByRole("button", { name: "‹ Holdings" }).click();

    await card.getByRole("button", { name: /^Liquid/ }).click();
    await expect(card.getByRole("button", { name: "USD", exact: true })).toHaveAttribute("aria-pressed", "true");
    await card.getByRole("button", { name: "‹ Holdings" }).click();
    await card.getByRole("button", { name: /^Investment/ }).click();
    await expect(card.getByRole("button", { name: "Category", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("no platforms: the empty message, and no list", async ({ page }) => {
    await page.unroute("**/api/net-worth");
    await page.route("**/api/net-worth", (route) =>
      route.fulfill({ json: { ...NET_WORTH, investment_total: 0, investment_groups: [] } })
    );
    await page.reload();
    await holdings(page).getByRole("button", { name: /^Investment/ }).click();
    await expect(holdings(page).getByText("No investment platforms yet.")).toBeVisible();
  });
});

// Without reduced motion (and in a visible tab) the donut animates; it must still draw.
test("the donut draws its sectors with animation on", async ({ page }) => {
  await mockAll(page);
  await page.goto("/overview");
  await expect(holdings(page).locator(".recharts-pie-sector")).toHaveCount(2);
});
