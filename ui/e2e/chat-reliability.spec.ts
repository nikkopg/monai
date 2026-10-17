// Chat reliability e2e (phase 34). This file covers the REL-07 proposal-card
// states; plan 34-04 appends the stream, composer and Stop tests.
// All values are synthetic and every /api/* call is stubbed (no live backend).
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";

const TOKEN = "tok-synthetic";

// D-19a: the chat page's sidebar fetches /api/threads; stub it for every test.
test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
});
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

// ---------------------------------------------------------------------------
// Stream, composer, Stop and model label (REL-01/02/03/05/06/09), plan 34-04.
// ---------------------------------------------------------------------------

const RUN = "00000000-0000-4000-8000-0000000000a1";
const PID = "00000000-0000-4000-8000-0000000000b2";
const QUESTION = "How much did I spend on synthetic things?";
const MODEL = "example-model:7b";
// Next dev injects its own <p role="alert"> route announcer; ours is excluded by id.
const alertBox = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');
const input = (page: Page) => page.getByLabel("Ask monai a question");

const sse = (...events: unknown[]) =>
  events.map((e) => `data: ${typeof e === "string" ? e : JSON.stringify(e)}\n\n`).join("");
const runEvt = { type: "run", run_id: RUN };
const stepEvt = { type: "step", msg: "working…" };
const errEvt = (code: string, extra: Record<string, unknown> = {}) => ({
  type: "error",
  code,
  model: MODEL,
  provider: "ollama",
  ...extra,
});

async function askWithBody(page: Page, body: string, status = 200) {
  await page.route(/\/api\/query-stream$/, (route) =>
    route.fulfill({
      status,
      contentType: status === 200 ? "text/event-stream" : "application/json",
      body: status === 200 ? body : JSON.stringify({ detail: "RAW-DETAIL-MUST-NOT-RENDER" }),
    })
  );
  await page.goto("/chat");
  await input(page).fill(QUESTION);
  await input(page).press("Enter");
}

