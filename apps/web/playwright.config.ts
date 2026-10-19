import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against the running stack (`make up` + `make migrate`), not a dev server:
 * they check what the user actually sees. Chromium only, to keep the download small.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // The API is one Python process and is already busy with two workers: more workers only add
  // waiting (4 workers: as fast overall, pages twice as slow, tests past their timeouts).
  // CI keeps Playwright's default (at most 2 on its runners). Override with --workers.
  workers: process.env.CI ? undefined : 2,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
