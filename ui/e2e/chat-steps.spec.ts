import { expect, test, type Page } from "@playwright/test";

import { mockInbox } from "./inbox-fixtures";
import { mockStreams, type StreamScript } from "./stream-mock";

import {
  argRows,
  formatDateRange,
  formatDuration,
  formatElapsed,
  toolLabel,
  type Source,
} from "../app/chat/labels";
import {
  EMPTY_LANE,
  createTokenBuffer,
  laneAppend,
  laneToolResult,
  laneToolStart,
  stepsFromParts,
  type Lane,
  type StepEntry,
} from "../app/chat/useChatStream";

// Node-only: pure label / lane logic, no browser. All values are synthetic.

const src = (over: Partial<Source> = {}): Source => ({
  label: "Spending",
  period_label: "Sep 2026",
  date_from: "2026-09-01",
  date_to: "2026-09-30",
  linked: true,
  ...over,
});

test.describe("labels and lane (node-only)", () => {
  test("toolLabel maps read tools and humanises the rest", () => {
    expect(toolLabel("spending_before_after_purchase")).toBe("Spending around a purchase");
    expect(toolLabel("list_categories")).toBe("Category list");
    expect(toolLabel("spending_in_category")).toBe("Spending in category");
    expect(toolLabel("propose_add_transaction")).toBe("Propose add transaction");
  });

  test("formatElapsed and formatDuration", () => {
    expect(formatElapsed(0)).toBe("0s");
    expect(formatElapsed(2400)).toBe("2s");
    expect(formatElapsed(65000)).toBe("1m 05s");
    expect(formatDuration(400)).toBe("0.4s");
    expect(formatDuration(2100)).toBe("2.1s");
    expect(formatDuration(12400)).toBe("12s");
    expect(formatDuration(65000)).toBe("1m 05s");
  });

  test("argRows orders known keys then humanised extras", () => {
    const rows = argRows({ limit: 5, zeta_key: "x", period: "this_month", category: "Food" });
    expect(rows).toEqual([
      { label: "Category", value: "Food" },
      { label: "Period", value: "This month" },
      { label: "Limit", value: "5" },
      { label: "Zeta key", value: "x" },
    ]);
  });

  test("argRows humanises periods, formats booleans and drops empties", () => {
    const rows = argRows({
      period: "custom",
      kind: null,
      merchant: "",
      name: undefined,
      flag: true,
      other: false,
    });
    expect(rows).toEqual([
      { label: "Period", value: "Custom range" },
      { label: "Flag", value: "Yes" },
      { label: "Other", value: "No" },
    ]);
    expect(argRows({ period: "all_time" })[0].value).toBe("All time");
  });

  test("argRows reports No filters when nothing remains", () => {
    expect(argRows({ kind: null })).toEqual([{ label: "", value: "No filters" }]);
    expect(argRows({})).toEqual([{ label: "", value: "No filters" }]);
  });

  test("argRows appends Dates rows from sources", () => {
    const one = argRows({ category: "Food" }, [src()]);
    expect(one[one.length - 1]).toEqual({ label: "Dates", value: "Sep 1 – Sep 30, 2026" });
    const two = argRows({ period_a: "this_month" }, [
      src(),
      src({ period_label: "Aug 2026", date_from: "2026-08-01", date_to: "2026-08-31" }),
    ]);
    expect(two.slice(-2)).toEqual([
      { label: "Sep 2026", value: "Sep 1 – Sep 30, 2026" },
      { label: "Aug 2026", value: "Aug 1 – Aug 31, 2026" },
    ]);
    const none = argRows({ category: "Food" }, [src({ date_from: undefined, date_to: undefined })]);
    expect(none).toEqual([{ label: "Category", value: "Food" }]);
  });

  test("formatDateRange", () => {
    expect(formatDateRange("2026-09-01", "2026-09-30", "en-US")).toBe("Sep 1 – Sep 30, 2026");
    expect(formatDateRange("2025-12-01", "2026-01-31", "en-US")).toBe(
      "Dec 1, 2025 – Jan 31, 2026",
    );
    expect(formatDateRange("2026-09-01", undefined, "en-US")).toBe("From Sep 1, 2026");
    expect(formatDateRange(undefined, "2026-09-30", "en-US")).toBe("Until Sep 30, 2026");
    // local calendar day: no timezone shift on the first of a month
    expect(formatDateRange("2026-01-01", "2026-01-01", "en-US")).toBe("Jan 1 – Jan 1, 2026");
  });

  test("laneAppend extends the draft and moves an older iteration into a note", () => {
    let lane: Lane = laneAppend(EMPTY_LANE, "Hello ", 0);
    lane = laneAppend(lane, "there", 0);
    expect(lane.draft).toBe("Hello there");
    expect(lane.timeline).toEqual([]);
    lane = laneAppend(lane, "Next", 1);
    expect(lane.draft).toBe("Next");
    expect(lane.draftIteration).toBe(1);
    expect(lane.timeline).toEqual([{ kind: "note", iteration: 0, text: "Hello there" }]);
  });

  test("laneToolStart moves the draft to a note and appends a running step", () => {
    const withDraft = laneAppend(EMPTY_LANE, "Let me check", 0);
    const lane = laneToolStart(
      withDraft,
      { call_id: "c0-0", tool: "net_worth", args: { period: "this_month" }, iteration: 0 },
      1000,
    );
    expect(lane.draft).toBe("");
    expect(lane.timeline[0]).toEqual({ kind: "note", iteration: 0, text: "Let me check" });
    const step = lane.timeline[1] as StepEntry;
    expect(step).toMatchObject({
      kind: "step",
      callId: "c0-0",
      tool: "net_worth",
      status: "running",
      startedAt: 1000,
      ms: null,
      failed: false,
    });
    // no draft: no note
    const bare = laneToolStart(
      EMPTY_LANE,
      { call_id: "c0-0", tool: "net_worth", args: {}, iteration: 0 },
      5,
    );
    expect(bare.timeline).toHaveLength(1);
  });

  test("laneToolResult completes the matching step or appends a done one", () => {
    const started = laneToolStart(
      EMPTY_LANE,
      { call_id: "c0-0", tool: "net_worth", args: { a: 1 }, iteration: 0 },
      1000,
    );
    const done = laneToolResult(started, {
      call_id: "c0-0",
      step: { tool: "net_worth", args: { a: 1 }, result: { total: 1 } },
      ms: 2100,
      sources: [src()],
    });
    expect(done.timeline[0]).toMatchObject({ status: "done", ms: 2100, failed: false });
    expect((done.timeline[0] as StepEntry).sources).toHaveLength(1);

    const failed = laneToolResult(started, {
      call_id: "c0-0",
      step: { tool: "net_worth", args: {}, result: { error: "boom" } },
    });
    expect((failed.timeline[0] as StepEntry).failed).toBe(true);

    const orphan = laneToolResult(EMPTY_LANE, {
      step: { tool: "list_categories", args: {}, result: {} },
      ms: 400,
    });
    expect(orphan.timeline).toHaveLength(1);
    expect(orphan.timeline[0]).toMatchObject({ tool: "list_categories", status: "done", ms: 400 });
  });

  test("stepsFromParts keeps ms and sources only when stored", () => {
    const steps = stepsFromParts([
      { tool: "net_worth", args: { a: 1 }, ms: 900, sources: [src()] },
      { tool: "list_categories" },
    ]) as StepEntry[];
    expect(steps[0]).toMatchObject({ status: "done", ms: 900 });
    expect(steps[0].sources).toHaveLength(1);
    expect(steps[1]).toMatchObject({ status: "done", ms: null, sources: [], args: {} });
    expect(stepsFromParts(undefined)).toEqual([]);
  });

  test("token buffer batches deltas, flushes on an iteration change, take and cancel", async () => {
    const got: [string, number][] = [];
    const buf = createTokenBuffer((t, i) => got.push([t, i]), 20);
    buf.push("a", 0);
    buf.push("b", 0);
    expect(got).toEqual([]);
    await new Promise((r) => setTimeout(r, 60));
    expect(got).toEqual([["ab", 0]]);

    buf.push("x", 0);
    buf.push("y", 1); // iteration change flushes the older text first
    expect(got[1]).toEqual(["x", 0]);
    expect(buf.take()).toEqual({ text: "y", iteration: 1 });
    await new Promise((r) => setTimeout(r, 60));
    expect(got).toHaveLength(2); // take() cleared the timer

    buf.push("z", 2);
    buf.cancel();
    await new Promise((r) => setTimeout(r, 60));
    expect(got).toHaveLength(2);
    expect(buf.take()).toEqual({ text: "", iteration: null });
  });
});

