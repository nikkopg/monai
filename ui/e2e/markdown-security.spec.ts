import { expect, test } from "@playwright/test";
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

  test("explicit GFM alignment wins over the numeric heuristic", () => {
    const html = render(
      ["| Name | Amount |", "| --- | :--- |", "| Food | 1,000 |"].join("\n"),
    );
    const td = html.match(/<td\s[^>]*>/g) ?? [];
    expect(td[1]).toContain("text-align:left");
    expect(td[1]).not.toContain("text-align:right");
  });

  test("a mixed text column is not right-aligned", () => {
    const html = render(
      ["| Name | Note |", "| --- | --- |", "| Food | 1,000 |", "| Fun | n/a |"].join("\n"),
    );
    expect(html).not.toContain("text-align:right");
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
