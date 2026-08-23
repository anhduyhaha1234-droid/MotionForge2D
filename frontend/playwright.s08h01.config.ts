import { defineConfig, devices } from "@playwright/test";

/**
 * S08-H01 (correction finding F — production authority) E2E — REAL isolated backend.
 *
 * Environment (the backend is started by the spec itself via the run root's
 * run-qa-backend.sh on port 8026; frontend dev server started separately):
 *   - Backend  : uvicorn app.main:app --port 8026, cwd + MOTIONFORGE_ROOT/
 *                OUTPUT/MODELS = output/s08-sprint/20260817-s08h01-r1/backend-root,
 *                MOTIONFORGE_EXTRACTION_PROVIDER=deterministic.
 *   - Frontend : npm run dev -p 3013 (NEXT_PUBLIC_API_URL=http://localhost:8026)
 *
 * The spec exercises REAL error paths only (404 not-found against the real
 * API; connection-refused by killing/restarting the real QA backend via
 * taskkill + run-qa-backend.sh) — no page.route() mock interception.
 *
 * Projects (each excludes the other — verified via --list):
 *   - desktop      : s08-h01-production-authority.spec.ts
 *   - mobile-390px : s08-h01-production-authority-mobile.spec.ts
 * All evidence under output/s08-sprint/20260817-s08h01-r1/ (fresh root — never
 * overwrites previous run screenshots).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-h01-.*\.spec\.ts/,
  testIgnore: /helpers\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 300_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260817-s08h01-r1/test-results",
  use: {
    baseURL: "http://localhost:3013",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s08-h01-production-authority\.spec\.ts/,
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-h01-production-authority-mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
