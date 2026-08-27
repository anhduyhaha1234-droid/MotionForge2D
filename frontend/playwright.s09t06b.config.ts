import { defineConfig, devices } from "@playwright/test";

/**
 * S09-T06B Approval UI/E2E QA — REAL backend (:8099) + REAL Next dev
 * server (:3014).  No route interception anywhere (the task contract
 * forbids mocks): the flow exercises the actual /api/v2/s09-approvals +
 * /api/v2/s09-corrections + structural-evidence + durable projects +
 * reskin-configs endpoints against the seeded isolated SQLite under
 * output/s09/20260823_sprint_full/t06b/.
 *
 * Environment (started separately):
 *   - Backend  : bash output/s09/20260823_sprint_full/t06b/run-qa-backend.sh
 *                → uvicorn qa_app_patch:app --port 8099 (production app with
 *                  BOTH S09 routers mounted at runtime).
 *   - Seeder   : PYTHONPATH=<worktree> python .../t06b/run-qa-seed.py
 *   - Frontend : npx next dev -p 3014 with NEXT_PUBLIC_API_URL=http://localhost:8099
 *
 * Evidence root: output/s09/20260823_sprint_full/t06b/e2e-results/
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s09-t06b-.*\.spec\.ts/,
  globalSetup: "./e2e/s09-t06b-global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s09/20260823_sprint_full/t06b/e2e-results",
  use: {
    baseURL: "http://localhost:3014",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s09-t06b-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s09-t06b-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
