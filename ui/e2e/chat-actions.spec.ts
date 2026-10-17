// Chat message actions e2e (phase 37, plan 08): Copy, Regenerate and Edit through
// replace_from. The thread GET is stubbed, the new turn is a mocked stream whose
// first event is the thread event with fresh ids. All values are synthetic.
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";
import { mockStreams, queryBodies, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000000a1";
const RUN = "00000000-0000-4000-8000-0000000000c3";
const TOKEN_KEY = (id: string) => `monai.proposalToken.${id}`;
const APPLIED = "Can't redo this: a change made from here on was already applied.";
const WAIT = "Wait for the current answer to finish, or stop it first.";
const conv = (page: Page) => page.getByLabel("Conversation");

let n = 0;
const uid = () => `00000000-0000-4000-8000-00000000e${String(++n).padStart(3, "0")}`;
const msg = (role: string, content: string, status = "complete", parts: Record<string, unknown> = {}) => ({
  id: uid(),
  seq: n,
  role,
  content,
  status,
  created_at: new Date().toISOString(),
  parts: { steps: [], proposals: [], ...parts },
});
const user = (t: string) => msg("user", t);
const asst = (t: string, status = "complete", parts: Record<string, unknown> = {}) =>
  msg("assistant", t, status, parts);

const rows = [
  { before: null, after: { date: "2020-01-01", amount: "-12345.00", merchant: "Example Merchant", account: "Account A" } },
];
const proposal = (id: string, status: string) => ({
  id,
  operation: "add_transaction",
  payload: { operation: "add_transaction", rows },
  status,
  expires_at: new Date(Date.now() + 9.5 * MIN).toISOString(),
});

const thread = (messages: unknown[]) => ({
  id: TID,
  title: "Synthetic chat",
  updated_at: new Date().toISOString(),
  active_run: null,
  messages: messages.map((m, i) => ({ ...(m as object), seq: i + 1 })),
});

// First GET serves `first`; every later GET (the reconcile / 409 re-read) serves `later`.
async function setup(page: Page, first: unknown[], later: unknown[] = first) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  let loads = 0;
  await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
    route.fulfill({ json: thread(++loads === 1 ? first : later) }),
  );
}

// A new turn: thread event (fresh ids), run, then the answer after `answerAt` ms.
const turn = (userId: string, asstId: string, text: string, answerAt = 20): StreamScript => [
  { at: 0, data: { type: "thread", thread_id: TID, user_message_id: userId, assistant_message_id: asstId } },
  { at: 5, data: { type: "run", run_id: RUN } },
  { at: answerAt, data: { type: "answer", text, proposals: [] } },
  { at: answerAt + 5, data: "[DONE]" },
];

const storedTokens = (page: Page) =>
  page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith("monai.proposalToken.")));

test.describe("Copy (D-17)", () => {
  test("copies the markdown source, shows Copied and announces once", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const md = "**Total:** Rp 1,250,000";
    await setup(page, [user("Synthetic total?"), asst(md)]);
    await page.goto(`/chat?thread=${TID}`);
    const copy = page.getByRole("button", { name: "Copy answer" });
    await copy.click();
    await expect(copy).toHaveText("Copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(md);
    await expect(page.getByTestId("chat-announcer")).toHaveText("Answer copied.");
    await expect(copy).toHaveText("Copy", { timeout: 4000 });
  });

  test("is absent on error and stopped messages", async ({ page }) => {
    await setup(page, [
      user("First synthetic question"),
      asst("", "error", { error: { code: "timeout" } }),
      user("Second synthetic question"),
      asst("", "cancelled"),
    ]);
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Stopped. No answer was kept.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy answer" })).toHaveCount(0);
  });

  test("falls back to a textarea when the clipboard API rejects", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator.clipboard, "writeText", {
        value: () => Promise.reject(new Error("denied")),
      });
    });
    await setup(page, [user("Synthetic total?"), asst("Fallback synthetic answer")]);
    await page.goto(`/chat?thread=${TID}`);
    const copy = page.getByRole("button", { name: "Copy answer" });
    await copy.click();
    await expect(copy).toHaveText(/^(Copied|Copy failed)$/);
    await expect(copy).toBeFocused();
    await expect(page.getByTestId("chat-announcer")).toHaveText(/^(Answer copied\.|Couldn't copy the answer\.)$/);
  });
});

