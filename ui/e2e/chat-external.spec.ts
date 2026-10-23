// External MCP in chat e2e (phase 41, plan 10): the approval card, Allow / Deny,
// receipts, reload, 409, expiry, the taint line, notices, the Servers menu and
// the ledger-only chips. The stream and every API are mocked; values are
// synthetic (zz-notes, notes.example.com, search_notes).
import { test, expect, type Page } from "@playwright/test";

import { MIN, mockInbox } from "./inbox-fixtures";
import { mockStreams, queryBodies, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000041a1";
const RUN = "00000000-0000-4000-8000-0000000041a2";
const CID = "00000000-0000-4000-8000-0000000041a3";
const UMID = "00000000-0000-4000-8000-0000000041a4";
const AMID = "00000000-0000-4000-8000-0000000041a5";
const SID = "00000000-0000-4000-8000-0000000041a6";
const EXT_TOOL = "ext__zz-notes__search_notes";
const ARGS = { query: "zz" };
const QUESTION = "Search my notes for zz";
const composer = (page: Page) => page.getByLabel("Ask monai a question");
const card = (page: Page) => page.getByTestId("ext-approval-card");
const iso = (ms: number) => new Date(Date.now() + ms).toISOString();

const call = (o: Record<string, unknown> = {}) => ({
  id: CID,
  message_id: null,
  server_slug: "zz-notes",
  tool: "search_notes",
  args: ARGS,
  destination: "notes.example.com",
  leaves_machine: true,
  reason: null,
  approval: "pending",
  decided_via: null,
  expires_at: iso(5 * MIN),
  receipt: null,
  error_class: null,
  ...o,
});
const sent = (o: Record<string, unknown> = {}) =>
  call({ message_id: AMID, approval: "approved", decided_via: "user", receipt: "confirmed", ...o });

// --- stream events ---------------------------------------------------------
const thread = { at: 0, data: { type: "thread", thread_id: TID, user_message_id: UMID, assistant_message_id: AMID } };
const run = { at: 5, data: { type: "run", run_id: RUN } };
const toolStart = {
  at: 20,
  data: { type: "tool_start", call_id: "c0-0", tool: EXT_TOOL, args: ARGS, iteration: 0 },
};
const approval = (at = 40, o: Record<string, unknown> = {}) => ({
  at,
  data: {
    type: "approval_required",
    call_id: CID,
    server: "zz-notes",
    tool: "search_notes",
    args: ARGS,
    destination: "notes.example.com",
    leaves_machine: true,
    expires_at: iso(5 * MIN),
    reason: null,
    ...o,
  },
});
const extCall = (at: number, o: Record<string, unknown>) => ({
  at,
  data: { type: "ext_call", call_id: CID, ...o },
});
const toolResult = (at: number, sources: unknown[] = []) => ({
  at,
  data: { type: "tool_result", call_id: "c0-0", ms: 300, sources, step: { tool: EXT_TOOL, args: ARGS, result: {} } },
});
const answer = (at: number) => ({
  at,
  data: { type: "answer", text: "Synthetic answer.", proposals: [], trace: [], model: "example-model:7b", provider: "ollama" },
});
const done = (at: number) => ({ at, data: "[DONE]" });

// --- thread detail ---------------------------------------------------------
const userMsg = (extra: Record<string, unknown> = {}) => ({
  id: UMID, seq: 1, role: "user", content: QUESTION, status: "complete", created_at: iso(0), parts: {}, ...extra,
});
const asstMsg = (parts: Record<string, unknown> = {}) => ({
  id: AMID,
  seq: 2,
  role: "assistant",
  content: "Synthetic answer.",
  status: "complete",
  created_at: iso(0),
  parts: { steps: [{ tool: EXT_TOOL, args: ARGS, ms: 300 }], proposals: [], ...parts },
});
const detail = (o: Record<string, unknown> = {}) => ({
  id: TID,
  title: "Synthetic chat",
  updated_at: iso(0),
  active_run: null,
  messages: [userMsg(), asstMsg()],
  ext_calls: [sent()],
  mcp_server_ids: [],
  ...o,
});

const server = (o: Record<string, unknown> = {}) => ({
  id: SID, slug: "zz-notes", transport: "http", url: "https://notes.example.com/mcp",
  destination: "notes.example.com", command: null, args: [], headers: [], env: [],
  enabled: true, changed_count: null, ...o,
});

type DetailReply = { status?: number; json?: unknown; delay?: number };
type Boot = {
  scripts?: StreamScript[];
  keepOpen?: boolean;
  detail?: () => DetailReply;
  decision?: { status: number; json: unknown };
  servers?: unknown[];
};

/** Mocks every API a chat touches; returns the decision and PUT bodies the page sent. */
async function boot(page: Page, o: Boot = {}) {
  const seen = { decisions: [] as unknown[], puts: [] as unknown[] };
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (r) => r.fulfill({ json: [] }));
  await page.route(/\/api\/mcp-servers$/, (r) => r.fulfill({ json: o.servers ?? [server()] }));
  await page.route(new RegExp(`/api/threads/${TID}$`), async (r) => {
    const d: DetailReply = o.detail ? o.detail() : { json: detail() };
    if (d.delay) await new Promise((res) => setTimeout(res, d.delay));
    return r.fulfill({ status: d.status ?? 200, json: d.json ?? {} });
  });
  await page.route(new RegExp(`/api/threads/${TID}/ext-calls/${CID}$`), (r) => {
    seen.decisions.push(r.request().postDataJSON());
    const d = o.decision ?? { status: 200, json: { approval: "approved" } };
    return r.fulfill({ status: d.status, json: d.json });
  });
  await page.route(new RegExp(`/api/threads/${TID}/mcp-servers$`), (r) => {
    seen.puts.push(r.request().postDataJSON());
    return r.fulfill({ json: { server_ids: (r.request().postDataJSON() as { server_ids: string[] }).server_ids } });
  });
  await mockStreams(page, o.scripts ?? [], { keepOpen: !!o.keepOpen });
  return seen;
}

