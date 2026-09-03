/**
 * S10-T04B-C3 (C6) — live-product Apply UI acceptance config.
 *
 * Runs the REAL production backend (uvicorn app.api.app on an isolated
 * runtime root) + the CURRENT production Next.js build; no page.route mocks.
 *
 * Environment (fail-closed):
 *   MOTIONFORGE_ROOT      required — isolated runtime root (DB/artifacts/output)
 *   MOTIONFORGE_WORKTREE  optional — defaults to the derived worktree
 *   PW_OUTPUT_DIR         optional — Playwright artifacts (default runRoot/e2e-results)
 *   S10_BACKEND_PORT      optional — default 8201 (must match the baked build origin)
 *   S10_FRONTEND_PORT     optional — default 3000 (CORS allowlisted origin, C5-proven)
 *
 * Projects: desktop-chromium (1280x800) AND mobile-390x844 (Chromium engine)
 * both match the whole spec — no test.skip anywhere, both paths always execute.
 */
import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

function requireWorktree(): string {
  const isListProbe = process.argv.includes("--list");
  const defaultWorktree = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
  const rootEnv = process.env.MOTIONFORGE_ROOT ?? "";
  const derived = rootEnv ? rootEnv.replace(/\/output\/.*/, "") : "";
  const w =
    process.env.MOTIONFORGE_WORKTREE ??
    (derived || undefined) ??
    (isListProbe ? defaultWorktree : undefined);
  if (w && fs.existsSync(w)) return w;
  if (isListProbe && fs.existsSync(defaultWorktree)) return defaultWorktree;
  throw new Error(
    `[s10-ui-config] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)}`,
  );
}

function requireRunRoot(worktree: string): string {
  const isListProbe = process.argv.includes("--list");
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim()) {
    if (isListProbe) {
      return path.join(worktree, "output/s10/dry-list/runtime");
    }
    throw new Error(
      `[s10-ui-config] MOTIONFORGE_ROOT is required (fail-closed); expected output/s10/c6/t04b-c3/<run>/runtime`,
    );
  }
  return r;
}

const worktree = requireWorktree();
const runRoot = requireRunRoot(worktree);
const pwOutputDir =
  process.env.PW_OUTPUT_DIR ??
  process.env.PLAYWRIGHT_OUTPUT_DIR ??
  path.join(runRoot, "e2e-results");
const frontendPort = Number(process.env.S10_FRONTEND_PORT ?? "3000");
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /s10-apply-ui\.spec\.ts/,
  globalSetup: "./e2e/helpers/s10-apply-ui/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 900_000,
  expect: { timeout: 30_000 },
  outputDir: pwOutputDir,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      testMatch: /s10-apply-ui\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
      },
    },
    {
      name: "mobile-390x844",
      testMatch: /s10-apply-ui\.spec\.ts/,
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
