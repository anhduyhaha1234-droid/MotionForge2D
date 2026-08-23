import { defineConfig, devices } from "@playwright/test";

/**
 * S07-T03 REAL VERTICAL (correction C1) — desktop + 390px FULL Scenario I.
 *
 * Production route ONLY: /object-gallery?project=...&video=...
 * The stale /test-s07-t03 harness route is DELETED and must never be
 * recreated. ZERO route.fulfill for /api/v2/project-cast* — the UI talks to
 * the real backend (temp SQLite seeded via global-setup).
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
      command:
        "python frontend/e2e/s07-t03-boot-backend.py",
      url: "http://127.0.0.1:8004/openapi.json",
      reuseExistingServer: false,
      timeout: 180_000,
      cwd: "../",
      env: {
        MOTIONFORGE_ROOT: "C:/Users/Admin/AppData/Local/Temp/s07t03-real-vertical",
        MOTIONFORGE_QA_MODE: "1",
        MOTIONFORGE_CORS_ORIGINS:
          "http://localhost:3014,http://127.0.0.1:3014,http://localhost:3013,http://127.0.0.1:3013",
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
