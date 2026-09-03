import { defineConfig, devices } from "@playwright/test";

/**
 * S11-T04D Review Queue — E2E + a11y/mobile (own ports/roots, REAL backend).
 *
 * Environment (started separately, ports RIÊNG — không đụng 8888/8201/8212/8025/8026):
 *   - Backend  : uvicorn app.main:app --port 8413
 *                MOTIONFORGE_QA_MODE=1 MOTIONFORGE_ROOT=%TEMP%/s11t04d_root
 *                MOTIONFORGE_EXTRACTION_QA_MODE=1 MOTIONFORGE_EXTRACTION_PROVIDER=deterministic
 *   - Frontend : npx next dev -p 3013 (NEXT_PUBLIC_API_URL=http://localhost:8413)
 *   - Seed     : e2e seed script (temp) — real project/video/roles/occurrences via HTTP,
 *                QC items via QCItemRepository on the QA root DB (Decision A: no public POST).
 *
 * Tests:
 *   - s11-t04-review.spec.ts : Scenario D (queue->item->gallery frame f role R->
 *                              correction preview->confirm, KHÔNG full timeline),
 *                              default blocker-first, warnings collapsible, empty/loading/
 *                              error/refresher, non-blocking recompute progress,
 *                              zero accepted-exception controls
 *   - s11-t04-a11y.spec.ts   : 8 a11y/mobile gates (keyboard-complete, dialog focus
 *                              management, severity icon+text, touch >=min-h-10,
 *                              role status/alert, reduced-motion, zoom 200%, 390px sheet)
 *
 * outputDir + evidence RIÊNG của task — KHÔNG bao giờ ghi frontend/test-results
 * (.last-run.json canonical).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s11-t04-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/AppData/Local/Temp/s11t04d_pw/test-results",
  use: {
    baseURL: "http://localhost:3013",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});