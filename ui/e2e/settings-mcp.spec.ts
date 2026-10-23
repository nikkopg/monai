// Settings "External MCP servers" card e2e (phase 41, plan 09): masked-secret form,
// stdio acknowledgement, raw-text tool review, hash-bound Enable with 409 recovery,
// per-tool policies, delete and disable. Every API is mocked; all values are
// synthetic (public repo).
import { test, expect, type Page } from "@playwright/test";

const SAFETY =
  'External servers are not part of monai. Whatever they return is labelled "external, unverified" and is never treated as your records.';
const STALE =
  "This server's tools changed after you opened this list. The list below is the new version. Read it, then enable it again.";
const MASKED = "••••0002";

type Srv = Record<string, unknown>;
const srv = (slug: string, o: Srv = {}): Srv => ({
  id: `id-${slug}`, slug, transport: "http", url: "https://notes.example.com/mcp", destination: "notes.example.com",
  command: null, args: [], headers: [{ name: "Authorization", value_masked: MASKED }], env: [],
  enabled: false, changed_count: null, ...o,
});
const tool = (name: string, o: Srv = {}): Srv => ({
  name, description: "Search notes by keyword.", input_schema: { type: "object", properties: { q: { type: "string" } } },
  annotations: null, usable_name: true, status: "new", ...o,
});
const testOut = (hash: string, tools: Srv[], o: Srv = {}) => ({ tools_hash: hash, tools, removed: [], policies: {}, ...o });

type Call = { method: string; path: string; body: Record<string, unknown> | null };
type Reply = { status?: number; json?: unknown };
type Mock = {
  list: Srv[]; listStatus: number; calls: Call[];
  q: { test: (Reply | object)[]; enable: Reply[]; tool: Reply[] };
};

/** Keeps every request off the live backend, then mocks the /api/mcp-servers routes. */
async function boot(page: Page, init: Partial<Mock> = {}): Promise<Mock> {
  const m: Mock = { list: [srv("zz-notes")], listStatus: 200, calls: [], q: { test: [], enable: [], tool: [] }, ...init };
  await page.route("**/api/**", (r) => r.fulfill({ status: 503, json: { detail: "mocked" } }));
  await page.route("**/api/mcp-servers", (r) => {
    if (r.request().method() === "GET") {
      return m.listStatus === 200
        ? r.fulfill({ json: m.list })
        : r.fulfill({ status: m.listStatus, json: { detail: "boom" } });
    }
    const body = r.request().postDataJSON();
    m.calls.push({ method: "POST", path: "/api/mcp-servers", body });
    const row = srv(body.slug, {
      transport: body.transport, url: body.url, command: body.command, args: body.args,
      headers: body.headers.map((h: { name: string }) => ({ name: h.name, value_masked: MASKED })),
      env: body.env.map((h: { name: string }) => ({ name: h.name, value_masked: MASKED })),
    });
    m.list = [...m.list, row];
    return r.fulfill({ json: row });
  });
  await page.route("**/api/mcp-servers/**", (r) => {
    const req = r.request();
    const parts = new URL(req.url()).pathname.split("/").slice(3); // after /api/mcp-servers
    const id = parts[0];
    const body = req.method() === "POST" || req.method() === "PUT" ? req.postDataJSON() : null;
    m.calls.push({ method: req.method(), path: new URL(req.url()).pathname, body });
    const slugOf = (x: string) => x.replace(/^id-/, "");
    const patch = (p: Srv) => (m.list = m.list.map((s) => (s.id === id ? { ...s, ...p } : s)));
    if (parts[1] === "test") {
      const next = m.q.test.shift() ?? testOut("hash-a", [tool("search_notes")]);
      const reply = next as Reply;
      return "tools_hash" in next
        ? r.fulfill({ json: next })
        : r.fulfill({ status: reply.status ?? 200, json: reply.json ?? {} });
    }
    if (parts[1] === "enabled") {
      const next = m.q.enable.shift() ?? {};
      if ((next.status ?? 200) === 200) patch({ enabled: body!.enabled, changed_count: 0 });
      return r.fulfill({ status: next.status ?? 200, json: next.json ?? srv(slugOf(id)) });
    }
    if (parts[1] === "tools") {
      const next = m.q.tool.shift() ?? {};
      return r.fulfill({ status: next.status ?? 200, json: next.json ?? { ok: true } });
    }
    if (req.method() === "DELETE") {
      m.list = m.list.filter((s) => s.id !== id);
      return r.fulfill({ json: { ok: true } });
    }
    patch(body ?? {});
    return r.fulfill({ json: srv(slugOf(id)) });
  });
  await page.goto("/settings");
  return m;
}

const rowOf = (page: Page, slug: string) => page.locator(`[data-testid="mcp-row"][data-server="${slug}"]`);
const status = (page: Page) => page.getByTestId("mcp-status");

