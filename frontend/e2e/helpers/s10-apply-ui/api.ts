/**
 * S10-T04B-C3 (C6) — live-product helpers.
 *
 * Real product contract only: public /api/v2 routes + read-only DB probes.
 * No page.route, no mocked responses, no direct run/status/evidence mutation.
 *
 * Backend/frontend launchers are imported READ-ONLY from the T04C helper
 * module (s09-t06bc4-helpers) — same isolated Windows launch contract.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";

import {
  launchFrontend,
  launchIsolatedBackend,
  stopLaunched,
  waitForBackendReady,
  waitForFrontendReady,
  assertPortFree,
  listenerOwnerPid,
  waitForPortListenerOwnedBy,
  isPidAlive,
  type LaunchedBackend,
  type LaunchedFrontend,
} from "../../s09-t06bc4-helpers.js";

// ── isolated runtime resolution (fail-closed) ─────────────────────────────

function requireWorktree(): string {
  const isListProbe = process.argv.includes("--list");
  const defaultWorktree = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
  const w =
    process.env.MOTIONFORGE_WORKTREE ??
    (process.env.MOTIONFORGE_ROOT
      ? process.env.MOTIONFORGE_ROOT.replace(/\/output\/.*/, "")
      : undefined) ??
    (isListProbe ? defaultWorktree : undefined);
  if (w && fs.existsSync(w)) return w;
  if (isListProbe && fs.existsSync(defaultWorktree)) return defaultWorktree;
  throw new Error(`[s10-ui-helpers] MOTIONFORGE_WORKTREE required; got ${JSON.stringify(w)}`);
}

function requireRunRoot(): string {
  const r = process.env.MOTIONFORGE_ROOT;
  if (!r || !r.trim()) {
    if (process.argv.includes("--list"))
      return path.join(requireWorktree(), "output/s10/dry-list/runtime");
    throw new Error("[s10-ui-helpers] MOTIONFORGE_ROOT required (fail-closed)");
  }
  return r;
}

export const WORKTREE = requireWorktree();
export const RUN_ROOT = requireRunRoot();
export const BACKEND_PORT = Number(process.env.S10_BACKEND_PORT ?? "8201");
export const FRONTEND_PORT = Number(process.env.S10_FRONTEND_PORT ?? "3000");
export const FRONTEND_BASE = `http://localhost:${FRONTEND_PORT}`;
export const WS = "default";
export const MAIN_PROJECT_NAME = "S10-PROD-E2E";
export const NOAUTH_PROJECT_NAME = "S10-C6-NOAUTH";
export const EXEC_PROJECT_NAME = "S10-C6A-EXEC";

// ── public API helpers (page.request — no mocks) ──────────────────────────

export async function apiGet(page: Page, apiPath: string): Promise<Record<string, unknown>> {
  const res = await page.request.get(
    `http://localhost:${BACKEND_PORT}/api/v2${apiPath}`,
  );
  if (!res.ok()) {
    const body = await res.text().catch(() => "");
    throw new Error(`GET ${apiPath} -> ${res.status()} ${body.slice(0, 800)}`);
  }
  return (await res.json()) as Record<string, unknown>;
}

export async function apiPostRaw(
  page: Page,
  apiPath: string,
  body: unknown,
): Promise<{ status: number; json: Record<string, unknown> }> {
  const res = await page.request.post(
    `http://localhost:${BACKEND_PORT}/api/v2${apiPath}`,
    { data: body },
  );
  let json: Record<string, unknown> = {};
  try {
    json = (await res.json()) as Record<string, unknown>;
  } catch {
    /* empty */
  }
  return { status: res.status(), json };
}

export async function apiPostOrThrow(
  page: Page,
  apiPath: string,
  body: unknown,
): Promise<Record<string, unknown>> {
  const { status, json } = await apiPostRaw(page, apiPath, body);
  if (status < 200 || status >= 300) {
    throw new Error(`POST ${apiPath} -> ${status} ${JSON.stringify(json).slice(0, 1200)}`);
  }
  return json;
}

// ── read-only DB probes ───────────────────────────────────────────────────

