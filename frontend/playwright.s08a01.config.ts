import { defineConfig, devices } from "@playwright/test";

/**
 * S08-A01 — Source-Locked 2D Role Taxonomy Bridge QA — REAL isolated backend.
 *
 * Environment (started separately, env inline so the MAIN DB can never be
 * targeted):
 *   - Backend  : output/s08-a01/20260819-s08a01-r1/run-qa-backend.sh
 *                → uvicorn app.main:app --port 8027, cwd + MOTIONFORGE_ROOT/
 *                  OUTPUT/MODELS = output/s08-a01/20260819-s08a01-r1/backend-root,
 *                  MOTIONFORGE_EXTRACTION_QA_MODE=1 +
 *                  MOTIONFORGE_EXTRACTION_PROVIDER=deterministic.
 *   - Frontend : npm run dev -p 3013 (NEXT_PUBLIC_API_URL=http://localhost:8027)
 *
 * Projects (EVERY project excludes the others explicitly — verified via --list):
 *   - desktop     : interaction suite (filter bar, removal-only, filtering)
 *   - mobile-390px: 390px no-overflow + removal-only suite (fresh project)
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-a01-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 300_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01/20260819-s08a01-r1/test-results",
  use: {
    baseURL: "http://localhost:3013",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s08-a01-role-taxonomy\.spec\.ts/,
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-a01-.*-mobile\.spec\.ts/,
      testIgnore: /role-taxonomy\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
