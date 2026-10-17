// Chat accessibility e2e (phase 37, plan 06): role log, the single announcer,
// the composer label, disclosure state and follow-the-bottom with Jump to latest.
// Streams are browser-side mocks (stream-mock.ts); all values are synthetic.
import { test, expect, type Page } from "@playwright/test";

import { mockInbox } from "./inbox-fixtures";
import { mockStreams, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000000a1";
const RUN = "00000000-0000-4000-8000-0000000000c3";
const input = (page: Page) => page.getByLabel("Ask monai a question");
const announcer = (page: Page) => page.getByTestId("chat-announcer");

const run = { data: { type: "run", run_id: RUN }, at: 0 };
const token = (delta: string, at: number, iteration = 0) => ({
  data: { type: "token", delta, iteration },
  at,
});
const answer = (text: string, at: number) => ({
  data: { type: "answer", text, proposals: [], trace: [], model: "example-model:7b", provider: "ollama" },
  at,
});
const done = (at: number) => ({ data: "[DONE]", at });

async function setup(page: Page, scripts: StreamScript[]) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await mockStreams(page, scripts);
}

async function ask(page: Page, q = "How much did I spend this month?") {
  await page.goto("/chat");
  await input(page).fill(q);
  await input(page).press("Enter");
}

// Records every non-empty announcer value.
async function recordAnnouncements(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __ann: string[] };
    w.__ann = [];
    const el = document.querySelector('[data-testid="chat-announcer"]')!;
    new MutationObserver(() => {
      if (el.textContent) w.__ann.push(el.textContent);
    }).observe(el, { childList: true, characterData: true, subtree: true });
  });
}
const announced = (page: Page) =>
  page.evaluate(() => (window as unknown as { __ann: string[] }).__ann);

test.describe("log, label and announcer (D-21)", () => {
  test("the list is a log with live off and the composer is labelled", async ({ page }) => {
    await setup(page, [[run, answer("Done.", 100), done(120)]]);
    await ask(page);
    const log = page.getByRole("log", { name: "Conversation" });
    await expect(log).toBeVisible();
    await expect(log).toHaveAttribute("aria-live", "off");
    await expect(input(page)).toHaveAttribute("id", "chat-composer");
    await expect(page.getByRole("textbox", { name: "Ask monai a question" })).toBeVisible();
  });

  test("tokens are never announced; the completed answer is announced once", async ({ page }) => {
    const tokens = Array.from({ length: 10 }, (_, i) => token(`word${i} `, 100 + i * 60));
    await setup(page, [[run, ...tokens, answer("Spent Rp 1,250,000 this month.", 1000), done(1020)]]);
    await page.goto("/chat");
    await recordAnnouncements(page);
    await input(page).fill("How much did I spend this month?");
    await input(page).press("Enter");

    await expect(page.getByTestId("answer")).toContainText("word0");
    expect(await announced(page)).toEqual([]);
    await expect(announcer(page)).toHaveText("monai: Spent Rp 1,250,000 this month.");
    await page.waitForTimeout(300);
    expect(await announced(page)).toEqual(["monai: Spent Rp 1,250,000 this month."]);
  });

  test("an Incomplete answer is announced once", async ({ page }) => {
    await setup(page, [[run, token("partial ", 100)]]);
    await page.goto("/chat");
    await recordAnnouncements(page);
    await input(page).fill("How much did I spend this month?");
    await input(page).press("Enter");
    await expect(announcer(page)).toContainText("Incomplete answer.");
    await page.waitForTimeout(300);
    const got = await announced(page);
    expect(got).toHaveLength(1);
    expect(got[0]).toBe(
      "Incomplete answer. The connection closed before the answer finished. Nothing was changed.",
    );
  });

  test("step toggles expose aria-expanded and aria-controls", async ({ page }) => {
    const args = { category: "Food", period: "this_month" };
    await setup(page, [
      [
        run,
        { data: { type: "tool_start", call_id: "c0-0", tool: "spending_in_category", args, iteration: 0 }, at: 50 },
        {
          data: {
            type: "tool_result",
            call_id: "c0-0",
            ms: 900,
            sources: [],
            step: { tool: "spending_in_category", args, result: { total: 1 } },
          },
          at: 200,
        },
        answer("Done.", 400),
        done(420),
      ],
    ]);
    await ask(page);
    await expect(page.getByTestId("answer")).toHaveText("Done.");

    const group = page.getByTestId("steps-toggle");
    await expect(group).toHaveAttribute("aria-expanded", "false");
    expect(await page.locator(`[id="${await group.getAttribute("aria-controls")}"]`).count()).toBe(1);
    await group.click();
    await expect(group).toHaveAttribute("aria-expanded", "true");

    const row = page.getByTestId("step-toggle").first();
    await expect(row).toHaveAttribute("aria-expanded", "false");
    expect(await page.locator(`[id="${await row.getAttribute("aria-controls")}"]`).count()).toBe(1);
    await row.click();
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await row.click();
    await expect(row).toHaveAttribute("aria-expanded", "false");
  });
});