export function dbPathForProbe(): string {
  if (process.env.MOTIONFORGE_DATABASE_URL) {
    const u = process.env.MOTIONFORGE_DATABASE_URL;
    const m = /sqlite:\/\/(.*)/.exec(u);
    if (m) return m[1];
    return u;
  }
  const direct = path.join(RUN_ROOT, "data/motionforge.db");
  if (fs.existsSync(direct)) return direct;
  const alt = path.join(RUN_ROOT, "prod-backend-root/data/motionforge.db");
  if (fs.existsSync(alt)) return alt;
  throw new Error(`[s10-ui-helpers] DB not found; MOTIONFORGE_ROOT=${RUN_ROOT}`);
}

function runPython(scriptBody: string, args: string[]): string {
  const tmp = path.join(RUN_ROOT, `_c6_probe_${Date.now()}_${Math.floor(Math.random() * 1e6)}.py`);
  fs.mkdirSync(path.dirname(tmp), { recursive: true });
  fs.writeFileSync(tmp, scriptBody, "utf-8");
  const r = spawnSync("python", [tmp, ...args], {
    encoding: "utf-8",
    timeout: 20000,
  });
  try {
    fs.unlinkSync(tmp);
  } catch {
    /* best-effort */
  }
  const out = `${r.stdout ?? ""}${r.stderr ?? ""}`;
  if (r.status !== 0) throw new Error(`probe python failed exit=${r.status}: ${out.slice(-1500)}`);
  const line = (r.stdout ?? "").trim().split("\n").filter(Boolean).pop() ?? "{}";
  return line;
}

export interface RunProbe {
  run: Record<string, unknown> | null;
  chunks: Array<Record<string, unknown>>;
  publications: Array<Record<string, unknown>>;
  jobs: Array<Record<string, unknown>>;
}

/** Read-only S10 run/chunks/publications/jobs snapshot. */
export function probeRun(runId: string): RunProbe {
  const db = dbPathForProbe();
  const py = `
import json, sqlite3, sys
db, rid = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
def q(sql, params=()):
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]
out = {}
try:
    rows = q("SELECT id, project_id, status, attempt FROM s10_full_apply_run WHERE id=?", (rid,))
    out["run"] = rows[0] if rows else None
except Exception as e:
    out["run_error"] = str(e)
try:
    out["chunks"] = q("SELECT id, chunk_index, shot_id, layer_id, core_start_frame, core_end_frame, content_hash, state, attempt, artifact_id, verified FROM s10_full_apply_chunk WHERE run_id=? ORDER BY order_index, chunk_index", (rid,))
except Exception as e:
    out["chunks_error"] = str(e)
try:
    out["publications"] = q("SELECT id, artifact_id, content_hash, frame_count, state FROM s10_full_apply_publication WHERE run_id=?", (rid,))
except Exception as e:
    out["pubs_error"] = str(e)
try:
    out["jobs"] = q("SELECT id, state, attempt FROM job WHERE workspace_id='default' AND idempotency_key=? ORDER BY created_at DESC LIMIT 3", ("s10_full_apply_job:" + rid,))
except Exception as e:
    out["jobs_error"] = str(e)
print(json.dumps(out, ensure_ascii=False))
`;
  return JSON.parse(runPython(py, [db, runId])) as RunProbe;
}

export interface LeaseProbe {
  lease: Record<string, unknown> | null;
  job: Record<string, unknown> | null;
}

/** Read-only durable-job lease probe (job_lease row: expires_at / fence grace).
 *  T01C-C9 moved the lease out of job.lease_json into the dedicated
 *  job_lease table (1:1 by job_id) — this probe reads THAT truth. */
export function probeJobForRun(runId: string): LeaseProbe {
  const db = dbPathForProbe();
  const py = `
import json, sqlite3, sys
db, rid = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
out = {}
row = cur.execute("SELECT id, state, attempt FROM job WHERE workspace_id='default' AND idempotency_key=? ORDER BY created_at DESC LIMIT 1", ("s10_full_apply_job:" + rid,)).fetchone()
if row is None:
    print(json.dumps({"job": None, "lease": None}))
    raise SystemExit(0)
out["job"] = {"id": row["id"], "state": row["state"], "attempt": row["attempt"]}
lease = cur.execute("SELECT worker_id, lease_version, fence_token, acquired_at, expires_at, heartbeat_at, ttl_seconds FROM job_lease WHERE job_id=?", (row["id"],)).fetchone()
out["lease"] = dict(lease) if lease is not None else None
print(json.dumps(out, ensure_ascii=False))
`;
  return JSON.parse(runPython(py, [db, runId])) as LeaseProbe;
}

