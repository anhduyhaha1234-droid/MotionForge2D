import { defineConfig, devices } from "@playwright/test";

/**
 * S09-T06B-C1 production-stack E2E — the ACTUAL production backend
 * (`app.api.app:app`, port 8199, isolated temp DB under t06b-c1/) and a
 * production-mode Next.js server (`next start`, port 3114).
 *
 * NO qa_app_patch, NO fake router, NO monkeypatched commit, NO test-only
 * app — the correction + approval routers are mounted in production by
 * T56-INTEGRATION-C1 and this lane exercises them exactly as served.
 *
 * Environment started separately:
 *   - Backend : bash ../output/s09/20260823_sprint_full/t06b-c1/run-prod-backend.sh
 *   - Seeder  : python ../output/.../t06b-c1/run-prod-seed.py (global-setup)
 *   - Frontend: npx next build && npx next start -p 3114
 *               with NEXT_PUBLIC_API_URL=http://localhost:8199
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s09-t06bc1-.*\.spec\.ts/,
  globalSetup: "./e2e/s09-t06bc1-global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s09/20260823_sprint_full/t06b-c1/e2e-results",
  use: {
    baseURL: "http://localhost:3114",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      testMatch: /s09-t06bc1-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
