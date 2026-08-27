/**
 * S09-T06B-C7 global setup — fail-closed, no silent t06b-c4 fallback.
 *
 * Requires explicit MOTIONFORGE_ROOT (or MOTIONFORGE_WORKTREE) and seeder
 * located via the worktree's t06b-c7 tree; missing => throw before any write.
 * Run1 and Run2 use isolated runtime roots under t06b-c7/r1/run1/runtime and
 * t06b-c7/r1/run2/runtime via the single parameterized C7 launcher template.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function requireWorktree(): string {
  const w = process.env.MOTIONFORGE_WORKTREE ?? process.env.MOTIONFORGE_ROOT?.replace(/\/output\/.*/, "");
  if (w && fs.existsSync(w)) return w;
  throw new Error(
    "[t06bc4-global-setup] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree is required and must exist; got " +
      JSON.stringify(w) +
      " — set MOTIONFORGE_WORKTREE (or MOTIONFORGE_ROOT pointing inside a worktree output/) before running. No silent t06b-c4 fallback.",
  );
}

function requireRunRoot(worktree: string): string {
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim()) {
    throw new Error(
      `[t06bc4-global-setup] MOTIONFORGE_ROOT is required (C7 fail-closed); none set. Set it to the isolated C7 runtime root (e.g. ${path.join(worktree, "output/s09/20260823_sprint_full/t06b-c7/run1/runtime")}).`,
    );
  }
  return r;
}

function resolveSeeder(worktree: string, runRoot: string): string {
  // Allow explicit override
  const explicit = process.env.T06BC4_SEEDER;
  if (explicit) {
    if (!fs.existsSync(explicit)) throw new Error(`[t06bc4-global-setup] T06BC4_SEEDER=${explicit} not found`);
    return explicit;
  }
  // C7 primary: t06b-c7 seeder (copied alongside runtime helpers)
  const c7 = path.join(worktree, "output/s09/20260823_sprint_full/t06b-c7/run-prod-seed.py");
  if (fs.existsSync(c7)) return c7;
  // Per-run staged seeder
  const staged = path.join(runRoot, "run-prod-seed.py");
  if (fs.existsSync(staged)) return staged;
  // Worktree-wide t06b-c7 seeder alt
  const c7b = path.join(worktree, "output/s09/20260823_sprint_full/t06b-c7/_seeder.py");
  if (fs.existsSync(c7b)) return c7b;
  throw new Error(
    `[t06bc4-global-setup] no C7 seeder found at ${c7} or ${staged}; set T06BC4_SEEDER explicitly. Refusing to fall back to t06b-c4 shared C4 runtime.`,
  );
}

export default function globalSetup(): void {
  const worktree = requireWorktree();
  const runRoot = requireRunRoot(worktree);
  const seedScript = resolveSeeder(worktree, runRoot);

  const env: NodeJS.ProcessEnv = { NODE_ENV: process.env.NODE_ENV } as NodeJS.ProcessEnv;
  for (const [k, v] of Object.entries(process.env)) {
    if (typeof v === "string") env[k] = v;
  }
  delete env.MOTIONFORGE_DATABASE_URL;
  env.PYTHONPATH = worktree;
  env.PYTHONUTF8 = "1";
  env.MOTIONFORGE_ROOT = runRoot;
  env.MOTIONFORGE_WORKTREE = worktree;
  if (process.env.MOTIONFORGE_DATABASE_URL) {
    env.MOTIONFORGE_DATABASE_URL = process.env.MOTIONFORGE_DATABASE_URL;
  }

  const res = spawnSync("python", [seedScript, "--runtime-root", runRoot], {
    env: env as unknown as NodeJS.ProcessEnv,
    encoding: "utf-8",
    timeout: 180_000,
  });
  let out = `${res.stdout ?? ""}${res.stderr ?? ""}`;
  let status = res.status;
  if (status !== 0 && /unrecognized arguments.*--runtime-root/.test(out)) {
    const res2 = spawnSync("python", [seedScript], {
      env: { ...env, MOTIONFORGE_ROOT: runRoot } as unknown as NodeJS.ProcessEnv,
      encoding: "utf-8",
      timeout: 180_000,
    });
    out = `${res2.stdout ?? ""}${res2.stderr ?? ""}`;
    status = res2.status;
  }
  if (status !== 0 || !/SEEDED(_RESET| )/.test(out)) {
    throw new Error(
      `[t06bc4-global-setup runRoot=${runRoot}] seed/reset failed (exit=${status}): ${out.slice(-1200)}`,
    );
  }
  const lines = out.split("\n").filter((l) => /^(SEEDED|SEEDED_RESET|C4_)/.test(l.trim()));
  console.log(`[t06bc4-global-setup runRoot=${runRoot}] ${lines[lines.length - 1]?.trim() ?? "SEEDED"}`);
}
