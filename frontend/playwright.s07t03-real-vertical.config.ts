import { defineConfig, devices } from "@playwright/test";

/**
 * S07-T03 REAL VERTICAL — desktop + 390px Scenario I
 * Uses real Object Gallery route (/object-gallery?project=...&video=...) and real backend
 * (temp SQLite via MOTIONFORGE_ROOT). ZERO route.fulfill for /api/v2/project-cast*.
 * Seed via production API/repository (real temp DB), not mocks.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s07-t03-real-vertical\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "line",
  timeout: 180_000,
  globalSetup: "./e2e/s07-t03-global-setup.ts",
  use: {
    baseURL: "http://localhost:3014",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8004 --log-level warning",
      url: "http://127.0.0.1:8004/openapi.json",
      reuseExistingServer: false,
      timeout: 120_000,
      cwd: "../",
      env: {
        MOTIONFORGE_ROOT: "C:/Users/Admin/AppData/Local/Temp/s07t03-real-vertical",
        MOTIONFORGE_QA_MODE: "1",
        MOTIONFORGE_CORS_ORIGINS: "http://localhost:3014,http://127.0.0.1:3014",
      },
    },
    {
      command: "npm run dev -- --port 3014",
      url: "http://localhost:3014/object-gallery",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:8004",
      },
    },
  ],
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
