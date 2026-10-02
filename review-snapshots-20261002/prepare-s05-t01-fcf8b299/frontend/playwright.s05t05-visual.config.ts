import { defineConfig } from "@playwright/test";

/**
 * S05-T05 visual QA config — captures desktop + 390px screenshots of the
 * Import/Analyze UI against the REAL backend (same QA env as
 * playwright.s05t05.config.ts: frontend :3011, backend :8003).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /import-analyze-visual\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 180_000,
  use: {
    baseURL: "http://localhost:3011",
    screenshot: "only-on-failure",
  },
});
