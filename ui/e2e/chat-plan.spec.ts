// Phase 38 plan bar and Approve all (D-16, D-17, D-18). The thread GET and the
// confirm route are mocked; all values are synthetic.
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";

const TID = "00000000-0000-4000-8000-0000000000a1";
const TOKEN_KEY = (id: string) => `monai.proposalToken.${id}`;
const approve = (page: Page) => page.getByRole("button", { name: "Approve", exact: true });
const reject = (page: Page) => page.getByRole("button", { name: "Reject", exact: true });
const approveAll = (page: Page) => page.getByRole("button", { name: "Approve all" });

const rows = [
  { before: null, after: { date: "2020-01-01", amount: "-12345.00", merchant: "Example Merchant", account: "Account A" } },
];
const proposal = (id: string, status = "pending") => ({
  id,
  operation: "add_transaction",
  payload: { operation: "add_transaction", rows },
  status,
  expires_at: new Date(Date.now() + 9.5 * MIN).toISOString(),
});
const msg = (id: string, seq: number, role: string, content: string, proposals: unknown[] = []) => ({
  id,
  seq,
  role,
  content,
  status: "complete",
  created_at: new Date().toISOString(),
  parts: { steps: [], proposals },
});

async function setup(page: Page, proposals: unknown[], tokenIds: string[]) {
  for (const id of tokenIds) {
    await page.addInitScript(([k]) => sessionStorage.setItem(k, "tok-synthetic"), [TOKEN_KEY(id)]);
  }
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
    route.fulfill({
      json: {
        id: TID,
        title: "Synthetic chat",
        updated_at: new Date().toISOString(),
        active_run: null,
        messages: [
          msg("00000000-0000-4000-8000-00000000f001", 1, "user", "Synthetic plan"),
          msg("00000000-0000-4000-8000-00000000f002", 2, "assistant", "Three steps.", proposals),
        ],
      },
    }),
  );
}

// Records every confirm path and body; `answer` overrides the response per id.
async function mockConfirm(
  page: Page,
  answer: (id: string) => { status: number; json: unknown } | Promise<{ status: number; json: unknown }> = (id) => ({
    status: 200,
    json: { id, status: "confirmed" },
  }),
) {
  const calls: { id: string; body: unknown }[] = [];
  await page.route(/\/api\/proposals\/[0-9a-f-]{36}\/confirm$/, async (route) => {
    const id = route.request().url().match(/proposals\/([0-9a-f-]{36})\/confirm/)![1];
    calls.push({ id, body: route.request().postDataJSON() });
    await route.fulfill(await answer(id));
  });
  return calls;
}

const three = () => [proposal(ids.a), proposal(ids.b), proposal(ids.c)];
const allTokens = [ids.a, ids.b, ids.c];

