/**
 * S10-T04C global setup — isolates DB/runtime, deterministic seed, no API mocking.
 *
 * Fail-closed: requires MOTIONFORGE_ROOT and MOTIONFORGE_WORKTREE (or --runtime-root).
 * Resets the S10 correction surface for the current video/project per run,
 * seeds a deterministic approval (reskin_config pinned), and stages the compact
 * S10 fixture under the runtime root. Missing env/path => throw before any write.
 *
 * No mocks of the production API: the production backend + production frontend
 * + real renderer adapter are exercised by the spec.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function requireWorktree(): string {
  const w = process.env.MOTIONFORGE_WORKTREE ?? process.env.MOTIONFORGE_ROOT?.replace(/\/output\/.*/, "");
  if (w && fs.existsSync(w)) return w;
  throw new Error(`[s10-full-apply-global-setup] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)}`);
}

function requireRunRoot(worktree: string): string {
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim()) throw new Error(`[s10-full-apply-global-setup] MOTIONFORGE_ROOT required; none set. Expected S10 isolated runtime root (e.g. ${path.join(worktree, "output/s10/<run-id>/runtime")})`);
  return r;
}

function resolveSeeder(worktree: string, runRoot: string): string {
  const c10 = path.join(worktree, "output/s10/run-prod-seed.py");
  if (fs.existsSync(c10)) return c10;
  const staged = path.join(runRoot, "run-prod-seed.py");
  if (fs.existsSync(staged)) return staged;
  throw new Error(`[s10-full-apply-global-setup] run-prod-seed.py not found at ${c10} nor ${staged}`);
}

function resolveFixture(worktree: string): string {
  const fp = path.join(worktree, "tests/fixtures/s10_full_apply");
  if (!fs.existsSync(path.join(fp, "manifest.json"))) throw new Error(`[s10-full-apply-global-setup] fixture missing: ${fp}/manifest.json`);
  return fp;
}

export default function globalSetup(): void {
  const worktree = requireWorktree();
  const runRoot = requireRunRoot(worktree);
  const seedScript = resolveSeeder(worktree, runRoot);
  const fixtureDir = resolveFixture(worktree);

  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (typeof v === "string") env[k] = v;
  delete env.MOTIONFORGE_DATABASE_URL;
  env.PYTHONPATH = worktree;
  env.PYTHONUTF8 = "1";
  env.MOTIONFORGE_ROOT = runRoot;
  env.MOTIONFORGE_WORKTREE = worktree;

  // Stage fixture into runtime (copy, not symlink — isolation proof)
  const dest = path.join(runRoot, "tests/fixtures/s10_full_apply");
  try {
    fs.mkdirSync(dest, { recursive: true });
    for (const name of ["manifest.json", "manifest.sha256", "generate_fixtures.py"]) {
      const src = path.join(fixtureDir, name);
      if (fs.existsSync(src)) fs.copyFileSync(src, path.join(dest, name));
    }
    const srcSprites = path.join(fixtureDir, "sprites");
    const dstSprites = path.join(dest, "sprites");
    fs.mkdirSync(dstSprites, { recursive: true });
    for (const e of fs.readdirSync(srcSprites)) fs.copyFileSync(path.join(srcSprites, e), path.join(dstSprites, e));
  } catch (e) {
    throw new Error(`[s10-full-apply-global-setup] fixture stage failed: ${String(e)}`);
  }

  const res = spawnSync("python", [seedScript, "--runtime-root", runRoot], {
    env: env as unknown as NodeJS.ProcessEnv,
    encoding: "utf-8",
    timeout: 180_000,
  });
  const out = `${res.stdout ?? ""}${res.stderr ?? ""}`;
  if (res.status !== 0 || !/SEEDED/.test(out)) {
    throw new Error(`[s10-full-apply-global-setup runRoot=${runRoot}] seed/reset failed (exit=${res.status}): ${out.slice(-1400)}`);
  }
  const lines = out.split("\n").filter((l: string) => /SEEDED/.test(l.trim()));
  console.log(`[s10-full-apply-global-setup runRoot=${runRoot}] ${lines[lines.length - 1]?.trim() ?? "SEEDED"}`);

  // C4A: complete REAL canonical authority through product handlers (source
  // media bytes + artifact pins, per-layer replacement assets + CharacterAsset,
  // structural segment/motion/contact/route rows). No stage_c4.py, no
  // input_manifest_json patch, no lease mutation, no direct reconciler.
  const postSeed = path.join(worktree, "tests/fixtures/s10_full_apply/post_seed_real_authority.py");
  if (!fs.existsSync(postSeed)) {
    throw new Error(`[s10-full-apply-global-setup] post_seed_real_authority.py missing: ${postSeed}`);
  }
  const postEnv: Record<string, string> = { ...env, MOTIONFORGE_ROOT: runRoot, MOTIONFORGE_WORKTREE: worktree };
  const post = spawnSync("python", [postSeed, "--runtime-root", runRoot, "--worktree", worktree], {
    env: postEnv as unknown as NodeJS.ProcessEnv,
    encoding: "utf-8",
    timeout: 120_000,
  });
  const postOut = `${post.stdout ?? ""}${post.stderr ?? ""}`;
  if (post.status !== 0 || !/POST_SEEDED/.test(postOut)) {
    throw new Error(`[s10-full-apply-global-setup runRoot=${runRoot}] post-seed failed (exit=${post.status}): ${postOut.slice(-1400)}`);
  }
  const postLines = postOut.split("\n").filter((l: string) => /POST_SEEDED/.test(l.trim()));
  console.log(`[s10-full-apply-global-setup runRoot=${runRoot}] ${postLines[postLines.length - 1]?.trim() ?? "POST_SEEDED"}`);
}
