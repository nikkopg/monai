// Opt-in live Inbox spec: QA-02 (MCP half) plus the approver-key proxy checks
// (D-03). It writes real rows, so it needs a SCRATCH backend on the `monai_test`
// database (never the owner's `monai` database) and refuses to run otherwise;
// the exact launch and run commands are in README.md ("UI tests"). Skipped
// unless E2E_LIVE=1. Synthetic values only; every row it creates is removed.
import { expect, test, type APIRequestContext } from "@playwright/test";

test.skip(!process.env.E2E_LIVE, "live Inbox spec runs only with E2E_LIVE=1");
test.describe.configure({ mode: "serial" });

let BACKEND = "";
let API_KEY = "";
let APPROVER_KEY = "";

const sfx = Math.random().toString(36).slice(2, 8);
const ACCOUNT = `E2E Account A ${sfx}`;
const jakartaDay = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta" });
const d1 = jakartaDay(1);
const d2 = jakartaDay(2);

let accountId = 0;
let seedTxId = 0;
let proposalId = "";
let code = "";
let mcpResultText = "";
// Every /api body+headers we saw, scanned for the approver key at the end.
const seen: string[] = [];

const apiHeaders = () => ({ MONAI_API_KEY: API_KEY });
const sseJson = (text: string) =>
  JSON.parse(text.split("\n").find((l) => l.startsWith("data:"))!.slice(5).trim());
const record = async (r: { text(): Promise<string>; headers(): Record<string, string> }) => {
  seen.push(await r.text(), JSON.stringify(r.headers()));
};

async function mcpCall(request: APIRequestContext, name: string, args: object) {
  const base = { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...apiHeaders() };
  const init = await request.post(`${BACKEND}/mcp/`, {
    headers: base,
    data: {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "e2e", version: "0" } },
    },
  });
  expect(init.status()).toBe(200);
  const h = { ...base, "mcp-session-id": init.headers()["mcp-session-id"] };
  const ack = await request.post(`${BACKEND}/mcp/`, {
    headers: h,
    data: { jsonrpc: "2.0", method: "notifications/initialized" },
  });
  expect(ack.status()).toBe(202);
  const r = await request.post(`${BACKEND}/mcp/`, {
    headers: h,
    data: { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name, arguments: args } },
  });
  expect(r.status()).toBe(200);
  const text = await r.text();
  mcpResultText = text;
  return sseJson(text).result;
}

test.beforeAll(async ({ request }) => {
  BACKEND = process.env.E2E_BACKEND ?? "";
  API_KEY = process.env.E2E_API_KEY ?? "";
  APPROVER_KEY = process.env.E2E_APPROVER_KEY ?? "";
  if (!BACKEND || !API_KEY || !APPROVER_KEY) {
    throw new Error("E2E_BACKEND, E2E_API_KEY and E2E_APPROVER_KEY must all be set");
  }
  if (BACKEND.includes(":8001") || BACKEND.includes(":3001")) {
    throw new Error("E2E_BACKEND must be a scratch backend on monai_test, never the live :8001 / :3001 stack");
  }
  if (process.env.MONAI_API !== BACKEND) {
    throw new Error("MONAI_API (the Next proxy target) must equal E2E_BACKEND");
  }
  if (process.env.MONAI_API_KEY !== API_KEY || process.env.MONAI_APPROVER_KEY !== APPROVER_KEY) {
    throw new Error("MONAI_API_KEY / MONAI_APPROVER_KEY for the Next server must equal the E2E_* values");
  }
  if (API_KEY === APPROVER_KEY) throw new Error("API key and approver key must differ");

  const acc = await request.post(`${BACKEND}/accounts`, {
    headers: apiHeaders(),
    data: { name: ACCOUNT, type: "liquid", currency: "IDR" },
  });
  expect(acc.status()).toBe(201);
  accountId = (await acc.json()).id;
  const tx = await request.post(`${BACKEND}/transactions`, {
    headers: apiHeaders(),
    data: { date: `${d2}T10:00:00`, amount: "-35000", currency: "IDR", merchant: `Seed ${sfx}`, account: ACCOUNT },
  });
  expect(tx.status()).toBe(201);
  seedTxId = (await tx.json()).id;

  const result = await mcpCall(request, "propose_transactions", {
    rows: [
      { date: d2, amount: -35000, account: ACCOUNT, merchant: `Cap ${sfx} 1` },
      { date: d1, amount: -42000, account: ACCOUNT, merchant: `Cap ${sfx} 2` },
      { date: d1, amount: -18000, account: ACCOUNT, merchant: `Cap ${sfx} 3` },
    ],
  });
  expect(result.isError).toBe(false);
  proposalId = result.structuredContent.proposal_id;
  const dup = result.structuredContent.duplicates.find((d: { row: number }) => d.row === 0);
  expect(dup).toBeTruthy();
  expect(dup.matches.some((m: { kind: string; id: number }) => m.kind === "transaction" && m.id === seedTxId)).toBe(true);
});

