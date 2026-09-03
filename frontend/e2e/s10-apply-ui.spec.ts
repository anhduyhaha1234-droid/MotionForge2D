/**
 * S10-T04B-C3 (C6) — live-product Apply UI acceptance (non-vacuous).
 *
 * Replaces the empty-state UI suite with deterministic real-browser proof:
 * real production backend (isolated runtime) + current production Next build.
 * No page.route, no mocked API response, no direct run/status/evidence
 * mutation.  Every scenario establishes its own precondition through the
 * public product contract (POST /api/v2/s09-approvals, POST .../full-apply)
 * and then drives the REAL /apply UI.  No test.skip, no conditional
 * `.or(empty/loading/error)` for scenario claims, no early returns.
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

import {
  WORKTREE,
  RUN_ROOT,
  BACKEND_PORT,
  FRONTEND_PORT,
  FRONTEND_BASE,
  WS,
  MAIN_PROJECT_NAME,
  NOAUTH_PROJECT_NAME,
  EXEC_PROJECT_NAME,
  apiGet,
  apiPostOrThrow,
  probeRun,
  probePublicationArtifacts,
  resolveManagedArtifactPath,
  findProject,
  listVideos,
  getReskinConfig,
  getPackVersionId,
  ensureApproval,
  buildSubmitBody,
  submitRun,
  waitForRunStatus,
  waitForPartialChunk,
  waitLeaseFencible,
  launchIsolatedBackend,
  launchFrontend,
  stopLaunched,
  waitForBackendReady,
  waitForFrontendReady,
  assertPortFree,
  listenerOwnerPid,
  waitForPortListenerOwnedBy,
  isPidAlive,
  type LaunchedBackend,
  type LaunchedFrontend,
  type ApprovalInfo,
} from "./helpers/s10-apply-ui/api";

// ── evidence ──────────────────────────────────────────────────────────────

const EVIDENCE_DIR = path.join(RUN_ROOT, "c6-evidence");
const EVIDENCE_LOG = path.join(EVIDENCE_DIR, "c6-ui-evidence.jsonl");
const BUILD_ID = (() => {
  try {
    return fs
      .readFileSync(path.join(WORKTREE, "frontend/.next/BUILD_ID"), "utf-8")
      .trim();
  } catch {
    return "UNKNOWN";
  }
})();

function logEvidence(entry: Record<string, unknown>): void {
  try {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    fs.appendFileSync(
      EVIDENCE_LOG,
      `${JSON.stringify({ ...entry, build_id: BUILD_ID, ts: new Date().toISOString() })}\n`,
      "utf-8",
    );
  } catch {
    /* evidence only */
  }
}

async function shot(page: Page, name: string): Promise<void> {
  try {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    await page.screenshot({ path: path.join(EVIDENCE_DIR, `${name}.png`), fullPage: true });
  } catch {
    /* evidence only */
  }
}

// ── shared owned services (per project) ───────────────────────────────────

const state: { backend: LaunchedBackend | null; frontend: LaunchedFrontend | null } = {
  backend: null,
  frontend: null,
};

interface ProjectIdentity {
  projectId: string;
  videoId: string;
  reskinConfigId: string;
  packVersionId: string;
  structuralLockManifestId: string | null;
  lockPolicyVersion: string | null;
}

const identityCache = new Map<string, Promise<ProjectIdentity>>();

function getIdentity(page: Page, projectName: string): Promise<ProjectIdentity> {
  const cached = identityCache.get(projectName);
  if (cached) return cached;
  const p = (async () => {
    const project = await findProject(page, projectName);
    const videos = await listVideos(page, project.id);
    if (!videos.length) throw new Error(`project ${projectName} has no videos`);
    const reskin = await getReskinConfig(page, project.id);
    const packVersionId = getPackVersionId(reskin.id);
    return {
      projectId: project.id,
      videoId: videos[0],
      reskinConfigId: reskin.id,
      packVersionId,
      structuralLockManifestId: reskin.structural_lock_manifest_id,
      lockPolicyVersion: reskin.lock_policy_version,
    };
  })();
  identityCache.set(projectName, p);
  return p;
}

function projectSalt(projectName: string): number {
  return projectName.includes("mobile") ? 1 : 0;
}