test.describe("chat stream reliability (REL-01/02/03/05/06/09)", () => {
  test.beforeEach(async ({ page }) => {
    await mockInbox(page, { list: [] });
  });

  const codes: [string, string, Record<string, unknown>?][] = [
    ["rate_limit", "The model is rate-limited"],
    ["provider_unavailable", "The model provider is having trouble"],
    ["timeout", "The model took too long to answer"],
    ["idle_timeout", "The answer stalled", { idle_seconds: 120 }],
    ["auth", "The model rejected monai's credentials"],
    ["connection", "monai can't reach the model"],
    ["empty", "The model returned no answer"],
    ["unknown", "Something went wrong"],
    ["teapot", "Something went wrong"],
  ];
  for (const [code, title, extra] of codes) {
    test(`error ${code} renders its typed block`, async ({ page }) => {
      await askWithBody(page, sse(runEvt, stepEvt, errEvt(code, extra), "[DONE]"));
      const alert = alertBox(page);
      await expect(alert).toContainText(title);
      await expect(alert.getByRole("button", { name: "Ask again" })).toBeVisible();
      await expect(input(page)).toHaveValue(QUESTION);
      if (code === "idle_timeout")
        await expect(alert).toContainText("No activity for 120 seconds, so monai ended the run.");
      if (code === "rate_limit") await expect(alert).toContainText(`Model: ${MODEL}`);
    });
  }

  test("409 renders the conflict block and no thinking state", async ({ page }) => {
    await askWithBody(page, "", 409);
    await expect(alertBox(page)).toContainText("Another answer is already running");
    await expect(page.getByText("thinking…")).toHaveCount(0);
    await expect(page.getByText("RAW-DETAIL-MUST-NOT-RENDER")).toHaveCount(0);
  });

  test("401 renders the unauthorized block", async ({ page }) => {
    await askWithBody(page, "", 401);
    await expect(alertBox(page)).toContainText("Chat isn't authorized");
  });

  test("a transport failure renders the connection block", async ({ page }) => {
    await page.route(/\/api\/query-stream$/, (route) => route.abort("failed"));
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    const alert = alertBox(page);
    await expect(alert).toContainText("monai can't reach the model");
    await expect(alert).toContainText(
      "The connection to monai failed. Check that the server is running, then retry."
    );
  });

  test("a 502 from the proxy renders the connection block with the transport copy", async ({ page }) => {
    await askWithBody(page, "", 502);
    const alert = alertBox(page);
    await expect(alert).toContainText("monai can't reach the model");
    await expect(alert).toContainText(
      "The connection to monai failed. Check that the server is running, then retry."
    );
    await expect(page.getByText("RAW-DETAIL-MUST-NOT-RENDER")).toHaveCount(0);
  });

  test("a stream that closes without a terminal event is stream_ended", async ({ page }) => {
    await askWithBody(page, sse(stepEvt, "[DONE]"));
    await expect(alertBox(page)).toContainText("Incomplete answer");
  });

  test("keep-alive pings are ignored", async ({ page }) => {
    await askWithBody(
      page,
      `: ping\n\n${sse(runEvt, { type: "answer", text: "Synthetic answer", proposals: [] })}: ping\n\ndata: [DONE]\n\n`
    );
    await expect(page.getByLabel("Conversation").getByText("Synthetic answer")).toBeVisible();
    await expect(alertBox(page)).toHaveCount(0);
  });

  test("Ask again re-sends the same question as a fresh run", async ({ page }) => {
    const bodies: string[] = [];
    await page.route(/\/api\/query-stream$/, (route) => {
      bodies.push(route.request().postDataJSON().question);
      const body =
        bodies.length === 1
          ? sse(runEvt, errEvt("rate_limit"), "[DONE]")
          : sse(runEvt, { type: "answer", text: "Synthetic answer", proposals: [] }, "[DONE]");
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    });
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await page.getByRole("button", { name: "Ask again" }).click();
    await expect(page.getByLabel("Conversation").getByText("Synthetic answer")).toBeVisible();
    await expect(alertBox(page)).toHaveCount(0);
    expect(bodies).toEqual([QUESTION, QUESTION]);
  });

  test("proposals on an error event stay actionable", async ({ page }) => {
    await askWithBody(
      page,
      sse(runEvt, errEvt("timeout", { proposals: [proposalOf(ids.h)] }), "[DONE]")
    );
    await expect(alertBox(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  });

  test("Enter while running never starts a second run", async ({ page }) => {
    let count = 0;
    await page.route(/\/api\/query-stream$/, () => {
      count++; // held open: never fulfilled
    });
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toHaveCount(0);
    expect(count).toBe(1);
    await input(page).fill("another synthetic question");
    await input(page).press("Enter");
    await page.waitForTimeout(300);
    expect(count).toBe(1);
  });

  test("Shift+Enter and IME composition do not submit", async ({ page }) => {
    let count = 0;
    await page.route(/\/api\/query-stream$/, () => {
      count++;
    });
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Shift+Enter");
    await input(page).dispatchEvent("keydown", { key: "Enter", isComposing: true, bubbles: true });
    await page.waitForTimeout(300);
    expect(count).toBe(0);
  });

  test("Stop cancels the run, rejects its proposals and ignores a late answer", async ({ page }) => {
    await page.addInitScript(
      ({ RUN, PID }) => {
        const real = window.fetch.bind(window);
        const enc = new TextEncoder();
        window.fetch = (url: RequestInfo | URL, init?: RequestInit) => {
          if (!String(url).endsWith("/api/query-stream")) return real(url, init);
          const stream = new ReadableStream({
            start(c) {
              const send = (o: unknown) =>
                c.enqueue(enc.encode(`data: ${typeof o === "string" ? o : JSON.stringify(o)}\n\n`));
              send({ type: "run", run_id: RUN });
              send({ type: "step", msg: "working…" });
              send({
                type: "tool_result",
                step: {
                  tool: "propose_add_transaction",
                  args: {},
                  result: {
                    proposal_id: PID,
                    before: null,
                    after: { date: "2020-01-01", amount: "-1.00", merchant: "Example Merchant" },
                  },
                },
              });
              init?.signal?.addEventListener("abort", () =>
                setTimeout(() => {
                  send({ type: "answer", text: "LATE-ANSWER-SYNTHETIC", proposals: [] });
                  send("[DONE]");
                  c.close();
                }, 100)
              );
            },
          });
          return Promise.resolve(
            new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
          );
        };
      },
      { RUN, PID }
    );
    let cancelPath = "";
    await page.route(/\/api\/query-stream\/[^/]+\/cancel$/, async (route) => {
      cancelPath = new URL(route.request().url()).pathname;
      await new Promise((r) => setTimeout(r, 400));
      await route.fulfill({ json: { rejected: [PID] } });
    });
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await expect(page.getByTestId("steps-toggle")).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    await expect(
      page.getByLabel("Conversation").getByText("Stopped. No answer was kept. Proposals from this run were rejected.")
    ).toBeVisible();
    await expect(page.getByText("Rejected — the run was stopped. No changes made.")).toBeVisible();
    await expect(page.getByText("LATE-ANSWER-SYNTHETIC")).toHaveCount(0);
    await expect(alertBox(page)).toHaveCount(0);
    await expect(input(page)).toHaveValue(QUESTION);
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeVisible();
    expect(cancelPath).toBe(`/api/query-stream/${RUN}/cancel`);
  });

  test("Stop gives up on a hung cancel request instead of sticking on Stopping…", async ({ page }) => {
    await page.addInitScript(
      ({ RUN }) => {
        const real = window.fetch.bind(window);
        const enc = new TextEncoder();
        window.fetch = (url: RequestInfo | URL, init?: RequestInit) => {
          if (!String(url).endsWith("/api/query-stream")) return real(url, init);
          const stream = new ReadableStream({
            start(c) {
              c.enqueue(enc.encode(`data: ${JSON.stringify({ type: "run", run_id: RUN })}\n\n`));
              c.enqueue(enc.encode(`data: ${JSON.stringify({ type: "step", msg: "working…" })}\n\n`));
              init?.signal?.addEventListener("abort", () => c.close());
            },
          });
          return Promise.resolve(
            new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
          );
        };
      },
      { RUN }
    );
    // The cancel route never answers; only the client-side timeout can end the stop.
    await page.route(/\/api\/query-stream\/[^/]+\/cancel$/, () => {});
    await page.clock.install();
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    await page.clock.fastForward(11_000);
    await expect(page.getByLabel("Conversation").getByText(/^Stopped\. No answer was kept\./)).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeVisible();
  });

  test("Stop before the run event still cancels the server run (WR-01)", async ({ page }) => {
    await page.addInitScript(
      ({ RUN }) => {
        const real = window.fetch.bind(window);
        const enc = new TextEncoder();
        const evt = (e: unknown) => enc.encode(`data: ${JSON.stringify(e)}\n\n`);
        window.fetch = (url: RequestInfo | URL, init?: RequestInit) => {
          if (!String(url).endsWith("/api/query-stream")) return real(url, init);
          const stream = new ReadableStream({
            start(c) {
              // The test releases the first events only after Stop was clicked.
              (window as unknown as { __emit: () => void }).__emit = () => {
                c.enqueue(evt({ type: "run", run_id: RUN }));
                c.enqueue(evt({ type: "thread", thread_id: "00000000-0000-4000-8000-0000000000c3" }));
              };
              init?.signal?.addEventListener("abort", () => c.close());
            },
          });
          return Promise.resolve(
            new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
          );
        };
      },
      { RUN }
    );
    await page.route(/\/api\/query-stream\/[^/]+\/cancel$/, (route) =>
      route.fulfill({ json: { rejected: [] } })
    );
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await page.getByRole("button", { name: "Stop" }).click();
    const cancel = page.waitForRequest(new RegExp(`/api/query-stream/${RUN}/cancel$`));
    await page.evaluate(() => (window as unknown as { __emit: () => void }).__emit());
    await cancel;
    await expect(page.getByLabel("Conversation").getByText(/^Stopped\. No answer was kept\./)).toBeVisible();
  });

  test("Stop after a terminal event clears the answer", async ({ page }) => {
    await page.addInitScript(
      ({ RUN }) => {
        const real = window.fetch.bind(window);
        const enc = new TextEncoder();
        window.fetch = (url: RequestInfo | URL, init?: RequestInit) => {
          if (!String(url).endsWith("/api/query-stream")) return real(url, init);
          const stream = new ReadableStream({
            start(c) {
              const send = (o: unknown) =>
                c.enqueue(enc.encode(`data: ${JSON.stringify(o)}\n\n`));
              send({ type: "run", run_id: RUN });
              // The answer lands but [DONE] never does, so Stop is still on screen.
              send({ type: "answer", text: "TERMINAL-ANSWER-SYNTHETIC", proposals: [], model: "example-model:7b", provider: "ollama" });
              init?.signal?.addEventListener("abort", () => c.close());
            },
          });
          return Promise.resolve(
            new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
          );
        };
      },
      { RUN }
    );
    await page.route(/\/api\/query-stream\/[^/]+\/cancel$/, (route) =>
      route.fulfill({ json: { rejected: [] } })
    );
    await page.goto("/chat");
    await input(page).fill(QUESTION);
    await input(page).press("Enter");
    await expect(page.getByLabel("Conversation").getByText("TERMINAL-ANSWER-SYNTHETIC")).toBeVisible();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByLabel("Conversation").getByText(/^Stopped\. No answer was kept\./)).toBeVisible();
    await expect(page.getByLabel("Conversation").getByText("TERMINAL-ANSWER-SYNTHETIC")).toHaveCount(0);
    await expect(page.getByText("example-model:7b", { exact: true })).toHaveCount(0);
    await expect(alertBox(page)).toHaveCount(0);
  });

  test("model label shows the server model with the provider as title", async ({ page }) => {
    await askWithBody(
      page,
      sse(runEvt, { type: "answer", text: "Synthetic answer", proposals: [], model: MODEL, provider: "ollama" }, "[DONE]")
    );
    const pill = page.getByText(MODEL, { exact: true });
    await expect(pill).toBeVisible();
    await expect(pill).toHaveAttribute("title", "ollama");
  });

  test("model label falls back to 'model unknown'", async ({ page }) => {
    await askWithBody(
      page,
      sse(runEvt, { type: "answer", text: "Synthetic answer", proposals: [] }, "[DONE]")
    );
    await expect(page.getByText("model unknown")).toBeVisible();
  });
});
