// Chat attach flow e2e (phase 39, plan 12): locality notice, pre-checks, account,
// password, chips, attachment_ids, the Inbox upload card and the purged chip.
// Every API is mocked; all values are synthetic (public repo).
import { test, expect, type Page } from "@playwright/test";

import { MIN, ids, mockInbox } from "./inbox-fixtures";
import { mockStreams, queryBodies, type StreamScript } from "./stream-mock";

const TID = "00000000-0000-4000-8000-0000000000b1";
const RUN = "00000000-0000-4000-8000-0000000000b2";
const AID = "00000000-0000-4000-8000-0000000000d1";
const UMID = "00000000-0000-4000-8000-0000000000e1";
const AMID = "00000000-0000-4000-8000-0000000000e2";
const PID = "00000000-0000-4000-8000-0000000000f1";
const FILE = "march-statement.csv";
const DEST = "Ollama Cloud (gemma4:31b-cloud)";
const PW = "synthetic-pw";
const ASK = "Propose the rows of this file";

const csv = { name: FILE, mimeType: "text/csv", buffer: Buffer.from("date,amount\n2026-03-01,-1000\n") };
const OK = {
  attachment_id: AID, thread_id: TID, kind: "csv", status: "ok",
  summary: "12 rows. Parsed on this computer.", row_count: 12,
};
const NEEDS_PW = { ...OK, attachment_id: null, kind: "pdf_text", status: "needs_password", summary: "", row_count: 0 };
const WRONG_PW = { ...NEEDS_PW, status: "wrong_password" };

type Upload = { json: unknown; status?: number; gate?: Promise<void> };
type Opts = {
  locality?: (n: number) => { status?: number; json: unknown };
  uploads?: Upload[];
  proposals?: unknown[];
  messages?: unknown[];
  attachments?: unknown[];
};

const msg = (id: string, seq: number, role: string, content: string, proposals: unknown[] = []) => ({
  id, seq, role, content, status: "complete", created_at: new Date().toISOString(),
  parts: { steps: [], proposals },
});
const attachment = (o: Record<string, unknown> = {}) => ({
  id: AID, filename: FILE, kind: "csv", status: "ok", summary: OK.summary, row_count: 12,
  message_id: UMID, purged_at: null, ...o,
});
const uploadProposal = (status = "pending") => ({
  id: PID, channel: "upload", token: null, operation: "add_transaction", status,
  expires_at: new Date(Date.now() + 40 * 60 * MIN).toISOString(),
  payload: {
    attachment: { id: AID, filename: FILE, kind: "csv", row_count: 12, invariant: null, llm_read: false, flagged_count: 0 },
  },
});

/** Mocks every API a new or open chat touches; returns the upload request URLs. */
async function boot(page: Page, o: Opts = {}) {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  await mockInbox(page, { list: [] });
  await page.route(/\/api\/threads$/, (r) => r.fulfill({ json: [] }));
  await page.route(/\/api\/accounts$/, (r) =>
    r.fulfill({ json: [{ id: 1, name: "Cash", type: "liquid" }, { id: 2, name: "Broker", type: "investment" }] }),
  );
  let loc = 0;
  await page.route(/\/api\/attachments\/locality$/, (r) => {
    const def: { status?: number; json: unknown } = { json: { local: false, destination: DEST } };
    const a = o.locality ? o.locality(++loc) : def;
    return r.fulfill({ status: a.status ?? 200, json: a.json });
  });
  let up = 0;
  const uploads = o.uploads ?? [{ json: OK }];
  await page.route(/\/api\/threads\/[0-9a-f-]{36}\/attachments$/, async (r) => {
    const u = uploads[Math.min(up++, uploads.length - 1)];
    await u.gate;
    return r.fulfill({ status: u.status ?? 200, json: u.json });
  });
  await page.route(new RegExp(`/api/threads/${TID}$`), (r) =>
    r.fulfill({
      json: {
        id: TID, title: "Synthetic chat", updated_at: new Date().toISOString(), active_run: null,
        messages: o.messages ?? [], attachments: o.attachments ?? [],
      },
    }),
  );
  const turn: StreamScript = [
    { at: 0, data: { type: "thread", thread_id: TID, user_message_id: UMID, assistant_message_id: AMID } },
    { at: 5, data: { type: "run", run_id: RUN } },
    { at: 20, data: { type: "answer", text: "Synthetic answer.", proposals: o.proposals ?? [] } },
    { at: 25, data: "[DONE]" },
  ];
  await mockStreams(page, [turn]);
  return urls;
}

