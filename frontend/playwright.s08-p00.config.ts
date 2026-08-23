import { defineConfig, devices } from "@playwright/test";

/**
 * S08-P00 integration smoke config — Import/Analyze + Character Library
 * against the REAL isolated integration backend.
 *
 * Environment (started separately):
 *   - Backend  : python -m uvicorn app.main:app --app-dir <worktree> --port 8003
 *                cwd + MOTIONFORGE_ROOT/OUTPUT/MODELS =
 *                output/s08-p00-integration/20260805-223518/backend-root
 *                (NEW isolated root/database; bootstrapped by the real lifespan)
 *   - Frontend : npm run dev -p 3011 (NEXT_PUBLIC_API_URL=http://localhost:8003)
 *   - Seed     : python output/s08-p00-integration/20260805-223518/qa-seed-s06-t05-p00.py
 *
 * P00 evidence tooling: all test-results and screenshots land under
 * output/s08-p00-integration/20260805-223518/ (reporter=list; no html report
 * writes; the visual specs capture desktop AND 390px internally, so the
 * mobile project only runs the interaction specs to avoid duplicates).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-p00-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir: "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-p00-integration/20260805-223518/test-results",
  use: {
    baseURL: "http://localhost:3011",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      // 390px mobile: the interaction specs must pass at mobile width; the
      // visual specs capture 390px themselves inside the desktop project.
      name: "mobile-390px",
      testIgnore: /visual\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
