/**
 * S09-T06B-C2-PREP global setup — resets the PRODUCTION backend QA data
 * (isolated temp DB + managed artifact root under t06b-c2/prod-backend-root/)
 * BEFORE each suite by running t06b-c2/run-prod-seed.py.  The reset ALSO
 * wipes the demo-loop surface (S09_DEMO_LOOP jobs + published loop
 * artifacts rows and files) so each run measures only its own effects.
 *
 * The backend is the ACTUAL production app (app.api.app:app) — no patch,
 * no test-only app.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";

export default function globalSetup(): void {
  const worktree = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
  const seedScript = path.join(
    worktree,
    "output/s09/20260823_sprint_full/t06b-c2/run-prod-seed.py",
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
      `[t06bc2-global-setup] seed/reset failed (exit=${res.status}): ${out.slice(-600)}`,
    );
  }
  const lastLine = out.trim().split("\n").pop() ?? "";
  console.log(`[t06bc2-global-setup] ${lastLine}`);
}
