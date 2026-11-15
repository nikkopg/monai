import { test, expect } from "@playwright/test";
import { UI_PASSWORD } from "../playwright.config";

// Nothing authenticates here except the cookie from /login: no stored session,
// and a Basic credential scoped to an origin the tests never visit.
test.use({
  storageState: { cookies: [], origins: [] },
  httpCredentials: { username: "none", password: "none", origin: "https://unused.invalid" },
});

const ALERT = '[role="alert"]:not(#__next-route-announcer__)';

test("protected page -> /login -> wrong password -> right password lands on next", async ({ page, context }) => {
  // Whatever page we land on must never reach the live backend.
  const apiCalls: string[] = [];
  await page.route("**/api/**", (route) => {
    apiCalls.push(route.request().url());
    return route.fulfill({ status: 503, body: "" });
  });

  await page.goto("/records");
  await expect(page).toHaveURL(/\/login\?next=%2Frecords$/);
  await expect(page.locator(".app-panel")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  expect(apiCalls).toEqual([]);

  await page.getByLabel("Password").fill("wrong-password-synthetic");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login\?error=1&next=%2Frecords$/);
  await expect(page.locator(ALERT)).toHaveText("That password didn't match. Try again.");
  const pw = page.getByLabel("Password");
  await expect(pw).toHaveAttribute("aria-invalid", "true");
  await expect(pw).toHaveAttribute("aria-describedby", "pw-err");
  expect(apiCalls).toEqual([]);

  await pw.fill(UI_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/records$/);
  await expect(page.locator(".app-panel")).toBeVisible();

  const cookie = (await context.cookies()).find((c) => c.name === "monai_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
});

test("signs in with JavaScript disabled", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, javaScriptEnabled: false, storageState: { cookies: [], origins: [] } });
  try {
    const page = await context.newPage();
    await page.route("**/api/**", (route) => route.fulfill({ status: 503, body: "" }));
    await page.goto("/records");
    await expect(page).toHaveURL(/\/login\?next=%2Frecords$/);
    await page.getByLabel("Password").fill(UI_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/records$/);
  } finally {
    await context.close();
  }
});

// tailscale serve passes Host through and sets X-Forwarded-Proto; synthetic host.
const via = { Host: "box.example.ts.net", "X-Forwarded-Proto": "https" };

test("redirects keep the host the browser used (reverse proxy)", async ({ page }) => {
  const gate = await page.request.get("/cashflow", { headers: via, maxRedirects: 0 });
  expect(gate.status()).toBe(307);
  expect(gate.headers()["location"]).toBe("https://box.example.ts.net/login?next=%2Fcashflow");
});
