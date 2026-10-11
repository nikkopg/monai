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

  test("a connection drop after the thread event reconciles instead of failing (WR-06)", async ({ page }) => {
    await setup(page);
    await page.addInitScript(
      ({ RUN, TID }) => {
        const real = window.fetch.bind(window);
        const enc = new TextEncoder();
        const evt = (e: unknown) => enc.encode(`data: ${JSON.stringify(e)}\n\n`);
        window.fetch = (url: RequestInfo | URL, init?: RequestInit) => {
          if (!String(url).endsWith("/api/query-stream")) return real(url, init);
          const stream = new ReadableStream({
            start(c) {
              c.enqueue(evt({ type: "run", run_id: RUN }));
              c.enqueue(evt({ type: "thread", thread_id: TID }));
              setTimeout(() => c.error(new TypeError("network error")), 50);
            },
          });
          return Promise.resolve(
            new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
          );
        };
      },
      { RUN, TID }
    );
    await stubThread(
      page,
      thread([userMsg("Synthetic question"), asstMsg("Persisted synthetic answer")])
    );
    await page.goto("/chat");
    await input(page).fill("Synthetic question");
    await input(page).press("Enter");
    await expect(page.getByText("Persisted synthetic answer")).toBeVisible();
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

// ---------------------------------------------------------------------------
// Thread sidebar, delete/rename, example questions, mobile drawer (36-08).
// ---------------------------------------------------------------------------

const DAY = 24 * 60 * 60 * 1000;
const sid = (n: number) => `00000000-0000-4000-8000-0000000000b${n}`;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();
const stubList = (page: Page, list: unknown, status = 200) =>
  page.route(/\/api\/threads$/, (route) => route.fulfill({ status, json: list as object }));
const rowsOf = (page: Page) => page.getByTestId("thread-row");
const examples = (page: Page) => page.getByTestId("example-question");
const ANSWER_STREAM =
  `data: ${JSON.stringify({ type: "answer", text: "Synthetic sidebar answer", proposals: [] })}\n\n` +
  "data: [DONE]\n\n";

test.describe("thread sidebar (THRD-02, D-20)", () => {
  test("sidebar groups threads by recency", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, [
      { id: sid(1), title: "ZZTest today", updated_at: ago(0) },
      { id: sid(2), title: "ZZTest yesterday", updated_at: ago(1) },
      { id: sid(3), title: "ZZTest this week", updated_at: ago(3) },
      { id: sid(4), title: "", updated_at: ago(12) },
      { id: sid(5), title: "ZZTest old", updated_at: ago(45) },
    ]);
    await page.goto("/chat");
    const headers = page.getByTestId("thread-sidebar").locator("h3");
    await expect(headers).toHaveText(["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]);
    await expect(rowsOf(page)).toHaveCount(5);
    await expect(rowsOf(page).nth(3)).toContainText("Untitled chat");
  });

  test("opening a row loads that thread and marks it current", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, [
      { id: TID, title: "ZZTest open me", updated_at: ago(0) },
      { id: sid(2), title: "ZZTest other", updated_at: ago(0) },
    ]);
    let hits = 0;
    await page.route(threadUrl, (route) => {
      hits++;
      return route.fulfill({ json: thread([userMsg("Synthetic q"), asstMsg("Synthetic a")]) });
    });
    await page.goto("/chat");
    await rowsOf(page).first().getByRole("link").click();
    await expect(page).toHaveURL(new RegExp(`/chat\\?thread=${TID}$`));
    await expect(page.getByText("Synthetic a", { exact: true })).toBeVisible();
    expect(hits).toBeGreaterThan(0);
    await expect(rowsOf(page).first()).toHaveAttribute("aria-current", "page");
    await expect(rowsOf(page).nth(1)).not.toHaveAttribute("aria-current", "page");
  });

  test("rename trims and saves, failure reverts with an alert", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, [{ id: TID, title: "ZZTest original", updated_at: ago(0) }]);
    const bodies: unknown[] = [];
    await page.route(threadUrl, (route) => {
      if (route.request().method() !== "PATCH") return route.fulfill({ json: thread([]) });
      bodies.push(route.request().postDataJSON());
      return bodies.length === 1
        ? route.fulfill({ json: { id: TID, title: "ZZTest renamed", updated_at: ago(0) } })
        : route.fulfill({ status: 500, json: { detail: "boom" } });
    });
    await page.goto("/chat");
    await page.getByRole("button", { name: "Rename chat: ZZTest original" }).click();
    const edit = page.getByLabel("Chat title");
    await edit.fill("  ZZTest renamed  ");
    await edit.press("Enter");
    await expect(rowsOf(page).first()).toContainText("ZZTest renamed");
    expect(bodies[0]).toEqual({ title: "ZZTest renamed" });

    await page.getByRole("button", { name: "Rename chat: ZZTest renamed" }).click();
    await page.getByLabel("Chat title").fill("ZZTest again");
    await page.getByLabel("Chat title").press("Enter");
    await expect(page.getByRole("alert").filter({ hasText: "Couldn't rename this chat. Try again." })).toBeVisible();
    await expect(rowsOf(page).first()).toContainText("ZZTest renamed");
  });

  test("delete confirms, handles 409 and leaves the open thread", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, [{ id: TID, title: "ZZTest delete me", updated_at: ago(0) }]);
    let deletes = 0;
    await page.route(threadUrl, (route) => {
      if (route.request().method() === "DELETE") {
        return ++deletes === 1 ? route.fulfill({ status: 409, json: { detail: "running" } }) : route.fulfill({ status: 204 });
      }
      return route.fulfill({ json: thread([userMsg("Synthetic q"), asstMsg("Synthetic a")]) });
    });
    await page.goto(`/chat?thread=${TID}`);
    const del = page.getByRole("button", { name: "Delete chat: ZZTest delete me" });
    await del.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Delete chat" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    await del.click();
    await dialog.getByRole("button", { name: "Delete chat" }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "This chat is still answering. Stop it first, then delete it." })
    ).toBeVisible();

    await del.click();
    await dialog.getByRole("button", { name: "Delete chat" }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(rowsOf(page)).toHaveCount(0);
    await expect(examples(page)).toHaveCount(5);
  });

  test("sidebar fetch failure is non-fatal", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, { detail: "bad gateway" }, 502);
    await page.route(/\/api\/query-stream$/, (route) =>
      route.fulfill({ status: 200, contentType: "text/event-stream", body: ANSWER_STREAM })
    );
    await page.goto("/chat");
    await expect(page.getByText("Couldn't load your chats.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await input(page).fill("Synthetic question");
    await input(page).press("Enter");
    await expect(page.getByText("Synthetic sidebar answer")).toBeVisible();
  });
});

