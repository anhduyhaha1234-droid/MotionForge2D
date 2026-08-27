import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * S09-T06B-C7 production-stack E2E — fail-closed, no silent t06b-c4 fallback.
 *
 * Every runtime/DB/evidence/output path is resolved via explicit env
 * (MOTIONFORGE_ROOT, MOTIONFORGE_WORKTREE, PW_OUTPUT_DIR). Missing
 * MOTIONFORGE_ROOT => throw before any write. No silent shared-C4 reuse.
 * Single parameterized C7 launcher template produces distinct run1/run2.
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
    `[t06bc4-config] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)} — set MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT explicitly. No t06b-c4 fallback.`,
  );
}

function requireRunRoot(worktree: string): string {
  const isListProbe = process.argv.includes("--list");
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim()) {
    if (isListProbe) {
      return path.join(worktree, "output/s09/20260823_sprint_full/t06b-c7/r1/run1/runtime");
    }
    throw new Error(
      `[t06bc4-config] MOTIONFORGE_ROOT is required (C7 fail-closed); none set. Expected an isolated C7 runtime root (e.g. ${path.join(worktree, "output/s09/20260823_sprint_full/t06b-c7/r1/run1/runtime")}).`,
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

export default defineConfig({
  testDir: "./e2e",
  testMatch: /s09-t06bc4-.*\.spec\.ts/,
  globalSetup: "./e2e/s09-t06bc4-global-setup.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 420_000,
  outputDir: pwOutputDir,
  use: {
    baseURL: "http://localhost:3115",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      testMatch: /s09-t06bc4-.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