// ---- Follow the bottom and Jump to latest (D-22, D-22a) ---------------------

const msg = (n: number, role: "user" | "assistant", content: string) => ({
  id: `00000000-0000-4000-8000-00000000e${String(n).padStart(3, "0")}`,
  seq: n,
  role,
  content,
  status: "complete",
  created_at: new Date().toISOString(),
  parts: { steps: [], proposals: [] },
});

async function openLongThread(page: Page, scripts: StreamScript[]) {
  const messages = Array.from({ length: 30 }, (_, i) => [
    msg(i * 2, "user", `Synthetic question ${i}`),
    msg(i * 2 + 1, "assistant", `Synthetic answer ${i}.`),
  ]).flat();
  await setup(page, scripts);
  await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
    route.fulfill({
      json: { id: TID, title: "Synthetic chat", updated_at: new Date().toISOString(), active_run: null, messages },
    }),
  );
  await page.goto(`/chat?thread=${TID}`);
  await expect(page.getByText("Synthetic answer 29.")).toBeVisible();
}

const atBottom = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 4);

const paragraphs = (from: number, n: number, gap: number, start: number) =>
  Array.from({ length: n }, (_, i) => token(`Paragraph ${from + i}.\n\n`, start + i * gap));

test.describe("follow the bottom (D-22)", () => {
  test("following: a streamed answer keeps the view at the bottom, no pill", async ({ page }) => {
    await openLongThread(page, [[run, ...paragraphs(0, 8, 120, 100), answer("Done.", 1300), done(1320)]]);
    expect(await atBottom(page)).toBe(true);
    await input(page).fill("Another question");
    await input(page).press("Enter");
    await expect(page.getByTestId("answer").last()).toHaveText("Done.");
    expect(await atBottom(page)).toBe(true);
    await expect(page.getByTestId("jump-to-latest")).toHaveCount(0);
  });

  test("scrolled up: growth shows Jump to latest; clicking resumes following", async ({ page }) => {
    await openLongThread(page, [
      [run, token("First.\n\n", 100), ...paragraphs(0, 10, 300, 1200), answer("Done.", 4500), done(4520)],
    ]);
    expect(await atBottom(page)).toBe(true);
    await expect(page.getByTestId("jump-to-latest")).toHaveCount(0);

    await input(page).fill("Another question");
    await input(page).press("Enter");
    await expect(page.getByTestId("answer").last()).toContainText("First.");
    // The scroll listener has run once the event fires.
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          window.addEventListener("scroll", () => resolve(), { once: true });
          window.scrollTo(0, 0);
        }),
    );

    const jump = page.getByTestId("jump-to-latest");
    await expect(jump).toBeVisible();
    expect(await atBottom(page)).toBe(false);
    // The composer is sticky, so the pill sits inside the viewport while scrolled up.
    const pill = await jump.boundingBox();
    const innerH = await page.evaluate(() => window.innerHeight);
    expect(pill!.y).toBeGreaterThanOrEqual(0);
    expect(pill!.y + pill!.height).toBeLessThanOrEqual(innerH);

    await jump.click();
    await expect(jump).toHaveCount(0);
    await expect(input(page)).toBeFocused();
    expect(await atBottom(page)).toBe(true);

    // Following resumed: later growth keeps the bottom and raises no pill.
    await expect(page.getByTestId("answer").last()).toHaveText("Done.");
    expect(await atBottom(page)).toBe(true);
    await expect(jump).toHaveCount(0);
  });
});
