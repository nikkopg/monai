import { expect, test, type Page } from "@playwright/test";

import { mockInbox } from "./inbox-fixtures";
import { mockStreams, type StreamScript } from "./stream-mock";
import type { Source } from "../app/chat/labels";
import { chipHref, dedupeSources } from "../app/chat/SourceChips";

// All values are synthetic.

const spending: Source = {
  tool: "spending_in_category",
  label: "Spending",
  period_label: "Sep 2026",
  date_from: "2026-09-01",
  date_to: "2026-09-30",
  category: "Food",
  type: "expense",
  cashflow: true,
  linked: true,
};
const netWorth: Source = { tool: "net_worth", label: "Net worth", period_label: "Now", linked: false };
const income: Source = { ...spending, label: "Income", category: undefined, type: "income" };

const run = { data: { type: "run", run_id: "00000000-0000-4000-8000-0000000000c3" }, at: 0 };
const toolStart = (id: string, tool: string, at: number) => ({
  data: { type: "tool_start", call_id: id, tool, args: {}, iteration: 0 },
  at,
});
const toolResult = (id: string, tool: string, sources: Source[], at: number) => ({
  data: { type: "tool_result", call_id: id, ms: 300, sources, step: { tool, args: {}, result: { total: 1 } } },
  at,
});
const finalAnswer = (at: number) => ({
  data: { type: "answer", text: "Done.", proposals: [], trace: [], model: "example-model:7b", provider: "ollama" },
  at,
});
const done = (at: number) => ({ data: "[DONE]", at });

const input = (page: Page) => page.getByLabel("Ask monai a question");
const chips = (page: Page) => page.getByTestId("source-chip");
const plain = (page: Page) => page.getByTestId("source-chip-plain");
const convo = (page: Page) => page.getByLabel("Conversation");

async function ask(page: Page, scripts: StreamScript[], keepOpen = false) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await mockStreams(page, scripts, { keepOpen });
  await page.goto("/chat");
  await input(page).fill("How much did I spend on food?");
  await input(page).press("Enter");
}

test.describe("chip helpers (node-only)", () => {
  test("chipHref keeps only present fields, adds cashflow, encodes values", () => {
    expect(chipHref(spending)).toBe(
      "/records?date_from=2026-09-01&date_to=2026-09-30&category=Food&type=expense&cashflow=1",
    );
    expect(chipHref({ ...spending, category: "A&B/../x", account_id: 7, type: undefined })).toBe(
      "/records?date_from=2026-09-01&date_to=2026-09-30&category=A%26B%2F..%2Fx&account_id=7&cashflow=1",
    );
    expect(chipHref(netWorth)).toBe("/records?cashflow=1");
  });

  test("dedupeSources keeps first occurrences in order", () => {
    expect(dedupeSources([spending, income, { ...spending }, netWorth, { ...netWorth }])).toEqual([
      spending,
      income,
      netWorth,
    ]);
  });
});

