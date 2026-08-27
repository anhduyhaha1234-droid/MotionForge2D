/**
 * S09-T06B-C1 global setup — resets the PRODUCTION backend QA data
 * (isolated temp DB under t06b-c1/prod-backend-root/) BEFORE each suite
 * by running output/s09/20260823_sprint_full/t06b-c1/run-prod-seed.py.
 *
 * The backend is the ACTUAL production app (app.api.app:app) — no patch,
 * no test-only app.  The reset deletes mutable surface rows (checkpoints,
 * corrections, render routes) and re-creates the baseline so the
 * transactional full-flow test always starts pristine (approvals are
 * immutable; confirmed route overrides own UNIQUE(segment,route,frame)).
 */
import { spawnSync } from "node:child_process";
import path from "node:path";

export default function globalSetup(): void {
  const worktree = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
  const seedScript = path.join(
    worktree,
    "output/s09/20260823_sprint_full/t06b-c1/run-prod-seed.py",
  );
  const env: NodeJS.ProcessEnv = { NODE_ENV: process.env.NODE_ENV };
  for (const [k, v] of Object.entries(process.env)) {
    if (typeof v === "string") env[k] = v;
  }
  delete env.MOTIONFORGE_DATABASE_URL; // hard isolation requirement
  env.PYTHONPATH = worktree;

  const res = spawnSync("python", [seedScript], {
    env,
    encoding: "utf-8",
    timeout: 120_000,
  });
  const out = `${res.stdout ?? ""}${res.stderr ?? ""}`;
  if (res.status !== 0 || !/SEEDED(_RESET| )/.test(out)) {
    throw new Error(
      `[t06bc1-global-setup] seed/reset failed (exit=${res.status}): ${out.slice(-600)}`,
    );
  }
  const lastLine = out.trim().split("\n").pop() ?? "";
  console.log(`[t06bc1-global-setup] ${lastLine}`);
}