test.describe("Regenerate (D-18)", () => {
  test("replaces the last answer through replace_from and clears its tokens", async ({ page }) => {
    const u1 = user("First synthetic question");
    const u2 = user("Second synthetic question");
    const newU = uid();
    const newA = uid();
    await page.addInitScript(([k]) => sessionStorage.setItem(k, "tok-synthetic"), [TOKEN_KEY(ids.h)]);
    await setup(
      page,
      [u1, asst("First answer"), u2, asst("Second answer", "complete", { proposals: [proposal(ids.h, "pending")] })],
      [u1, asst("First answer"), { ...user(u2.content), id: newU }, { ...asst("Regenerated synthetic answer"), id: newA }],
    );
    await mockStreams(page, [turn(newU, newA, "Regenerated synthetic answer", 600)]);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByRole("button", { name: "Regenerate answer" })).toHaveCount(1);
    await expect.poll(() => storedTokens(page)).toEqual([TOKEN_KEY(ids.h)]);

    await page.getByRole("button", { name: "Regenerate answer" }).click();
    await expect(conv(page).getByText("Second answer")).toHaveCount(0);
    await expect(page.getByText("thinking…")).toBeVisible();
    await expect(conv(page).getByText("Regenerated synthetic answer")).toBeVisible();
    expect(await queryBodies(page)).toEqual([
      { question: u2.content, thread_id: TID, replace_from: u2.id },
    ]);
    await expect.poll(() => storedTokens(page)).toEqual([]);
    await expect(conv(page).getByText("Second synthetic question", { exact: true })).toHaveCount(1);
  });
});

