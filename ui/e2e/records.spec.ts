import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 17 Plan 02 — RED e2e spec for the Records ledger (REC-01/02/03/05).
//
// Route-mocked per cashflow-crud.spec.ts / platform-crud.spec.ts convention —
// no live backend. Locks the 17-UI-SPEC.md copy + endpoint contract that
// 17-04 (ui/app/records/page.tsx) must implement to turn these tests GREEN.
// RED now: /records route + page do not exist yet.
// ---------------------------------------------------------------------------

type FixtureTx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  account_id: number | null;
  notes: string | null;
  is_transfer: boolean;
  transfer_pair_id: number | null;
};

const money = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));
const signed = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(n));

function isoAt(daysAgo: number): string {
  const d = new Date();
  d.setUTCHours(10, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString();
}

function weekdayLabel(daysAgo: number): string {
  const d = new Date();
  d.setUTCHours(10, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

function accountsFixture() {
  return [
    { id: 1, name: "Cash" },
    { id: 2, name: "Bank" },
  ];
}

function categoriesFixture() {
  return [
    { id: 1, name: "Food & Drinks", is_system: false, children: [] },
    { id: 2, name: "Transport", is_system: false, children: [] },
    { id: 3, name: "Salary", is_system: false, children: [] },
    { id: 99, name: "Transfer", is_system: true, children: [] },
  ];
}

// Today: 1 normal expense (id 301) + 1 collapsed transfer pair (302/303,
// shared transfer_pair_id 555) — the pair must contribute ZERO to the daily
// net (17-UI-SPEC Component 3's locked rule).
// Yesterday: 1 normal income (304).
// 10 days ago: 1 Adjustment row (305, is_transfer=true but transfer_pair_id
// IS null — so it IS included in the daily net per the locked rule, unlike
// the transfer-pair legs) + 1 normal expense (306).
function transactionsFixture(): FixtureTx[] {
  return [
    {
      id: 301, date: isoAt(0), amount: -25000, category: "Food & Drinks",
      merchant: "Warung Sate", account_id: 1, notes: null,
      is_transfer: false, transfer_pair_id: null,
    },
    {
      id: 302, date: isoAt(0), amount: -100000, category: "Transfer",
      merchant: null, account_id: 1, notes: null,
      is_transfer: true, transfer_pair_id: 555,
    },
    {
      id: 303, date: isoAt(0), amount: 100000, category: "Transfer",
      merchant: null, account_id: 2, notes: null,
      is_transfer: true, transfer_pair_id: 555,
    },
    {
      id: 304, date: isoAt(1), amount: 50000, category: "Salary",
      merchant: "Employer", account_id: 2, notes: null,
      is_transfer: false, transfer_pair_id: null,
    },
    {
      id: 305, date: isoAt(10), amount: 200000, category: "Adjustment",
      merchant: null, account_id: 1, notes: null,
      is_transfer: true, transfer_pair_id: null,
    },
    {
      id: 306, date: isoAt(10), amount: -15000, category: "Transport",
      merchant: "Grab", account_id: 1, notes: null,
      is_transfer: false, transfer_pair_id: null,
    },
  ];
}

async function mockSupportRoutes(page: Page) {
  await page.route("**/api/accounts", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accountsFixture()),
    });
  });
  await page.route("**/api/categories", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(categoriesFixture()),
    });
  });
}

async function mockRecords(page: Page, rows: FixtureTx[] = transactionsFixture()) {
  await mockSupportRoutes(page);
  await page.route("**/api/transactions*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(rows),
    });
  });
}

test.describe("Records ledger — date-grouped, daily net (REC-01)", () => {
  test("day-group headers use the locked labels and the daily net excludes collapsed transfer-pair rows", async ({
    page,
  }) => {
    await mockRecords(page);
    await page.goto("/records");

    await expect(page.getByText("Today", { exact: true })).toBeVisible();
    await expect(page.getByText("Yesterday", { exact: true })).toBeVisible();
    await expect(page.getByText(weekdayLabel(10), { exact: true })).toBeVisible();

    // "Today": the transfer-pair legs (302/303) contribute zero — only the
    // -25000 expense counts.
    await expect(page.getByText(`Net ${signed(-25000)}`, { exact: true })).toBeVisible();
    // "Yesterday": a single +50000 income row.
    await expect(page.getByText(`Net ${signed(50000)}`, { exact: true })).toBeVisible();
    // 10-days-ago: Adjustment row (transfer_pair_id null -> INCLUDED) + a
    // -15000 expense = +185,000.
    await expect(page.getByText(`Net ${signed(185000)}`, { exact: true })).toBeVisible();
  });
});

test.describe("Records filter bar (REC-02)", () => {
  test("renders the locked fields/placeholders/defaults and refetches with the matching query param on change", async ({
    page,
  }) => {
    let lastUrl = "";
    await mockSupportRoutes(page);
    await page.route("**/api/transactions*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      lastUrl = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(transactionsFixture()),
      });
    });

    await page.goto("/records");

    await expect(page.getByPlaceholder("Search merchant or notes…")).toBeVisible();
    // Native <option> elements are never "visible" per Playwright/browser
    // semantics while their parent <select> is closed (regardless of being
    // selected) — assert against the <select> itself via hasText instead of
    // the unrenderable <option> (Rule 3 test-authoring fix, 17-04).
    await expect(page.locator("select").filter({ hasText: "All accounts" })).toBeVisible();
    await expect(page.locator("select").filter({ hasText: "All categories" })).toBeVisible();
    await expect(page.locator("select").filter({ hasText: "All types" })).toBeVisible();
    await expect(page.getByPlaceholder("Min amount")).toBeVisible();
    await expect(page.getByPlaceholder("Max amount")).toBeVisible();
    // Default checked — matches D-01's include_transfers default true.
    await expect(page.getByRole("checkbox", { name: "Show transfers" })).toBeChecked();

    await page.getByPlaceholder("Search merchant or notes…").fill("sate");
    await expect.poll(() => lastUrl).toContain("q=sate");
  });
});

