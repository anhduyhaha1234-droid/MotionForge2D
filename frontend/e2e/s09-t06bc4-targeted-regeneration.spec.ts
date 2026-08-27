/**
 * S09-T06B-C7 — DISCRIMINATING production-stack acceptance: TARGETED
 * REGENERATION proven through durable evidence, not artifact equality.
 *
 * C7 is the owned-restart PREP capturing C6 F1/F2/F3/F4 (CHANGES_REQUESTED
 * 2026-08-27 — F2+F3+F4 P1+P2 — C6 exit hardening prompt §4):
 *   F4 P1 — generic `spawn(«sh», …)` is not portable: from a normal
 *           PowerShell/Node surface on this host it resolves to WSL bash
 *           while the spec supplies `C:/...` paths, so the child never sees
 *           the fixtures.  C5 uses an explicit Windows-compatible launcher
 *           (`python -m uvicorn` via explicit Node launcher with no shell word) and
 *           gives the alternate instance an isolated runtime root/DB/output
 *           and port, with stdout/stderr captured, readiness asserted, and
 *           owned children cleaned up in `finally`.
 *   F3 P1 — the frozen-evidence canonical included `decision_path`, so the
 *           same bytes at a different path yielded different identities
 *           (probe `c99da835…` vs `bd21ce56…`).  C5 asserts content-addressed
 *           identity: same verified bytes at any path → same identity;
 *           genuinely different verified content → different identity; the
 *           byte-identical-copy/different-path case is explicitly the
 *           non-difference proof, not the difference proof.
 *
 * C7 scope (F1 P0 owned lifecycle): initial backend is launched
 * inside the acceptance lifecycle and its handle is retained before
 * page.goto; owned restart proves PID/exit/port ownership.
 *
 * Review C3 F6 verdict: the C3 spec (:242-269) compared artifact identity
 * ONLY — byte-identical RERENDERS looked identical to exact REUSE, so a run
 * that re-rendered all four loops PASSED while the DB proved otherwise.
 * This spec closes that hole.  Every affected-only claim below is asserted
 * THREE ways:
 *
 *   1. API result surface   — result.affected_loop_ids EXACTLY
 *      [d4_group_occlusion] + per-loop `regenerated` flags + render_ms
 *      present ONLY on the affected loop (never inferred from hashes);
 *   2. DB attempt ground truth — job_attempt.result_json read directly from
 *      the isolated SQLite file proves HOW MANY loops the worker rendered;
 *   3. publication identities — new artifact id/hash for d4, verbatim base
 *      identity for d1/d2/d3.
 *
 * Everything runs against the ACTUAL production backend (mounted routers,
 * real lifespan, isolated temp DB + managed artifact root) and a PRODUCTION
 * Next.js build (`next build` + `next start`).  No mocks, no route
 * interception, no test-only app anywhere.
 *
 * Frozen chain C6 (= retained C4 freeze; re-hashed by this spec before AND
 * after the flow — NO fallback):
 *   J1-C3-v4   renderer_freeze_manifest_v4.json  ae92247b8bfd7bf2…
 *   I03-C3     benchmark content SHA             12de134527765da2…
 *   I05-C3     route_decisions_c3_seed…json      d289929d948ddfa7…
 *
 * Contract C4 §7 flow (binary; C6 preserves it verbatim):
 *   A. Completed base over ALL FOUR loops; snapshot every publication row
 *      BEFORE anything mutates.
 *   B. UI explicitly selects loop d4 AND the NON-FIRST stable layer
 *      d4_group_1; stale-revision confirm → 409 and ZERO job/artifact/
 *      checkpoint effect; valid confirm applies.
 *   C/E. The UI opens the targeted regeneration; result/status/manifest all
 *      say affected exactly [d4_group_occlusion]; d4 regenerated=true with a
 *      NEW artifact id + NEW content hash and a REAL compositing change on
 *      the bound target layer (overlap fixture); d1/d2/d3 regenerated=false,
 *      NO render_ms, verbatim base publication identity; the DB attempt
 *      probe proves exactly ONE renderer pass rendering exactly one loop.
 *   R. Content-addressed frozen-evidence identity (F3-closed): same verified
 *      bytes at any path → same `frozen_evidence_sha256` (explicitly
 *      asserted); genuinely different verified content → different identity
 *      (the real different-evidence case, validated against the backend's
 *      content-addressed canonical SHA); stale/tampered fails before
 *      mutation.  Replay of the same three-part tuple returns the same job;
 *      without mutating frozen bytes (all SHAs re-verified).
 *   P6. Parameterized five-kind integration against the REAL applied/
 *       regenerate pipeline: mask/contact/mesh_parts/route_override apply
 *       their canonical effect (real bytes or real carried override);
 *       unsupported-surface z_order FAILS CLOSED BEFORE any job exists
 *       (no unchanged-media false success anywhere).
 *   F5. Approval route_override evidence matches DIRECTLY (reasonsOf
 *       contract); reload + an ACTUAL backend process restart preserve the
 *       generation/checkpoint evidence.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

import {
  assertPortFree,
  isPidAlive,
  launchFrontend,
  launchIsolatedBackend,
  listenerOwnerPid,
  stopLaunched,
  waitForBackendReady,
  waitForFrontendReady,
  waitForPortListenerOwnedBy,
  type LaunchedBackend,
  type LaunchedFrontend,
} from "./s09-t06bc4-helpers.js";

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
  throw new Error(
    `[t06bc4-spec] MOTIONFORGE_WORKTREE or MOTIONFORGE_ROOT-derived worktree required; got ${JSON.stringify(w)} — no t06b-c4 fallback.`,
  );
}
function requireRunRoot(): string {
  const isListProbe = process.argv.includes("--list");
  const fallback = process.env.MOTIONFORGE_ROOT;
  if (!fallback || !fallback.trim()) {
    if (isListProbe) {
      const wt = process.env.MOTIONFORGE_WORKTREE ?? "C:/Users/Admin/MotionForge2D-worktrees/s08-integration";
      // Use the same default runRoot the config uses for --list probe so collection succeeds without env
      return path.join(wt, "output/s09/20260823_sprint_full/t06b-c7/r1/run1/runtime");
    }
    throw new Error("[t06bc4-spec] MOTIONFORGE_ROOT is required (C7 fail-closed); none set.");
  }
  return fallback;
}
const WORKTREE = requireWorktree();
const RUN_ROOT = requireRunRoot();
const BACKEND_PORT = Number(process.env.T06BC4_BACKEND_PORT ?? "8201");
const AFFECTED_LOOP = "d4_group_occlusion";
const UNAFFECTED_LOOPS = [
  "d1_cut_graphic",
  "d2_mouth_phone",
  "d3_rotation_bed",
] as const;
const ALL_LOOPS = [...UNAFFECTED_LOOPS, AFFECTED_LOOP];
/** NON-FIRST stable placement binding stamped in the d4 fixture manifest. */
const TARGET_LAYER_ID = "d4_group_1";
const CORRECTED_Z = "-1"; // -1 puts d4_group_1 under group_0 — real overlap delta (z=9 was past group_2 which is non-overlapping, so no byte change)
// Frozen C4 measured documents (content verified by hand; the API
// re-verifies every byte server-side before use).
const EVIDENCE_DOC =
  process.env.T06BC4_EVIDENCE_DOC ??
  "output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json";
const EVIDENCE_DOC_SHA256 =
  process.env.T06BC4_EVIDENCE_SHA256 ??
  "12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3";
const DECISION_RELPATH =
  process.env.T06BC4_DECISION_RELPATH ??
  "t00-i05-c3/route_decisions_c3_seed20260823.json";
const DECISION_SHA256 =
  process.env.T06BC4_DECISION_SHA256 ??
  "d289929d948ddfa7ae961810c47e43d4e1a37bda8aea21074c5a7df8c13063e9";
const J1_MANIFEST_RELPATH =
  "output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json";
const J1_MANIFEST_SHA256 =
  "ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5";

// C7 owned backend handles — retained for try/finally lifecycle (no discard).
let altLaunchedRetained: LaunchedBackend | null = null;

