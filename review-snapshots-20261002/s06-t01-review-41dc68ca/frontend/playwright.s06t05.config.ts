import { defineConfig, devices } from "@playwright/test";

/** S06-T05 focused config — runs ONLY the Pack Review & Publish UX specs
 *  against the real QA backend (localhost:8002) and frontend dev server
 *  (localhost:3010). Serial, chromium desktop; the visual spec sets its own
 *  mobile viewport for the 390px check. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /pack-publish-ux.*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "line",
  timeout: 120_000,
  use: {
    baseURL: "http://localhost:3010",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
