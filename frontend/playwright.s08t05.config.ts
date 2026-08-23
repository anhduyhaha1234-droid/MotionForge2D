import { defineConfig, devices } from "@playwright/test";

// The S08-T04-C2 shared helpers retargeted QA_API_BASE (default 8025).  The
// S08-T05 QA harness is a dedicated backend on 8014 — pin it here so the
// suite is hermetic (an explicit shell QA_API_BASE still wins).
process.env.QA_API_BASE ??= "http://localhost:8014";

/**
 * S08-T05 Targeted Object Correction QA — REAL isolated backend.
 *
 * Environment (started separately):
 *   - Backend  : uvicorn app.main:app --port 8014, cwd + MOTIONFORGE_ROOT/
 *                 OUTPUT/MODELS = output/s08-sprint/20260817-s08t05-c2-r1/backend-root,
 *                 MOTIONFORGE_EXTRACTION_PROVIDER=deterministic (explicit QA
 *                 selection; the production default path fails closed).
 *   - Frontend : npm run dev -p 3012 (NEXT_PUBLIC_API_URL=http://localhost:8014)
 *
 * Project isolation (S08-T05-C2): the top-level testMatch already limits to
 * S08-T05 specs only; the desktop project ignores mobile specs and the
 * mobile project matches ONLY the S08-T05 mobile spec — H01/T04 specs can
 * never appear in `--list` for this config.
 *
 * Projects:
 *   - desktop    : full correction-flow suite (scope before confirmation,
 *                  reassign/edit/merge/split through the correction API,
 *                  recompute strip terminal outcome, regenerated media after
 *                  completion AND reload, escape = zero mutations)
 *   - mobile-390 : 390px suite (own isolated QA project)
 * All evidence under output/s08-sprint/20260817-s08t05-c2-r1/.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-t05-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260817-s08t05-c2-r1/test-results",
  use: {
    baseURL: "http://localhost:3012",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-t05-.*mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