test.describe("source chips (browser)", () => {
  test("no chip while streaming; a linked chip after the answer", async ({ page }) => {
    await ask(page, [
      [run, toolStart("c0-0", "spending_in_category", 50), toolResult("c0-0", "spending_in_category", [spending], 100), finalAnswer(1500), done(1520)],
    ]);
    await expect(convo(page).getByText("Sources", { exact: true })).toHaveCount(0);
    await expect(chips(page)).toHaveCount(0);
    await expect(chips(page)).toHaveCount(1, { timeout: 8000 });
    await expect(chips(page)).toHaveText(/Spending · Food · Sep 2026/);
    await expect(chips(page)).toHaveAttribute(
      "href",
      "/records?date_from=2026-09-01&date_to=2026-09-30&category=Food&type=expense&cashflow=1",
    );
  });

  test("order, dedupe across steps, and plain chips are not focusable", async ({ page }) => {
    await ask(page, [
      [
        run,
        toolStart("c0-0", "compare_periods", 50),
        toolResult("c0-0", "compare_periods", [spending, income], 100),
        toolStart("c0-1", "spending_in_category", 150),
        toolResult("c0-1", "spending_in_category", [{ ...spending }], 200),
        toolStart("c0-2", "net_worth", 250),
        toolResult("c0-2", "net_worth", [netWorth], 300),
        finalAnswer(400),
        done(420),
      ],
    ]);
    await expect(chips(page)).toHaveCount(2);
    await expect(chips(page).nth(0)).toContainText("Spending");
    await expect(chips(page).nth(1)).toContainText("Income");
    await expect(plain(page)).toHaveCount(1);
    await expect(plain(page)).toHaveText("Net worth · Now");
    await expect(plain(page)).not.toHaveAttribute("href", /.*/);
    await expect(plain(page)).not.toHaveAttribute("tabindex", /.*/);
    await chips(page).nth(1).focus();
    await page.keyboard.press("Tab");
    await expect(plain(page)).not.toBeFocused();
    expect(await page.evaluate(() => document.activeElement?.closest("[data-testid=source-chip-plain]"))).toBeNull();
  });

  test("an error shows no SOURCES row", async ({ page }) => {
    await ask(page, [
      [
        run,
        toolStart("c0-0", "spending_in_category", 50),
        toolResult("c0-0", "spending_in_category", [spending], 100),
        { data: { type: "error", code: "timeout", model: "example-model:7b", provider: "ollama" }, at: 200 },
        done(220),
      ],
    ]);
    await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toContainText(
      "took too long",
    );
    await expect(chips(page)).toHaveCount(0);
    await expect(convo(page).getByText("Sources", { exact: true })).toHaveCount(0);
  });

  test("a stream that ends with no answer (Incomplete) shows no SOURCES row", async ({ page }) => {
    await ask(page, [[run, toolStart("c0-0", "spending_in_category", 50), toolResult("c0-0", "spending_in_category", [spending], 100), done(150)]]);
    await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toContainText(
      "Incomplete answer",
    );
    await expect(chips(page)).toHaveCount(0);
  });

  test("a persisted message without sources shows none, with sources shows them", async ({ page }) => {
    await mockInbox(page, { list: [] });
    const TID = "00000000-0000-4000-8000-0000000000a1";
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
    const base = { status: "complete", created_at: new Date().toISOString() };
    const msg = (n: number, role: string, content: string, parts: unknown) => ({
      ...base, id: `00000000-0000-4000-8000-00000000d0${n}`, seq: n, role, content, parts,
    });
    await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
      route.fulfill({
        json: {
          id: TID,
          title: "Synthetic chat",
          updated_at: base.created_at,
          active_run: null,
          messages: [
            msg(11, "user", "Q1?", {}),
            msg(12, "assistant", "Plain.", { steps: [{ tool: "list_categories", args: {} }], proposals: [] }),
            msg(13, "user", "Q2?", {}),
            msg(14, "assistant", "Sourced.", {
              steps: [{ tool: "spending_in_category", args: {}, sources: [spending] }],
              proposals: [],
            }),
          ],
        },
      }),
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(chips(page)).toHaveCount(1);
    await expect(convo(page).getByText("Sources", { exact: true })).toHaveCount(1);
  });

  test("clicking a linked chip opens Records with the same query and cash-flow request", async ({ page }) => {
    const urls: URL[] = [];
    await ask(page, [
      [run, toolStart("c0-0", "spending_in_category", 50), toolResult("c0-0", "spending_in_category", [spending], 100), finalAnswer(200), done(220)],
    ]);
    // Registered after ask(): mockInbox installs an /api catch-all that would shadow these.
    await page.route("**/api/accounts", (route) => route.fulfill({ json: [{ id: 1, name: "Cash" }] }));
    await page.route("**/api/categories", (route) =>
      route.fulfill({ json: [{ id: 1, name: "Food", is_system: false, children: [] }] }),
    );
    await page.route("**/api/transactions*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      urls.push(new URL(route.request().url()));
      await route.fulfill({ json: [] });
    });
    await chips(page).click();
    await expect(page).toHaveURL(
      /\/records\?date_from=2026-09-01&date_to=2026-09-30&category=Food&type=expense&cashflow=1$/,
    );
    await expect(page.getByTestId("records-pill-cashflow")).toBeVisible();
    await expect.poll(() => urls.length).toBeGreaterThan(0);
    const first = urls[0];
    expect(first.searchParams.get("cashflow")).toBe("true");
    expect(first.searchParams.get("date_from")).toBe("2026-09-01");
    expect(first.searchParams.get("date_to")).toBe("2026-09-30");
  });
});
