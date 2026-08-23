import { defineConfig } from "@playwright/test";

/**
 * S05-C04-R2 visual QA config — desktop + 390px screenshots of the
 * Import/Analyze UI against the REAL isolated C04 backend (frontend
 * :3011, backend :8003 rooted at output/s05-c04-r2-evidence/backend-root).
 *
 * C04-specific: screenshots land in
 * output/s05-c04-r2-evidence/screenshots/ (NEW C04 evidence dir — the
 * existing C01 screenshots are never touched). The html reporter is NOT
 * used so the existing playwright-report-s05t05 dir is never overwritten;
 * pass --output=<new dir> on the CLI so test-results/.last-run.json is
 * never touched either.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /import-analyze-c04-visual\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 180_000,
  use: {
    baseURL: "http://localhost:3011",
    screenshot: "only-on-failure",
  },
});
