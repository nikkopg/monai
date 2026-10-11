// Chat threads e2e (phase 36, plan 07): rehydrated proposal cards, persisted
// error/stopped notices, re-attach to a running turn and the thread load states.
// Every /api/* call is stubbed (no live backend); all values are synthetic.
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";

const TID = "00000000-0000-4000-8000-0000000000a1";
const RUN = "00000000-0000-4000-8000-0000000000c3";
const TOKEN_KEY = (id: string) => `monai.proposalToken.${id}`;
const alertBox = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');
const input = (page: Page) => page.getByLabel("Ask monai a question");

const rows = [
  {
    before: null,
    after: { date: "2020-01-01", amount: "-12345.00", merchant: "Example Merchant", account: "Account A" },
  },
];

const proposal = (id: string, status: string, o: Record<string, unknown> = {}) => ({
  id,
  operation: "add_transaction",
  payload: { operation: "add_transaction", rows },
  status,
  expires_at: new Date(Date.now() + 9.5 * MIN).toISOString(),
  ...o,
});

let seq = 0;
const userMsg = (text: string) => ({
  id: `00000000-0000-4000-8000-00000000d${String(++seq).padStart(3, "0")}`,
  seq,
  role: "user",
  content: text,
  status: "complete",
  created_at: new Date().toISOString(),
  parts: { steps: [], proposals: [] },
});
const asstMsg = (content: string, status = "complete", parts: Record<string, unknown> = {}) => ({
  ...userMsg(content),
  role: "assistant",
  status,
  parts: { steps: [], proposals: [], ...parts },
});

const thread = (messages: unknown[], active_run: { run_id: string } | null = null) => ({
  id: TID,
  title: "Synthetic chat",
  updated_at: new Date().toISOString(),
  active_run,
  messages,
});

const threadUrl = new RegExp(`/api/threads/${TID}$`);

async function setup(page: Page) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
}

const stubThread = (page: Page, body: unknown, status = 200) =>
  page.route(threadUrl, (route) => route.fulfill({ status, json: body as object }));

const seed = (page: Page, key: string, value: string) =>
  page.addInitScript(([k, v]) => sessionStorage.setItem(k, v), [key, value]);

const storedTokens = (page: Page) =>
  page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith("monai.proposalToken.")));

const pendingThread = () =>
  thread([userMsg("Add a synthetic expense"), asstMsg("Proposed it.", "complete", { proposals: [proposal(ids.h, "pending")] })]);

test.describe("rehydrated proposal cards (D-16, D-17, THRD-06)", () => {
  test("rehydrated pending card with a same-tab token is actionable", async ({ page }) => {
    await setup(page);
    await seed(page, TOKEN_KEY(ids.h), "tok-synthetic");
    await stubThread(page, pendingThread());
    const posts: unknown[] = [];
    await page.route(/\/api\/proposals\/[0-9a-f-]{36}\/confirm$/, (route) => {
      posts.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: ids.h, status: "confirmed" } });
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Applied successfully.")).toBeVisible();
    expect(posts).toEqual([{ token: "tok-synthetic" }]);
    await expect.poll(() => storedTokens(page)).toEqual([]);
  });

  test("rehydrated pending card without a token is read-only", async ({ page }) => {
    await setup(page);
    await stubThread(page, pendingThread());
    await page.goto(`/chat?thread=${TID}`);
    await expect(
      page.getByText("This chat can no longer approve this change. Review and approve it in the Inbox.")
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("proposal-open-inbox")).toHaveAttribute("href", "/inbox");
    await expect(page.getByText("Example Merchant", { exact: true })).toBeVisible();
  });

  test("terminal statuses render fixed copy and clear the token", async ({ page }) => {
    await setup(page);
    for (const id of [ids.a, ids.b, ids.c]) await seed(page, TOKEN_KEY(id), "tok-synthetic");
    await stubThread(
      page,
      thread([
        userMsg("Add synthetic expenses"),
        asstMsg("Done.", "complete", {
          proposals: [
            proposal(ids.a, "confirmed"),
            proposal(ids.b, "rejected"),
            proposal(ids.c, "expired"),
            proposal(ids.d, "missing"),
          ],
        }),
      ])
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("Applied successfully.")).toBeVisible();
    await expect(page.getByText("Rejected — no changes made.")).toBeVisible();
    await expect(page.getByText("Expired — ask again to redo this")).toBeVisible();
    await expect(page.getByText("This proposal is no longer available.")).toBeVisible();
    await expect.poll(() => storedTokens(page)).toEqual([]);
  });
});

