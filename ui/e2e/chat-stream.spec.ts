// Answer lane e2e (phase 37, plan 05): streamed draft, working notes, the
// authoritative answer, Incomplete, Stop keeping a dimmed partial, re-attach
// replay. The stream is a browser-side mock (stream-mock.ts); all values are
// synthetic.
import { test, expect, type Page } from "@playwright/test";

import { mockInbox } from "./inbox-fixtures";
import { mockStreams, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000000a1";
const RUN = "00000000-0000-4000-8000-0000000000c3";
const QUESTION = "How much did I spend on food?";
const input = (page: Page) => page.getByLabel("Ask monai a question");
const alertBox = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');

const run = { data: { type: "run", run_id: RUN }, at: 0 };
const step = { data: { type: "step", msg: "working…" }, at: 10 };
const token = (delta: string, at: number, iteration = 0) => ({
  data: { type: "token", delta, iteration },
  at,
});
const answer = (text: string, at: number) => ({
  data: { type: "answer", text, proposals: [], trace: [], model: "example-model:7b", provider: "ollama" },
  at,
});
const done = (at: number) => ({ data: "[DONE]", at });

async function setup(page: Page, scripts: StreamScript[], keepOpen = false) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await mockStreams(page, scripts, { keepOpen });
}

async function ask(page: Page) {
  await page.goto("/chat");
  await input(page).fill(QUESTION);
  await input(page).press("Enter");
}

test.describe("answer lane (streamed)", () => {
  test("draft renders live, then the authoritative answer replaces it", async ({ page }) => {
    await setup(page, [
      [run, step, token("Draft one ", 100), token("two", 250), answer("Final **answer**", 1500), done(1520)],
    ]);
    await ask(page);
    const box = page.getByTestId("answer");
    await expect(box).toHaveText("Draft one two");
    await expect(box).toHaveAttribute("aria-busy", "true");
    await expect(page.getByText("answering…")).toBeVisible();

    await expect(box).toHaveText("Final answer");
    await expect(box.locator("strong")).toHaveText("answer");
    await expect(box).not.toHaveAttribute("aria-busy", "true");
    await expect(page.getByText("Draft one")).toHaveCount(0);
  });

  test("narration becomes a working note and never the answer", async ({ page }) => {
    const source = {
      tool: "spending_in_category",
      label: "Spending",
      period_label: "Sep 2026",
      date_from: "2026-09-01",
      date_to: "2026-09-30",
      category: "Food",
      linked: true,
    };
    const args = { category: "Food", period: "this_month" };
    await setup(page, [
      [
        run,
        step,
        token("Let me check", 50),
        {
          data: { type: "tool_start", call_id: "c0-0", tool: "spending_in_category", args, iteration: 0 },
          at: 300,
        },
        {
          data: {
            type: "tool_result",
            call_id: "c0-0",
            ms: 2100,
            sources: [source],
            step: { tool: "spending_in_category", args, result: { total: 1250000 } },
          },
          at: 700,
        },
        step,
        token("Reading results", 1000, 1),
        answer("You spent Rp 1,250,000 on Food.", 1800),
        done(1820),
      ],
    ]);
    await ask(page);
    await expect(page.getByTestId("steps-toggle")).toBeVisible();
    // the narration left the answer area when the tool started
    await expect(page.getByTestId("answer")).toHaveCount(0);

    const box = page.getByTestId("answer");
    await expect(box).toHaveText("You spent Rp 1,250,000 on Food.");
    await expect(box).not.toContainText("Let me check");
    await page.getByRole("button", { name: "Used 1 tool" }).click();
    await page.getByRole("button", { name: "Working note" }).click();
    await expect(page.getByText("Let me check")).toBeVisible();
    await expect(box).not.toContainText("Let me check");
  });

  test("a stream that closes without an answer is Incomplete and hides the partial", async ({ page }) => {
    await setup(page, [[run, step, token("partial text", 50)]]);
    await ask(page);
    const alert = alertBox(page);
    await expect(alert).toContainText("Incomplete answer");
    await expect(alert).toContainText(
      "The connection closed before the answer finished. Nothing was changed.",
    );
    await expect(alert.getByRole("button", { name: "Ask again" })).toBeVisible();
    await page.waitForTimeout(300); // a late buffer flush must not resurrect the draft
    await expect(page.getByText("partial text")).toHaveCount(0);
  });

  test("Stop keeps the partial text dimmed and marks it unsaved", async ({ page }) => {
    await setup(page, [[run, step, token("half an ans", 100)]], true);
    await ask(page);
    await expect(page.getByTestId("answer")).toHaveText("half an ans");
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByText(/· stopped/)).toBeVisible();
    await expect(page.getByTestId("answer")).toHaveText("half an ans");
    await expect(page.getByText("Stopped. This partial answer was not saved.")).toBeVisible();
  });

  test("re-attach replays tokens then the answer once, without duplicated text", async ({ page }) => {
    await setup(page, [
      [run, token("Draft ", 0), token("replay ", 0), token("burst", 5), answer("Final replayed answer", 40), done(60)],
    ]);
    const msg = (seq: number, role: string, content: string) => ({
      id: `00000000-0000-4000-8000-00000000d00${seq}`,
      seq,
      role,
      content,
      status: "complete",
      created_at: new Date().toISOString(),
      parts: { steps: [], proposals: [] },
    });
    let calls = 0;
    await page.route(new RegExp(`/api/threads/${TID}$`), (route) => {
      calls++;
      const messages =
        calls === 1
          ? [msg(1, "user", QUESTION)]
          : [msg(1, "user", QUESTION), msg(2, "assistant", "Final replayed answer")];
      return route.fulfill({
        json: {
          id: TID,
          title: "Synthetic chat",
          updated_at: new Date().toISOString(),
          active_run: calls === 1 ? { run_id: RUN } : null,
          messages,
        },
      });
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("answer")).toHaveText("Final replayed answer");
    await expect(page.getByTestId("answer")).toHaveCount(1);
    await expect(page.getByText("Draft replay burst")).toHaveCount(0);
    await expect(page.getByText("Final replayed answer")).toHaveCount(1);
  });
});
