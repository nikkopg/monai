import { defineConfig, devices } from "@playwright/test";

// Sandbox note: Chromium is preinstalled at PLAYWRIGHT_BROWSERS_PATH
// (/opt/pw-browsers) with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 set — do NOT run
// `playwright install`. We prefer the default channel resolver first and only
// fall back to an explicit executablePath if PLAYWRIGHT_CHROMIUM_PATH is set
// (or, absent that, the known preinstalled binary) so this config still works
// on machines with a normally-installed Playwright browser cache.
const fallbackChromiumPath =
  process.env.PLAYWRIGHT_CHROMIUM_PATH ||
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:3001",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          executablePath: fallbackChromiumPath,
        },
      },
    },
  ],
});
