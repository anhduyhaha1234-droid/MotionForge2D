/**
 * S09-T06B global setup — resets the QA lane data BEFORE the suite runs.
 *
 * Runs output/s09/20260823_sprint_full/t06b/run-qa-seed.py against the
 * isolated QA backend root.  On an existing database the seeder performs a
 * RESET of the mutable approval surface (deletes all apply_checkpoint rows
 * of the seeded project + s09_correction + segment_render_route rows for
 * the video, then re-creates the pose_swap baseline + active manifest pin)
 * so the transactional full-flow test always starts from the pristine seed
 * state — required because approvals are IMMUTABLE and confirmed route
 * overrides own UNIQUE(segment, route, start_frame) rows.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";

export default function globalSetup(): void {
  const worktree = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
  const seedScript = path.join(
    worktree,
    "output/s09/20260823_sprint_full/t06b/run-qa-seed.py",
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
  const ok =
    res.status === 0 && /SEEDED(_RESET| )/.test(out);
  if (!ok) {
    throw new Error(
      `[t06b-global-setup] seed/reset failed (exit=${res.status}): ${out.slice(-600)}`,
    );
  }
  const lastLine = out.trim().split("\n").pop() ?? "";
  console.log(`[t06b-global-setup] ${lastLine}`);
}
