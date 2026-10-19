// Settings Skills card e2e (phase 40, plan 02): status in words, raw-text review
// panel, hash-echo enable with 409 recovery, one-click disable, no HTML rendering.
// Every API is mocked; all values are synthetic (public repo).
import { test, expect, type Page } from "@playwright/test";

const INSTRUCTIONS = "Skills are instructions only. monai never runs scripts or code from a skill folder.";
const OFF = "zzeval-monthly-review";
const ON = "how-i-categorise";
const CHANGED = "zzeval-changed";
const BROKEN = "zzeval-broken";
const STALE =
  "This skill changed after you opened it. The text below is the new version. Read it, then enable it again.";

const row = (name: string, o: Record<string, unknown> = {}) => ({
  name, description: "Use when the owner asks for the monthly review checklist.", valid: true, reason: null,
  enabled: false, changed: false, declares_allowed_tools: false, ...o,
});
const ROWS = [
  row(OFF),
  row(ON, { description: "Use when the owner asks how a purchase is categorised.", enabled: true, declares_allowed_tools: true }),
  row(CHANGED, { description: "Use when the owner asks about the changed checklist.", enabled: true, changed: true }),
  row(BROKEN, { description: "", valid: false, reason: "no frontmatter" }),
];
const HOSTILE = '# heading\n\nSome **bold** text.\n<img src=x onerror="window.__pwned=1">\n';
const detail = (hash: string, content = HOSTILE) => ({
  name: OFF, description: "Use when the owner asks for the monthly review checklist.", content, hash,
  files: [
    { path: "SKILL.md", text: content },
    { path: "references/format.md", text: "Line one of the format.\nLine two." },
    { path: "references/big.md", reason: "file is larger than 6000 bytes" },
  ],
});

type Put = { status?: number; json?: unknown; onHit?: () => void };
type Mock = {
  list: unknown; listStatus: number; detail: unknown;
  puts: { name: string; body: Record<string, unknown> }[]; queue: Put[];
};

/** Keeps every request off the live backend, then mocks the skills routes. */
async function boot(page: Page, init: Partial<Mock> = {}): Promise<Mock> {
  const m: Mock = { list: ROWS, listStatus: 200, detail: detail("zzhash-a"), puts: [], queue: [], ...init };
  await page.route("**/api/**", (r) => r.fulfill({ status: 503, json: { detail: "mocked" } }));
  await page.route("**/api/skills", (r) =>
    m.listStatus === 200
      ? r.fulfill({ json: m.list })
      : r.fulfill({ status: m.listStatus, json: { detail: "boom" } }));
  await page.route("**/api/skills/*", (r) => {
    const name = decodeURIComponent(new URL(r.request().url()).pathname.split("/").pop()!);
    if (r.request().method() === "GET") return r.fulfill({ json: m.detail });
    const body = r.request().postDataJSON();
    m.puts.push({ name, body });
    const next = m.queue.shift() ?? {};
    next.onHit?.();
    if ((next.status ?? 200) === 200 && Array.isArray(m.list)) {
      m.list = (m.list as Record<string, unknown>[]).map((s) =>
        s.name === name ? { ...s, enabled: body.enabled, changed: false } : s);
    }
    return r.fulfill({ status: next.status ?? 200, json: next.json ?? { ok: true } });
  });
  await page.goto("/settings");
  return m;
}

const rowOf = (page: Page, name: string) => page.locator(`[data-testid="skill-row"][data-skill="${name}"]`);
const panel = (page: Page) => page.getByTestId("skill-panel");

