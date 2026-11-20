import { test, expect, type Page, type Route } from "@playwright/test";

// ---------------------------------------------------------------------------
// Phase 16 Plan 01 (Wave 0) — record-modal.spec.ts (REC-04).
//
// Pins the Expense/Income/Transfer segmented-control contract for
// TransactionModal.tsx BEFORE it is built (Wave 1, Plan 02). Route-mocked,
// no live backend — mirrors cashflow-crud.spec.ts's fixture + route-mock
// idiom and modal-open navigation verbatim. Every scenario asserts a request
// BODY or endpoint, never just a UI toggle, so it is a real RED->GREEN
// signal for Wave 1.
//
// Expected to run RED against today's code (no segmented control, no
// currency field, no Transfer branch, no "Save & add another", no edit-leg
// lock yet) — that is the intended Wave 0 baseline (16-01-PLAN.md).
// ---------------------------------------------------------------------------

// The modal opens from Records ("+ Add record", or a row's options menu →
// Edit); every GET it needs is mocked so nothing reaches a live backend.
// Noon on the local day, so the row lands in "Today" at any hour of the run.
const TODAY = (() => {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
})();

function txFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return [
    {
      id: 101,
      date: TODAY,
      amount: -25000,
      category: "Food & Drinks",
      merchant: "warung sate",
      account_id: 1,
      notes: null,
      is_transfer: false,
      transfer_pair_id: null,
      ...overrides,
    },
  ];
}

async function mockRecords(page: Page, txOverrides: Partial<Record<string, unknown>> = {}) {
  const json = (body: unknown) => (route: Route) =>
    route.request().method() === "GET" ? route.fulfill({ json: body as object }) : route.fallback();
  await page.route("**/api/accounts", json([{ id: 1, name: "Cash" }, { id: 2, name: "Bank" }]));
  await page.route(
    "**/api/categories",
    json([
      { id: 1, name: "Food & Drinks", is_system: false, children: [] },
      { id: 2, name: "Transport", is_system: false, children: [] },
    ])
  );
  await page.route("**/api/transactions?*", json(txFixture(txOverrides)));
}

async function openCreateModal(page: Page) {
  await page.goto("/records");
  await page.getByRole("button", { name: "+ Add record", exact: true }).click();
  await expect(page.getByText("Add transaction").first()).toBeVisible();
}

async function openEditModal(page: Page) {
  await page.goto("/records");
  await page.getByRole("button", { name: /^Record options: warung sate on / }).click();
  await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
  await expect(page.getByText("Edit transaction")).toBeVisible();
}

test.describe("record-modal — Expense/Income segment (REC-04)", () => {
  test("default segment is Expense, options render Expense/Income/Transfer in order", async ({
    page,
  }) => {
    await mockRecords(page);
    await openCreateModal(page);

    const form = page.locator("form").filter({ hasText: "Add transaction" });
    const segmentButtons = form.getByRole("button", {
      name: /^(Expense|Income|Transfer)$/,
    });
    await expect(segmentButtons).toHaveCount(3);
    await expect(segmentButtons.nth(0)).toHaveText("Expense");
    await expect(segmentButtons.nth(1)).toHaveText("Income");
    await expect(segmentButtons.nth(2)).toHaveText("Transfer");
    // Active segment carries fontWeight 600 per UI-SPEC's active-segment style.
    await expect(segmentButtons.nth(0)).toHaveCSS("font-weight", "600");
  });

  test("Expense posts a negative signed amount and no currency", async ({ page }) => {
    await mockRecords(page);
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Expense", exact: true }).click();
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form
      .getByRole("button", { name: "Add transaction", exact: true })
      .click();

    await expect.poll(() => postedBody?.amount).toBe(-25000);
    expect(Object.keys(postedBody ?? {})).not.toContain("currency");
  });

  test("Income posts a positive signed amount", async ({ page }) => {
    await mockRecords(page);
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999, amount: 25000 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByRole("button", { name: "Income", exact: true }).click();
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form
      .getByRole("button", { name: "Add transaction", exact: true })
      .click();

    await expect.poll(() => postedBody?.amount).toBe(25000);
  });

  test("Save & add another keeps the modal open and resets amount/category/notes", async ({
    page,
  }) => {
    await mockRecords(page);
    let postCount = 0;
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        postCount += 1;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], id: 999 }),
        });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.getByLabel("Amount", { exact: true }).fill("25000");
    await form.getByPlaceholder("warung sate").fill("some notes");
    await form
      .getByRole("button", { name: "Save & add another", exact: true })
      .click();

    await expect.poll(() => postCount).toBe(1);
    // Modal heading still visible -> modal did not close.
    await expect(page.getByText("Add transaction").first()).toBeVisible();
    await expect(form.getByLabel("Amount", { exact: true })).toHaveValue("");
    await expect(form.getByPlaceholder("warung sate")).toHaveValue("");
  });

  test("editing a non-transfer negative-amount row reverse-maps to Expense + absolute magnitude, saves via PUT", async ({
    page,
  }) => {
    await mockRecords(page, { amount: -25000, is_transfer: false });
    let putCalled = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture()[0], amount: -25000 }),
        });
        return;
      }
      await route.fallback();
    });

    await openEditModal(page);
    const form = page.locator("form").filter({ hasText: "Save changes" });
    await expect(form.getByRole("button", { name: "Expense", exact: true })).toHaveCSS(
      "font-weight",
      "600"
    );
    await expect(form.getByLabel("Amount", { exact: true })).toHaveValue("25000");

    await form.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect.poll(() => putCalled).toBe(true);
  });
});

