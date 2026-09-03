/**
 * S10-T04B-C3 (C6A) — isolated runtime global setup.
 *
 * 1) Invokes the T04C canonical setup (s10-full-apply-global-setup.ts,
 *    READ-ONLY import — run-prod-seed.py + post_seed_real_authority.py)
 *    which provisions a fresh isolated DB/runtime/artifact root and the
 *    deterministic S10-PROD-E2E authority.
 * 2) Seeds the bounded S10-C6-NOAUTH project (no structural lock manifest)
 *    for the genuine missing-authority reason-truth branch.
 * 3) Seeds the bounded S10-C6A-EXEC project — every manifest-selected
 *    segment uses the executable route sprite_affine with real boxed
 *    geometry + published pack assets + source artifact, so its v2 approval
 *    authority IS executable under the server-derived minimal contract
 *    (the run-creating scenarios of the 20-case suite use this project).
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import s10T04CGlobalSetup from "../../s10-full-apply-global-setup";

function requireWorktree(): string {
  const w =
    process.env.MOTIONFORGE_WORKTREE ??
    process.env.MOTIONFORGE_ROOT?.replace(/\/output\/.*/, "");
  if (w && fs.existsSync(w)) return w;
  throw new Error(
    `[s10-ui-global-setup] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)}`,
  );
}

function requireRunRoot(worktree: string): string {
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim())
    throw new Error(
      `[s10-ui-global-setup] MOTIONFORGE_ROOT required; none set (worktree=${worktree})`,
    );
  return r;
}

export default function globalSetup(): void {
  // 1) T04C canonical isolated setup (seeder + post-seed real authority).
  s10T04CGlobalSetup();

  // 2) Bounded noauth project for the missing-authority BLOCKED branch.
  const worktree = requireWorktree();
  const runRoot = requireRunRoot(worktree);
  const script = path.join(__dirname, "seed_noauth_project.py");
  if (!fs.existsSync(script)) {
    throw new Error(`[s10-ui-global-setup] noauth seed script missing: ${script}`);
  }
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (typeof v === "string") env[k] = v;
  delete env.MOTIONFORGE_DATABASE_URL;
  env.PYTHONPATH = worktree;
  env.PYTHONUTF8 = "1";
  env.MOTIONFORGE_ROOT = runRoot;
  env.MOTIONFORGE_WORKTREE = worktree;

  const res = spawnSync(
    "python",
    [script, "--runtime-root", runRoot, "--worktree", worktree],
    {
      env: env as unknown as NodeJS.ProcessEnv,
      encoding: "utf-8",
      timeout: 120_000,
    },
  );
  const out = `${res.stdout ?? ""}${res.stderr ?? ""}`;
  if (res.status !== 0 || !/NOAUTH_SEEDED/.test(out)) {
    throw new Error(
      `[s10-ui-global-setup runRoot=${runRoot}] noauth seed failed (exit=${res.status}): ${out.slice(-1600)}`,
    );
  }
  const lines = out.split("\n").filter((l) => /NOAUTH_SEEDED/.test(l.trim()));
  console.log(
    `[s10-ui-global-setup runRoot=${runRoot}] ${lines[lines.length - 1]?.trim() ?? "NOAUTH_SEEDED"}`,
  );

  // 3) Bounded executable authority project for the 20-case suite
  //    (run-creating scenarios need a v2 approval whose eligibility
  //    full_apply_executable === true).
  const execScript = path.join(__dirname, "seed_exec_project.py");
  if (!fs.existsSync(execScript)) {
    throw new Error(`[s10-ui-global-setup] exec seed script missing: ${execScript}`);
  }
  const execRes = spawnSync(
    "python",
    [execScript, "--runtime-root", runRoot, "--worktree", worktree],
    {
      env: env as unknown as NodeJS.ProcessEnv,
      encoding: "utf-8",
      timeout: 120_000,
    },
  );
  const execOut = `${execRes.stdout ?? ""}${execRes.stderr ?? ""}`;
  if (execRes.status !== 0 || !/EXEC_SEEDED/.test(execOut)) {
    throw new Error(
      `[s10-ui-global-setup runRoot=${runRoot}] exec seed failed (exit=${execRes.status}): ${execOut.slice(-1600)}`,
    );
  }
  const execLines = execOut.split("\n").filter((l) => /EXEC_SEEDED/.test(l.trim()));
  console.log(
    `[s10-ui-global-setup runRoot=${runRoot}] ${execLines[execLines.length - 1]?.trim() ?? "EXEC_SEEDED"}`,
  );

  // 4) v1 disk-store mirror: the legacy list page (GET /api/projects) reads
  //    ONLY <MOTIONFORGE_ROOT>/projects/<id>/project.json (dual-store design).
  //    The isolated runtime seeds the durable SQLite store only, so mirror
  //    every durable project onto disk through the exact POST /api/projects
  //    contract (ProjectService.create) before any test runs.
  const mirrorScript = path.join(__dirname, "mirror_v1_disk_projects.py");
  if (!fs.existsSync(mirrorScript)) {
    throw new Error(`[s10-ui-global-setup] mirror script missing: ${mirrorScript}`);
  }
  const mirrorRes = spawnSync(
    "python",
    [mirrorScript, "--runtime-root", runRoot, "--worktree", worktree],
    {
      env: env as unknown as NodeJS.ProcessEnv,
      encoding: "utf-8",
      timeout: 120_000,
    },
  );
  const mirrorOut = `${mirrorRes.stdout ?? ""}${mirrorRes.stderr ?? ""}`;
  if (mirrorRes.status !== 0 || !/MIRROR_V1_SEEDED/.test(mirrorOut)) {
    throw new Error(
      `[s10-ui-global-setup runRoot=${runRoot}] v1 disk mirror failed (exit=${mirrorRes.status}): ${mirrorOut.slice(-1600)}`,
    );
  }
  const mirrorLines = mirrorOut.split("\n").filter((l) => /MIRROR_V1_SEEDED/.test(l.trim()));
  console.log(
    `[s10-ui-global-setup runRoot=${runRoot}] ${mirrorLines[mirrorLines.length - 1]?.trim() ?? "MIRROR_V1_SEEDED"}`,
  );
}