const toggle = (page: Page) => page.getByTestId("attach-toggle");
const panel = (page: Page) => page.getByTestId("attach-panel");
const fileInput = (page: Page) => page.getByTestId("attach-file");
const submit = (page: Page) => page.getByTestId("attach-submit");
const composer = (page: Page) => page.getByLabel("Ask monai a question");

async function openPanel(page: Page) {
  await toggle(page).click();
  await expect(fileInput(page)).toBeEnabled();
}

async function attach(page: Page, file: Parameters<ReturnType<typeof fileInput>["setInputFiles"]>[0] = csv) {
  await openPanel(page);
  await fileInput(page).setInputFiles(file);
  await page.getByTestId("attach-account").selectOption({ label: "Cash" });
  await submit(page).click();
}

test.describe("locality notice (DOC-06, D-15)", () => {
  test("names the outside service before any file is chosen", async ({ page }) => {
    await boot(page);
    await page.goto("/chat");
    await toggle(page).click();
    const loc = page.getByTestId("attach-locality");
    await expect(loc).toContainText("WHERE YOUR FILE GOES");
    await expect(loc).toContainText(`CSV and text PDF: Parsed on this computer. Its text is sent to ${DEST} when you ask about it.`);
    await expect(loc).toContainText(`Image or scan: The image is sent to ${DEST} to be read.`);
    await expect(loc).not.toContainText("Stays on this computer.");
    await expect(fileInput(page)).toHaveAttribute("aria-describedby", /attach-locality/);
  });

  test("a local setup says only that it stays on this computer", async ({ page }) => {
    await boot(page, { locality: () => ({ json: { local: true, destination: null } }) });
    await page.goto("/chat");
    await toggle(page).click();
    const loc = page.getByTestId("attach-locality");
    await expect(loc).toContainText("Stays on this computer.");
    await expect(loc).not.toContainText("Ollama");
  });

  test("a failed check keeps the file input disabled until Try again works", async ({ page }) => {
    await boot(page, { locality: (n) => (n === 1 ? { status: 500, json: { detail: "boom" } } : { json: { local: false, destination: DEST } }) });
    await page.goto("/chat");
    await toggle(page).click();
    await expect(page.getByTestId("attach-locality")).toContainText("Couldn't check where files are sent.");
    await expect(fileInput(page)).toBeDisabled();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(fileInput(page)).toBeEnabled();
    await expect(page.getByTestId("attach-locality")).toContainText(DEST);
  });
});