async function createRealRun(
  page: Page,
  opts: { tag: string; chunkFrames: number; projectName: string },
): Promise<{ runId: string; approval: ApprovalInfo; identity: ProjectIdentity }> {
  // Run-creating scenarios use the EXEC project: its v2 approval authority is
  // executable under the minimal public contract (all sprite_affine segments
  // with real boxed geometry + published pack + source artifact).  The MAIN
  // project is NOT executable (mesh_warp + missing geometry) and stays as the
  // fail-closed reason-truth fixture.
  const identity = await getIdentity(page, EXEC_PROJECT_NAME);
  const approval = await ensureApproval(page, {
    projectId: identity.projectId,
    reskinConfigId: identity.reskinConfigId,
    packVersionId: identity.packVersionId,
    note: `S10-C6A ${opts.tag} approval`,
    tag: `${opts.tag}-${opts.projectName}`,
  });
  const body = buildSubmitBody({
    projectId: identity.projectId,
    videoId: identity.videoId,
    approval,
    chunkFrames: opts.chunkFrames + projectSalt(opts.projectName),
    overlapFrames: 4,
  });
  const run = await submitRun(page, identity.projectId, body);
  logEvidence({
    step: "run-created",
    tag: opts.tag,
    project: opts.projectName,
    project_id: identity.projectId,
    run_id: run.runId,
    approval_id: approval.id,
    chunk_frames: opts.chunkFrames + projectSalt(opts.projectName),
    status: run.status,
    created: run.created,
    method: "POST",
    path: `/api/v2/projects/${identity.projectId}/full-apply`,
  });
  return { runId: run.runId, approval, identity };
}

function uiStatusText(page: Page): Promise<string> {
  return page
    .getByTestId("apply-status")
    .innerText()
    .then((t) => t.split(":").pop()?.trim() ?? "");
}

function uiPct(page: Page): Promise<number> {
  return page
    .getByTestId("apply-progress-pct")
    .innerText()
    .then((t) => Number.parseInt(t.replace(/[^0-9]/g, ""), 10) || 0);
}

function uiChunkCount(page: Page): Promise<number> {
  return page
    .getByTestId("apply-frame-count")
    .innerText()
    .then((t) => {
      const m = /(\d+)\s*chunks?/.exec(t);
      return m ? Number.parseInt(m[1], 10) : -1;
    });
}

// ── suite ─────────────────────────────────────────────────────────────────

