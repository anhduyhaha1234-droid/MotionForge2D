import { defineConfig, devices } from "@playwright/test";

/**
 * S08-A01-C1 — Taxonomy Safety Correction QA — REAL isolated backend.
 *
 * Environment (started separately, env inline so the MAIN DB can never be
 * targeted):
 *   - Backend  : output/s08-a01-c1/20260819-s08a01c1-r1/run-qa-backend-s08a01c1.sh
 *                → uvicorn app.main:app --port 8028, cwd + MOTIONFORGE_ROOT/
 *                  OUTPUT/MODELS = output/s08-a01-c1/20260819-s08a01c1-r1/backend-root,
 *                  MOTIONFORGE_EXTRACTION_QA_MODE=1 +
 *                  MOTIONFORGE_EXTRACTION_PROVIDER=deterministic.
 *   - Frontend : npm run dev -p 3013 (NEXT_PUBLIC_API_URL=http://localhost:8028)
 *
 * Projects (EVERY project excludes the others explicitly — verified via --list):
 *   - desktop     : F4 source_overlay reclassify + no-curation + F2 kind-safe
 *                   merge source guard.
 *   - mobile-390px: same contract at 390px, fresh project, no overflow.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-a01-c1.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 300_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01-c1/20260819-s08a01c1-r1/test-results",
  use: {
    baseURL: "http://localhost:3013",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s08-a01-c1\.spec\.ts/,
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-a01-c1-mobile\.spec\.ts/,
      testIgnore: /s08-a01-c1\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
