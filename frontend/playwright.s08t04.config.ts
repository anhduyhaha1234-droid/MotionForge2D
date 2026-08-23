import { defineConfig, devices } from "@playwright/test";

/**
 * S08-T04-C2 Object Gallery QA (correction round, finding: GALLERY GENERATION
 * ISOLATION) — REAL isolated backend.
 *
 * Environment (started separately):
 *   - Backend  : output/s08-sprint/20260816-s08t04-c2-r1/run-qa-backend.sh
 *                → uvicorn app.main:app --port 8026, the isolated root +
 *                  deterministic + RECOMPUTE providers + MOTIONFORGE_EXTRACTION_QA_MODE=1
 *                  (inline; the production default fails closed).
 *   - Frontend : npm run dev -p 3012 (NEXT_PUBLIC_API_URL=http://localhost:8026)
 *
 * Projects (EVERY project excludes the others explicitly — verified via --list):
 *   - desktop     : interaction suite + generation isolation + visual screenshots
 *   - mobile-390px: read-only 390px suite (fresh isolated project) — never touches
 *                   desktop-mutated state; asserts NO horizontal overflow.
 * All evidence under output/s08-sprint/20260816-s08t04-c2-r1/ (never overwrites
 * the C1 or original run roots).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /s08-t04-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 240_000,
  outputDir:
    "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260816-s08t04-c2-r1/test-results",
  use: {
    baseURL: "http://localhost:3012",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "desktop",
      testMatch: /s08-t04-object-gallery\.spec\.ts|s08-t04-object-gallery-visual\.spec\.ts/,
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390px",
      testMatch: /s08-t04-object-gallery-mobile\.spec\.ts/,
      testIgnore: /object-gallery\.spec\.ts|s08-t04-object-gallery-visual\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
});