test.describe("persisted notices (THRD-07)", () => {
  test("persisted error and cancelled turns render as notices", async ({ page }) => {
    await setup(page);
    await stubThread(
      page,
      thread([
        userMsg("First synthetic question"),
        asstMsg("OLD-ANSWER-MUST-NOT-RENDER", "error", { error: { code: "timeout" } }),
        userMsg("Second synthetic question"),
        asstMsg("", "cancelled", { proposals: [proposal(ids.e, "rejected")] }),
        userMsg("Third synthetic question"),
        asstMsg("ANSWER-MUST-NOT-RENDER", "error", {
          error: { code: "rate_limit" },
          provider: { name: "ollama", model: "example-model:7b" },
        }),
      ])
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(alertBox(page)).toHaveCount(2);
    await expect(alertBox(page).last()).toContainText("The model is rate-limited");
    await expect(alertBox(page).last()).toContainText("Model: example-model:7b");
    await expect(alertBox(page).first()).toContainText("The model took too long to answer");
    await expect(page.getByText(/ANSWER-MUST-NOT-RENDER/)).toHaveCount(0);
    await expect(
      page.getByText("Stopped. No answer was kept. Proposals from this run were rejected.")
    ).toBeVisible();
    await expect(page.getByText("Rejected — the run was stopped. No changes made.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask again" })).toHaveCount(1);
    await expect(alertBox(page).last().getByRole("button", { name: "Ask again" })).toBeVisible();
  });
});

test.describe("re-attach to a running turn (THRD-09, D-09)", () => {
  test("reload re-attaches to a running turn", async ({ page }) => {
    await setup(page);
    let finished = false;
    await page.route(threadUrl, (route) =>
      route.fulfill({
        json: finished
          ? thread([userMsg("Slow synthetic question"), asstMsg("Persisted synthetic answer")])
          : thread([userMsg("Slow synthetic question")], { run_id: RUN }),
      })
    );
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await page.route(new RegExp(`/api/threads/${TID}/stream$`), async (route) => {
      await gate;
      const ev = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;
      finished = true;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          ev({ type: "run", run_id: RUN }) +
          ev({ type: "step", msg: "working…" }) +
          ev({ type: "answer", text: "Streamed synthetic answer", proposals: [] }) +
          "data: [DONE]\n\n",
      });
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("thinking…")).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await expect(page.getByText("Reconnected to the answer in progress.")).toHaveCount(1);
    release();
    await expect(page.getByText("Persisted synthetic answer")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeVisible();
    await expect(alertBox(page)).toHaveCount(0);
  });

  test("stream 204 refetches the thread", async ({ page }) => {
    await setup(page);
    let hits = 0;
    await page.route(threadUrl, (route) =>
      route.fulfill({
        json:
          ++hits === 1
            ? thread([userMsg("Quick synthetic question")], { run_id: RUN })
            : thread([userMsg("Quick synthetic question"), asstMsg("Finished synthetic answer")]),
      })
    );
    await page.route(new RegExp(`/api/threads/${TID}/stream$`), (route) =>
      route.fulfill({ status: 204 })
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("Finished synthetic answer")).toBeVisible();
    expect(hits).toBe(2);
  });
});

test.describe("thread load states (THRD-01)", () => {
  test("unknown thread shows the not-available notice", async ({ page }) => {
    await setup(page);
    await stubThread(page, { detail: "not found" }, 404);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("That chat isn't available")).toBeVisible();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(input(page)).toBeEnabled();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeEnabled();
  });

  test("load failure shows the open-chat error with Try again", async ({ page }) => {
    await setup(page);
    let hits = 0;
    await page.route(threadUrl, (route) =>
      ++hits === 1
        ? route.fulfill({ status: 500, json: { detail: "RAW-DETAIL-MUST-NOT-RENDER" } })
        : route.fulfill({ json: thread([userMsg("Synthetic question"), asstMsg("Recovered synthetic answer")]) })
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(alertBox(page)).toContainText("Couldn't open this chat");
    await expect(page.getByText("RAW-DETAIL-MUST-NOT-RENDER")).toHaveCount(0);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("Recovered synthetic answer")).toBeVisible();
    await expect(alertBox(page)).toHaveCount(0);
  });
});
