// D-11 CSP header e2e. Synthetic values; /api/* is stubbed (in dev it would
// proxy to the live backend, so nothing here may reach it unmocked).
import { test, expect } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";

const RUN = "00000000-0000-4000-8000-0000000000a1";
const sse = (...events: unknown[]) =>
  events.map((e) => `data: ${typeof e === "string" ? e : JSON.stringify(e)}\n\n`).join("");

test.describe("Content-Security-Policy (D-11)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/\/api\/threads$/, (route) => route.fulfill({ json: [] }));
  });

  test("the chat document carries the policy", async ({ page }) => {
    const res = await page.goto("/chat");
    const csp = res?.headers()["content-security-policy"] ?? "";
    for (const d of ["img-src 'self' data:", "connect-src 'self'", "frame-ancestors 'none'", "object-src 'none'"]) {
      expect(csp).toContain(d);
    }
  });

  test("a 404 route carries the policy too", async ({ page }) => {
    const res = await page.goto("/no-such-route-synthetic");
    expect(res?.status()).toBe(404);
    expect(res?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  });

  test("a rendered answer causes no violations", async ({ page }) => {
    await watchCsp(page);
    await page.route(/\/api\/query-stream$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sse(
          { type: "run", run_id: RUN },
          { type: "answer", text: "**Synthetic** answer with a list:\n\n- one\n- two", proposals: [], trace: [] },
          "[DONE]",
        ),
      }),
    );
    await page.goto("/chat");
    await page.getByLabel("Ask monai a question").fill("Synthetic question?");
    await page.getByLabel("Ask monai a question").press("Enter");
    await expect(page.locator('[data-testid="answer"]')).toContainText("Synthetic");
    expect(await cspViolations(page)).toEqual([]);
  });

  test("control: an image and a fetch to another host are reported", async ({ page }) => {
    await watchCsp(page);
    await page.goto("/chat");
    await page.evaluate(async () => {
      new Image().src = "https://evil.example/x.png";
      await fetch("https://evil.example/").catch(() => undefined);
    });
    await expect.poll(async () => (await cspViolations(page)).map((v) => v.directive).sort()).toEqual(
      expect.arrayContaining(["connect-src", "img-src"]),
    );
  });
});