// ---- Browser: the step UI ----------------------------------------------------

const TID = "00000000-0000-4000-8000-0000000000a1";
const input = (page: Page) => page.getByLabel("Ask monai a question");
const toggle = (page: Page) => page.getByTestId("steps-toggle");

const food = { category: "Food", period: "this_month" };
const toolStart = (id: string, tool: string, args: Record<string, unknown>, at: number) => ({
  data: { type: "tool_start", call_id: id, tool, args, iteration: 0 },
  at,
});
const toolResult = (
  id: string,
  tool: string,
  args: Record<string, unknown>,
  ms: number,
  sources: Source[],
  at: number,
) => ({
  data: { type: "tool_result", call_id: id, ms, sources, step: { tool, args, result: { total: 1 } } },
  at,
});
const run = { data: { type: "run", run_id: "00000000-0000-4000-8000-0000000000c3" }, at: 0 };
const finalAnswer = (at: number) => ({
  data: { type: "answer", text: "Done.", proposals: [], trace: [], model: "example-model:7b", provider: "ollama" },
  at,
});

async function ask(page: Page, scripts: StreamScript[], keepOpen = false) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await mockStreams(page, scripts, { keepOpen });
  await page.goto("/chat");
  await input(page).fill("How much did I spend on food?");
  await input(page).press("Enter");
}