test.describe("Edit and resend (D-20)", () => {
  const u1 = user("First synthetic question");
  const u2 = user("Second synthetic question");
  const editBtn = (page: Page, q: string) =>
    page.getByRole("button", { name: `Edit question: ${q}` });

  test("edits the last question with no dialog; Escape restores the bubble", async ({ page }) => {
    const newU = uid();
    const newA = uid();
    await setup(page, [u1, asst("First answer"), u2, asst("Second answer")], [
      u1,
      asst("First answer"),
      { ...user("Edited synthetic question"), id: newU },
      { ...asst("Edited synthetic answer"), id: newA },
    ]);
    await mockStreams(page, [turn(newU, newA, "Edited synthetic answer")]);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByRole("button", { name: /^Edit question:/ })).toHaveCount(2);

    await editBtn(page, u2.content).click();
    const box = page.getByLabel("Edit your question");
    await expect(box).toHaveValue(u2.content);
    await expect(page.getByRole("button", { name: "Resend question" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Discard edit" })).toBeVisible();
    await box.press("Escape");
    await expect(box).toHaveCount(0);
    await expect(editBtn(page, u2.content)).toBeFocused();

    await editBtn(page, u2.content).click();
    await page.getByLabel("Edit your question").fill("Edited synthetic question");
    await page.getByRole("button", { name: "Resend question" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(conv(page).getByText("Edited synthetic answer")).toBeVisible();
    expect(await queryBodies(page)).toEqual([
      { question: "Edited synthetic question", thread_id: TID, replace_from: u2.id },
    ]);
    await expect(conv(page).getByText("Second synthetic question")).toHaveCount(0);
    await expect(page.getByLabel("Ask monai a question")).toBeFocused();
  });

  test("editing an earlier question confirms the truncation first", async ({ page }) => {
    const newU = uid();
    const newA = uid();
    await setup(page, [u1, asst("First answer"), u2, asst("Second answer")], [
      { ...user("Edited first question"), id: newU },
      { ...asst("Edited synthetic answer"), id: newA },
    ]);
    await mockStreams(page, [turn(newU, newA, "Edited synthetic answer")]);
    await page.goto(`/chat?thread=${TID}`);

    await editBtn(page, u1.content).click();
    await page.getByLabel("Edit your question").fill("Edited first question");
    await page.getByRole("button", { name: "Resend question" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(
      "Edit and resend? The 2 later messages in this chat will be removed, and any pending proposals from them will be cancelled.",
    );
    await dialog.getByRole("button", { name: "Keep chat" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByLabel("Edit your question")).toHaveValue("Edited first question");
    expect(await queryBodies(page)).toEqual([]);

    await page.getByRole("button", { name: "Resend question" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Remove and resend" }).click();
    await expect(conv(page).getByText("Edited synthetic answer")).toBeVisible();
    expect(await queryBodies(page)).toEqual([
      { question: "Edited first question", thread_id: TID, replace_from: u1.id },
    ]);
    await expect(conv(page).getByText("Second answer")).toHaveCount(0);
  });
});

test.describe("Disabled states (D-19)", () => {
  test("a confirmed proposal locks Regenerate and that turn's Edit", async ({ page }) => {
    const u1 = user("Synthetic change request");
    await setup(page, [u1, asst("Done.", "complete", { proposals: [proposal(ids.a, "confirmed")] })]);
    await mockStreams(page, [[]]);
    await page.goto(`/chat?thread=${TID}`);
    const regen = page.getByRole("button", { name: "Regenerate answer" });
    const edit = page.getByRole("button", { name: `Edit question: ${u1.content}` });
    await expect(regen).toHaveAttribute("aria-disabled", "true");
    await expect(edit).toHaveAttribute("aria-disabled", "true");
    await regen.hover();
    await expect(page.getByRole("tooltip")).toHaveText(APPLIED);
    await edit.hover();
    await expect(page.getByRole("tooltip")).toHaveText(APPLIED);
    await regen.click({ force: true });
    await edit.click({ force: true });
    await expect(page.getByLabel("Edit your question")).toHaveCount(0);
    expect(await queryBodies(page)).toEqual([]);
  });

  test("a running answer disables earlier edits with the wait reason", async ({ page }) => {
    const u1 = user("First synthetic question");
    await setup(page, [u1, asst("First answer")]);
    await mockStreams(page, [[{ at: 0, data: { type: "run", run_id: RUN } }]], { keepOpen: true });
    await page.goto(`/chat?thread=${TID}`);
    await page.getByLabel("Ask monai a question").fill("Another synthetic question");
    await page.getByLabel("Ask monai a question").press("Enter");
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    const edit = page.getByRole("button", { name: `Edit question: ${u1.content}` });
    await expect(edit).toHaveAttribute("aria-disabled", "true");
    await edit.hover();
    await expect(page.getByRole("tooltip")).toHaveText(WAIT);
  });

  const refusals: [string, number, string][] = [
    ["applied", 409, "This answer's changes were already applied, so it can't be redone."],
    ["still answering", 409, "This chat is still answering. Wait for it to finish."],
    ["other", 422, "Couldn't redo this. Try again."],
  ];
  for (const [name, status, text] of refusals) {
    test(`a late ${status} refusal (${name}) restores the view with an inline error`, async ({ page }) => {
      const u1 = user("Synthetic question");
      const pending = [u1, asst("Original synthetic answer", "complete", { proposals: [proposal(ids.h, "pending")] })];
      const applied = [u1, asst("Original synthetic answer", "complete", { proposals: [proposal(ids.h, "confirmed")] })];
      await setup(page, pending, name === "applied" ? applied : pending);
      await page.route(/\/api\/query-stream$/, (route) =>
        route.fulfill({ status, json: { detail: "SERVER-DETAIL-MUST-NOT-RENDER" } }),
      );
      await page.goto(`/chat?thread=${TID}`);
      await page.getByRole("button", { name: "Regenerate answer" }).click();
      await expect(page.getByRole("alert").filter({ hasText: text })).toBeVisible();
      await expect(conv(page).getByText("Original synthetic answer")).toBeVisible();
      await expect(page.getByText("SERVER-DETAIL-MUST-NOT-RENDER")).toHaveCount(0);
      if (name === "applied") {
        await expect(page.getByRole("button", { name: "Regenerate answer" })).toHaveAttribute("aria-disabled", "true");
      }
    });
  }

  // WR-06: a transport failure after the server already replaced the branch must
  // show the server's thread, not the stale pre-replace snapshot.
  for (const [name, fail] of [
    ["dropped connection", (r: import("@playwright/test").Route) => r.abort("connectionreset")],
    ["502", (r: import("@playwright/test").Route) => r.fulfill({ status: 502, body: "bad gateway" })],
  ] as const) {
    test(`a ${name} on replace re-reads the thread instead of restoring the snapshot`, async ({ page }) => {
      const u1 = user("Synthetic question");
      await setup(page, [u1, asst("Original synthetic answer")], [u1, asst("Answer the server kept")]);
      await page.route(/\/api\/query-stream$/, fail);
      await page.goto(`/chat?thread=${TID}`);
      await page.getByRole("button", { name: "Regenerate answer" }).click();
      await expect(conv(page).getByText("Answer the server kept")).toBeVisible();
      await expect(conv(page).getByText("Original synthetic answer")).toHaveCount(0);
    });
  }
});