test.describe("choosing a file", () => {
  test("pre-checks: kind line, size limit and type", async ({ page }) => {
    await boot(page);
    await page.goto("/chat");
    await openPanel(page);
    const loc = page.getByTestId("attach-locality");
    const err = page.getByTestId("attach-file-error");

    await fileInput(page).setInputFiles(csv);
    await expect(loc).toContainText("CSV and text PDF:");
    await expect(loc).not.toContainText("Image or scan:");

    await fileInput(page).setInputFiles({ name: "big.csv", mimeType: "text/csv", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
    await expect(err).toHaveText("That file is 10.0 MB. The limit is 10 MB. Choose a smaller file.");
    await expect(submit(page)).toBeDisabled();

    await fileInput(page).setInputFiles({ name: "book.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("x") });
    await expect(err).toHaveText("monai reads CSV, PDF, PNG, JPEG and WebP files. Choose one of those.");
    await expect(submit(page)).toBeDisabled();
  });

  test("lists only liquid accounts and remembers the choice after a reload", async ({ page }) => {
    await boot(page);
    await page.goto("/chat");
    await openPanel(page);
    await expect(page.getByTestId("attach-account").locator("option")).toHaveText(["Choose an account", "Cash"]);
    await fileInput(page).setInputFiles(csv);
    await page.getByTestId("attach-account").selectOption({ label: "Cash" });
    await submit(page).click();
    await expect(page.getByTestId("attach-chip")).toBeVisible();

    await page.reload();
    await openPanel(page);
    await expect(page.getByTestId("attach-account")).toHaveValue("1");
  });
});

test.describe("uploading", () => {
  test("a good upload adopts a new thread and shows a Ready chip", async ({ page }) => {
    const urls = await boot(page);
    await page.goto("/chat");
    await attach(page);

    await expect(panel(page)).toHaveCount(0);
    const chip = page.getByTestId("attach-chip");
    await expect(chip).toContainText(`${FILE} · Ready`);
    await expect(chip).toContainText("12 rows. Parsed on this computer.");
    await expect(composer(page)).toBeFocused();
    await expect(composer(page)).toHaveAttribute("placeholder", "Ask about this file, or ask me to propose its rows…");
    await expect(page).toHaveURL(new RegExp(`/chat\\?thread=${TID}$`));
    const up = urls.find((u) => u.endsWith("/attachments")) ?? "";
    expect(up).toMatch(/\/api\/threads\/[0-9a-f-]{36}\/attachments$/);
    expect(up).not.toContain(TID); // the first upload used a client-made id
    await expect(page.getByText(/This chat has a document/)).toHaveCount(0); // no always-on notice
  });

  test("password flow: field focused, wrong password alert, never in a URL or storage", async ({ page }) => {
    const urls = await boot(page, { uploads: [{ json: NEEDS_PW }, { json: WRONG_PW }, { json: OK }] });
    await page.goto("/chat");
    await attach(page, { name: "march-statement.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });

    const pw = page.getByTestId("attach-password");
    await expect(pw).toBeFocused();
    await expect(page.getByTestId("attach-chip")).toContainText("Needs a password");
    await pw.fill(PW);
    await submit(page).click();
    await expect(panel(page).getByRole("alert").filter({ hasText: "That password didn't open the file." })).toBeVisible();
    await expect(pw).toHaveValue("");
    await expect(pw).toBeFocused();

    await pw.fill(PW);
    await submit(page).click();
    await expect(panel(page)).toHaveCount(0);
    await expect(page.getByTestId("attach-chip")).toContainText("Ready");

    expect(urls.some((u) => u.includes(PW))).toBe(false);
    const stored = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
    expect(stored).not.toContain(PW);
  });

  test("Ask is aria-disabled while a file uploads and Enter is swallowed", async ({ page }) => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await boot(page, { uploads: [{ json: OK, gate }] });
    await page.goto("/chat");
    await attach(page);

    const ask = page.getByRole("button", { name: "Ask", exact: true });
    await expect(ask).toHaveAttribute("aria-disabled", "true");
    await ask.hover();
    await expect(page.getByRole("tooltip")).toHaveText("Wait for the file to finish uploading.");
    await composer(page).fill("What is in this file?");
    await composer(page).press("Enter");
    expect(await queryBodies(page)).toHaveLength(0);

    release();
    await expect(page.getByTestId("attach-chip")).toContainText("Ready");
    await expect(ask).not.toHaveAttribute("aria-disabled", "true");
  });
});

test.describe("asking", () => {
  test("sends attachment_ids and moves the chip under the user bubble", async ({ page }) => {
    await boot(page, {
      messages: [msg(UMID, 1, "user", "What is in this file?"), msg(AMID, 2, "assistant", "Synthetic answer.")],
      attachments: [attachment()],
    });
    await page.goto("/chat");
    await attach(page);
    await composer(page).fill("What is in this file?");
    await composer(page).press("Enter");

    await expect(page.getByLabel("Conversation").getByText("Synthetic answer.")).toBeVisible();
    const [body] = (await queryBodies(page)) as Record<string, unknown>[];
    expect(body.attachment_ids).toEqual([AID]);
    expect(body.thread_id).toBe(TID);
    await expect(page.getByTestId("attach-tray")).toHaveCount(0);
    await expect(page.getByTestId("message-attachment")).toContainText(`${FILE} · CSV · 12 rows`);
    await expect(composer(page)).toHaveAttribute("placeholder", "Ask anything about your finances…");
  });

  test("removing a Ready chip drops it from the question and says it stays stored", async ({ page }) => {
    await boot(page, {
      messages: [msg(UMID, 1, "user", "Anything else?"), msg(AMID, 2, "assistant", "Synthetic answer.")],
    });
    await page.goto("/chat");
    await attach(page);
    await page.getByTestId("attach-chip-remove").click();

    await expect(page.getByTestId("attach-chip")).toHaveCount(0);
    await expect(page.getByTestId("composer-note")).toContainText(
      `Removed ${FILE} from your question. It stays stored with this chat for 7 days.`,
    );
    await composer(page).fill("Anything else?");
    await composer(page).press("Enter");
    await expect(page.getByLabel("Conversation").getByText("Synthetic answer.")).toBeVisible();
    const [body] = (await queryBodies(page)) as Record<string, unknown>[];
    expect(body).not.toHaveProperty("attachment_ids");
  });
});

test.describe("upload cards (DOC-05, D-22)", () => {
  async function ask(page: Page) {
    await page.goto("/chat");
    await composer(page).fill(ASK);
    await composer(page).press("Enter");
  }

  test("an upload proposal is one Inbox line with no PlanBar or Approve", async ({ page }) => {
    const ps = [uploadProposal()];
    await boot(page, { proposals: ps, messages: [msg(UMID, 1, "user", ASK), msg(AMID, 2, "assistant", "Synthetic answer.", ps)] });
    await ask(page);

    const card = page.getByTestId("upload-card");
    await expect(card).toContainText("12 rows proposed, 0 flagged — Review in Inbox");
    await expect(page.getByTestId("upload-card-link")).toHaveAttribute("href", `/inbox#proposal-${PID}`);
    await expect(page.getByTestId("plan-bar")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("chat-announcer")).toContainText("12 rows proposed, 0 flagged — Review in Inbox");
    const stored = await page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith("monai.proposalToken.")));
    expect(stored).toEqual([]);
  });

  test("beside one chat proposal there is still no PlanBar, and Approve stays on the chat card", async ({ page }) => {
    const chatProposal = {
      id: ids.a, token: "tok-synthetic", operation: "add_transaction", status: "pending",
      expires_at: new Date(Date.now() + 9 * MIN).toISOString(),
      payload: {
        operation: "add_transaction",
        rows: [{ before: null, after: { date: "2020-01-01", amount: "-12345.00", merchant: "Example Merchant", account: "Cash" } }],
      },
    };
    const ps = [chatProposal, uploadProposal()];
    await boot(page, { proposals: ps, messages: [msg(UMID, 1, "user", ASK), msg(AMID, 2, "assistant", "Synthetic answer.", ps)] });
    await ask(page);

    await expect(page.getByTestId("upload-card")).toBeVisible();
    await expect(page.getByTestId("plan-bar")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(1);
  });
});

test.describe("after a reload (D-07, DOC-08)", () => {
  test("a purged attachment keeps its chip with the original-file-removed suffix", async ({ page }) => {
    await boot(page, {
      messages: [msg(UMID, 1, "user", "What is in this file?"), msg(AMID, 2, "assistant", "Synthetic answer.")],
      attachments: [attachment({ purged_at: new Date().toISOString() })],
    });
    await page.goto(`/chat?thread=${TID}`);

    const pill = page.getByTestId("message-attachment");
    await expect(pill).toContainText(`${FILE} · CSV · 12 rows`);
    await expect(pill).toContainText("original file removed");
    await expect(page.getByTestId("attach-tray")).toHaveCount(0);
  });

  test("a decided upload proposal drops the Review link", async ({ page }) => {
    await boot(page, {
      messages: [msg(UMID, 1, "user", "Propose the rows"), msg(AMID, 2, "assistant", "Done.", [uploadProposal("confirmed")])],
      attachments: [attachment()],
    });
    await page.goto(`/chat?thread=${TID}`);

    await expect(page.getByTestId("upload-card")).toContainText("12 rows proposed, 0 flagged — Approved in Inbox");
    await expect(page.getByTestId("upload-card-link")).toHaveCount(0);
  });
});
