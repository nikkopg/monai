// Chat reliability e2e (phase 34). This file covers the REL-07 proposal-card
// states; plan 34-04 appends the stream, composer and Stop tests.
// All values are synthetic and every /api/* call is stubbed (no live backend).
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";

const TOKEN = "tok-synthetic";
const PLACEHOLDER = "Ask anything about your finances…";

const payload = (rows: unknown[]) => ({ operation: "add_transaction", rows });
const goodRows = [
  {
    before: null,
    after: {
      date: "2020-01-01",
      amount: "-12345.00",
      merchant: "Example Merchant",
      account: "Account A",
    },
  },
];

function proposalOf(id: string, o: Record<string, unknown> = {}) {
  return {
    id,
    token: TOKEN,
    operation: "add_transaction",
    payload: payload(goodRows),
    expires_at: new Date(Date.now() + 9.5 * MIN).toISOString(),
    ...o,
  };
}

async function askWithAnswer(page: Page, proposals: unknown[]) {
  await mockInbox(page, { list: [] });
  const answer = { type: "answer", text: "Done.", proposals, trace: [] };
  await page.route(/\/api\/query-stream$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        `data: ${JSON.stringify({ type: "step", msg: "working…" })}\n\n` +
        `data: ${JSON.stringify(answer)}\n\n` +
        "data: [DONE]\n\n",
    })
  );
  await page.goto("/chat");
  const input = page.getByPlaceholder(PLACEHOLDER);
  await input.fill("Add a synthetic expense");
  await input.press("Enter");
}

test.describe("chat proposal cards (REL-07)", () => {
  test("renders the server payload, operation and expiry", async ({ page }) => {
    await askWithAnswer(page, [proposalOf(ids.h)]);
    await expect(page.getByText("Proposed add transaction")).toBeVisible();
    await expect(page.getByText("Example Merchant", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
    await expect(page.getByText(/expires \d{2}:\d{2} · in 9 min/)).toBeVisible();
  });

  test("shows 'under 1 min' when less than a minute remains", async ({ page }) => {
    await askWithAnswer(page, [
      proposalOf(ids.h, { expires_at: new Date(Date.now() + 30_000).toISOString() }),
    ]);
    await expect(page.getByText(/expires \d{2}:\d{2} · in under 1 min/)).toBeVisible();
  });

  test("unapprovable when rows are empty or payload is missing", async ({ page }) => {
    await askWithAnswer(page, [
      proposalOf(ids.h, { payload: payload([]) }),
      proposalOf(ids.i, { payload: null }),
    ]);
    const notices = page.getByText(/^Nothing to review: this proposal has no details/);
    await expect(notices).toHaveCount(2);
    const approves = page.getByRole("button", { name: "Approve", exact: true });
    const rejects = page.getByRole("button", { name: "Reject", exact: true });
    await expect(approves).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      await expect(approves.nth(i)).toBeDisabled();
      await expect(rejects.nth(i)).toBeEnabled();
      const noticeId = await notices.nth(i).getAttribute("id");
      expect(noticeId).toBeTruthy();
      await expect(approves.nth(i)).toHaveAttribute("aria-describedby", noticeId as string);
    }
  });

  test("unapprovable when expires_at is missing", async ({ page }) => {
    await askWithAnswer(page, [proposalOf(ids.h, { expires_at: null })]);
    await expect(
      page.getByText(/^No expiry came with this proposal, so it can't be approved/)
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
  });

  test("Approve posts the server token", async ({ page }) => {
    await askWithAnswer(page, [proposalOf(ids.h)]);
    // Registered after mockInbox so it wins over the catch-all.
    const posts: { path: string; body: unknown }[] = [];
    await page.route(/\/api\/proposals\/[0-9a-f-]{36}\/(confirm|reject)$/, (route) => {
      const req = route.request();
      posts.push({ path: new URL(req.url()).pathname, body: req.postDataJSON() });
      return route.fulfill({ json: { id: ids.h, status: "confirmed" } });
    });
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Applied successfully.")).toBeVisible();
    expect(posts).toEqual([{ path: `/api/proposals/${ids.h}/confirm`, body: { token: TOKEN } }]);
  });
});