test.describe("example questions and new chat (THRD-08, D-21)", () => {
  test("examples fill the composer without sending", async ({ page }) => {
    await setup(page);
    let posts = 0;
    await page.route(/\/api\/query-stream$/, (route) => {
      posts++;
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: ANSWER_STREAM });
    });
    await page.goto("/chat");
    await expect(examples(page)).toHaveCount(5);
    await expect(page.getByText("You approve it before anything changes.")).toHaveCount(1);
    await examples(page).filter({ hasText: "Compare" }).click();
    await expect(input(page)).toHaveValue("Compare my spending last month against this month");
    await expect(input(page)).toBeFocused();
    expect(posts).toBe(0);

    await stubThread(page, thread([userMsg("Synthetic q"), asstMsg("Synthetic a")]));
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("Synthetic a", { exact: true })).toBeVisible();
    await expect(examples(page)).toHaveCount(0);
  });

  test("new chat clears the view and keeps the draft", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await stubList(page, [{ id: TID, title: "ZZTest open", updated_at: ago(0) }]);
    await stubThread(page, thread([userMsg("Synthetic q"), asstMsg("Synthetic a")]));
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByText("Synthetic a", { exact: true })).toBeVisible();
    await input(page).fill("half-typed synthetic draft");
    await page.getByTestId("thread-new").click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(examples(page)).toHaveCount(5);
    await expect(input(page)).toHaveValue("half-typed synthetic draft");
  });
});

test.describe("mobile drawer (D-20)", () => {
  test("toggle opens the sidebar and Escape closes it", async ({ page }) => {
    await setup(page);
    await page.setViewportSize({ width: 800, height: 900 });
    await page.goto("/chat");
    const side = page.getByTestId("thread-sidebar");
    const toggle = page.getByTestId("threads-toggle");
    await expect(side).toBeHidden();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(side).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(side).toBeHidden();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();
  });
});