/** Read-only: reskin_config -> character/pack_version (mirrors T04C probe). */
export function getPackVersionId(reskinConfigId: string): string {
  const db = dbPathForProbe();
  const py = `
import json, sqlite3, sys
db, rc = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
cur = con.cursor()
r = cur.execute("SELECT character_id, pack_version_id, structural_lock_manifest_id, lock_policy_version FROM reskin_config WHERE id=?", (rc,)).fetchone()
print(json.dumps({"char": r[0] if r else None, "pv": r[1] if r else None, "slm": r[2] if r else None, "ver": r[3] if r else None}))
`;
  const j = JSON.parse(runPython(py, [db, reskinConfigId])) as Record<string, unknown>;
  const pv = (j.pv as string) ?? "";
  if (!pv) throw new Error(`pack_version_id not found for reskin_config ${reskinConfigId}`);
  return pv;
}

// ── product identity helpers ──────────────────────────────────────────────

export async function findProject(
  page: Page,
  name: string,
): Promise<{ id: string; name: string }> {
  const raw = (await apiGet(page, `/projects?active_only=false`)) as Record<string, unknown>;
  const list = Array.isArray(raw)
    ? (raw as Array<Record<string, unknown>>)
    : ((raw.projects as Array<Record<string, unknown>> | undefined) ??
      (raw.items as Array<Record<string, unknown>> | undefined) ??
      []);
  const p = list.find(
    (r) => String(r.name) === name || String(r.project_id ?? r.id ?? r.projectId) === name,
  );
  if (!p) throw new Error(`project ${name} not found via public API`);
  return {
    id: String(p.project_id ?? p.id ?? p.projectId),
    name: String(p.name),
  };
}

export async function listVideos(page: Page, projectId: string): Promise<string[]> {
  const raw = (await apiGet(page, `/projects/${encodeURIComponent(projectId)}/videos`)) as Record<
    string,
    unknown
  >;
  const list = Array.isArray(raw)
    ? (raw as Array<Record<string, unknown>>)
    : ((raw.videos as Array<Record<string, unknown>> | undefined) ??
      (raw.items as Array<Record<string, unknown>> | undefined) ??
      []);
  return list.map((v) => String(v.id ?? v.video_item_id ?? v.videoId));
}

export async function getReskinConfig(
  page: Page,
  projectId: string,
): Promise<{ id: string; structural_lock_manifest_id: string | null; lock_policy_version: string | null }> {
  const raw = (await apiGet(page, `/reskin-configs?project_id=${encodeURIComponent(projectId)}`)) as Record<
    string,
    unknown
  >;
  const list = Array.isArray(raw)
    ? (raw as Array<Record<string, unknown>>)
    : ((raw.configs as Array<Record<string, unknown>> | undefined) ??
      (raw.items as Array<Record<string, unknown>> | undefined) ??
      []);
  if (!list.length) throw new Error(`reskin_config not found for project ${projectId}`);
  const c = list[0];
  return {
    id: String(c.id),
    structural_lock_manifest_id: (c.structural_lock_manifest_id as string | null) ?? null,
    lock_policy_version: (c.lock_policy_version as string | null) ?? null,
  };
}

export interface ApprovalInfo {
  id: string;
  checkpoint_hash: string;
  revision: number;
}

/** Create a CURRENT approval through the public product contract.
 *  Default schema "v2" uses POST /s09-approvals/reapprove (submit_checkpoint_v2)
 *  which freezes the nested full_apply_authority — the only schema the
 *  minimal public submit accepts.  schema "v1" uses POST /s09-approvals
 *  (legacy demo approval; full-apply-authority fails closed 422
 *  REAPPROVAL_REQUIRED). */