test.describe("tool steps (browser)", () => {
  test("the live line ticks and the toggle is a collapsed disclosure", async ({ page }) => {
    await ask(page, [[run, toolStart("c0-0", "spending_in_category", food, 50)]], true);
    await expect(toggle(page)).toContainText(/Spending in category · 0s/);
    await expect(toggle(page)).toContainText("· 2s", { timeout: 6000 });
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
    const panelId = await toggle(page).getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    await expect(page.locator(`[id="${panelId}"]`)).toHaveAttribute("hidden", "");
  });

  test("Used 2 tools expands to labelled rows with resolved dates and no JSON", async ({ page }) => {
    const source: Source = {
      label: "Spending",
      period_label: "Sep 2026",
      date_from: "2026-09-01",
      date_to: "2026-09-30",
      category: "Food",
      linked: true,
    };
    await ask(page, [
      [
        run,
        toolStart("c0-0", "spending_in_category", food, 50),
        toolResult("c0-0", "spending_in_category", food, 400, [source], 100),
        toolStart("c0-1", "net_worth", {}, 150),
        toolResult("c0-1", "net_worth", {}, 2100, [], 200),
        finalAnswer(300),
        { data: "[DONE]", at: 320 },
      ],
    ]);
    await expect(toggle(page)).toHaveText(/Used 2 tools/);
    await toggle(page).click();
    await expect(toggle(page)).toHaveAttribute("aria-expanded", "true");
    const panel = page.locator(`[id="${await toggle(page).getAttribute("aria-controls")}"]`);
    await expect(panel).toBeVisible();
    await page.getByTestId("step-toggle").first().click();
    await expect(page.getByText("Category", { exact: true })).toBeVisible();
    await expect(page.getByText("Food", { exact: true })).toBeVisible();
    await expect(page.getByText("Period", { exact: true })).toBeVisible();
    await expect(page.getByText("This month", { exact: true })).toBeVisible();
    await expect(page.getByText("Dates", { exact: true })).toBeVisible();
    await expect(page.getByText("Sep 1 \u2013 Sep 30, 2026", { exact: true })).toBeVisible();
    await expect(panel).not.toContainText("{");
  });

  test("persisted steps show duration and dates only when stored", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
    const base = { status: "complete", created_at: new Date().toISOString() };
    await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
      route.fulfill({
        json: {
          id: TID,
          title: "Synthetic chat",
          updated_at: base.created_at,
          active_run: null,
          messages: [
            { ...base, id: "00000000-0000-4000-8000-00000000d001", seq: 1, role: "user", content: "Q?", parts: {} },
            {
              ...base,
              id: "00000000-0000-4000-8000-00000000d002",
              seq: 2,
              role: "assistant",
              content: "Done.",
              parts: {
                steps: [
                  {
                    tool: "spending_in_category",
                    args: food,
                    ms: 2100,
                    sources: [src({ category: "Food" })],
                  },
                  { tool: "net_worth", args: {} },
                ],
                proposals: [],
              },
            },
          ],
        },
      }),
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(toggle(page)).toHaveText(/Used 2 tools/);
    await toggle(page).click();
    const [first, second] = [page.getByTestId("step-toggle").nth(0), page.getByTestId("step-toggle").nth(1)];
    await expect(first).toContainText("· 2.1s");
    await expect(second).not.toContainText("·");
    await first.click();
    await second.click();
    await expect(page.getByText("Dates", { exact: true })).toHaveCount(1);
    await expect(page.getByText("No filters")).toBeVisible();
  });

  test("an unknown tool name falls back to a humanised label", async ({ page }) => {
    await ask(page, [[run, toolStart("c0-0", "propose_add_transaction", {}, 50)]], true);
    await expect(toggle(page)).toContainText("Propose add transaction");
  });
});