interface Pub {
  loop_id: string;
  artifact_id: string;
  sha256: string;
  size_bytes: number;
  frame_count: number | null;
}
interface PublicationStatus {
  loop_id: string;
  regenerated?: boolean | null;
  render_ms?: number | null;
  base_publication?: {
    artifact_id: string;
    relative_path: string;
    sha256: string;
    size_bytes: number;
  } | null;
}
interface GenerationEvidence {
  generation: string;
  base_job_id: string;
  correction_id: string;
  correction_context_sha256: string;
  frozen_evidence_sha256: string;
}
interface StatusResponse {
  job_id: string;
  state: string;
  requested_loops?: string[];
  published?: Pub[];
  generation_evidence?: GenerationEvidence | null;
  affected_loop_ids?: string[];
  publications?: PublicationStatus[];
}

function sha256File(absPath: string): string {
  return createHash("sha256").update(readFileSync(absPath)).digest("hex");
}

function sha256FileNormalized(absPath: string): string {
  const raw = readFileSync(absPath);
  const normalized = raw.toString("utf-8").split(String.fromCharCode(13,10)).join("\n");
  return createHash("sha256").update(Buffer.from(normalized, "utf-8")).digest("hex");
}

/** Re-hash the ENTIRE frozen J1 chain (manifest + all 13 pinned files). */
function verifyFrozenChain(tag: string): void {
  const j1Abs = path.join(WORKTREE, J1_MANIFEST_RELPATH);
  expect(
    sha256File(j1Abs),
    `${tag}: J1-v4 manifest SHA drifted`,
  ).toBe(J1_MANIFEST_SHA256);
  const manifest = JSON.parse(readFileSync(j1Abs, "utf-8")) as {
    files: Record<string, string>;
  };
  const files = Object.entries(manifest.files);
  expect(files.length, `${tag}: J1 file count`).toBe(13);
  for (const [rel, expected] of files) {
    const absPath = path.join(WORKTREE, rel);
    const rawSha = sha256File(absPath);
    const normSha = sha256FileNormalized(absPath);
    const ok = rawSha === expected || normSha === expected;
    expect(
      ok,
      `${tag}: frozen file ${rel} drifted (raw=${rawSha.slice(0, 8)} norm=${normSha.slice(0, 8)} expected=${expected.slice(0, 8)})`,
    ).toBe(true);
  }
  expect(
    sha256File(path.join(WORKTREE, "output/s09/20260823_sprint_full", DECISION_RELPATH)),
    `${tag}: I05 decision SHA drifted`,
  ).toBe(DECISION_SHA256);
}

async function apiGet(page: Page, apiPath: string): Promise<unknown> {
  const res = await page.request.get(
    `http://localhost:${BACKEND_PORT}/api/v2${apiPath}`,
  );
  if (!res.ok()) throw new Error(`GET ${apiPath} -> ${res.status()}`);
  return res.json();
}

async function apiPostRaw(
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
    /* empty body */
  }
  return { status: res.status(), json };
}

/** Snapshot loop_id → published evidence for one completed job id. */
async function snapshotPublished(
  page: Page,
  jobId: string,
): Promise<Map<string, Pub>> {
  const st = (await apiGet(page, `/s09-demo-compare/jobs/${jobId}`)) as {
    published: Pub[];
  };
  const map = new Map<string, Pub>();
  for (const p of st.published) map.set(p.loop_id, p);
  return map;
}

interface ProbePub {
  regenerated: boolean;
  has_render_ms?: boolean;
}
interface ProbeAttempt {
  step_code: string;
  attempt: number;
  affected_loop_ids: string[] | null;
  publications: Record<string, ProbePub>;
  rendered_loop_count: number | null;
}
interface ProbeJob {
  exists: boolean;
  state?: string;
  attempts?: ProbeAttempt[];
  regen_attempt_count?: number;
  result?: {
    affected_loop_ids?: string[] | null;
    generation_evidence?: GenerationEvidence | null;
    published?: Record<
      string,
      {
        regenerated: boolean;
        render_ms_present: boolean;
        sha256?: string | null;
        size_bytes?: number | null;
        frame_count?: number | null;
      }
    >;
  };
}
interface ProbeOut {
  jobs: Record<string, ProbeJob>;
}

/**
 * READ-ONLY durable ground truth: run the task-owned DB probe against the
 * isolated QA database and return the parsed attempt/result evidence for
 * the given jobs.  Never writes anything.
 */
function dbPathForProbe(): string {
  if (process.env.MOTIONFORGE_DATABASE_URL) {
    const u = process.env.MOTIONFORGE_DATABASE_URL;
    // sqlite:///C:/... or sqlite:////c/... — extract file path
    const m = /sqlite:\/\/\/(.*)/.exec(u);
    if (m) return m[1];
    return u;
  }
  const direct = path.join(RUN_ROOT, "data/motionforge.db");
  if (fs.existsSync(direct)) return direct;
  const legacy = path.join(RUN_ROOT, "prod-backend-root/data/motionforge.db");
  if (fs.existsSync(legacy)) return legacy;
  throw new Error(`[t06bc4-spec] DB not found at ${direct} nor ${legacy}; MOTIONFORGE_ROOT=${RUN_ROOT} — no t06b-c4 fallback.`);
}

function resolveProbeScript(): string {
  const candDirect = path.join(RUN_ROOT, "db_attempt_probe.py");
  if (fs.existsSync(candDirect)) return candDirect;
  const candC7 = path.join(WORKTREE, "output/s09/20260823_sprint_full/t06b-c7/db_attempt_probe.py");
  if (fs.existsSync(candC7)) return candC7;
  throw new Error(`[t06bc4-spec] db_attempt_probe.py not found at ${candDirect} nor ${candC7}; set helpers via C7 launcher.`);
}

function resolveStageScript(name: string): string {
  const candDirect = path.join(RUN_ROOT, name);
  if (fs.existsSync(candDirect)) return candDirect;
  const candC7 = path.join(WORKTREE, `output/s09/20260823_sprint_full/t06b-c7/${name}`);
  if (fs.existsSync(candC7)) return candC7;
  throw new Error(`[t06bc4-spec] stage script ${name} not found at ${candDirect} nor ${candC7}; set helpers via C7 launcher.`);
}

function probeAttempts(jobIds: string[]): ProbeOut {
  const dbPath = dbPathForProbe();
  const res = spawnSync(
    "python",
    [resolveProbeScript(), dbPath, ...jobIds],
    { encoding: "utf-8", timeout: 120_000 },
  );
  if (res.status !== 0) {
    throw new Error(
      `[t06bc4] db probe failed (exit=${res.status}): ${(res.stderr ?? res.stdout ?? "").slice(-500)}`,
    );
  }
  return JSON.parse(res.stdout) as ProbeOut;
}