test.describe("S10-T04B-C3 live-product Apply UI acceptance (C6)", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ request }) => {
    await assertPortFree(BACKEND_PORT, 4000);
    state.backend = launchIsolatedBackend({
      worktree: WORKTREE,
      runtimeRoot: RUN_ROOT,
      port: BACKEND_PORT,
    });
    const pid = state.backend.proc.pid as number;
    await waitForBackendReady(
      request as unknown as Parameters<typeof waitForBackendReady>[0],
      BACKEND_PORT,
      45000,
    );
    await waitForPortListenerOwnedBy(BACKEND_PORT, pid, 10000);
    expect(isPidAlive(pid)).toBe(true);

    state.frontend = launchFrontend({
      worktree: WORKTREE,
      port: FRONTEND_PORT,
      backendPort: BACKEND_PORT,
      logFile: path.join(RUN_ROOT, `prod-frontend-${FRONTEND_PORT}.log`),
    });
    await waitForFrontendReady(FRONTEND_PORT, 90000);
    expect(isPidAlive(state.frontend.proc.pid as number)).toBe(true);
    logEvidence({
      step: "services-up",
      backend_pid: pid,
      frontend_pid: state.frontend.proc.pid,
      backend_port: BACKEND_PORT,
      frontend_port: FRONTEND_PORT,
      run_root: RUN_ROOT,
    });
  });

  test.afterAll(async () => {
    const errors: string[] = [];
    for (const h of [state.backend, state.frontend]) {
      if (!h) continue;
      try {
        await stopLaunched(h, { graceMs: 5000, killGraceMs: 3000 });
      } catch (e) {
        errors.push(String(e));
      }
    }
    state.backend = null;
    state.frontend = null;
    for (const p of [BACKEND_PORT, FRONTEND_PORT]) {
      const owner = listenerOwnerPid(p);
      expect(owner, `task port ${p} must be released after cleanup`).toBeNull();
    }
    if (errors.length) throw new Error(`afterAll stopLaunched errors: ${errors.join(" | ")}`);
    logEvidence({ step: "services-down" });
  });

  // ── 1. Approval gate ────────────────────────────────────────────────────
  test("approval gate: Apply disabled with no approval; v1 shows REAPPROVAL_REQUIRED; v2 product approval enables", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const execIdentity = await getIdentity(page, EXEC_PROJECT_NAME);

    await page.goto(`${FRONTEND_BASE}/apply`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const card = page.getByTestId("apply-card");
    await expect(card).toBeVisible({ timeout: 30000 });
    const submit = page.getByTestId("apply-submit");
    await expect(submit).toBeVisible({ timeout: 30000 });

    // Select the EXEC project explicitly (it has no approvals at this point).
    const projectSelect = page.getByTestId("apply-project-select");
    await expect(projectSelect).toBeVisible({ timeout: 30000 });
    await projectSelect.selectOption(execIdentity.projectId);

    // REAL disabled (no approval yet): exact truthful product reason.
    await expect(submit).toBeDisabled();
    const helper = page.getByTestId("apply-submit-helper");
    await expect(helper).toBeVisible();
    const disabledText = (await helper.innerText()).toLowerCase();
    expect(disabledText).toMatch(
      /chưa có checkpoint duyệt|chưa chọn checkpoint duyệt|chưa có approval|approval/,
    );
    await shot(page, `t1-disabled-${projectName}`);
    logEvidence({
      step: "approval-gate-disabled",
      project: projectName,
      disabled: true,
      helper_text: disabledText,
    });

    // v1 approval through the public product contract → selecting it must
    // show the truthful REAPPROVAL_REQUIRED reason and keep Apply disabled.
    const v1 = await ensureApproval(page, {
      projectId: execIdentity.projectId,
      reskinConfigId: execIdentity.reskinConfigId,
      packVersionId: execIdentity.packVersionId,
      note: "S10-C6A approval gate v1",
      tag: `gate-v1-${projectName}`,
      schema: "v1",
    });
    await page.reload();
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    await expect(projectSelect).toBeVisible({ timeout: 30000 });
    await projectSelect.selectOption(execIdentity.projectId);
    const cpSelect = page.getByTestId("apply-checkpoint-select");
    await expect(cpSelect).toBeVisible({ timeout: 30000 });
    await cpSelect.selectOption(v1.id);
    await expect(submit).toBeDisabled();
    const v1Helper = (await helper.innerText()).toLowerCase();
    expect(v1Helper).toMatch(/reapproval_required|duyệt lại|reapproval/);
    await shot(page, `t1-v1-reapproval-${projectName}`);
    logEvidence({
      step: "approval-gate-v1-reapproval-required",
      project: projectName,
      approval_id: v1.id,
      disabled: true,
      helper_text: v1Helper,
    });

    // v2 approval via reapprove → selecting the SAME identity authority
    // enables Apply (eligibility truth full_apply_executable === true).
    const v2 = await ensureApproval(page, {
      projectId: execIdentity.projectId,
      reskinConfigId: execIdentity.reskinConfigId,
      packVersionId: execIdentity.packVersionId,
      note: "S10-C6A approval gate v2",
      tag: `gate-v2-${projectName}`,
    });
    await page.reload();
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    await expect(projectSelect).toBeVisible({ timeout: 30000 });
    await projectSelect.selectOption(execIdentity.projectId);
    await expect(cpSelect).toBeVisible({ timeout: 30000 });
    await cpSelect.selectOption(v2.id);
    // CORE: selecting the executable v2 authority must enable Apply.
    await expect(submit).toBeEnabled();
    const enabledText = (await helper.innerText()).toLowerCase();
    expect(enabledText).not.toContain("không thể gửi apply");
    await shot(page, `t1-enabled-${projectName}`);
    logEvidence({
      step: "approval-gate-enabled",
      project: projectName,
      approval_id: v2.id,
      enabled: true,
      helper_text: enabledText,
    });

    // Incomplete authority (NOAUTH v2 — no structural lock manifest pinned)
    // must keep Apply disabled with the truthful server reason.
    const noauthIdentity = await getIdentity(page, NOAUTH_PROJECT_NAME);
    expect(noauthIdentity.structuralLockManifestId).toBeFalsy();
    const noauthV2 = await ensureApproval(page, {
      projectId: noauthIdentity.projectId,
      reskinConfigId: noauthIdentity.reskinConfigId,
      packVersionId: noauthIdentity.packVersionId,
      note: "S10-C6A approval gate noauth v2",
      tag: `gate-noauth-${projectName}`,
    });
    await projectSelect.selectOption(noauthIdentity.projectId);
    await expect(cpSelect).toBeVisible({ timeout: 30000 });
    await cpSelect.selectOption(noauthV2.id);
    await expect(submit).toBeDisabled();
    const noauthHelper = (await helper.innerText()).toLowerCase();
    expect(noauthHelper).toMatch(/không cho phép apply|structural lock|manifest|authority/);
    await shot(page, `t1-incomplete-authority-${projectName}`);
    logEvidence({
      step: "approval-gate-incomplete-authority",
      project: projectName,
      approval_id: noauthV2.id,
      disabled: true,
      helper_text: noauthHelper,
    });
  });

  // ── 2. Submit from UI ───────────────────────────────────────────────────
  test("submit from UI: Apply click sends real request, durable run identity persists", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const identity = await getIdentity(page, EXEC_PROJECT_NAME);
    const approval = await ensureApproval(page, {
      projectId: identity.projectId,
      reskinConfigId: identity.reskinConfigId,
      packVersionId: identity.packVersionId,
      note: "S10-C6A submit-from-UI",
      tag: `submit-${projectName}`,
    });

    await page.goto(`${FRONTEND_BASE}/apply`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const projectSelect = page.getByTestId("apply-project-select");
    await expect(projectSelect).toBeVisible({ timeout: 30000 });
    await projectSelect.selectOption(identity.projectId);
    const cpSelect = page.getByTestId("apply-checkpoint-select");
    await expect(cpSelect).toBeVisible({ timeout: 30000 });
    await cpSelect.selectOption(approval.id);
    const submit = page.getByTestId("apply-submit");
    await expect(submit).toBeEnabled();

    const submitResp = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/api/v2/projects/${identity.projectId}/full-apply`),
      { timeout: 30000 },
    );
    await submit.click();
    const resp = await submitResp;
    expect([200, 202]).toContain(resp.status());
    const body = (await resp.json()) as Record<string, unknown>;
    const runId = String(body.run_id ?? "");
    expect(runId.length).toBeGreaterThan(0);
    await shot(page, `t2-submitted-${projectName}`);

    // Displayed run, URL query, local storage all carry the exact ID/project.
    await expect(page.getByTestId("apply-page-run-id")).toContainText(runId, { timeout: 30000 });
    await expect.poll(() => page.url()).toContain(`run_id=${encodeURIComponent(runId)}`);
    await expect.poll(() => page.url()).toContain(`project=${encodeURIComponent(identity.projectId)}`);
    const ls = await page.evaluate(() => ({
      run: localStorage.getItem("s10:apply:lastRunId"),
      project: localStorage.getItem("s10:apply:lastProjectId"),
    }));
    expect(ls.run).toBe(runId);
    expect(ls.project).toBe(identity.projectId);

    // Public status API confirms the durable run.
    const status = (await apiGet(
      page,
      `/full-apply/${encodeURIComponent(runId)}?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(identity.projectId)}`,
    )) as Record<string, unknown>;
    expect(status.run_id).toBe(runId);
    expect(status.project_id).toBe(identity.projectId);
    logEvidence({
      step: "submit-from-ui",
      project: projectName,
      run_id: runId,
      project_id: identity.projectId,
      approval_id: approval.id,
      status: String(status.status ?? ""),
      method: "POST",
      path: `/api/v2/projects/${identity.projectId}/full-apply`,
      http_status: resp.status(),
      url_run_id: runId,
      localStorage_run_id: ls.run,
    });
  });

  // ── 3. Reload / history ─────────────────────────────────────────────────
  test("reload/history: run identity survives reload and back/forward without replace loop", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const a = await createRealRun(page, { tag: "history-a", chunkFrames: 25, projectName });
    const b = await createRealRun(page, { tag: "history-b", chunkFrames: 20, projectName });
    expect(a.runId).not.toBe(b.runId);
    const pid = a.identity.projectId;

    // Run A: deep link, reload retains identity.
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${a.runId}&project=${pid}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("apply-page-run-id")).toContainText(a.runId, { timeout: 30000 });
    await page.reload();
    await expect(page.getByTestId("apply-page-run-id")).toContainText(a.runId, { timeout: 30000 });
    expect(page.url()).toContain(`run_id=${a.runId}`);

    // Run B via supported URL navigation.
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${b.runId}&project=${pid}`);
    await expect(page.getByTestId("apply-page-run-id")).toContainText(b.runId, { timeout: 30000 });

    // Back → A, Forward → B, no replace loop, no stale storage override.
    await page.goBack();
    await expect(page.getByTestId("apply-page-run-id")).toContainText(a.runId, { timeout: 30000 });
    expect(new URL(page.url()).searchParams.get("run_id")).toBe(a.runId);
    await page.goForward();
    await expect(page.getByTestId("apply-page-run-id")).toContainText(b.runId, { timeout: 30000 });
    expect(new URL(page.url()).searchParams.get("run_id")).toBe(b.runId);
    const ls = await page.evaluate(() => localStorage.getItem("s10:apply:lastRunId"));
    expect(ls).toBe(b.runId);
    await shot(page, `t3-history-${projectName}`);
    logEvidence({
      step: "reload-history",
      project: projectName,
      run_a: a.runId,
      run_b: b.runId,
      project_id: pid,
      final_url: page.url(),
      final_localStorage_run_id: ls,
    });
  });

  // ── 4. Progress truth ───────────────────────────────────────────────────
  test("progress truth: UI status/progress/chunks match public backend response during nonterminal", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const run = await createRealRun(page, { tag: "progress", chunkFrames: 15, projectName });
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${run.identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });

    // Poll UI + public status in lockstep; require a real agreement on a
    // NONTERMINAL state (empty/loading/error never counts as success).
    let matchedNonterminal = false;
    let lastUiStatus = "";
    let lastApiStatus = "";
    const deadline = Date.now() + 240000;
    while (Date.now() < deadline) {
      const api = (await apiGet(
        page,
        `/full-apply/${encodeURIComponent(run.runId)}?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(run.identity.projectId)}`,
      )) as Record<string, unknown>;
      const apiStatus = String(api.status ?? "");
      const chunks = (api.chunks as Array<Record<string, unknown>>) ?? [];
      const done = chunks.filter((c) => c.state === "completed" || Boolean(c.verified)).length;
      const apiPct = chunks.length ? Math.round((done / chunks.length) * 100) : null;
      lastApiStatus = apiStatus;
      if (["pending", "running", "verifying"].includes(apiStatus)) {
        const progressVisible = await page
          .getByTestId("apply-progress")
          .isVisible()
          .catch(() => false);
        if (progressVisible) {
          const uiStatus = await uiStatusText(page);
          const uiPctNow = await uiPct(page);
          const uiChunks = await uiChunkCount(page);
          lastUiStatus = uiStatus;
          if (
            uiStatus === apiStatus &&
            apiPct !== null &&
            Math.abs(uiPctNow - apiPct) <= 2 &&
            uiChunks === chunks.length
          ) {
            matchedNonterminal = true;
            logEvidence({
              step: "progress-nonterminal-match",
              project: projectName,
              run_id: run.runId,
              ui_status: uiStatus,
              api_status: apiStatus,
              ui_pct: uiPct,
              api_pct: apiPct,
              ui_chunks: uiChunks,
              api_chunks: chunks.length,
            });
            break;
          }
        }
      }
      await page.waitForTimeout(300);
    }
    expect(matchedNonterminal, `must match a real nonterminal UI state (ui=${lastUiStatus} api=${lastApiStatus})`).toBe(true);

    // Terminal truth from the same backend.
    const final = await waitForRunStatus(page, run.runId, run.identity.projectId, (s) => s === "completed", 300000);
    expect(String(final.status)).toBe("completed");
    await page.reload();
    await expect(page.getByTestId("apply-status")).toContainText("completed", { timeout: 30000 });
    const finalUiPct = await uiPct(page);
    expect(finalUiPct).toBe(100);
    logEvidence({
      step: "progress-terminal",
      project: projectName,
      run_id: run.runId,
      final_status: String(final.status),
      final_ui_pct: finalUiPct,
    });
  });

  // ── 5. Cancel ───────────────────────────────────────────────────────────
  test("cancel: visible enabled Cancel performs real transition to terminal cancelled", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const run = await createRealRun(page, { tag: "cancel", chunkFrames: 15, projectName });
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${run.identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });

    const cancelBtn = page.getByTestId("apply-cancel");
    await expect(cancelBtn).toBeVisible({ timeout: 60000 });
    await expect(cancelBtn).toBeEnabled({ timeout: 60000 });

    const cancelResp = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/full-apply/${run.runId}/cancel`),
      { timeout: 30000 },
    );
    await cancelBtn.click();
    const resp = await cancelResp;
    expect(resp.status()).toBeGreaterThanOrEqual(200);
    expect(resp.status()).toBeLessThan(300);
    const body = (await resp.json()) as Record<string, unknown>;
    expect(body.cancelled).toBe(true);

    // Poll public backend to terminal cancelled semantics.
    const cancelled = await waitForRunStatus(page, run.runId, run.identity.projectId, (s) => s === "cancelled", 120000);
    expect(String(cancelled.status)).toBe("cancelled");

    // UI truth survives reload; Cancel now disabled.
    await page.reload();
    await expect(page.getByTestId("apply-status")).toContainText("cancelled", { timeout: 30000 });
    await expect(cancelBtn).toBeDisabled();
    await shot(page, `t5-cancelled-${projectName}`);
    logEvidence({
      step: "cancel",
      project: projectName,
      run_id: run.runId,
      project_id: run.identity.projectId,
      http_status: resp.status(),
      response_cancelled: body.cancelled,
      method: "POST",
      path: `/api/v2/full-apply/${run.runId}/cancel`,
      final_status: String(cancelled.status),
    });
  });

  // ── 6. Retry ────────────────────────────────────────────────────────────
  test("retry: genuine retry on cancelled run creates new identity via UI click", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const run = await createRealRun(page, { tag: "retry", chunkFrames: 15, projectName });

    // Establish a genuine retryable run via supported cancel semantics.
    const c = await apiPostOrThrow(
      page,
      `/full-apply/${encodeURIComponent(run.runId)}/cancel?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(run.identity.projectId)}`,
      {},
    );
    expect(c.cancelled).toBe(true);
    await waitForRunStatus(page, run.runId, run.identity.projectId, (s) => s === "cancelled", 60000);

    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${run.identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const retryBtn = page.getByTestId("apply-retry");
    await expect(retryBtn).toBeVisible({ timeout: 30000 });
    await expect(retryBtn).toBeEnabled();

    const retryResp = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/full-apply/${run.runId}/retry`),
      { timeout: 30000 },
    );
    await retryBtn.click();
    const resp = await retryResp;
    expect(resp.status()).toBeGreaterThanOrEqual(200);
    expect(resp.status()).toBeLessThan(300);
    const body = (await resp.json()) as Record<string, unknown>;
    const newRunId = String(body.run_id ?? "");
    expect(newRunId.length).toBeGreaterThan(0);
    expect(String(body.predecessor_run_id ?? "")).toBe(run.runId);
    expect(newRunId).not.toBe(run.runId);

    // URL + localStorage + displayed run now carry the NEW identity.
    await expect(page.getByTestId("apply-page-run-id")).toContainText(newRunId, { timeout: 30000 });
    await expect.poll(() => page.url()).toContain(`run_id=${encodeURIComponent(newRunId)}`);
    const ls = await page.evaluate(() => localStorage.getItem("s10:apply:lastRunId"));
    expect(ls).toBe(newRunId);

    // Backend transition: new lineage pending/running with attempt bumped.
    const st = (await apiGet(
      page,
      `/full-apply/${encodeURIComponent(newRunId)}?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(run.identity.projectId)}`,
    )) as Record<string, unknown>;
    expect(["pending", "running", "verifying"]).toContain(String(st.status));
    expect(Number(st.attempt)).toBeGreaterThanOrEqual(2);
    await shot(page, `t6-retried-${projectName}`);
    logEvidence({
      step: "retry",
      project: projectName,
      predecessor_run_id: run.runId,
      new_run_id: newRunId,
      http_status: resp.status(),
      new_status: String(st.status),
      new_attempt: Number(st.attempt),
      method: "POST",
      path: `/api/v2/full-apply/${run.runId}/retry`,
    });
  });

  // ── 7. Resume (interrupted/leased run via controlled stop/restart) ──────
  test("resume: interrupted leased run resumes through UI after controlled backend restart", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    const run = await createRealRun(page, { tag: "resume", chunkFrames: 15, projectName });

    // Real durable checkpoint (0 < verified < total) — product process truth.
    await waitForPartialChunk(page, run.runId, run.identity.projectId, 180000);

    // Controlled stop of the OWNED backend (interrupt mid-run).
    const initialPid = state.backend!.proc.pid as number;
    await stopLaunched(state.backend!);
    state.backend = null;
    expect(isPidAlive(initialPid)).toBe(false);
    expect(listenerOwnerPid(BACKEND_PORT)).toBeNull();
    await assertPortFree(BACKEND_PORT, 4000);

    // Wait for the stale lease to become fencible (expires_at + 90s grace) —
    // read-only probe; production startup reconcile then fences + requeues.
    const leaseExpires = await waitLeaseFencible(run.runId, 220000);
    logEvidence({ step: "resume-lease-fencible", project: projectName, run_id: run.runId, lease_expires_at: leaseExpires });

    // Replacement backend owns the same port (fresh worker).
    state.backend = launchIsolatedBackend({
      worktree: WORKTREE,
      runtimeRoot: RUN_ROOT,
      port: BACKEND_PORT,
    });
    const replacementPid = state.backend.proc.pid as number;
    expect(replacementPid).toBeGreaterThan(0);
    expect(replacementPid).not.toBe(initialPid);
    await waitForBackendReady(
      page.request as unknown as Parameters<typeof waitForBackendReady>[0],
      BACKEND_PORT,
      45000,
    );
    await waitForPortListenerOwnedBy(BACKEND_PORT, replacementPid, 10000);
    expect(listenerOwnerPid(BACKEND_PORT)).toBe(replacementPid);

    // UI deep-link + Resume click on the interrupted run.
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${run.identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const resumeBtn = page.getByTestId("apply-resume");
    await expect(resumeBtn).toBeVisible({ timeout: 30000 });
    await expect(resumeBtn).toBeEnabled({ timeout: 60000 });
    const resumeResp = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/full-apply/${run.runId}/resume`),
      { timeout: 30000 },
    );
    await resumeBtn.click();
    const resp = await resumeResp;
    expect([200, 409]).toContain(resp.status());
    if (resp.status() === 200) {
      const body = (await resp.json()) as Record<string, unknown>;
      expect(body.resumed).toBe(true);
    }

    // Lease/recovery: run reaches completed from public truth.
    const final = await waitForRunStatus(page, run.runId, run.identity.projectId, (s) => s === "completed", 420000);
    expect(String(final.status)).toBe("completed");
    const db = probeRun(run.runId);
    expect((db.chunks ?? []).length).toBeGreaterThan(0);
    expect((db.chunks ?? []).every((c) => Boolean(c.verified))).toBe(true);

    // UI truth after reload.
    await page.reload();
    await expect(page.getByTestId("apply-status")).toContainText("completed", { timeout: 30000 });
    await shot(page, `t7-resumed-${projectName}`);
    logEvidence({
      step: "resume",
      project: projectName,
      run_id: run.runId,
      initial_pid: initialPid,
      replacement_pid: replacementPid,
      http_status: resp.status(),
      final_status: String(final.status),
      verified_chunks: (db.chunks ?? []).filter((c) => Boolean(c.verified)).length,
      method: "POST",
      path: `/api/v2/full-apply/${run.runId}/resume`,
    });
  });

  // ── 8. Structural evidence + Review gate ────────────────────────────────
  test("structural evidence: completed run compare → REVIEW_REQUIRED + Review enabled; missing authority → BLOCKED + Review disabled", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;

    // PART 1 — genuine completed run, UI-driven compare.
    const run = await createRealRun(page, { tag: "struct", chunkFrames: 15, projectName });
    await waitForRunStatus(page, run.runId, run.identity.projectId, (s) => s === "completed", 420000);
    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${run.identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const compareBtn = page.getByTestId("apply-compare-btn");
    await expect(compareBtn).toBeVisible({ timeout: 30000 });
    await expect(compareBtn).toBeEnabled();

    const cmpResp = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/full-apply/${run.runId}/structural-compare`),
      { timeout: 30000 },
    );
    await compareBtn.click();
    const resp = await cmpResp;
    expect(resp.status()).toBe(200);
    const body = (await resp.json()) as Record<string, unknown>;
    expect(body.status).toBe("REVIEW_REQUIRED");
    expect(body.passed).toBe(true);
    const checks = (body.checks as Record<string, unknown>) ?? {};
    expect(Object.keys(checks).length).toBeGreaterThan(0);

    // Actionable role/layer/segment/route evidence rendered in the UI.
    await expect(page.getByTestId("apply-evidence")).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("apply-evidence-status")).toContainText("REVIEW_REQUIRED", { timeout: 30000 });
    await expect(page.getByTestId("apply-evidence-pass")).toBeVisible({ timeout: 10000 });
    const reviewLink = page.getByTestId("apply-review-link");
    await expect(reviewLink).toBeVisible();
    await expect(reviewLink).toBeEnabled();
    const href = await reviewLink.getAttribute("href");
    expect(href).toContain(`/projects/${encodeURIComponent(run.identity.projectId)}`);
    await shot(page, `t8-review-required-${projectName}`);
    logEvidence({
      step: "structural-review-required",
      project: projectName,
      run_id: run.runId,
      http_status: resp.status(),
      status: String(body.status),
      passed: Boolean(body.passed),
      checks: Object.keys(checks).length,
      review_href: href,
    });

    // PART 2 — genuine rendered-file tamper on a completed EXEC run: corrupt
    // the published artifact bytes, then the server-derived compare must
    // BLOCK (SHA mismatch -> RENDERED_TAMPERED) and the Review gate must be
    // disabled — no response injection, no DB patch.
    const blocked = await createRealRun(page, { tag: "struct-blocked", chunkFrames: 15, projectName });
    await waitForRunStatus(page, blocked.runId, blocked.identity.projectId, (s) => s === "completed", 420000);

    const pubs = probePublicationArtifacts(blocked.runId);
    expect(pubs.length).toBeGreaterThan(0);
    const pub = pubs[pubs.length - 1];
    expect(pub.relative_path).toBeTruthy();
    const pubAbs = resolveManagedArtifactPath(pub.relative_path);
    expect(fs.existsSync(pubAbs)).toBe(true);
    const origBytes = fs.readFileSync(pubAbs);
    fs.writeFileSync(pubAbs, Buffer.concat([origBytes, Buffer.from([0x00, 0x01, 0x02])]));
    logEvidence({
      step: "structural-tamper-applied",
      project: projectName,
      run_id: blocked.runId,
      artifact_id: pub.artifact_id,
      relative_path: pub.relative_path,
      sha_before: pub.sha256,
    });
    try {
      await page.goto(`${FRONTEND_BASE}/apply?run_id=${blocked.runId}&project=${blocked.identity.projectId}`);
      await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
      const cmpBtn2 = page.getByTestId("apply-compare-btn");
      await expect(cmpBtn2).toBeVisible({ timeout: 30000 });
      await expect(cmpBtn2).toBeEnabled();
      const cmpResp2 = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().includes(`/full-apply/${blocked.runId}/structural-compare`),
        { timeout: 30000 },
      );
      await cmpBtn2.click();
      const resp2 = await cmpResp2;
      expect(resp2.status()).toBe(200);
      const body2 = (await resp2.json()) as Record<string, unknown>;
      expect(body2.status).toBe("BLOCKED");
      expect(body2.passed).toBe(false);
      const failures = (body2.failures as Array<Record<string, unknown>>) ?? [];
      expect(failures.length).toBeGreaterThan(0);
      const f = failures[0];
      expect(String(f.code ?? "")).toBeTruthy();
      expect(String(f.code ?? "")).toMatch(/TAMPERED|MISMATCH/);
      expect(String(f.reason ?? "")).toBeTruthy();

      // UI: BLOCKED + Review disabled.
      await expect(page.getByTestId("apply-evidence-status")).toContainText("BLOCKED", { timeout: 30000 });
      const reviewBtn = page.getByTestId("apply-review-btn");
      await expect(reviewBtn).toBeVisible();
      await expect(reviewBtn).toBeDisabled();
      await shot(page, `t8-blocked-${projectName}`);
      logEvidence({
        step: "structural-blocked",
        project: projectName,
        run_id: blocked.runId,
        project_id: blocked.identity.projectId,
        http_status: resp2.status(),
        status: String(body2.status),
        passed: Boolean(body2.passed),
        failure_code: String(f.code ?? ""),
        review_disabled: true,
      });
    } finally {
      // Restore the pristine published bytes so later scenarios are unaffected.
      try {
        fs.writeFileSync(pubAbs, origBytes);
      } catch {
        /* best-effort */
      }
    }
  });

  // ── 9. Project Detail entry ─────────────────────────────────────────────
  test("project detail: entry link reaches /apply with the expected project selection", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;

    await page.goto(`${FRONTEND_BASE}/projects`);
    const row = page.locator("tbody tr", { hasText: MAIN_PROJECT_NAME });
    await expect(row.first()).toBeVisible({ timeout: 30000 });
    const mono = row.first().locator(".font-mono").first();
    const pid = (await mono.innerText()).trim();
    expect(pid.length).toBeGreaterThanOrEqual(8);

    await page.goto(`${FRONTEND_BASE}/projects/${encodeURIComponent(pid)}`);
    const link = page.getByTestId("project-go-apply");
    await expect(link).toBeVisible({ timeout: 30000 });
    const href = await link.getAttribute("href");
    expect(href).toMatch(/\/apply\?project=/);
    const helper = link.locator("xpath=following-sibling::p[1]");
    await expect(helper).toBeVisible();
    await expect(helper).toContainText("Mở luồng Apply");

    // Reach /apply with the expected project selection.
    await page.goto(`${FRONTEND_BASE}${href}`);
    await expect(page).toHaveURL(/\/apply\?project=/);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const select = page.getByTestId("apply-project-select");
    await expect(select).toBeVisible({ timeout: 30000 });
    await expect(select).toHaveValue(pid);
    await shot(page, `t9-detail-${projectName}`);
    logEvidence({
      step: "project-detail-entry",
      project: projectName,
      project_id: pid,
      href: href,
      url: page.url(),
      select_value: await select.inputValue().catch(() => ""),
    });
  });

  // ── 10. Mobile execution (runs in BOTH projects — never skipped) ────────
  test("mobile 390px layout: no horizontal overflow, core button/helper visible, no clipping", async ({
    page,
  }, testInfo) => {
    const projectName = testInfo.project.name;
    await page.goto(`${FRONTEND_BASE}/apply`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("apply-card")).toBeVisible({ timeout: 30000 });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);

    const submit = page.getByTestId("apply-submit");
    await expect(submit).toBeVisible();
    const submitBox = await submit.boundingBox();
    expect(submitBox).not.toBeNull();
    const vp = page.viewportSize();
    if (submitBox && vp) {
      expect(submitBox.x).toBeGreaterThanOrEqual(0);
      expect(submitBox.x + submitBox.width).toBeLessThanOrEqual(vp.width + 1);
      expect(submitBox.y).toBeGreaterThanOrEqual(0);
    }

    const helper = page.getByTestId("apply-submit-helper");
    await expect(helper).toBeVisible();
    const helperBox = await helper.boundingBox();
    if (helperBox && submitBox) {
      // Directly below the button — no overlap, no clipping.
      expect(helperBox.y).toBeGreaterThanOrEqual(submitBox.y + submitBox.height - 1);
      expect(helperBox.x).toBeGreaterThanOrEqual(0);
    }
    const helperClass = (await helper.getAttribute("class")) ?? "";
    expect(helperClass).toMatch(/text-gray-400/);
    expect(helperClass).toMatch(/text-\[11px\]/);
    await shot(page, `t10-mobile-${projectName}`);
    logEvidence({
      step: "mobile-layout",
      project: projectName,
      viewport: vp ?? null,
      overflow: overflow,
      submit_box: submitBox,
      helper_box: helperBox,
    });
  });
});