test.describe("/settings Skills card", () => {
  test("instructions line is verbatim and always shown", async ({ page }) => {
    await boot(page);
    await expect(page.getByText(INSTRUCTIONS, { exact: true })).toBeVisible();
    await expect(page.getByTestId("skill-row")).toHaveCount(4);
    const empty = await page.context().newPage();
    await boot(empty, { list: [] });
    await expect(empty.getByText(INSTRUCTIONS, { exact: true })).toBeVisible();
  });

  test("empty folder shows the empty state", async ({ page }) => {
    await boot(page, { list: [] });
    await expect(page.getByTestId("skills-empty")).toContainText("No skills found.");
  });

  test("rows show status by words", async ({ page }) => {
    await boot(page);
    const chips = page.getByTestId("skill-status");
    await expect(chips).toHaveText(["Off", "On", "Changed since enabled", "Invalid"]);

    const buttons = (name: string) => rowOf(page, name).getByRole("button");
    await expect(buttons(OFF)).toHaveText(["View"]);
    await expect(buttons(ON)).toHaveText(["View", "Disable"]);
    await expect(buttons(CHANGED)).toHaveText(["Review", "Disable"]);
    await expect(rowOf(page, CHANGED)).toContainText(
      "Changed since you enabled it, so the agent can't see it. Review it and enable it again, or disable it.");
    await expect(rowOf(page, BROKEN)).toContainText(
      "No frontmatter. Fix the file in the skills folder, then reload this page.");
    await expect(buttons(BROKEN)).toHaveCount(0);
    await expect(rowOf(page, ON)).toContainText("This skill declares allowed-tools. It is ignored.");
    await expect(rowOf(page, OFF)).not.toContainText("This skill declares allowed-tools.");
  });

  test("view panel shows every file raw, Enable last", async ({ page }) => {
    await boot(page);
    await page.getByRole("button", { name: `View ${OFF}` }).click();
    await expect(panel(page)).toContainText(
      `${OFF}: Use when the owner asks for the monthly review checklist.`);
    await expect(page.getByTestId("skill-content")).toContainText("**bold**");
    await expect(page.getByTestId("skill-file")).toHaveCount(2);
    await expect(panel(page)).toContainText("Not shown: file is larger than 6000 bytes. The agent can't read it either.");
    await expect(page.getByTestId("skill-enable")).toHaveText("Enable skill");
    const enableLast = await panel(page).evaluate((p) => {
      const pres = p.querySelectorAll("pre");
      const enable = p.querySelector('[data-testid="skill-enable"]')!;
      const last = pres[pres.length - 1];
      return pres.length === 2 && !!(last.compareDocumentPosition(enable) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(enableLast).toBe(true);
  });

  test("skill text renders as text, never HTML", async ({ page }) => {
    await boot(page);
    await page.getByRole("button", { name: `View ${OFF}` }).click();
    await expect(page.getByTestId("skill-content")).toContainText('<img src=x');
    await expect(panel(page).locator("img")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });

  test("enable sends the viewed hash and announces", async ({ page }) => {
    const m = await boot(page);
    await page.getByRole("button", { name: `View ${OFF}` }).click();
    await page.getByTestId("skill-enable").click();
    await expect(page.getByTestId("skills-status")).toHaveText(`${OFF} is now on.`);
    await expect(panel(page)).toHaveCount(0);
    expect(m.puts).toEqual([{ name: OFF, body: { enabled: true, hash: "zzhash-a" } }]);
    await expect(rowOf(page, OFF).getByTestId("skill-status")).toHaveText("On");
  });

  test("a 409 keeps the panel open with the new text", async ({ page }) => {
    const m = await boot(page, {
      queue: [{ status: 409, json: { detail: "stale" } }],
    });
    m.queue[0].onHit = () => { m.detail = detail("zzhash-b", "# New text\nNothing hostile here.\n"); };
    await page.getByRole("button", { name: `View ${OFF}` }).click();
    await page.getByTestId("skill-enable").click();
    await expect(page.getByTestId("skill-error")).toHaveText(STALE);
    await expect(page.getByTestId("skill-content")).toContainText("Nothing hostile here.");
    await expect(panel(page)).toBeVisible();
    await expect(page.getByTestId("skill-enable")).toBeEnabled();
    await page.getByTestId("skill-enable").click();
    await expect(page.getByTestId("skills-status")).toHaveText(`${OFF} is now on.`);
    expect(m.puts.map((p) => p.body)).toEqual([
      { enabled: true, hash: "zzhash-a" },
      { enabled: true, hash: "zzhash-b" },
    ]);
  });

  test("disable is one click", async ({ page }) => {
    const m = await boot(page);
    await page.getByRole("button", { name: `Disable ${ON}` }).click();
    await expect(page.getByTestId("skills-status")).toHaveText(`${ON} is now off.`);
    expect(m.puts).toEqual([{ name: ON, body: { enabled: false } }]);
    await expect(rowOf(page, ON).getByTestId("skill-status")).toHaveText("Off");
  });

  test("an enabled pack that went invalid or missing can still be disabled", async ({ page }) => {
    // WR-04: the approval survives invalidity, so revoking it must stay possible.
    const GONE = "zzeval-gone";
    const m = await boot(page, {
      list: [
        row(BROKEN, { description: "", valid: false, reason: "no frontmatter", enabled: true }),
        row(GONE, { description: "", valid: false, reason: "skill folder not found", enabled: true, changed: true }),
      ],
    });
    const note = "Still enabled: it turns back on if the files return to the text you approved. Disable it to revoke that.";
    for (const name of [BROKEN, GONE]) {
      await expect(rowOf(page, name).getByRole("button")).toHaveText(["Disable"]);
      await expect(rowOf(page, name)).toContainText(note);
    }
    await page.getByRole("button", { name: `Disable ${GONE}` }).click();
    await expect(page.getByTestId("skills-status")).toHaveText(`${GONE} is now off.`);
    expect(m.puts).toEqual([{ name: GONE, body: { enabled: false } }]);
    await expect(rowOf(page, GONE).getByRole("button")).toHaveCount(0);
    await expect(rowOf(page, GONE)).not.toContainText(note);
  });

  test("list load error offers Try again", async ({ page }) => {
    const m = await boot(page, { listStatus: 500 });
    await expect(page.getByTestId("skills-load-error")).toContainText(
      "Couldn't load skills: boom. Check the backend is running, then try again.");
    await expect(page.getByText(INSTRUCTIONS, { exact: true })).toBeVisible();
    m.listStatus = 200;
    await page.getByTestId("skills-retry").click();
    await expect(page.getByTestId("skill-row")).toHaveCount(4);
  });

  test("Escape closes the panel and returns focus", async ({ page }) => {
    await boot(page);
    const view = page.getByRole("button", { name: `View ${OFF}` });
    await view.click();
    await expect(panel(page)).toBeVisible();
    await expect(panel(page).getByRole("heading", { name: OFF })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(panel(page)).toHaveCount(0);
    await expect(view).toBeFocused();
  });
});