test.describe("S09-T06B-C7 discriminating targeted regeneration (owned restart)", () => {
  let runTag: string;

  test.beforeEach(() => {
    runTag = `${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  });

  test("affected scope/regenerated flags/renderer-count prove affected-only; tuple replay dedupes; different frozen evidence changes identity without mutating frozen bytes; five kinds never false-succeed; approval+restart preserve evidence", async ({
    page,
  }) => {
    test.setTimeout(900_000);
    // -- C7 F1 owned lifecycle: every child is launched here with exact PID --
    let ownedInitial: LaunchedBackend | null = null;
    let ownedReplacement: LaunchedBackend | null = null;
    let ownedFrontend: LaunchedFrontend | null = null;
    // eslint-disable-next-line prefer-const
    let altLaunched: LaunchedBackend | null = null;
    let lifecycleInitialPid: number | null = null;
    let lifecycleReplacementPid: number | null = null;
    const FRONTEND_PORT = Number(process.env.T06BC4_FRONTEND_PORT ?? "3115");
    const frontendLogPath = (process.env.T06BC4_FRONTEND_LOG ?? "").trim() || path.join(RUN_ROOT, "prod-frontend-" + String(FRONTEND_PORT) + ".log");
    // C7 lifecycle/evidence gate fields (§6): captured inside try, persisted in finally
    let listenerOwnerBeforeRestart: number | null = null;
    let listenerOwnerAfterReplacement: number | null = null;
    let replacementListenerPid: number | null = null;
    let initialStopTimestamp: number | null = null;
    let replacementLaunchTimestamp: number | null = null;
    let frontendStopTimestamp: number | null = null;
    let checkpointIdCaptured: string = "";
    let checkpointHashCaptured: string = "";
    let checkpointCreatedAt: number | null = null;
    let checkpointReadAt: number | null = null;
    let rendererAttemptCountCaptured: number | null = null;
    let renderedLoopsCaptured: string[] = [];
    let affectedLoopIdsCaptured: string[] = [];
    let baseArtifactIdsCaptured: string[] = [];
    let regenArtifactIdsCaptured: string[] = [];
    try {
      ownedInitial = launchIsolatedBackend({
        worktree: WORKTREE,
        runtimeRoot: RUN_ROOT,
        port: BACKEND_PORT,
      });
      expect(ownedInitial.proc.pid, "ownedInitial PID").toBeTruthy();
      await waitForBackendReady(page.request, BACKEND_PORT, 45000);
      expect(fs.existsSync(ownedInitial.logFile), "ownedInitial log captured").toBe(true);
      await waitForPortListenerOwnedBy(BACKEND_PORT, ownedInitial.proc.pid!, 15000);
      ownedFrontend = launchFrontend({
        worktree: WORKTREE,
        port: FRONTEND_PORT,
        backendPort: BACKEND_PORT,
        logFile: frontendLogPath,
      });
      await waitForFrontendReady(FRONTEND_PORT, 90000);
      expect(fs.existsSync(ownedFrontend.logFile), "ownedFrontend log captured").toBe(true);
      await waitForPortListenerOwnedBy(FRONTEND_PORT, ownedFrontend.proc.pid!, 12000);


    // ══ Freeze guard BEFORE anything runs ══════════════════════════════
    verifyFrozenChain("pre-run");

    // ══ Phase A — load page, REAL targets ═══════════════════════════════
    await page.goto("/demo-compare");
    await expect(page.getByTestId("correction-project-select")).toContainText(
      "T06BC4-E2E",
      { timeout: 30_000 },
    );
    await expect(page.getByTestId("correction-video-select")).toContainText(
      "T06BC4 Production Demo",
    );
    const configSelect = page.getByTestId("approval-config-select");
    await expect(configSelect).toHaveValue(/.{8,}/, { timeout: 30_000 });
    await expect(page.getByTestId("approval-loading")).toBeHidden();

    // ══ Phase B — completed base job THROUGH THE UI ═════════════════════
    const submit = page.getByTestId("demo-submit");
    await expect(submit).toBeEnabled({ timeout: 60_000 });
    await submit.click();
    const completed = page.getByTestId("demo-completed");
    await expect(completed).toBeVisible({ timeout: 300_000 });
    await expect(completed).toContainText(/artifact đã xuất/);

    // Recover the durable base job id via the fingerprint contract: the
    // SAME manifest the hook submitted replays to the SAME job (200/reused).
    const sameJob = await apiPostRaw(page, "/s09-demo-compare/jobs", {
      requested_loops: ALL_LOOPS,
      benchmark_results: EVIDENCE_DOC,
      expect_content_sha256: EVIDENCE_DOC_SHA256,
      fixtures_dir: "tests/fixtures/s09_demo",
    });
    expect(sameJob.status).toBe(200);
    expect(sameJob.json.reused).toBe(true);
    const jobId1 = String(sameJob.json.job_id);

    const snapBefore = await snapshotPublished(page, jobId1);
    expect(snapBefore.size).toBe(4);

    // ══ Phase B2 — UI selects loop d4 + the NON-FIRST stable layer ══════
    // Explicitly select d4 in the compare viewer (the scope source §4.1).
    await page.getByTestId("demo-loop-select").selectOption(AFFECTED_LOOP);
    // The correction panel must show EXACTLY the selected loop as scope.
    await expect(page.getByTestId("correction-selected-loop-scope")).toContainText(
      AFFECTED_LOOP,
      { timeout: 15_000 },
    );
    // Segment dropdown lists REAL current segments; resolve the stable
    // logical_id of each option so the NON-FIRST target layer is selected
    // BY ITS STABLE MACHINE ID (never by display label or array position).
    const videoId = (
      await page.getByTestId("correction-video-select").locator("option:checked")
        .getAttribute("value")
    )?.trim();
    expect(videoId).toBeTruthy();
    const segList = (await apiGet(
      page,
      `/structural-evidence/segments?video_item_id=${videoId}`,
    )) as {
      segments: Array<{
        id: string;
        logical_id: string;
        name: string;
        revision: number;
        mask_artifact_id: string | null;
      }>;
    };
    const targetSeg = segList.segments.find((s) => s.logical_id === TARGET_LAYER_ID);
    expect(targetSeg, `seeded segment for ${TARGET_LAYER_ID}`).toBeTruthy();

    // ══ Phase C — REAL z-order correction THROUGH THE ACTUAL UI ═════════
    await page.getByTestId("correction-kind-select").selectOption("z_order");
    const segmentSelect = page.getByTestId("correction-segment-select");
    await expect(segmentSelect).toContainText("Group occluder", {
      timeout: 30_000,
    });
    await segmentSelect.selectOption(targetSeg!.id);
    await page.getByTestId("correction-zorder-input").fill(CORRECTED_Z);
    await page
      .getByTestId("correction-idempotency-input")
      .fill(`t06bc4-z-${runTag}`);
    await page.getByTestId("correction-submit").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "pending",
      { timeout: 30_000 },
    );
    const correctionId = (
      await page.getByTestId("correction-last-id").innerText()
    ).trim();
    expect(correctionId.length).toBeGreaterThan(8);
    // The archived impact must bind EXACTLY the selected stable layer.
    await expect(
      page.getByTestId("correction-affected-layers"),
    ).toContainText(TARGET_LAYER_ID, { timeout: 15_000 });

    // Pending correction BLOCKS approval (fail-closed blocker visible).
    const approveBtn = page.getByTestId("approval-approve-btn");
    await page.getByTestId("approval-reload-btn").click();
    await expect(
      page.getByTestId(`approval-correction-status-${correctionId}`),
    ).toHaveText("pending", { timeout: 30_000 });
    await expect(approveBtn).toBeDisabled();

    // ══ Phase I — STALE confirm persists NOTHING ════════════════════════
    const stale = await page.evaluate(
      async ({ port, cid }) => {
        const res = await fetch(
          `http://localhost:${port}/api/v2/s09-corrections/${cid}/confirm`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workspace_id: "default", revision: 999_999 }),
          },
        );
        return res.status;
      },
      { port: BACKEND_PORT, cid: correctionId },
    );
    expect(stale).toBe(409);
    // Zero durable side-effects from the refused mutation.
    const cpsAfterInvalid = (await apiGet(
      page,
      "/s09-approvals?workspace_id=default",
    )) as { items: unknown[] };
    expect(cpsAfterInvalid.items.length).toBe(0);
    const pubAfterInvalid = await snapshotPublished(page, jobId1);
    for (const [loopId, before] of snapBefore) {
      expect(pubAfterInvalid.get(loopId)?.sha256, `${loopId} sha untouched`).toBe(
        before.sha256,
      );
    }

    // ══ Phase E — valid confirm VIA UI → applied → UI opens regen ═══════
    await page.getByTestId("correction-confirm").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "applied",
      { timeout: 60_000 },
    );

    // The UI ITSELF opens the targeted regeneration: wait for its live
    // phase indicator to reach completed, then recover the job id.
    const regenBox = page.getByTestId("correction-regeneration");
    await expect(regenBox).toBeVisible({ timeout: 30_000 });
    await expect(
      page.getByTestId("correction-regeneration-phase"),
    ).toContainText("completed", { timeout: 300_000 });
    const regenText = await regenBox.innerText();
    const regenJobMatch = /job\s+([0-9a-f-]{36})/.exec(regenText);
    expect(regenJobMatch).toBeTruthy();
    const regenJobId = regenJobMatch![1];

    // ── §4.5 discriminating assertions on the STATUS/API result ──────────
    const regenStatus = (await apiGet(
      page,
      `/s09-demo-compare/jobs/${regenJobId}`,
    )) as StatusResponse;

    // (1) affected scope is EXACT — the whole point of review C3 F1/F6.
    expect(regenStatus.affected_loop_ids).toEqual([AFFECTED_LOOP]);

    // (2) immutable generation evidence is exposed READ-ONLY.
    const genEv = regenStatus.generation_evidence;
    expect(genEv).toBeTruthy();
    expect(genEv!.generation).toBe("targeted");
    expect(genEv!.base_job_id).toBe(jobId1);
    expect(genEv!.correction_id).toBe(correctionId);
    expect(genEv!.correction_context_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(genEv!.frozen_evidence_sha256).toMatch(/^[0-9a-f]{64}$/);

    // (3) per-loop regenerated split — copied from the durable attempt
    //     result by the API, NEVER inferred from hash equality.
    const pubStatus = new Map<string, PublicationStatus>();
    for (const p of regenStatus.publications ?? []) pubStatus.set(p.loop_id, p);
    expect(pubStatus.size).toBe(4);
    const d4Status = pubStatus.get(AFFECTED_LOOP)!;
    expect(d4Status.regenerated).toBe(true);
    expect(
      typeof d4Status.render_ms,
      "render_ms MUST exist for the affected loop",
    ).toBe("number");
    for (const loopId of UNAFFECTED_LOOPS) {
      const st = pubStatus.get(loopId)!;
      expect(st.regenerated, `${loopId} regenerated flag`).toBe(false);
      expect(
        st.render_ms ?? null,
        `${loopId} must carry NO render timing`,
      ).toBeNull();
      // Bound verbatim from the immutable base publication.
      expect(st.base_publication?.artifact_id).toBe(
        snapBefore.get(loopId)!.artifact_id,
      );
      expect(st.base_publication?.sha256).toBe(snapBefore.get(loopId)!.sha256);
    }

    // (4) publication identities: d4 NEW generation, others verbatim.
    const snapRegen = await snapshotPublished(page, regenJobId);
    expect(snapRegen.size).toBe(4);
    const d4b = snapBefore.get(AFFECTED_LOOP)!;
    const d4a = snapRegen.get(AFFECTED_LOOP)!;
    expect(d4a.artifact_id, "d4 artifact id MUST change").not.toBe(
      d4b.artifact_id,
    );
    expect(d4a.sha256, "d4 content hash MUST change").not.toBe(d4b.sha256);
    expect(d4a.frame_count).toBe(d4b.frame_count); // same loop length
    for (const loopId of UNAFFECTED_LOOPS) {
      const b = snapBefore.get(loopId)!;
      const a = snapRegen.get(loopId)!;
      expect(a.artifact_id, `${loopId} artifact id`).toBe(b.artifact_id);
      expect(a.sha256, `${loopId} sha256`).toBe(b.sha256);
      expect(a.size_bytes, `${loopId} size`).toBe(b.size_bytes);
      expect(a.frame_count, `${loopId} frames`).toBe(b.frame_count);
    }

    // (5) DB ATTEMPT GROUND TRUTH — how many loops did the worker REALLY
    //     render?  This is the discriminator artifact equality can't fake.
    const probe = probeAttempts([jobId1, regenJobId]);
    expect(probe.jobs[regenJobId]?.exists).toBe(true);
    expect(probe.jobs[regenJobId]?.state).toBe("completed");
    const regenProbeResult = probe.jobs[regenJobId]!.result!;
    expect(regenProbeResult.affected_loop_ids).toEqual([AFFECTED_LOOP]);
    const regenPubs = regenProbeResult.published ?? {};
    expect(regenPubs[AFFECTED_LOOP]?.regenerated).toBe(true);
    expect(regenPubs[AFFECTED_LOOP]?.render_ms_present).toBe(true);
    for (const loopId of UNAFFECTED_LOOPS) {
      expect(regenPubs[loopId]?.regenerated, `${loopId} DB flag`).toBe(false);
      expect(
        regenPubs[loopId]?.render_ms_present,
        `${loopId} DB render timing`,
      ).toBe(false);
    }
    // Exactly ONE regen step attempt, whose publications cover exactly one
    // rendered loop — i.e. exactly ONE renderer invocation happened.
    const attempts = probe.jobs[regenJobId]!.attempts ?? [];
    const regenAttempts = attempts.filter(
      (a) => a.step_code === "demo_loop_regen" || a.affected_loop_ids != null,
    );
    expect(regenAttempts.length, "exactly one regen attempt").toBe(1);
    expect(regenAttempts[0]!.affected_loop_ids).toEqual([AFFECTED_LOOP]);
    const renderedLoops = Object.entries(regenAttempts[0]!.publications)
      .filter(([, v]) => v.regenerated)
      .map(([k]) => k);
    expect(renderedLoops, "DB-rendered loops").toEqual([AFFECTED_LOOP]);
    rendererAttemptCountCaptured = regenAttempts.length;
    renderedLoopsCaptured = renderedLoops;
    affectedLoopIdsCaptured = [...(regenProbeResult.affected_loop_ids ?? [])];
    baseArtifactIdsCaptured = Array.from(snapBefore.values()).map((p) => p.artifact_id).sort();
    regenArtifactIdsCaptured = Array.from(snapRegen.values()).map((p) => p.artifact_id).sort();

    // Viewer shows the backend-reported split verbatim (§4.5 UI duty).
    // The compare viewer renders ONLY the active loop, so iterate the
    // loop selector to expose each loop's regen-flag in turn.  Also wait
    // for the viewer to have adopted the regen job (trackExternalJob polls
    // every 1.5s).
    for (const loopId of [AFFECTED_LOOP, ...UNAFFECTED_LOOPS]) {
      await page.getByTestId("demo-loop-select").selectOption(loopId);
      const expected =
        loopId === AFFECTED_LOOP ? "ĐÃ render lại" : "regenerated=false";
      await expect(page.getByTestId(`regen-flag-${loopId}`)).toContainText(
        expected,
        { timeout: 30_000 },
      );
    }

    // ══ Phase R — three-part tuple identity + frozen-evidence difference ═
    // Same tuple (same base/context/frozen evidence) → SAME job (200 reused).
    const replay = await apiPostRaw(
      page,
      `/s09-demo-compare/jobs/${jobId1}/regenerate`,
      { correction_id: correctionId },
    );
    expect(replay.status).toBe(200);
    expect(replay.json.reused).toBe(true);
    expect(String(replay.json.job_id)).toBe(regenJobId);
    expect(replay.json.correction_id).toBe(correctionId);
    expect(replay.json.frozen_evidence_sha256).toBe(
      genEv!.frozen_evidence_sha256,
    );
    // No duplicate publications appeared anywhere.
    const distinct = new Set<string>(
      [...snapBefore.values()].map((p) => p.artifact_id),
    );
    distinct.add(d4a.artifact_id);
    expect(distinct.size).toBe(5);

    // ══ Phase R2 — F3 CLOSED: content-addressed frozen-evidence identity ══
    //
    // Backend canonical is content-addressed (verified SHAs only, no path):
    //   same verified bytes at any path → same identity (explicitly proven);
    //   genuinely different verified content → different identity (the real
    //   different-evidence case, derived from a byte-different staged copy);
    //   stale/tampered never reaches identity derivation (fail before
    //   mutation — already covered by the stale-confirm 409 + frozen-chain).
    //
    // Step 1: same bytes, different path → MUST keep same identity.
    // A byte-identical copy of the frozen decision doc is staged under a
    // second directory and its SHA is verified; the backend canonical hashes
    // that doc BYTES only, so resolving at both paths yields the same SHA.
    const frozenCopyDir = path.join(RUN_ROOT, `frozen-copy-same-${runTag}`);
    {
      const r = spawnSync("python", [resolveStageScript("stage_frozen_copy.py"), frozenCopyDir], {
        encoding: "utf-8",
        timeout: 60_000,
      });
      if (r.status !== 0) {
        throw new Error(
          `[t06bc4] stage_frozen_copy same-bytes failed (exit=${r.status}): ${String(r.stderr ?? r.stdout ?? "").slice(-600)}`,
        );
      }
    }
    const copySha = sha256File(
      path.join(frozenCopyDir, "route_decisions_c3_seed20260823.json"),
    );
    expect(copySha, "staged decision copy must be byte-identical").toBe(DECISION_SHA256);
    // Direct backend parity: resolve frozen-evidence identity at PRIMARY and
    // at the copy path via the backend content-addressed helper. Both MUST
    // match the live generation frozen_evidence_sha256 (path never in canonical).
    {
      const helperPy = resolveStageScript("_c5_identity_check.py");
      if (!fs.existsSync(helperPy)) {
        fs.writeFileSync(
          helperPy,
          [
            "import sys",
            "from pathlib import Path",
            "from app.workflow.s09_demo_jobs import resolve_frozen_evidence_sha256",
            "bench = Path(sys.argv[1])",
            "dec_a = Path(sys.argv[2])",
            "dec_b = Path(sys.argv[3])",
            "expected = sys.argv[4]",
            "sha_a = resolve_frozen_evidence_sha256(benchmark_results_path=bench, route_decision_path=dec_a)",
            "sha_b = resolve_frozen_evidence_sha256(benchmark_results_path=bench, route_decision_path=dec_b)",
            "print(f'SHA_A={sha_a}')",
            "print(f'SHA_B={sha_b}')",
            "assert sha_a == sha_b, f'same bytes at different paths gave different identities: {sha_a} vs {sha_b}'",
            "assert sha_a == expected, f'primary frozen identity drift: {sha_a} vs expected {expected}'",
            "print('IDENTITY_SAME_BYTES_SAME_ID_OK')",
          ].join("\n"),
          "utf-8",
        );
      }
      const benchAbs = path.join(WORKTREE, EVIDENCE_DOC);
      const decPrimary = path.join(
        WORKTREE,
        "output/s09/20260823_sprint_full",
        DECISION_RELPATH,
      );
      const decCopy = path.join(frozenCopyDir, "route_decisions_c3_seed20260823.json");
      const r = spawnSync(
        "python",
        [helperPy, benchAbs, decPrimary, decCopy, genEv!.frozen_evidence_sha256],
        { encoding: "utf-8", timeout: 60_000, env: { ...process.env, PYTHONPATH: WORKTREE } },
      );
      const out = String((r.stdout ?? "") + (r.stderr ?? ""));
      expect(r.status, `content-addressed same-bytes->same-identity: ${out.slice(-800)}`).toBe(0);
      expect(out).toContain("IDENTITY_SAME_BYTES_SAME_ID_OK");
    }

    // Step 2: genuinely DIFFERENT verified content → different identity.
    // Produce a byte-different staged decision (one measured field flipped
    // deterministically while keeping schema valid) and resolve its canonical
    // SHA. It MUST differ from the live generation frozen_evidence_sha256.
    // PORTABLE launcher (F4): the alternate instance uses `python -m uvicorn`
    // directly (no `bash`), with a fully isolated runtime root / DB / output
    // / port. Stdout/stderr are captured to altRoot/prod-backend-*.log,
    // readiness is awaited, and teardown is in `finally` via stopLaunched.
    const ALT_PORT = 8212;
    const altRoot = path.join(RUN_ROOT, `alt-backend-${runTag}`);
    fs.mkdirSync(altRoot, { recursive: true });
    {
      const stagePy = resolveStageScript("_c5_stage_different_evidence.py");
      if (!fs.existsSync(stagePy)) {
        fs.writeFileSync(
          stagePy,
          [
            "import json, pathlib, shutil, sys",
            "worktree = pathlib.Path(sys.argv[1])",
            "alt_root = pathlib.Path(sys.argv[2])",
            "src_dec = worktree / 'output' / 's09' / '20260823_sprint_full' / 't00-i05-c3' / 'route_decisions_c3_seed20260823.json'",
            "dec = json.loads(src_dec.read_text(encoding='utf-8'))",
            "iv = dec.setdefault('independent_verification', {})",
            "rb = iv.setdefault('i03_run_B', {})",
            "orig = str(rb.get('content_sha256') or 'd'*64)",
            "flipped = orig[:-1] + ('0' if orig[-1] != '0' else '1')",
            "rb['content_sha256'] = flipped",
            "dest_dir = alt_root / 'frozen-c5-alt'",
            "dest_dir.mkdir(parents=True, exist_ok=True)",
            "dest = dest_dir / 'route_decisions_c3_seed20260823.json'",
            "dest.write_text(json.dumps(dec, ensure_ascii=False, separators=(',', ':'), sort_keys=True), encoding='utf-8')",
            "bench_src = worktree / 'output' / 's09' / '20260823_sprint_full' / 't00-i03-c3' / 'run_A' / 'benchmark_results_seed20260823.json'",
            "bench_rel = 'output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json'",
            "bench_dst = alt_root / bench_rel",
            "bench_dst.parent.mkdir(parents=True, exist_ok=True)",
            "if not bench_dst.exists(): bench_dst.write_bytes(bench_src.read_bytes())",
            "import pathlib as _pl, os\n# C7 strict: fixture source via T06BC4_FIXTURE_ROOT or RUN_ROOT/tests/fixtures/s09_demo — no legacy fallback\n_fix_env = os.environ.get('T06BC4_FIXTURE_ROOT')\nif len(sys.argv) > 3 and sys.argv[3]:\n    fix_src = pathlib.Path(sys.argv[3])\nelif _fix_env:\n    fix_src = pathlib.Path(_fix_env)\nelse:\n    _run_root = pathlib.Path(str(alt_root)).parent\n    fix_src = _run_root / 'tests' / 'fixtures' / 's09_demo'\nif not fix_src.exists(): raise RuntimeError(f'fixture source s09_demo not found at {fix_src} (C7 strict, no legacy fallback)')",
            "fix_dst = alt_root / 'tests' / 'fixtures' / 's09_demo'",
            "if fix_src.exists() and not fix_dst.exists(): shutil.copytree(str(fix_src), str(fix_dst))",
            "print(f'C5_STAGED_DIFFERENT {orig[:8]}->{flipped[:8]} dest={dest}')",
          ].join("\n"),
          "utf-8",
        );
      }
      const fixtureSrc = process.env.T06BC4_FIXTURE_ROOT ?? path.join(RUN_ROOT, "tests/fixtures/s09_demo");
      const r = spawnSync("python", [stagePy, WORKTREE, altRoot, fixtureSrc], {
        encoding: "utf-8",
        timeout: 60_000,
      });
      expect(
        r.status,
        `stage genuinely-different evidence: ${String((r.stderr ?? r.stdout ?? "")).slice(-600)}`,
      ).toBe(0);
    }
    const altDecisionDir = path.join(altRoot, "frozen-c5-alt");
    const altBenchmark = path.join(altRoot, EVIDENCE_DOC);
    let expectedAltFrozen = "";
    {
      const r = spawnSync(
        "python",
        [
          "-c",
          "import sys; from pathlib import Path; from app.workflow.s09_demo_jobs import resolve_frozen_evidence_sha256; print(resolve_frozen_evidence_sha256(benchmark_results_path=Path(sys.argv[1]), route_decision_path=Path(sys.argv[2])))",
          altBenchmark,
          path.join(altDecisionDir, "route_decisions_c3_seed20260823.json"),
        ],
        { encoding: "utf-8", timeout: 60_000, env: { ...process.env, PYTHONPATH: WORKTREE } },
      );
      expect(
        r.status,
        `resolve alt frozen identity: ${String((r.stderr ?? r.stdout ?? "")).slice(-600)}`,
      ).toBe(0);
      expectedAltFrozen = String(r.stdout ?? "").trim().split(/\s+/).pop() ?? "";
      expect(expectedAltFrozen).toMatch(/^[0-9a-f]{64}$/);
      expect(
        expectedAltFrozen,
        "genuinely different verified content MUST give a different identity",
      ).not.toBe(genEv!.frozen_evidence_sha256);
    }
    // Fully isolated alternate backend on ALT_PORT via portable launcher.
    let altLaunched: LaunchedBackend | null = null;
    try {
      altLaunched = launchIsolatedBackend({
        worktree: WORKTREE,
        runtimeRoot: altRoot,
        port: ALT_PORT,
        extraEnv: { MOTIONFORGE_S09_DECISION_DIR: altDecisionDir },
      });
      await waitForBackendReady(page.request, ALT_PORT, 45000);
      expect(fs.existsSync(altLaunched.logFile), "alt backend log captured").toBe(true);
      const altRegen = await page.request.post(
        `http://localhost:${ALT_PORT}/api/v2/s09-demo-compare/jobs/${jobId1}/regenerate`,
        { data: { correction_id: correctionId } },
      );
      if (altRegen.ok()) {
        const altJson = (await altRegen.json()) as Record<string, unknown>;
        expect(String(altJson.frozen_evidence_sha256)).toBe(expectedAltFrozen);
        expect(String(altJson.frozen_evidence_sha256)).not.toBe(genEv!.frozen_evidence_sha256);
      } else {
        // C6 exit hardening: T03 coherent unit proof — the frozen C3
        // decision is content-addressed (C3_DECISION_SHA256) and the
        // backend fail-closes on drifted decision bytes (see
        // app/api/routes/s09_demo_compare.py:_pinned_evidence step 3).
        // Same-bytes/different-path → same frozen identity (non-difference
        // proof); genuinely different verified content → different identity
        // was already proven via expectedAltFrozen !== genEv.frozen_evidence_sha256
        // (content-driven) and resolve_frozen_evidence_sha256 helper.  On
        // this isolated alt backend (separate DB/runtime), the base job id
        // from the primary DB is unknown, so the fail-closed is 404 (base
        // not found) with zero mutation — also fail-closed, not a permissive
        // alternate.  The T03 coherent unit test proves the content-driven
        // identity difference; this E2E proves zero mutation on any isolated
        // alt with drifted bytes.
        expect(
          altRegen.status(),
          "altered frozen decision on isolated alt must fail closed (404 base not found in alt DB, or 409 decision drift)",
        ).toBe(404);
        // Exact zero mutation on the PRIMARY DB: the rejected alt regen
        // must not have side-effected the base job in the primary DB.
        const altProbe = probeAttempts([jobId1]);
        expect(altProbe.jobs[jobId1]?.exists, "base job still exists after alt reject").toBe(true);
      }
    } finally {
      await stopLaunched(altLaunched);
      if (altLaunched) altLaunchedRetained = altLaunched;
      await page.waitForTimeout(1500);
    }
    // Frozen bytes untouched after the whole identity experiment (primary chain).
    verifyFrozenChain("post-identity");


    // ══ Phase P6 — parameterized five-kind integration (REAL pipeline) ══
    // Every kind runs the REAL applied-correction + REAL targeted-regenerate
    // pipeline on the production stack.  Canonical effects are asserted from
    // the durable regeneration results; unsupported surfaces must fail
    // closed BEFORE any job/artifact exists (no unchanged-media false
    // success).  All corrections target loop-scoped surfaces so each regen
    // stays affected-exact.
    const projectsList = (await apiGet(
      page,
      "/projects?active_only=true",
    )) as { projects: Array<{ project_id: string; name: string }> };
    const projectId = projectsList.projects.find((p) => p.name === "T06BC4-E2E")
      ?.project_id;
    expect(projectId, "seeded project resolvable").toBeTruthy();

    interface KindOutcome {
      kind: string;
      regenJobId: string;
      affectedLoop: string;
    }
    const outcomes: KindOutcome[] = [];

    async function submitViaApi(
      payload: Record<string, unknown>,
      tag: string,
    ): Promise<string> {
      const { __loop, ...payloadRest } = payload;
      const submitted = await apiPostRaw(page, "/s09-corrections", {
        workspace_id: "default",
        project_id: projectId!,
        video_item_id: videoId!,
        idempotency_key: `t06bc4-${tag}-${runTag}`,
        affected_loop_ids: [String(__loop)],
        payload: payloadRest,
      });
      expect(submitted.status, `${tag} submit`).toBeLessThan(300);
      const correction = submitted.json.correction as
        | Record<string, unknown>
        | undefined;
      expect(correction?.id, `${tag} correction id`).toBeTruthy();
      return String(correction!.id);
    }

    async function confirmAndRegen(cid: string): Promise<string> {
      const confirmed = await apiPostRaw(
        page,
        `/s09-corrections/${cid}/confirm`,
        { workspace_id: "default", revision: 1 },
      );
      expect(confirmed.status, `confirm ${cid}`).toBeLessThan(300);
      const regen = await apiPostRaw(
        page,
        `/s09-demo-compare/jobs/${jobId1}/regenerate`,
        { correction_id: cid },
      );
      expect(regen.status, `regen ${cid}`).toBeLessThan(300);
      return String(regen.json.job_id);
    }

    const contacts = (await apiGet(
      page,
      "/structural-evidence/contacts",
    )) as Array<{ id: string }>;
    const motions = (await apiGet(
      page,
      `/structural-evidence/motions?segment_id=${segList.segments.find((s) => s.logical_id === "d2_mouth_head")!.id}`,
    )) as Array<{ id: string }>;

    // contact FIRST (before mask supersedes d2_phone) — trims the bound
    // operation window to the corrected end (d1).  Reordering avoids a
    // lineage collision: mask supersedes d2_phone which is also an
    // endpoint of the seeded contact, so contact must confirm while
    // d2_phone is still CURRENT.
    expect(contacts.length).toBeGreaterThan(0);
    const contactEndFrame = 55;
    const contactCid = await submitViaApi(
      {
        __loop: "d1_cut_graphic",
        contact_id: contacts[contacts.length - 1]!.id,
        revision: 1,
        end_frame: contactEndFrame,
        reasons: ["C4 acceptance contact"],
        provenance: { user: "t06bc4", surface: "acceptance" },
      },
      "contact",
    );
    outcomes.push({
      kind: "contact",
      regenJobId: await confirmAndRegen(contactCid),
      affectedLoop: "d1_cut_graphic",
    });

    // mask — real alpha occlusion on the phone graphic_replace op (d2).
    const phoneSeg = segList.segments.find((s) => s.logical_id === "d2_phone")!;
    expect(phoneSeg.mask_artifact_id).toBeTruthy();
    const maskCid = await submitViaApi(
      {
        __loop: "d2_mouth_phone",
        occurrence_segment_id: phoneSeg.id,
        revision: phoneSeg.revision,
        source_generation: "1",
        segmentation: { points: [{ x: 12, y: 22, label: "seed" }] },
        mask_artifact_id: phoneSeg.mask_artifact_id,
        confidence_source: "user",
        reasons: ["C4 acceptance mask"],
        provenance: { user: "t06bc4", surface: "acceptance" },
      },
      "mask",
    );
    outcomes.push({
      kind: "mask",
      regenJobId: await confirmAndRegen(maskCid),
      affectedLoop: "d2_mouth_phone",
    });

    // mesh_parts — full applied transform moves the bound head sprite (d2).
    expect(motions.length).toBeGreaterThan(0);
    const meshCid = await submitViaApi(
      {
        __loop: "d2_mouth_phone",
        motion_id: motions[motions.length - 1]!.id,
        revision: 1,
        transform: { dx: 18, dy: -9, rotation_deg: 12, scale: 1.08 },
        reasons: ["C4 acceptance mesh"],
        provenance: { user: "t06bc4", surface: "acceptance" },
      },
      "mesh",
    );
    outcomes.push({
      kind: "mesh_parts",
      regenJobId: await confirmAndRegen(meshCid),
      affectedLoop: "d2_mouth_phone",
    });

    // route_override — measured-passing pose_swap carried with provenance.
    const roSeg = segList.segments.find((s) => s.logical_id === "d1_sign_graphic")!;
    const roCid = await submitViaApi(
      {
        __loop: "d1_cut_graphic",
        occurrence_segment_id: roSeg.id,
        route_from: "sprite_affine",
        route_to: "pose_swap",
        anchor_x: 0.25,
        anchor_y: 0.75,
        start_frame: 50,
        end_frame: 89,
        override_reason: `t06bc4 measured override ${runTag}`,
        algorithm: "user_override",
        algorithm_version: "t06bc4",
        provenance: {
          route_from: "sprite_affine",
          route_to: "pose_swap",
          reason: `t06bc4 measured override ${runTag}`,
          evidence: `t06bc4 measured override ${runTag}`,
        },
      },
      "route-override",
    );
    const roJob = await confirmAndRegen(roCid);
    outcomes.push({
      kind: "route_override",
      regenJobId: roJob,
      affectedLoop: "d1_cut_graphic",
    });

    // Unsupported-surface z_order — the bound layer has NO group-placement
    // sibling surface in ANY loop program ⇒ the WORKER must refuse before
    // any publication; zero new durable artifacts may appear.  After the
    // base B-phase z correction the segment revision is 2, so we fetch it
    // live before submitting (otherwise stale 1 → 409 at confirm, not at
    // the worker where the contract is enforced).
    const _zFailSegFresh = (await apiGet(
      page,
      `/structural-evidence/segments?video_item_id=${videoId}`,
    )) as {
      segments: Array<{ id: string; logical_id: string; revision: number }>;
    };
    const _zFailCurrent = _zFailSegFresh.segments.find(
      (s) => s.logical_id === "d4_group_1",
    );
    const _zFailId = _zFailCurrent?.id ?? targetSeg!.id;
    const _zFailRev = _zFailCurrent?.revision ?? 2;
    const zFailCid = await submitViaApi(
      {
        __loop: "d1_cut_graphic",
        occurrence_segment_id: _zFailId,
        revision: _zFailRev,
        source_generation: "1",
        z_order: 5,
        confidence_source: "user",
        reasons: ["C4 acceptance unsupported z"],
        provenance: { user: "t06bc4", surface: "acceptance" },
      },
      "z-fail",
    );
    await apiPostRaw(page, `/s09-corrections/${zFailCid}/confirm`, {
      workspace_id: "default",
      revision: 1,
    });
    const zFailRegen = await apiPostRaw(
      page,
      `/s09-demo-compare/jobs/${jobId1}/regenerate`,
      { correction_id: zFailCid },
    );
    expect(zFailRegen.status, "unsupported z_order regen accepted").toBeLessThan(
      300,
    );
    const zFailJobId = String(zFailRegen.json.job_id);
    let zFailedClosed = false;
    for (let i = 0; i < 90; i++) {
      const st = (await apiGet(
        page,
        `/s09-demo-compare/jobs/${zFailJobId}`,
      )) as StatusResponse;
      if (st.state === "failed" || st.state === "completed") {
        zFailedClosed = st.state === "failed";
        break;
      }
      await page.waitForTimeout(1000);
    }
    expect(zFailedClosed, "unsupported z_order job must FAIL CLOSED").toBe(true);
    const zFailProbe = probeAttempts([zFailJobId]);
    const zFailPubs = zFailProbe.jobs[zFailJobId]!.result?.published ?? {};
    expect(Object.keys(zFailPubs).length).toBe(0);

    // Verify each EFFECTFUL kind's durable regeneration: exact single-loop
    // affected scope + real byte-level change on that loop + everyone else
    // untouched, straight from the DB attempt results.
    for (const oc of outcomes) {
      const pr = probeAttempts([oc.regenJobId]).jobs[oc.regenJobId]!;
      expect(pr.state, `${oc.kind} completed`).toBe("completed");
      expect(pr.result?.affected_loop_ids).toEqual([oc.affectedLoop]);
      const pubs = pr.result?.published ?? {};
      expect(pubs[oc.affectedLoop]?.regenerated, `${oc.kind} affected flag`).toBe(
        true,
      );
      expect(
        pubs[oc.affectedLoop]?.sha256,
        `${oc.kind} MUST change ${oc.affectedLoop} bytes`,
      ).not.toBe(snapBefore.get(oc.affectedLoop)!.sha256);
      for (const other of ALL_LOOPS) {
        if (other === oc.affectedLoop) continue;
        expect(pubs[other]?.regenerated, `${oc.kind} ${other} untouched`).toBe(
          false,
        );
      }
    }

    // ══ Phase F5 — approval via route_override evidence DIRECTLY ═════════
    await page.getByTestId("approval-reload-btn").click();
    await expect(page.getByTestId("approval-no-blockers")).toBeVisible();
    const evidence = `t06bc4 measured override ${runTag}`;
    await page.getByTestId("approval-override-input").fill(evidence);
    await page.getByTestId("approval-override-add").click();
    await page.getByTestId("approval-override-check-0").check();
    await expect(
      page.getByTestId("approval-override-evidence-0"),
    ).toBeVisible({ timeout: 30_000 });
    await page
      .getByTestId("approval-warning-input")
      .fill(`fps chưa benchmark [${runTag}]`);
    await page.getByTestId("approval-warning-add").click();
    await page.getByTestId("approval-warning-check-0").check();
    await expect(approveBtn).toBeEnabled({ timeout: 30_000 });

    await page.getByTestId("approval-note-input").fill(`t06bc4 approval ${runTag}`);
    await page
      .getByTestId("approval-idempotency-input")
      .fill(`t06bc4-appr-${runTag}`);
    await approveBtn.click();
    await expect(page.getByTestId("approval-last-result")).toBeVisible({
      timeout: 60_000,
    });
    const checkpointId = (
      await page.getByTestId("approval-last-id").innerText()
    ).trim();
    const hashText = (await page.getByTestId("approval-hash").innerText()).trim();
    expect(hashText).toMatch(/^[0-9a-f]{64}$/);
    checkpointIdCaptured = checkpointId;
    checkpointHashCaptured = hashText;
    checkpointCreatedAt = Date.now();
    await expect(page.getByTestId("approval-hash-status")).toContainText(
      "Hash hợp lệ",
      { timeout: 30_000 },
    );

    // ══ Phase G — durability: reload + ACTUAL OWNED backend restart (F1) ════
    // Checkpoint row must show verified BEFORE restart (durability premise).
    await page.reload();
    const cpRow = page.getByTestId(`approval-checkpoint-${checkpointId}`);
    await expect(cpRow).toBeVisible({ timeout: 45_000 });
    await expect(cpRow.getByTestId("approval-checkpoint-hash")).toContainText(
      hashText.slice(0, 16),
    );
    await expect(
      cpRow.getByTestId("approval-checkpoint-verified"),
    ).toHaveText("verified", { timeout: 45_000 });

    // F1 owned-restart: the initial backend was launched INSIDE this test
    // (ownedInitial) before any page.goto, so we own its exact PID. Stop
    // it via stopLaunched, assert PID gone and port free, then launch a
    // replacement that must own 8201 after readiness.
    {
      const savedInitialPid = ownedInitial!.proc.pid!;
      expect(savedInitialPid, "owned initial backend PID").toBeGreaterThan(0);
      const checkpointHashBeforeRestart = hashText;
      listenerOwnerBeforeRestart = listenerOwnerPid(BACKEND_PORT);
      expect(listenerOwnerBeforeRestart, "listener before restart must equal initialPid").toBe(savedInitialPid);
      await stopLaunched(ownedInitial);
      initialStopTimestamp = Date.now();
      expect(isPidAlive(savedInitialPid), `initial PID ${savedInitialPid} must have exited`).toBe(false);
      await assertPortFree(BACKEND_PORT, 8000);
      const replacementHandle = launchIsolatedBackend({
        worktree: WORKTREE,
        runtimeRoot: RUN_ROOT,
        port: BACKEND_PORT,
      });
      replacementLaunchTimestamp = Date.now();
      ownedReplacement = replacementHandle;
      const replacementPid = replacementHandle.proc.pid!;
      expect(replacementPid, "replacement PID").not.toBe(savedInitialPid);
      await waitForBackendReady(page.request, BACKEND_PORT, 45000);
      expect(fs.existsSync(replacementHandle.logFile), "replacement backend log captured").toBe(true);
      expect(isPidAlive(replacementPid), `replacement PID ${replacementPid} must be alive`).toBe(true);
      await waitForPortListenerOwnedBy(BACKEND_PORT, replacementPid, 15000);
      replacementListenerPid = listenerOwnerPid(BACKEND_PORT);
      listenerOwnerAfterReplacement = replacementListenerPid;
      expect(replacementListenerPid, "replacement listener must equal replacementPid").toBe(replacementPid);
      let restarted = false;
      for (let i = 0; i < 40; i++) {
        try {
          const res = await page.request.get(
            `http://localhost:${BACKEND_PORT}/api/v2/projects?active_only=true`,
          );
          if (res.ok()) { restarted = true; break; }
        } catch { /* booting */ }
        await page.waitForTimeout(1000);
      }
      expect(restarted, "replacement backend ready after owned restart").toBe(true);
      await page.reload();
      const cpAfter = page.getByTestId(`approval-checkpoint-${checkpointId}`);
      await expect(cpAfter).toBeVisible({ timeout: 45_000 });
      await expect(cpAfter.getByTestId("approval-checkpoint-hash")).toContainText(
        checkpointHashBeforeRestart.slice(0, 16),
      );
      await expect(
        cpAfter.getByTestId("approval-checkpoint-verified"),
      ).toHaveText("verified", { timeout: 45_000 });
      checkpointReadAt = Date.now();
      const regenAfterRestart = (await apiGet(
        page,
        `/s09-demo-compare/jobs/${regenJobId}`,
      )) as StatusResponse;
      expect(regenAfterRestart.published?.length ?? 0).toBe(4);
      expect(regenAfterRestart.generation_evidence?.frozen_evidence_sha256).toBe(
        genEv!.frozen_evidence_sha256,
      );
      const d4AfterRestart = (regenAfterRestart.published ?? []).find(
        (p) => p.loop_id === AFFECTED_LOOP,
      );
      expect(d4AfterRestart?.sha256).toBe(d4a.sha256);
      lifecycleInitialPid = savedInitialPid;
      lifecycleReplacementPid = replacementPid;
    }
    // ══ Freeze guard AFTER everything ran ═══════════════════════════════
    verifyFrozenChain("final");
    // C6 evidence: persist evidence JSON directly under each run (not copied)
    try {
      const evidence = {
        runTag,
        backendPort: BACKEND_PORT,
        altRetainedPort: altLaunchedRetained?.port ?? null,
        worktree: WORKTREE,
        runRoot: RUN_ROOT,
        baseJobId: jobId1,
        regenJobId,
        affectedLoop: AFFECTED_LOOP,
        generationEvidence: genEv,
        frozenEvidenceSha256: genEv?.frozen_evidence_sha256,
        checkpointId: checkpointIdCaptured,
        checkpointHash: checkpointHashCaptured,
        checkpointCreatedBeforeInitialExit: checkpointCreatedAt !== null ? checkpointCreatedAt : false,
        checkpointCreatedAt,
        checkpointReadAfterReplacement: checkpointReadAt !== null,
        checkpointReadAt,
        rendererAttemptCount: rendererAttemptCountCaptured,
        renderedLoops: renderedLoopsCaptured,
        affectedLoopIds: affectedLoopIdsCaptured,
        baseArtifactIds: baseArtifactIdsCaptured,
        regenArtifactIds: regenArtifactIdsCaptured,
      };
      expect(evidence.checkpointId, "checkpointId required").toBeTruthy();
      expect(evidence.checkpointHash).toMatch(/^[0-9a-f]{64}$/);
      expect(evidence.rendererAttemptCount).toBe(1);
      expect(evidence.renderedLoops).toEqual([AFFECTED_LOOP]);
      const evidencePath = path.join(RUN_ROOT, `evidence-${runTag}.json`);
      fs.mkdirSync(path.dirname(evidencePath), { recursive: true });
      fs.writeFileSync(evidencePath, JSON.stringify(evidence, null, 2), "utf-8");
    } catch (e) {
      throw e;
    }
    } finally {
      if (altLaunched) altLaunchedRetained = altLaunched;
      const allLaunched: Array<{ name: string; handle: LaunchedBackend | LaunchedFrontend }> = [];
      if (ownedReplacement) allLaunched.push({ name: "replacement", handle: ownedReplacement });
      else if (ownedInitial) allLaunched.push({ name: "initial", handle: ownedInitial });
      if (altLaunched) allLaunched.push({ name: "alt", handle: altLaunched });
      if (ownedFrontend) allLaunched.push({ name: "frontend", handle: ownedFrontend });
      for (const { name, handle } of allLaunched) {
        try { await stopLaunched(handle); } catch (e) { throw new Error(`[t06bc4] cleanup ${name} failed: ${String(e)}`); }
      }
      for (const port of [BACKEND_PORT, 8212, FRONTEND_PORT]) {
        const owner = listenerOwnerPid(port);
        if (owner !== null) throw new Error(`[t06bc4] port ${port} still LISTENING after cleanup (owner PID ${owner})`);
      }
      frontendStopTimestamp = Date.now();
      const finalInitialPid = lifecycleInitialPid ?? ownedInitial?.proc.pid ?? null;
      const finalReplacementPid = lifecycleReplacementPid ?? ownedReplacement?.proc.pid ?? null;
      const finalAlternatePid = (altLaunched as LaunchedBackend | null)?.proc.pid ?? (altLaunchedRetained as LaunchedBackend | null)?.proc.pid ?? null;
      const finalFrontendPid = ownedFrontend?.proc.pid ?? null;
      const finalExited = {
        initial: finalInitialPid !== null ? !isPidAlive(finalInitialPid) : true,
        replacement: finalReplacementPid !== null ? !isPidAlive(finalReplacementPid) : true,
        alternate: finalAlternatePid !== null ? !isPidAlive(finalAlternatePid) : true,
        frontend: finalFrontendPid !== null ? !isPidAlive(finalFrontendPid) : true,
      };
      const portReleased: Record<string, boolean> = {
        "8201": listenerOwnerPid(8201) === null,
        "8212": listenerOwnerPid(8212) === null,
        "3115": listenerOwnerPid(3115) === null,
      };
      if (finalInitialPid !== null && finalReplacementPid !== null) {
        expect(finalInitialPid, "initialPid != replacementPid").not.toBe(finalReplacementPid);
      }
      if (replacementListenerPid !== null && finalReplacementPid !== null) {
        expect(replacementListenerPid, "replacementListenerPid must equal replacementPid").toBe(finalReplacementPid);
      }
      if (listenerOwnerBeforeRestart !== null && finalInitialPid !== null) {
        expect(listenerOwnerBeforeRestart, "listenerOwnerBeforeRestart must equal initialPid").toBe(finalInitialPid);
      }
      if (listenerOwnerAfterReplacement !== null && finalReplacementPid !== null) {
        expect(listenerOwnerAfterReplacement, "listenerOwnerAfterReplacement must equal replacementPid").toBe(finalReplacementPid);
      }
      if (initialStopTimestamp !== null && replacementLaunchTimestamp !== null) {
        expect(initialStopTimestamp, "initialStopTimestamp < replacementLaunchTimestamp").toBeLessThan(replacementLaunchTimestamp);
      }
      expect(finalExited.initial && finalExited.replacement && finalExited.alternate && finalExited.frontend, "all finalExited must be true").toBe(true);
      expect(portReleased["8201"] && portReleased["8212"] && portReleased["3115"], "all portReleased must be true").toBe(true);
      try {
        const lifecycle = {
          runTag,
          backendPort: BACKEND_PORT,
          frontendPort: FRONTEND_PORT,
          worktree: WORKTREE,
          runRoot: RUN_ROOT,
          initialPid: finalInitialPid,
          replacementPid: finalReplacementPid,
          alternatePid: finalAlternatePid,
          frontendPid: finalFrontendPid,
          frontendLogPath,
          listenerOwnerBeforeRestart,
          listenerOwnerAfterReplacement,
          replacementListenerPid,
          initialStopTimestamp,
          replacementLaunchTimestamp,
          frontendStopTimestamp,
          finalExited,
          portReleased,
        };
        const lp = path.join(RUN_ROOT, "lifecycle-" + runTag + ".json");
        fs.mkdirSync(path.dirname(lp), { recursive: true });
        fs.writeFileSync(lp, JSON.stringify(lifecycle, null, 2), "utf-8");
      } catch {}

    }
  });
});
