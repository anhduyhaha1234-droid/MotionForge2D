/** S10-T04B-C3 diagnostic probe config (not part of acceptance). */
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const worktree = process.env.MOTIONFORGE_WORKTREE ?? "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
const runRoot = process.env.MOTIONFORGE_ROOT ?? path.join(worktree, "output/s10/c6a/t04b-c3/probe/runtime");
const frontendPort = Number(process.env.S10_FRONTEND_PORT ?? "3000");

export default defineConfig({
  testDir: "./e2e/helpers/s10-apply-ui",
  testMatch: /retry-url-probe\.spec\.ts/,
  globalSetup: "./e2e/helpers/s10-apply-ui/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 600_000,
  expect: { timeout: 30_000 },
  outputDir: path.join(runRoot, "e2e-results"),
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