async function ask(page: Page) {
  await page.goto("/chat");
  await composer(page).fill(QUESTION);
  await composer(page).press("Enter");
}

const openSteps = async (page: Page) => {
  const t = page.getByTestId("steps-toggle");
  if ((await t.getAttribute("aria-expanded")) !== "true") await t.click();
};

test.describe("approval card (EXT-04)", () => {
  test("a live card names what leaves, focuses Deny and claims nothing sent", async ({ page }) => {
    await boot(page, { scripts: [[thread, run, toolStart, approval()]], keepOpen: true });
    await ask(page);
    await expect(page.getByRole("heading", { name: "zz-notes wants to run search_notes" })).toBeVisible();
    await expect(card(page)).toContainText("notes.example.com");
    await expect(page.getByTestId("ext-leaves")).toContainText("This leaves your computer.");
    await expect(page.getByTestId("ext-args")).toContainText('"query": "zz"');
    await expect(page.getByTestId("ext-countdown")).toContainText("Auto-denies in");
    await expect(page.getByTestId("ext-deny")).toBeFocused();
    await expect(page.getByTestId("ext-badge")).toHaveText(["external, unverified", "external, unverified"]); // live summary + step row
    await expect(page.getByTestId("steps-toggle")).toContainText("search_notes on zz-notes");
    await expect(page.getByTestId("steps-toggle")).toContainText(" · waiting for your answer");
    await expect(page.locator("body")).not.toContainText("Sent to");
  });

  test("Allow once posts the decision and a confirmed receipt reads Sent to", async ({ page }) => {
    const seen = await boot(page, {
      scripts: [[
        thread, run, toolStart, approval(),
        extCall(2000, { approval: "approved", decided_via: "user", receipt: "pending" }),
        extCall(2100, { approval: "approved", receipt: "confirmed" }),
        toolResult(2200), answer(2300), done(2320),
      ]],
    });
    await ask(page);
    await page.getByTestId("ext-allow").click();
    await expect.poll(() => seen.decisions).toEqual([{ approve: true }]);
    await expect(card(page)).toHaveAttribute("data-state", "sent");
    await expect(card(page)).toContainText("Sent to zz-notes.");
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await openSteps(page);
    await expect(page.getByTestId("step-toggle")).toContainText("search_notes on zz-notes");
    await expect(page.getByTestId("step-toggle")).toContainText(" · Sent to zz-notes");
    await expect(page.getByTestId("ext-footer")).toHaveText(
      "Used external tools: zz-notes. External results are unverified.",
    );
  });

  test("Deny reads Nothing was sent, with no footer and no Sent to", async ({ page }) => {
    const seen = await boot(page, {
      scripts: [[
        thread, run, toolStart, approval(),
        extCall(2000, { approval: "denied", decided_via: "user" }),
        toolResult(2100), answer(2200), done(2220),
      ]],
      decision: { status: 200, json: { approval: "denied" } },
      detail: () => ({ json: detail({ ext_calls: [sent({ approval: "denied", receipt: null })] }) }),
    });
    await ask(page);
    await page.getByTestId("ext-deny").click();
    await expect.poll(() => seen.decisions).toEqual([{ approve: false }]);
    await expect(card(page)).toContainText("Denied. Nothing was sent to zz-notes.");
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await openSteps(page);
    await expect(page.getByTestId("step-toggle")).toContainText(" · denied");
    await expect(page.getByTestId("ext-footer")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("Sent to");
  });

  test("a failed receipt says failed and never Sent to", async ({ page }) => {
    await boot(page, {
      scripts: [[
        thread, run, toolStart, approval(),
        extCall(2000, { approval: "approved", decided_via: "user", receipt: "failed", error_class: "timeout" }),
        toolResult(2100), answer(2200), done(2220),
      ]],
      detail: () => ({ json: detail({ ext_calls: [sent({ receipt: "failed", error_class: "timeout" })] }) }),
    });
    await ask(page);
    await page.getByTestId("ext-allow").click();
    await expect(card(page)).toContainText(
      "Allowed, but the call to zz-notes failed (timeout). Don't assume it happened.",
    );
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await openSteps(page);
    await expect(page.getByTestId("step-toggle")).toContainText(" · failed");
    await expect(page.locator("body")).not.toContainText("Sent to");
  });

  test("the taint line explains an Always tool that asks again", async ({ page }) => {
    await boot(page, { scripts: [[thread, run, toolStart, approval(40, { reason: "ledger_read" })]], keepOpen: true });
    await ask(page);
    await expect(card(page)).toContainText(
      "You set this tool to Always, but monai asks again after an answer has used your monai data.",
    );
  });
});

test.describe("reload, 409 and expiry (D-14, D-16)", () => {
  test("a reloaded pending card keeps focus away and is not duplicated by the replay", async ({ page }) => {
    await boot(page, {
      scripts: [[run, approval(30)]],
      keepOpen: true,
      detail: () => ({
        json: detail({
          active_run: { run_id: RUN },
          messages: [userMsg()],
          ext_calls: [call()],
        }),
      }),
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(card(page)).toHaveCount(1);
    await expect(page.getByTestId("ext-deny")).toBeEnabled();
    await expect(page.getByTestId("ext-allow")).toBeEnabled();
    await page.waitForTimeout(300); // the replayed approval_required has landed
    await expect(card(page)).toHaveCount(1);
    await expect(page.getByTestId("ext-deny")).not.toBeFocused();
    await expect(page.getByTestId("ext-allow")).not.toBeFocused();
  });

  test("a decided call from history shows the step suffix and footer, no card", async ({ page }) => {
    await boot(page);
    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await expect(card(page)).toHaveCount(0);
    await openSteps(page);
    await expect(page.getByTestId("step-toggle")).toContainText(" · Sent to zz-notes");
    await expect(page.getByTestId("ext-footer")).toContainText("Used external tools: zz-notes.");
  });

  test("a 409 re-reads the thread and shows the real state", async ({ page }) => {
    await boot(page, {
      scripts: [[thread, run, toolStart, approval()]],
      keepOpen: true,
      decision: { status: 409, json: { detail: "already decided" } },
      detail: () => ({
        json: detail({
          messages: [userMsg()],
          ext_calls: [call({ approval: "expired", decided_via: "expiry" })],
        }),
      }),
    });
    await ask(page);
    await page.getByTestId("ext-allow").click();
    await expect(page.getByText("That request had already been answered or had expired.")).toBeVisible();
    await expect(card(page)).toHaveAttribute("data-state", "expired");
  });

  test("an expired countdown re-reads and reads No answer in time", async ({ page }) => {
    await boot(page, {
      scripts: [[thread, run, toolStart, approval(40, { expires_at: iso(3000) })]],
      keepOpen: true,
      detail: () => ({
        delay: 1500,
        json: detail({
          messages: [userMsg()],
          ext_calls: [call({ approval: "expired", decided_via: "expiry" })],
        }),
      }),
    });
    await ask(page);
    await expect(page.getByTestId("ext-countdown")).toHaveText("Auto-denying…", { timeout: 10_000 });
    await expect(card(page)).toContainText(
      "No answer in time, so it was denied. Nothing was sent to zz-notes.",
    );
  });
});

test.describe("notices (EXT-08)", () => {
  const notices = [
    { code: "tools_changed", server: "zz-notes" },
    { code: "unreachable", server: "zz-notes" },
    { code: "cap", limit: 16 },
  ];
  const sentences = [
    "zz-notes changed its tools; review them in Settings.",
    "Couldn't reach zz-notes, so its tools were left out of this answer.",
    "Only the first 16 external tools were offered this time. Set the ones you don't need to Deny in Settings.",
  ];

  test("live and reloaded notices render one line each with the Settings link", async ({ page }) => {
    await boot(page, {
      scripts: [[thread, run, ...notices.map((n, i) => ({ at: 10 + i, data: { type: "notice", ...n } }))]],
      keepOpen: true,
      detail: () => ({
        json: detail({ ext_calls: [], messages: [userMsg(), asstMsg({ steps: [], notices })] }),
      }),
    });
    await ask(page);
    const lines = page.getByTestId("ext-notice");
    await expect(lines).toHaveCount(3);
    for (let i = 0; i < 3; i++) await expect(lines.nth(i)).toHaveText(sentences[i]);
    await expect(page.getByTestId("ext-notice-link")).toHaveAttribute("href", "/settings#external-mcp");

    await page.goto(`/chat?thread=${TID}`);
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await expect(lines).toHaveCount(3);
    for (let i = 0; i < 3; i++) await expect(lines.nth(i)).toHaveText(sentences[i]);
  });
});

test.describe("Servers menu (EXT-03)", () => {
  const toggle = (page: Page) => page.getByTestId("servers-toggle");

  test("a new chat sends its selection with the first question only", async ({ page }) => {
    await boot(page, { scripts: [[thread, run, answer(20), done(30)]] });
    await page.goto("/chat");
    await toggle(page).click();
    await page.getByTestId("servers-option").check();
    await composer(page).fill(QUESTION);
    await composer(page).press("Enter");
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    expect(((await queryBodies(page))[0] as Record<string, unknown>).mcp_server_ids).toEqual([SID]);
  });

  test("an existing chat PUTs the full set", async ({ page }) => {
    const seen = await boot(page, { detail: () => ({ json: detail({ ext_calls: [], messages: [userMsg()] }) }) });
    await page.goto(`/chat?thread=${TID}`);
    await toggle(page).click();
    await page.getByTestId("servers-option").click(); // checked after the PUT answers
    await expect.poll(() => seen.puts).toEqual([{ server_ids: [SID] }]);
    await expect(page.getByTestId("servers-status")).toHaveText("Servers for this chat updated.");
  });

  test("a chat with a document disables the toggle and says why", async ({ page }) => {
    await boot(page, {
      detail: () => ({
        json: detail({
          ext_calls: [],
          messages: [userMsg()],
          attachments: [{
            id: "00000000-0000-4000-8000-0000000041b1", filename: "march-statement.csv", kind: "csv",
            status: "ok", summary: "12 rows.", row_count: 12, message_id: UMID, purged_at: null,
          }],
        }),
      }),
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(toggle(page)).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId("servers-reason")).toHaveText(
      "This chat has a document, so external servers can't be used here. Start a new chat for those.",
    );
  });

  test("no enabled server means no toggle", async ({ page }) => {
    await boot(page, { servers: [server({ enabled: false })] });
    await page.goto("/chat");
    await expect(composer(page)).toBeVisible();
    await expect(toggle(page)).toHaveCount(0);
  });
});

test.describe("labels (EXT-07, D-25)", () => {
  test("an external step never produces a source chip", async ({ page }) => {
    const source = {
      tool: "spending_in_category", label: "Spending", period_label: "Sep 2026",
      date_from: "2026-09-01", date_to: "2026-09-30", category: "Food", linked: true,
    };
    await boot(page, {
      scripts: [[
        thread, run, toolStart, approval(),
        extCall(1500, { approval: "approved", decided_via: "user", receipt: "confirmed" }),
        toolResult(1600, [source]), answer(1700), done(1720),
      ]],
      detail: () => ({ status: 500, json: {} }), // keep the live view: the live path is what is under test
    });
    await ask(page);
    await page.getByTestId("ext-allow").click();
    await expect(page.getByTestId("answer")).toHaveText("Synthetic answer.");
    await expect(page.getByTestId("ext-footer")).toBeVisible();
    await expect(page.getByTestId("source-chip")).toHaveCount(0);
    await expect(page.getByTestId("source-chip-plain")).toHaveCount(0);
  });
});