test.describe("plan bar and Approve all (LOOP-04)", () => {
  test("shows the order line and numbered cards", async ({ page }) => {
    await setup(page, three(), allTokens);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("plan-bar")).toContainText("3 changes, in this order");
    for (const n of [1, 2, 3]) await expect(page.getByText(new RegExp(`^${n}\\. Proposed`))).toBeVisible();
    await expect(approveAll(page)).toBeVisible();
  });

  test("applies in order and reports success", async ({ page }) => {
    await setup(page, three(), allTokens);
    const calls = await mockConfirm(page);
    await page.goto(`/chat?thread=${TID}`);
    await approveAll(page).click();
    await expect(page.getByText("Applied successfully.")).toHaveCount(3);
    await expect(page.getByRole("status").filter({ hasText: "All 3 changes applied." })).toBeVisible();
    await expect(approveAll(page)).toHaveCount(0);
    expect(calls.map((c) => c.id)).toEqual([ids.a, ids.b, ids.c]);
    expect(calls.map((c) => c.body)).toEqual(Array(3).fill({ token: "tok-synthetic" }));
  });

  test("stops at the first failure and leaves the rest approvable", async ({ page }) => {
    await setup(page, three(), allTokens);
    let failB = true;
    const calls = await mockConfirm(page, (id) =>
      id === ids.b && failB
        ? { status: 409, json: { detail: "Synthetic conflict" } }
        : { status: 200, json: { id, status: "confirmed" } },
    );
    await page.goto(`/chat?thread=${TID}`);
    await approveAll(page).click();
    await expect(page.getByText("Synthetic conflict")).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Applied 1 of 3. Stopped at change 2; the rest are still pending." }),
    ).toBeVisible();
    expect(calls.map((c) => c.id)).toEqual([ids.a, ids.b]);
    await expect(page.getByText("Applied successfully.")).toHaveCount(1);
    await expect(approveAll(page)).toHaveCount(0);

    // One-by-one still works for the pending card (the third).
    failB = false;
    await expect(approve(page).nth(1)).toBeEnabled();
    await approve(page).nth(1).click();
    await expect.poll(() => calls.map((c) => c.id)).toEqual([ids.a, ids.b, ids.c]);
    await expect(page.getByText("Applied successfully.")).toHaveCount(2);
  });

  test("locks every Approve and Reject while it runs", async ({ page }) => {
    await setup(page, three(), allTokens);
    let release!: () => void;
    const held = new Promise<void>((r) => (release = r));
    const calls = await mockConfirm(page, async (id) => {
      if (id === ids.a) await held;
      return { status: 200, json: { id, status: "confirmed" } };
    });
    await page.goto(`/chat?thread=${TID}`);
    await approveAll(page).click();
    await expect(page.getByText("Applying 1 of 3…")).toBeVisible();
    for (const b of await approve(page).all()) await expect(b).toBeDisabled();
    for (const b of await reject(page).all()) await expect(b).toBeDisabled();
    release();
    await expect(page.getByText("Applied successfully.")).toHaveCount(3);
    expect(calls.map((c) => c.id)).toEqual([ids.a, ids.b, ids.c]);
  });

  test("hides Approve all unless every card is ready", async ({ page }) => {
    await setup(page, three(), [ids.a, ids.b]); // no token for c
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("plan-bar")).toContainText("3 changes, in this order");
    await expect(approveAll(page)).toHaveCount(0);
  });

  test("hides Approve all when a proposal is already confirmed", async ({ page }) => {
    await setup(page, [proposal(ids.a, "confirmed"), proposal(ids.b), proposal(ids.c)], allTokens);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("plan-bar")).toBeVisible();
    await expect(approveAll(page)).toHaveCount(0);
  });

  test("hides Approve all once a card is rejected on its own", async ({ page }) => {
    await setup(page, three(), allTokens);
    const calls = await mockConfirm(page);
    await page.route(/\/api\/proposals\/[0-9a-f-]{36}\/reject$/, (route) =>
      route.fulfill({ json: { status: "rejected" } }),
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(approveAll(page)).toBeVisible();
    await reject(page).nth(1).click();
    await expect(page.getByText("Rejected — no changes made.")).toBeVisible();
    await expect(approveAll(page)).toHaveCount(0);
    expect(calls).toEqual([]);
  });

  test("hides Approve all while a card's own confirm is in flight", async ({ page }) => {
    await setup(page, three(), allTokens);
    let release!: () => void;
    const held = new Promise<void>((r) => (release = r));
    const calls = await mockConfirm(page, async (id) => {
      await held;
      return { status: 200, json: { id, status: "confirmed" } };
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(approveAll(page)).toBeVisible();
    await approve(page).nth(0).click();
    await expect.poll(() => calls.length).toBe(1);
    await expect(approveAll(page)).toHaveCount(0);
    release();
    await expect(page.getByText("Applied successfully.")).toHaveCount(1);
    expect(calls.map((c) => c.id)).toEqual([ids.a]);
  });

  test("a single proposal has no bar and approves one-by-one", async ({ page }) => {
    await setup(page, [proposal(ids.a)], [ids.a]);
    const calls = await mockConfirm(page);
    await page.goto(`/chat?thread=${TID}`);
    await expect(approve(page)).toBeEnabled();
    await expect(page.getByTestId("plan-bar")).toHaveCount(0);
    await expect(page.getByText(/^1\. Proposed/)).toHaveCount(0);
    await approve(page).click();
    await expect(page.getByText("Applied successfully.")).toBeVisible();
    expect(calls.map((c) => c.id)).toEqual([ids.a]);
  });
});
