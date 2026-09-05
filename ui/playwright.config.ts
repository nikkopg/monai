import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// Sandbox note: Chromium is preinstalled at PLAYWRIGHT_BROWSERS_PATH
// (/opt/pw-browsers) with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 set — do NOT run
// `playwright install`. We prefer the default channel resolver first and only
// fall back to an explicit executablePath if a candidate path actually exists
// (WR-08: the old config pinned a hard-coded path that doesn't exist on every
// machine, so `browserType.launch` failed 9/9). If none of the candidates
// exist we leave executablePath undefined and let Playwright's own resolver
// find the installed browser cache.
const chromiumCandidates = [
  process.env.PLAYWRIGHT_CHROMIUM_PATH,
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
].filter((p): p is string => Boolean(p));
const chromiumPath = chromiumCandidates.find((p) => existsSync(p));

// Dedicated e2e port (WR-08): the app's own dev script serves :3001, which a
// stale pre-Phase-18 Docker frontend also occupies — `reuseExistingServer`
// would silently test that old build. Serve on :3099 instead so no running
// container can shadow the build under test.
const PORT = 3099;
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "line",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npx next dev -p ${PORT}`,
    url: baseURL,
    // Never reuse a foreign server in CI; locally, reuse only a server we
    // ourselves started on this dedicated port.
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: chromiumPath ? { executablePath: chromiumPath } : {},
      },
    },
  ],
});