export async function ensureApproval(
  page: Page,
  opts: {
    projectId: string;
    reskinConfigId: string;
    packVersionId: string;
    note: string;
    tag: string;
    schema?: "v1" | "v2";
  },
): Promise<ApprovalInfo> {
  const body: Record<string, unknown> = {
    reskin_config_id: opts.reskinConfigId,
    expected_reskin_revision: 1,
    pack_version_ids: [opts.packVersionId],
    demo_artifact_ids: [],
    correction_ids: [],
    accepted_warnings: [],
    overrides: [],
    note: opts.note,
    idempotency_key: `s10-c6-${opts.tag}-${opts.projectId.slice(0, 8)}`,
  };
  const path =
    opts.schema === "v1"
      ? `/s09-approvals?workspace_id=${encodeURIComponent(WS)}`
      : `/s09-approvals/reapprove?workspace_id=${encodeURIComponent(WS)}`;
  const resp = await apiPostOrThrow(page, path, body);
  const id = String(resp.id ?? resp.checkpoint_id ?? "");
  const hash = String(resp.checkpoint_hash ?? "");
  if (!id || hash.length !== 64) {
    throw new Error(`approval response malformed: ${JSON.stringify(resp).slice(0, 800)}`);
  }
  const verify = await apiPostOrThrow(
    page,
    `/s09-approvals/${encodeURIComponent(id)}/verify?workspace_id=${encodeURIComponent(WS)}`,
    {},
  );
  if (verify.verified !== true) {
    throw new Error(`approval verify failed for ${id}: ${JSON.stringify(verify)}`);
  }
  return { id, checkpoint_hash: hash, revision: Number(resp.reskin_config_revision ?? 1) };
}

// ── FullApply minimal submit body (server-derived authority) ──────────────

export interface SubmitBodyOpts {
  projectId: string;
  videoId: string;
  approval: ApprovalInfo;
  chunkFrames?: number;
  overlapFrames?: number;
}

/** Minimal public identity/CAS contract — the server derives the plan and
 *  render authority EXCLUSIVELY from the frozen v2 checkpoint.  No client
 *  scene_manifest/mapping/approved_checkpoint/structural_lock_manifest, no
 *  fixture truth, no route coercion, no hard-coded affected region. */
export function buildSubmitBody(opts: SubmitBodyOpts): Record<string, unknown> {
  return {
    video_item_id: opts.videoId,
    apply_checkpoint_id: opts.approval.id,
    expected_checkpoint_hash: opts.approval.checkpoint_hash,
    expected_checkpoint_revision: opts.approval.revision,
    chunk_frames: opts.chunkFrames ?? 25,
    overlap_frames: opts.overlapFrames ?? 4,
  };
}

export interface CreatedRun {
  runId: string;
  status: string;
  created: boolean;
}

/** Submit a REAL FullApply run through the public product API (minimal
 *  identity/CAS body; the project is an explicit argument — the body no
 *  longer carries any authority copy to derive it from). */
export async function submitRun(
  page: Page,
  projectId: string,
  body: Record<string, unknown>,
): Promise<CreatedRun> {
  const { status, json } = await apiPostRaw(
    page,
    `/projects/${encodeURIComponent(projectId)}/full-apply?workspace_id=${encodeURIComponent(WS)}`,
    body,
  );
  if (![200, 202].includes(status)) {
    throw new Error(`submit full-apply -> ${status} ${JSON.stringify(json).slice(0, 1200)}`);
  }
  const runId = String(json.run_id ?? json.id ?? "");
  if (!runId) throw new Error(`submit full-apply returned no run_id: ${JSON.stringify(json)}`);
  return { runId, status: String(json.status ?? ""), created: Boolean(json.created ?? true) };
}

// ── managed artifact resolution (read-only, tamper branch) ────────────────

function lpWin(p: string): string {
  const abs = path.resolve(p);
  if (abs.length > 259 && !abs.startsWith("\\\\?\\")) return "\\\\?\\" + abs;
  return abs;
}

/** Resolve a managed artifact relative_path to an absolute file (mirrors the
 *  T04C helper: canonical managed_root = RUN_ROOT/artifacts + relative_path). */
export function resolveManagedArtifactPath(relativePath: string): string {
  const cand1 = lpWin(path.join(RUN_ROOT, "artifacts", relativePath));
  if (fs.existsSync(cand1)) return cand1;
  const cand2 = lpWin(path.join(RUN_ROOT, relativePath));
  if (fs.existsSync(cand2)) return cand2;
  return cand1;
}

