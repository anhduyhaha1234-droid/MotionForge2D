import { defineConfig, devices } from "@playwright/test";

/** S07-T02 Library Picker + Compatibility — desktop + 390px against REAL object-gallery. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s07-picker.*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "line",
  timeout: 120_000,
  use: {
    baseURL: "http://localhost:3012",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 3012",
    url: "http://localhost:3012/object-gallery",
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_API_URL: "http://localhost:8002",
    },
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-390",
      use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } },
    },
  ],
});