test.describe("/settings External MCP servers card", () => {
  test("safety line is verbatim; empty state and load error with retry", async ({ page }) => {
    const m = await boot(page, { list: [], listStatus: 500 });
    await expect(page.getByTestId("mcp-safety").locator("p").first()).toHaveText(SAFETY);
    await expect(page.getByTestId("mcp-load-error")).toContainText("Couldn't load servers: boom.");
    m.listStatus = 200;
    await page.getByTestId("mcp-list-retry").click();
    await expect(page.getByTestId("mcp-empty")).toContainText("No external servers yet.");
    await expect(page.getByTestId("mcp-safety")).toBeVisible();
  });

  test("add an HTTP server: header value is sent, server starts Off", async ({ page }) => {
    const m = await boot(page, { list: [] });
    await page.getByTestId("mcp-add").click();
    await page.locator("#mcp-slug").fill("zz-notes");
    await page.locator("#mcp-url").fill("https://notes.example.com/mcp");
    await page.getByRole("button", { name: "Add header" }).click();
    await page.getByLabel("Header 1 name").fill("Authorization");
    const value = page.getByLabel("Header 1 value");
    await expect(value).toHaveAttribute("type", "password");
    await value.fill("Bearer zz-synthetic-secret-0001");
    await page.getByTestId("mcp-save").click();
    await expect(status(page)).toHaveText("Added zz-notes. It is off. Test it, review its tools, then enable it.");
    const post = m.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({
      slug: "zz-notes", transport: "http", url: "https://notes.example.com/mcp",
      headers: [{ name: "Authorization", value: "Bearer zz-synthetic-secret-0001" }], acknowledged_local_read: false,
    });
    const row = rowOf(page, "zz-notes");
    await expect(row.getByTestId("mcp-transport")).toHaveText("HTTP");
    await expect(row.getByTestId("mcp-status-chip")).toHaveText("Off");
    // The secret is gone from the page once saved: only the masked string comes back.
    await expect(page.locator("body")).not.toContainText("zz-synthetic-secret-0001");
  });

  test("local command: npx/uvx only, Save needs the acknowledgement, unpinned warns", async ({ page }) => {
    await boot(page, { list: [] });
    await page.getByTestId("mcp-add").click();
    await page.getByLabel("Local command (npx or uvx)").check();
    await expect(page.locator("#mcp-command option")).toHaveText(["npx", "uvx"]);
    await page.locator("#mcp-slug").fill("zz-files");
    await page.locator("#mcp-args").fill("@example/notes-mcp");
    await expect(page.getByTestId("mcp-unpinned")).toContainText("@example/notes-mcp has no pinned version");
    const save = page.getByTestId("mcp-save");
    await expect(save).toBeDisabled();
    await expect(page.getByText("Tick the box above to save.")).toBeVisible();
    await page.getByTestId("mcp-stdio-ack").getByRole("checkbox").check();
    await expect(save).toBeEnabled();
    await page.locator("#mcp-args").fill("@example/notes-mcp@1.2.3");
    await expect(page.getByTestId("mcp-unpinned")).toHaveCount(0);
    await expect(save).toBeEnabled();
  });

  test("edit: masked values are shown and echoed back, slug is not an input", async ({ page }) => {
    const m = await boot(page);
    await page.getByRole("button", { name: "Edit zz-notes" }).click();
    const form = page.getByTestId("mcp-form");
    await expect(page.locator("#mcp-slug")).toHaveCount(0);
    await expect(form.getByText("zz-notes", { exact: true })).toBeVisible();
    await expect(page.locator("#mcp-url")).toBeFocused();
    const value = page.getByLabel("Header 1 value");
    await expect(value).toHaveValue(MASKED);
    await expect(value).toHaveAttribute("type", "password");
    await page.getByTestId("mcp-save").click();
    await expect(status(page)).toHaveText("Saved zz-notes.");
    const put = m.calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe("/api/mcp-servers/id-zz-notes");
    expect(put.body).toMatchObject({ headers: [{ name: "Authorization", value: MASKED }] });
  });

  test("review: server text renders literally, annotations are labelled, Enable comes last", async ({ page }) => {
    const hostile = "Search <b>bold</b> notes.";
    const m = await boot(page);
    m.q.test.push(testOut("hash-a", [
      tool("search_notes", { description: hostile, annotations: { readOnlyHint: true } }),
      tool("bad name", { usable_name: false }),
    ]));
    await page.getByRole("button", { name: "Test zz-notes" }).click();
    const panel = page.getByTestId("mcp-panel");
    await expect(panel.getByRole("heading", { name: "Tools from zz-notes" })).toBeFocused();
    await expect(page.getByTestId("mcp-tool")).toHaveCount(2);
    const first = page.locator('[data-testid="mcp-tool"][data-tool="search_notes"]');
    await expect(first.locator("pre").first()).toHaveText(hostile);
    await expect(panel.locator("pre b")).toHaveCount(0);
    await expect(panel.getByText("Claimed by the server")).toHaveCount(1);
    await expect(first.locator("pre").nth(2)).toContainText('"readOnlyHint": true');
    const bad = page.locator('[data-testid="mcp-tool"][data-tool="bad name"]');
    await expect(bad).toContainText("Unusable name");
    await expect(bad.getByTestId("mcp-policy")).toHaveCount(0);
    await expect(page.getByTestId("mcp-policy")).toHaveCount(1);
    const enableAfterPres = await panel.evaluate((el) => {
      const pres = el.querySelectorAll("pre");
      const btn = el.querySelector('[data-testid="mcp-enable"]')!;
      return !!(pres[pres.length - 1].compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(enableAfterPres).toBe(true);
    await expect(page.getByTestId("mcp-enable")).toHaveText("Enable server");
  });

  test("enable 409: the list is replaced and the second Enable sends the new hash", async ({ page }) => {
    const m = await boot(page);
    m.q.test.push(
      testOut("hash-a", [tool("search_notes", { description: "Old text." })]),
      testOut("hash-b", [tool("search_notes", { description: "New text from the server." })]),
    );
    m.q.enable.push({ status: 409, json: { detail: "tools changed" } });
    await page.getByRole("button", { name: "Test zz-notes" }).click();
    await page.getByTestId("mcp-enable").click();
    await expect(page.getByTestId("mcp-panel-error")).toHaveText(STALE);
    await expect(page.getByTestId("mcp-tool").locator("pre").first()).toHaveText("New text from the server.");
    await expect(page.getByTestId("mcp-enable")).toBeEnabled();
    await expect(page.getByTestId("mcp-enable")).toBeFocused();
    await page.getByTestId("mcp-enable").click();
    await expect(status(page)).toHaveText("zz-notes is now on.");
    await expect(rowOf(page, "zz-notes").getByTestId("mcp-status-chip")).toHaveText("On");
    const puts = m.calls.filter((c) => c.path.endsWith("/enabled")).map((c) => c.body);
    expect(puts).toEqual([
      { enabled: true, tools_hash: "hash-a" },
      { enabled: true, tools_hash: "hash-b" },
    ]);
  });

  test("policy: Always is saved immediately; a 422 reverts the select", async ({ page }) => {
    const m = await boot(page);
    await page.getByRole("button", { name: "Test zz-notes" }).click();
    const select = page.getByTestId("mcp-policy");
    await expect(select).toHaveValue("ask");
    await select.selectOption("always");
    await expect(status(page)).toHaveText("search_notes is now set to Always.");
    const put = m.calls.find((c) => c.path.endsWith("/tools/search_notes"))!;
    expect(put.path).toBe("/api/mcp-servers/id-zz-notes/tools/search_notes");
    expect(put.body).toEqual({ policy: "always" });
    m.q.tool.push({ status: 422, json: { detail: "nope" } });
    await select.selectOption("deny");
    await expect(page.getByTestId("mcp-tool-error")).toHaveText("Couldn't change search_notes: nope. It stays on Always.");
    await expect(select).toHaveValue("always");
  });

  test("changed tools: chip, Review button and Approve these tools", async ({ page }) => {
    const m = await boot(page, { list: [srv("zz-notes", { enabled: true, changed_count: 2 })] });
    m.q.test.push(testOut("hash-c", [
      tool("search_notes", { status: "changed" }),
      tool("list_notes", { status: "changed" }),
      tool("read_note", { status: "unchanged" }),
    ], { removed: ["old_tool"] }));
    const row = rowOf(page, "zz-notes");
    await expect(row.getByTestId("mcp-changed")).toHaveText("2 tools changed, review");
    await row.getByRole("button", { name: "Review zz-notes" }).click();
    await expect(page.getByTestId("mcp-enable")).toHaveText("Approve these tools");
    await expect(page.getByTestId("mcp-panel")).toContainText("2 changed, 1 no longer offered.");
    await expect(page.getByTestId("mcp-panel")).toContainText("No longer offered by the server: old_tool.");
  });

  test("delete: confirmation focuses Keep, Delete server removes the row", async ({ page }) => {
    const m = await boot(page);
    await page.getByRole("button", { name: "Delete zz-notes" }).click();
    await expect(page.getByTestId("mcp-delete-confirm")).toContainText("Delete zz-notes? This removes its address");
    await expect(page.getByTestId("mcp-keep")).toBeFocused();
    await page.getByTestId("mcp-delete").click();
    await expect(status(page)).toHaveText("zz-notes was deleted.");
    expect(m.calls.some((c) => c.method === "DELETE" && c.path === "/api/mcp-servers/id-zz-notes")).toBe(true);
    await expect(page.getByTestId("mcp-empty")).toBeVisible();
  });

  test("disable: one click sends enabled false and the row shows Off", async ({ page }) => {
    const m = await boot(page, { list: [srv("zz-notes", { enabled: true, changed_count: 0 })] });
    const row = rowOf(page, "zz-notes");
    await expect(row.getByTestId("mcp-status-chip")).toHaveText("On");
    await row.getByRole("button", { name: "Disable zz-notes" }).click();
    await expect(row.getByTestId("mcp-status-chip")).toHaveText("Off");
    await expect(status(page)).toHaveText("zz-notes is now off.");
    expect(m.calls.find((c) => c.path.endsWith("/enabled"))!.body).toEqual({ enabled: false });
    await expect(row.getByRole("button", { name: "Test zz-notes" })).toBeFocused();
  });
});
