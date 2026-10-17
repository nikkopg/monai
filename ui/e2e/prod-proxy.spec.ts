// Production-proxy checks (phase 37 plan 09): SSE incrementality, the Incomplete
// path and the CSP through a real `next build` + `next start` in front of the
// chunked fake backend (support/fake-sse-backend.cjs). Skipped unless
// PROD_BASE_URL is set; see the 37-09 SUMMARY for the scratch-build recipe.
// All values are synthetic.
import http from "node:http";

import { test, expect, type Page } from "@playwright/test";

import { cspViolations, watchCsp } from "./csp-fixture";

const BASE = process.env.PROD_BASE_URL ?? "";
const input = (page: Page) => page.getByLabel("Ask monai a question");
const alertBox = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');

test.describe("production proxy", () => {
  test.skip(!process.env.PROD_BASE_URL, "needs the scratch production build (37-09 recipe)");

  test("SSE chunks arrive spread over time, uncompressed", async () => {
    const url = new URL(`${BASE}/api/query-stream`);
    const t0 = Date.now();
    const arrivals: number[] = [];
    const encoding = await new Promise<string | string[] | undefined>((resolve, reject) => {
      const req = http.request(
        {
          host: url.hostname,
          port: url.port,
          path: url.pathname,
          method: "POST",
          headers: { "content-type": "application/json", "accept-encoding": "gzip, deflate, br" },
        },
        (res) => {
          res.on("data", (chunk: Buffer) => {
            const n = chunk.toString().split("\n\n").filter((s) => s.startsWith("data:")).length;
            for (let i = 0; i < n; i++) arrivals.push(Date.now() - t0);
          });
          res.on("end", () => resolve(res.headers["content-encoding"]));
          res.on("error", reject);
        },
      );
      req.on("error", reject);
      req.end(JSON.stringify({ question: "How much did I spend on food?" }));
    });
    console.log(`prod-proxy arrivals (ms): ${arrivals.join(", ")}`);
    expect(encoding).toBeUndefined();
    expect(arrivals[0]).toBeLessThan(1000);
    expect(arrivals.length).toBeGreaterThanOrEqual(6);
    expect(arrivals[arrivals.length - 1] - arrivals[0]).toBeGreaterThan(1500);
  });

  test("the chat renders tokens before the answer", async ({ page }) => {
    await page.goto("/chat");
    await input(page).fill("How much did I spend on food?");
    await input(page).press("Enter");
    const box = page.getByTestId("answer");
    await expect(box).toContainText("w1");
    await expect(box).not.toContainText("w6");
    await expect(box).toHaveAttribute("aria-busy", "true");
    await expect(box).toHaveText("w0 w1 w2 w3 w4 w5 w6 w7 done", { timeout: 15_000 });
  });

  test("a mid-stream close shows Incomplete and none of the partial", async ({ page }) => {
    await page.goto("/chat");
    await input(page).fill("close-early please");
    await input(page).press("Enter");
    const alert = alertBox(page);
    await expect(alert).toContainText("Incomplete answer");
    await expect(alert.getByRole("button", { name: "Ask again" })).toBeVisible();
    await page.waitForTimeout(300);
    await expect(page.getByText("w0")).toHaveCount(0);
  });

  test("the CSP header is on pages and API routes", async ({ request }) => {
    for (const path of ["/chat", "/api/threads"]) {
      const csp = (await request.get(`${BASE}${path}`)).headers()["content-security-policy"] ?? "";
      expect(csp, path).toContain("connect-src 'self'");
      expect(csp, path).toContain("img-src 'self' data:");
      expect(csp, path).not.toContain("unsafe-eval");
    }
  });

  test("every page loads with zero CSP violations", async ({ page }) => {
    const refused: string[] = [];
    page.on("console", (m) => {
      if (m.text().startsWith("Refused to")) refused.push(m.text());
    });
    await watchCsp(page);
    await page.route("**/api/**", (r) => r.fulfill({ json: [] }));
    for (const path of ["/", "/cashflow", "/chat", "/records", "/investments", "/settings", "/inbox"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await cspViolations(page), path).toEqual([]);
    }
    expect(refused).toEqual([]);
  });
});