export interface PublicationArtifact {
  artifact_id: string;
  relative_path: string;
  sha256: string;
  size_bytes: number;
}

/** Read-only: publications of a run joined with their artifact rows
 *  (id/relative_path/sha256/size_bytes) so a genuine rendered-file tamper can
 *  be applied and re-verified (RENDERED_TAMPERED path — no response
 *  injection, no DB patch). */
export function probePublicationArtifacts(runId: string): PublicationArtifact[] {
  const db = dbPathForProbe();
  const py = `
import json, sqlite3, sys
db, rid = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
out = []
try:
    rows = cur.execute("SELECT artifact_id, content_hash, state FROM s10_full_apply_publication WHERE run_id=? ORDER BY created_at, id", (rid,)).fetchall()
    for r in rows:
        aid = r["artifact_id"]
        art = cur.execute("SELECT id, relative_path, sha256, size_bytes FROM artifact WHERE id=?", (aid,)).fetchone()
        if art is not None:
            out.append({"artifact_id": aid, "relative_path": art["relative_path"], "sha256": art["sha256"], "size_bytes": art["size_bytes"], "content_hash": r["content_hash"], "state": r["state"]})
except Exception as e:
    out.append({"error": str(e)})
print(json.dumps(out, ensure_ascii=False))
`;
  return JSON.parse(runPython(py, [db, runId])) as PublicationArtifact[];
}

// ── status polling ────────────────────────────────────────────────────────

export async function waitForRunStatus(
  page: Page,
  runId: string,
  projectId: string,
  predicate: (status: string) => boolean,
  deadlineMs = 180_000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + deadlineMs;
  let last: Record<string, unknown> = {};
  while (Date.now() < deadline) {
    last = (await apiGet(
      page,
      `/full-apply/${encodeURIComponent(runId)}?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(projectId)}`,
    )) as Record<string, unknown>;
    if (predicate(String(last.status ?? ""))) return last;
    await page.waitForTimeout(750);
  }
  throw new Error(
    `waitForRunStatus timeout: run=${runId} last status=${String(last.status ?? "")}`,
  );
}

export async function waitForPartialChunk(
  page: Page,
  runId: string,
  projectId: string,
  deadlineMs = 180_000,
): Promise<void> {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    const s = (await apiGet(
      page,
      `/full-apply/${encodeURIComponent(runId)}?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(projectId)}`,
    )) as Record<string, unknown>;
    const chunks = (s.chunks as Array<Record<string, unknown>>) ?? [];
    const verified = chunks.filter((c) => Boolean(c.verified) || c.state === "completed").length;
    if (chunks.length > 0 && verified > 0 && verified < chunks.length) return;
    const db = probeRun(runId);
    const dbChunks = db.chunks ?? [];
    const dbVerified = dbChunks.filter((c) => Boolean(c.verified) || c.state === "completed").length;
    if (dbChunks.length > 0 && dbVerified > 0 && dbVerified < dbChunks.length) return;
    await page.waitForTimeout(750);
  }
  throw new Error(`waitForPartialChunk timeout: run=${runId} (no durable partial checkpoint observed)`);
}

/** Wait until the stale job lease is fencible (expires_at + 90s grace) — read-only. */
export async function waitLeaseFencible(
  runId: string,
  deadlineMs = 220_000,
): Promise<string> {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    const p = probeJobForRun(runId);
    const lease = p.lease;
    if (lease?.expires_at) {
      const expiresMs = new Date(String(lease.expires_at).replace(" ", "T") + "Z").getTime();
      if (Number.isFinite(expiresMs) && Date.now() >= expiresMs + 90_000) {
        return String(lease.expires_at);
      }
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`waitLeaseFencible timeout: run=${runId} lease=${JSON.stringify((probeJobForRun(runId)).lease)}`);
}

// ── launcher re-exports (read-only T04C helpers) ──────────────────────────

export {
  launchFrontend,
  launchIsolatedBackend,
  stopLaunched,
  waitForBackendReady,
  waitForFrontendReady,
  assertPortFree,
  listenerOwnerPid,
  waitForPortListenerOwnedBy,
  isPidAlive,
};
export type { LaunchedBackend, LaunchedFrontend };

export function sha256File(p: string): string {
  return createHash("sha256").update(fs.readFileSync(p)).digest("hex");
}