test.afterAll(async ({ request }) => {
  const safe = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch {
      /* cleanup is best effort */
    }
  };
  if (proposalId) {
    await safe(() =>
      request.post(`${BACKEND}/proposals/${proposalId}/reject`, {
        headers: { ...apiHeaders(), MONAI_APPROVER_KEY: APPROVER_KEY },
      }),
    );
  }
  if (accountId) {
    await safe(async () => {
      const list = await request.get(`${BACKEND}/transactions?account_id=${accountId}&limit=100`, {
        headers: apiHeaders(),
      });
      for (const t of (await list.json()) as { id: number }[]) {
        await request.delete(`${BACKEND}/transactions/${t.id}`, { headers: apiHeaders() });
      }
    });
    await safe(() => request.delete(`${BACKEND}/accounts/${accountId}`, { headers: apiHeaders() }));
  }
});

test.describe("proxy", () => {
  type Row = { id: string; code?: string };
  const mine = async (request: APIRequestContext, url: string, headers: Record<string, string> = {}) => {
    const r = await request.get(url, { headers });
    expect(r.status()).toBe(200);
    await record(r);
    const rows = (await r.json()) as Row[];
    return rows.find((p) => p.id === proposalId);
  };

  test("allowlisted list returns the MCP code; the MCP result never does", async ({ request }) => {
    const p = await mine(request, "/api/proposals?status=pending");
    expect(p?.code).toMatch(/^[0-9A-HJKMNP-TV-Z]{6}$/);
    code = p!.code!;
    expect(mcpResultText).not.toContain(code);
  });

  test("non-allowlisted query gets no code, even with a client-supplied approver header", async ({ request }) => {
    const plain = await mine(request, "/api/proposals?status=pending&x=1");
    expect(plain).toBeTruthy();
    expect(plain!.code).toBeUndefined();
    const forged = await mine(request, "/api/proposals?status=pending&x=1", { MONAI_APPROVER_KEY: APPROVER_KEY });
    expect(forged).toBeTruthy();
    expect(forged!.code).toBeUndefined();
  });
});

test.describe("QA-02 MCP batch", () => {
  test("skip one flagged row, approve, and exactly the other two land in Records", async ({ page, request }) => {
    page.on("response", async (r) => {
      if (new URL(r.url()).pathname.startsWith("/api/")) await record(r).catch(() => undefined);
    });
    await page.goto("/inbox");
    const card = page.getByRole("article", { name: `Add 3 transactions to ${ACCOUNT}` });
    await expect(card).toBeVisible();
    await expect(card.getByText("Possible duplicate").first()).toBeVisible();
    await expect(card.getByRole("code")).toHaveText(code);

    await card.getByRole("button", { name: new RegExp(`^Skip row 1: Cap ${sfx} 1`) }).click();
    // The card's title (its accessible name) counts only non-skipped rows, so re-locate it.
    const after = page.getByRole("article", { name: `Add 2 transactions to ${ACCOUNT}` });
    const approve = after.getByRole("button", { name: "Approve: Add 2 transactions, 1 skipped" });
    await expect(approve).toBeVisible();
    await approve.click();
    await expect(page.locator(`#inbox-status-${proposalId}`)).toContainText("✓ Approved");

    await page.goto("/records");
    await page.getByPlaceholder("Search merchant or notes…").fill(`Cap ${sfx}`);
    await expect(page.getByText(`Cap ${sfx} 2`, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(`Cap ${sfx} 3`, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(`Cap ${sfx} 1`, { exact: true })).toHaveCount(0);

    const list = await request.get(`${BACKEND}/transactions?account_id=${accountId}&limit=100`, {
      headers: apiHeaders(),
    });
    const merchants = ((await list.json()) as { merchant: string | null }[])
      .map((t) => t.merchant ?? "")
      .filter((m) => m.startsWith(`Cap ${sfx}`));
    expect(merchants.sort()).toEqual([`Cap ${sfx} 2`, `Cap ${sfx} 3`]);
  });
});

test.describe("no leak", () => {
  test("the approver key is absent from /api responses, /inbox HTML and served JS", async ({ request }) => {
    const html = await request.get("/inbox");
    expect(html.status()).toBe(200);
    const page = await html.text();
    seen.push(page, JSON.stringify(html.headers()));
    // Every script chunk under /_next/static/ that the HTML references.
    const scripts = Array.from(page.matchAll(/(?:src|href)="([^"]*\/_next\/static\/[^"]+\.js[^"]*)"/g), (m) => m[1]);
    expect(scripts.length).toBeGreaterThan(0);
    for (const src of Array.from(new Set(scripts))) {
      const js = await request.get(src);
      await record(js);
    }
    expect(seen.length).toBeGreaterThan(4);
    for (const blob of seen) expect(blob.includes(APPROVER_KEY)).toBe(false);
  });
});
