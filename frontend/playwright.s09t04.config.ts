import { defineConfig, devices } from "@playwright/test";

/**
 * S09-T04 Demo comparison QA — REAL backend (:8099) + REAL Next dev server
 * (:3014).  No route interception anywhere in the suite (route.fulfill is
 * forbidden by the task contract): the flow exercises the actual
 * /api/v2/s09-demo-compare endpoints against the deterministic s09 demo
 * pipeline.
 *
 * Environment (started separately — see output/.../t04/run-qa-backend.sh):
 *   - Backend  : bash output/s09/20260823_sprint_full/t04/run-qa-backend.sh
 *                → uvicorn app.main:app --port 8099 with isolated
 *                  MOTIONFORGE_ROOT under the task output dir.
 *   - Frontend : npx next dev -p 3014 with NEXT_PUBLIC_API_URL=http://localhost:8099
 *
 * Evidence root: output/s09/20260823_sprint_full/t04/e2e-results/
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s09-t04-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s09/20260823_sprint_full/t04/e2e-results",
  use: {
    baseURL: "http://localhost:3014",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s09-t04-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s09-t04-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
