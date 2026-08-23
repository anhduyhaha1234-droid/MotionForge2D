import { defineConfig, devices } from "@playwright/test";

/**
 * S05-T05 QA config — Import/Analyze UI against the REAL backend.
 *
 * Frontend dev server runs on :3011 (NEXT_PUBLIC_API_URL=http://localhost:8002
 * via frontend/.env.local; :3010 is owned by an S06 worktree dev server, so
 * S05-T05 uses :3011); the backend runs on :8002 rooted at the worktree
 * QA root (cwd = output/qa-root, MOTIONFORGE_ROOT set) with its durable
 * worker started by the FastAPI lifespan. Servers are started separately —
 * this config intentionally does NOT auto-start them (same convention as
 * playwright.config.ts).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /import-analyze\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-s05t05" }]],
  timeout: 180_000,
  use: {
    baseURL: "http://localhost:3011",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      // S05-C04-R3: the cancel interaction must also be proven at 390px
      // mobile (Codex finding 1 evidence). Run with `--grep cancel` so
      // only the cancel case runs on this project.
      name: "mobile-390px",
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