test.describe("Transfer-pair collapse (REC-05, D-07)", () => {
  test("a shared transfer_pair_id renders as ONE collapsed 'Transfer: From → To' row with an unsigned amount", async ({
    page,
  }) => {
    await mockRecords(page);
    await page.goto("/records");

    // Exactly one collapsed row, not two separate legs.
    await expect(page.getByText("Transfer: Cash → Bank", { exact: true })).toHaveCount(1);
    const pairRow = page.locator("div").filter({ hasText: "Transfer: Cash → Bank" }).last();
    await expect(pairRow).toContainText(money(100000));
    // Net-neutral — unsigned, no +/- prefix (17-UI-SPEC Color table).
    await expect(pairRow).not.toContainText(`+${money(100000)}`);
    await expect(pairRow).not.toContainText(`-${money(100000)}`);
  });
});

test.describe("Multi-select + bulk actions (REC-03)", () => {
  test("selecting a row shows the bulk bar; Delete opens ConfirmDialog and POSTs bulk-delete with the selected ids", async ({
    page,
  }) => {
    await mockRecords(page);
    let bulkDeleteBody: { ids?: number[] } | null = null;
    await page.route("**/api/transactions/bulk-delete", async (route) => {
      bulkDeleteBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ deleted: bulkDeleteBody?.ids ?? [], skipped: [] }),
      });
    });

    await page.goto("/records");
    // .last() (not .first()) — the app shell (layout.tsx) wraps every page in
    // its own outer <div>s, which also match `hasText` as ancestors of any
    // row's text; the row itself is the innermost/deepest matching div, i.e.
    // last in document order (Rule 3 test-authoring fix, 17-04).
    const row = page.locator("div", { hasText: "Warung Sate" }).last();
    await row.locator('input[type="checkbox"]').check();

    await expect(page.getByText("1 selected", { exact: true })).toBeVisible();
    // Row-level Edit/Delete actions are <span role="button">; bulk-bar
    // actions are real <button> elements — scope by tag to disambiguate
    // (matches the cashflow-crud.spec.ts idiom).
    await expect(page.locator("button").filter({ hasText: "Recategorize" })).toBeVisible();
    await expect(page.locator("button").filter({ hasText: "Delete" }).first()).toBeVisible();
    await expect(page.getByText("Cancel selection", { exact: true })).toBeVisible();

    await page.locator("button").filter({ hasText: "Delete" }).first().click();
    await expect(
      page.getByText("Delete 1 records? Transfer pairs are deleted together. This can't be undone.")
    ).toBeVisible();
    // Two real <button>s now visible (bulk-bar Delete + dialog confirm) — the
    // confirm is the last one added to the DOM.
    await page.locator("button").filter({ hasText: "Delete" }).last().click();

    await expect.poll(() => bulkDeleteBody?.ids).toEqual([301]);
  });

  test("Recategorize POSTs bulk-recategorize with the selected ids and chosen category", async ({
    page,
  }) => {
    await mockRecords(page);
    let recatBody: { ids?: number[]; category?: string } | null = null;
    await page.route("**/api/transactions/bulk-recategorize", async (route) => {
      recatBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ recategorized: recatBody?.ids ?? [], skipped: [] }),
      });
    });

    await page.goto("/records");
    // .last() (not .first()) — the app shell (layout.tsx) wraps every page in
    // its own outer <div>s, which also match `hasText` as ancestors of any
    // row's text; the row itself is the innermost/deepest matching div, i.e.
    // last in document order (Rule 3 test-authoring fix, 17-04).
    const row = page.locator("div", { hasText: "Warung Sate" }).last();
    await row.locator('input[type="checkbox"]').check();

    const bulkBar = page.locator("div").filter({ hasText: "1 selected" }).last();
    await bulkBar.locator("select").selectOption("Transport");
    await bulkBar.locator("button").filter({ hasText: "Recategorize" }).click();

    await expect.poll(() => recatBody?.category).toBe("Transport");
    await expect.poll(() => recatBody?.ids).toEqual([301]);
  });
});

test.describe('Pagination — "Load 100 more" (REC-01)', () => {
  test("appears when a full 100-row page returns", async ({ page }) => {
    await mockSupportRoutes(page);
    const fullPage: FixtureTx[] = Array.from({ length: 100 }, (_, i) => ({
      id: 2000 + i,
      date: isoAt(0),
      amount: -1000 * (i + 1),
      category: "Food & Drinks",
      merchant: `Merchant ${i}`,
      account_id: 1,
      notes: null,
      is_transfer: false,
      transfer_pair_id: null,
    }));
    await page.route("**/api/transactions*", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(fullPage),
      });
    });

    await page.goto("/records");
    await expect(page.getByRole("button", { name: "Load 100 more" })).toBeVisible();
  });

  test("is hidden when a short page returns", async ({ page }) => {
    await mockRecords(page);
    await page.goto("/records");
    await expect(page.getByRole("button", { name: "Load 100 more" })).toHaveCount(0);
  });
});