test.describe("record-modal — category", () => {
  test("choosing (no category) POSTs a null category", async ({ page }) => {
    await mockRecords(page);
    let posted: { category?: unknown; called?: boolean } = {};
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        posted = { called: true, category: route.request().postDataJSON().category };
        await route.fulfill({ status: 201, json: { ...txFixture()[0], id: 999, category: null } });
        return;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    const form = page.locator("form").filter({ hasText: "Add transaction" });
    await form.locator("select").filter({ hasText: "(no category)" }).selectOption("");
    await form.getByLabel("Amount", { exact: true }).fill("10000");
    await form.getByRole("button", { name: "Add transaction", exact: true }).click();

    await expect.poll(() => posted.called).toBe(true);
    expect(posted.category).toBeNull();
  });
});

test.describe("record-modal — Transfer segment (REC-04)", () => {
  test("Transfer branch hides Category, shows From/To account selects, POSTs the whitelist body to /api/transactions/transfer", async ({
    page,
  }) => {
    await mockRecords(page);
    let transferPosted = false;
    let transactionsPosted = false;
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/api/transactions/transfer", async (route) => {
      if (route.request().method() === "POST") {
        transferPosted = true;
        postedBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ status: "ok" }),
        });
        return;
      }
      await route.fallback();
    });
    await page.route("**/api/transactions", async (route) => {
      if (route.request().method() === "POST") {
        transactionsPosted = true;
      }
      await route.fallback();
    });

    await openCreateModal(page);
    // Not filtered by hasText: "Add transaction" — the primary CTA legitimately
    // switches to "Add transfer" once this segment is selected (distinct copy
    // per UI-SPEC), which would stop matching a hasText-scoped locator on every
    // subsequent action. Only one <form> renders while the modal is open.
    const form = page.locator("form");
    await form.getByRole("button", { name: "Transfer", exact: true }).click();

    await expect(form.getByLabel("Category", { exact: true })).toHaveCount(0);
    const fromSelect = form.getByLabel("From account", { exact: true });
    const toSelect = form.getByLabel("To account", { exact: true });
    await expect(fromSelect).toBeVisible();
    await expect(toSelect).toBeVisible();
    await expect(fromSelect.locator("option", { hasText: "Cash" })).toHaveCount(1);
    await expect(fromSelect.locator("option", { hasText: "Bank" })).toHaveCount(1);

    await fromSelect.selectOption({ label: "Cash" });
    await toSelect.selectOption({ label: "Bank" });
    await form.getByLabel("Amount", { exact: true }).fill("50000");
    await form.getByRole("button", { name: "Add transfer", exact: true }).click();

    await expect.poll(() => transferPosted).toBe(true);
    expect(transactionsPosted).toBe(false);
    expect(postedBody).not.toBeNull();
    // postedBody is control-flow-narrowed to null (assigned only inside the
    // route closure), so go through `unknown` per TS2352 before reading keys.
    const body = postedBody as unknown as Record<string, unknown>;
    const keys = Object.keys(body).sort();
    expect(keys).toEqual(
      ["amount", "date", "from_account", "notes", "to_account"].sort()
    );
    expect(body.from_account).toBe("Cash");
    expect(body.to_account).toBe("Bank");
    expect(body.amount).toBe(50000);
  });

  test("To account never offers the From account", async ({ page }) => {
    await mockRecords(page);
    await openCreateModal(page);
    // No hasText filter: the CTA switches to "Add transfer" for this segment.
    const form = page.locator("form");
    await form.getByRole("button", { name: "Transfer", exact: true }).click();
    const from = form.getByLabel("From account", { exact: true });
    const to = form.getByLabel("To account", { exact: true });

    await from.selectOption({ label: "Cash" });
    expect(await to.locator("option").allTextContents()).toEqual(["Bank"]);
    await from.selectOption({ label: "Bank" });
    expect(await to.locator("option").allTextContents()).toEqual(["Cash"]);
  });

  test("editing a transfer-tinted row locks the segment, keeps legacy Account select, never routes to the pair endpoint", async ({
    page,
  }) => {
    await mockRecords(page, { is_transfer: true, amount: -25000 });
    let putCalled = false;
    let transferPosted = false;
    await page.route("**/api/transactions/101", async (route) => {
      if (route.request().method() === "PUT") {
        putCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...txFixture({ is_transfer: true })[0] }),
        });
        return;
      }
      await route.fallback();
    });
    await page.route("**/api/transactions/transfer", async (route) => {
      transferPosted = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });

    await openEditModal(page);
    const form = page.locator("form").filter({ hasText: "Save changes" });

    // Segmented control disabled: clicking Income must not change the active segment.
    const transferSegment = form.getByRole("button", { name: "Transfer", exact: true });
    const incomeSegment = form.getByRole("button", { name: "Income", exact: true });
    await expect(transferSegment).toHaveCSS("font-weight", "600");
    await incomeSegment.click({ force: true });
    await expect(transferSegment).toHaveCSS("font-weight", "600");

    // Legacy single Account select shown, not From/To.
    await expect(form.getByLabel("Account", { exact: true })).toBeVisible();
    await expect(form.getByLabel("From account", { exact: true })).toHaveCount(0);
    await expect(form.getByLabel("To account", { exact: true })).toHaveCount(0);

    await expect(
      page.getByText(
        "This is one leg of a transfer. Full pair editing isn't available yet."
      )
    ).toBeVisible();
    await expect(
      form.getByRole("button", { name: "Save & add another", exact: true })
    ).toHaveCount(0);

    await form.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect.poll(() => putCalled).toBe(true);
    expect(transferPosted).toBe(false);
  });
});
