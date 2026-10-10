import { test, expect } from "@playwright/test";
import { approverHeaderAllowed } from "../app/lib/approverAllowlist";

// ---------------------------------------------------------------------------
// Phase 33 Plan 01 — non-browser logic spec (D-05): pure modules only, no page
// fixture. Synthetic values throughout.
// ---------------------------------------------------------------------------

const U = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01";
const UPPER = U.toUpperCase();

test.describe("allowlist", () => {
  const allowed: [string, string, string][] = [
    ["GET", "proposals", ""],
    ["GET", "proposals", "?status=pending"],
    ["POST", `proposals/${U}/approve`, ""],
    ["POST", `proposals/${U}/reject`, ""],
    ["PATCH", `proposals/${U}/rows/0`, ""],
    ["PATCH", `proposals/${U}/rows/123456`, ""],
    ["post", `proposals/${U}/approve`, ""],
    ["POST", `proposals/${UPPER}/approve`, ""],
  ];
  for (const [m, p, s] of allowed) {
    test(`allows ${m} ${p}${s}`.replace(U, "<uuid>"), () => {
      expect(approverHeaderAllowed(m, p, s)).toBe(true);
    });
  }

  const denied: [string, string, string][] = [
    ["GET", "proposals/counts", ""],
    ["POST", `proposals/${U}/confirm`, ""],
    ["GET", "proposals", "?status=expired"],
    ["GET", "proposals", "?status=pending&x=1"],
    ["GET", "proposals", "?x=1"],
    ["GET", `proposals/${U}/approve`, ""],
    ["DELETE", `proposals/${U}`, ""],
    ["POST", `proposals/${U}/approve/`, ""],
    ["POST", `proposals/${U}/approve`, "?x=1"],
    ["POST", "proposals/abc/approve", ""],
    ["POST", `proposals/../proposals/${U}/approve`, ""],
    ["PATCH", `proposals/${U}/rows/abc`, ""],
    ["PATCH", `proposals/${U}/rows/1234567`, ""],
    ["HEAD", "proposals", ""],
    ["POST", `PROPOSALS/${U}/approve`, ""],
    ["GET", "transactions", ""],
  ];
  for (const [m, p, s] of denied) {
    test(`denies ${m} ${p}${s}`.replace(U, "<uuid>"), () => {
      expect(approverHeaderAllowed(m, p, s)).toBe(false);
    });
  }
});
