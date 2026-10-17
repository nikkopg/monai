// Phase 38 slash commands and the context divider (38-07). The thread GET and the
// compact/clear routes are mocked; the model never runs. All values are synthetic.
import { test, expect, type Page } from "@playwright/test";

import { mockInbox } from "./inbox-fixtures";
import { mockStreams, queryBodies, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000000b1";
const RUN = "00000000-0000-4000-8000-0000000000d3";
const conv = (page: Page) => page.getByLabel("Conversation");
const composer = (page: Page) => page.getByLabel("Ask monai a question");
const DIVIDER = (page: Page) => page.getByTestId("context-divider");

const mk = (seq: number, role: string, content: string) => ({
  id: `00000000-0000-4000-8000-00000000f${String(seq).padStart(3, "0")}`,
  seq,
  role,
  content,
  status: "complete",
  created_at: new Date().toISOString(),
  parts: { steps: [], proposals: [] },
});
const MESSAGES = [
  mk(1, "user", "First synthetic question"),
  mk(2, "assistant", "First synthetic answer"),
  mk(3, "user", "Second synthetic question"),
  mk(4, "assistant", "Second synthetic answer"),
];

type Flags = { summary_upto_seq: number; has_summary: boolean };

// Thread GET serves `flags` (mutable, so a route can change what the re-read sees).
async function setup(page: Page, flags: Flags = { summary_upto_seq: 0, has_summary: false }) {
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await page.route(new RegExp(`/api/threads/${TID}$`), (route) =>
    route.fulfill({
      json: {
        id: TID,
        title: "Synthetic chat",
        updated_at: new Date().toISOString(),
        active_run: null,
        messages: MESSAGES,
        ...flags,
      },
    }),
  );
  return flags;
}

// Records every compact/clear POST; `reply` decides the response, `gate` can hold it.
async function mockCommands(
  page: Page,
  reply: (cmd: string) => { status: number; json: unknown },
  gate?: Promise<void>,
) {
  const posts: string[] = [];
  await page.route(new RegExp(`/api/threads/${TID}/(compact|clear)$`), async (route) => {
    const cmd = new URL(route.request().url()).pathname.split("/").pop() as string;
    posts.push(cmd);
    if (gate) await gate;
    await route.fulfill(reply(cmd));
  });
  return posts;
}

const ok = () => ({ status: 200, json: { summary_upto_seq: 4, has_summary: true, compacted: true } });
const NO_STREAM: StreamScript = [];

test.describe("/compact and /clear (D-26)", () => {
  test("/compact is intercepted, shows progress, then the divider; nothing leaves the screen", async ({
    page,
  }) => {
    const flags = await setup(page);
    await mockStreams(page, [NO_STREAM]);
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const posts = await mockCommands(page, () => {
      flags.summary_upto_seq = 4;
      flags.has_summary = true;
      return ok();
    }, gate);
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
    await expect(DIVIDER(page)).toHaveCount(0);

    await composer(page).fill("  /compact  ");
    await composer(page).press("Enter");
    await expect(page.getByTestId("composer-note")).toHaveText("Compacting…");
    await expect(composer(page)).toBeDisabled();
    await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
    release();

    await expect(DIVIDER(page)).toHaveText("Earlier messages summarized");
    await expect(composer(page)).toBeEnabled();
    await expect(composer(page)).toHaveValue("");
    expect(posts).toEqual(["compact"]);
    expect(await queryBodies(page)).toEqual([]);
    for (const m of MESSAGES) await expect(conv(page).getByText(m.content, { exact: true })).toBeVisible();
    await expect(conv(page).getByText("/compact")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Copy answer" })).toHaveCount(2);
    // The divider sits after the fourth (last) message.
    const kids = conv(page).locator("> *");
    expect(await kids.last().getAttribute("data-testid")).toBe("context-divider");
  });

  test("/clear is intercepted and the divider says the context was cleared", async ({ page }) => {
    const flags = await setup(page);
    await mockStreams(page, [NO_STREAM]);
    const posts = await mockCommands(page, () => {
      flags.summary_upto_seq = 4;
      flags.has_summary = false;
      return { status: 200, json: { summary_upto_seq: 4, has_summary: false } };
    });
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
    await composer(page).fill("/clear");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(DIVIDER(page)).toHaveText("Context cleared — earlier messages are not sent to the model");
    expect(posts).toEqual(["clear"]);
    expect(await queryBodies(page)).toEqual([]);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
  });

  test("other slash text is a normal question", async ({ page }) => {
    await setup(page);
    await mockStreams(page, [
      [
        { at: 0, data: { type: "thread", thread_id: TID, user_message_id: "u", assistant_message_id: "a" } },
        { at: 5, data: { type: "run", run_id: RUN } },
        { at: 10, data: { type: "answer", text: "Synthetic reply", proposals: [] } },
        { at: 15, data: "[DONE]" },
      ],
    ]);
    const posts = await mockCommands(page, ok);
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
    const typed = ["/compact please", "/compactx"];
    for (let i = 0; i < typed.length; i++) {
      const text = typed[i];
      await composer(page).fill(text);
      await composer(page).press("Enter");
      await expect.poll(async () => (await queryBodies(page)).length).toBe(i + 1);
      await expect(composer(page)).toBeEnabled();
    }
    const bodies = (await queryBodies(page)) as { question: string }[];
    expect(bodies.map((b) => b.question)).toEqual(["/compact please", "/compactx"]);
    expect(posts).toEqual([]);
  });

  test("does nothing while a run is active", async ({ page }) => {
    await setup(page);
    await mockStreams(
      page,
      [[{ at: 0, data: { type: "thread", thread_id: TID, user_message_id: "u", assistant_message_id: "a" } }]],
      { keepOpen: true },
    );
    const posts = await mockCommands(page, ok);
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
    await composer(page).fill("Synthetic running question");
    await composer(page).press("Enter");
    await expect(page.getByRole("button", { name: /Stop/ })).toBeVisible();
    await composer(page).fill("/compact");
    await composer(page).press("Enter");
    await page.waitForTimeout(300);
    expect(posts).toEqual([]);
    expect(await queryBodies(page)).toHaveLength(1);
    await expect(composer(page)).toHaveValue("/compact");
  });

  test("errors show a note and keep the command in the composer", async ({ page }) => {
    await setup(page);
    await mockStreams(page, [NO_STREAM]);
    let status = 409;
    await mockCommands(page, () =>
      status === 409
        ? { status, json: { detail: "thread busy" } }
        : { status, json: { detail: "Couldn't compact this chat right now. Try again later." } },
    );
    await page.goto(`/chat?thread=${TID}`);
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
    await composer(page).fill("/compact");
    await composer(page).press("Enter");
    await expect(page.getByTestId("composer-note")).toHaveText(
      "Wait for the current answer to finish, then try again.",
    );
    await expect(composer(page)).toHaveValue("/compact");
    await expect(DIVIDER(page)).toHaveCount(0);

    status = 503;
    await composer(page).press("Enter");
    await expect(page.getByTestId("composer-note")).toHaveText(
      "Couldn't compact this chat right now. Try again later.",
    );
    await expect(composer(page)).toHaveValue("/compact");
  });

  test("a thread with an automatic summary shows the divider on load", async ({ page }) => {
    await setup(page, { summary_upto_seq: 2, has_summary: true });
    await mockStreams(page, [NO_STREAM]);
    await page.goto(`/chat?thread=${TID}`);
    await expect(DIVIDER(page)).toHaveText("Earlier messages summarized");
    const kids = conv(page).locator("> *");
    expect(await kids.nth(2).getAttribute("data-testid")).toBe("context-divider");
    await expect(conv(page).getByText("Second synthetic answer")).toBeVisible();
  });

  test("with no saved thread, /clear says there is nothing to clear", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
    await mockStreams(page, [NO_STREAM]);
    await page.goto("/chat");
    await composer(page).fill("/clear");
    await composer(page).press("Enter");
    await expect(page.getByTestId("composer-note")).toHaveText("Nothing to clear yet.");
    expect(await queryBodies(page)).toEqual([]);
  });
});
