import { defineConfig, devices } from "@playwright/test";

/**
 * S08-T06 — Sprint-exit integrated E2E (T06-owned evidence tooling).
 *
 * Re-runs ALL S08 interaction suites (T04 gallery, T05 correction) plus the
 * T06 golden evidence spec against ONE fresh isolated backend root
 * (output/s08-sprint/20260816-s08t06-r1/backend-root).
 *
 * The OLD visual specs (s08-t04-...-visual.spec.ts / s08-t05-...-visual.spec.ts)
 * are intentionally EXCLUDED: their screenshot dirs are hardcoded to the
 * T04/T05 run dirs, and sprint-exit must not overwrite sibling-task evidence.
 * NEW screenshots come from the T06-owned spec (s08-t06-golden-evidence.spec.ts).
 *
 * Environment (started separately, env inline so the MAIN DB can never be
 * targeted):
 *   - Backend  : uvicorn app.main:app --port 8014, cwd + MOTIONFORGE_ROOT/
 *                 OUTPUT/MODELS = output/s08-sprint/20260816-s08t06-r1/backend-root,
 *                 MOTIONFORGE_EXTRACTION_PROVIDER=deterministic.
 *   - Frontend : npm run dev -p 3012 (NEXT_PUBLIC_API_URL=http://localhost:8014)
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-t0(4|5|6)-.*\.spec\.ts/,
  testIgnore: /visual\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260818-s08t06-c2/test-results",
  use: {
    baseURL: "http://localhost:3012",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testIgnore: /(mobile|visual)\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-t0(4|5|6)-.*mobile\.spec\.ts/,
      testIgnore: /visual\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
