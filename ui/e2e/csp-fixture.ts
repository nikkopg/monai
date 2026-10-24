// CSP violation collector shared by specs (D-11). watchCsp must run before
// navigation; the init script records every securitypolicyviolation event.
import type { Page } from "@playwright/test";

export async function watchCsp(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: { directive: string; uri: string }[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      w.__csp.push({ directive: e.violatedDirective, uri: e.blockedURI });
    });
  });
}

export async function cspViolations(page: Page): Promise<{ directive: string; uri: string }[]> {
  return page.evaluate(() => (window as unknown as { __csp?: { directive: string; uri: string }[] }).__csp ?? []);
}
