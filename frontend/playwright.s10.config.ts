import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * S10-T04C production FullApply E2E — isolated, fail-closed, no mocks.
 *
 * Every runtime/DB/evidence/output path is resolved via explicit env
 * (MOTIONFORGE_ROOT, MOTIONFORGE_WORKTREE, PW_OUTPUT_DIR). Missing
 * MOTIONFORGE_ROOT => throw before any write. No silent shared fallback.
 * baseURL env || 3000, workers 1, no webServer, Chromium only.
 * globalSetup -> s10-full-apply-global-setup.ts seeds isolated S10 DB/runtime.
 */

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
    `[s10-config] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)} — set MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT explicitly.`,
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
      `[s10-config] MOTIONFORGE_ROOT is required (fail-closed); none set. Expected S10 isolated runtime root (e.g. ${path.join(worktree, "output/s10/<run-id>/runtime")}).`,
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

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /s10-full-apply\.spec\.ts/,
  globalSetup: "./e2e/s10-full-apply-global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 900_000,
  outputDir: pwOutputDir,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      testMatch: /s10-full-apply\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
