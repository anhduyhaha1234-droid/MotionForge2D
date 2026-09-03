/**
 * S10-T04B-C3 probe — retry URL behavior on the real product (diagnostic).
 *
 * Reproduces the run2 retry failure: create a real run, cancel it through the
 * public API, wait terminal cancelled, open /apply?run_id=<predecessor>,
 * click the Retry button, then capture the URL timeline + console/pageerror
 * evidence to decide whether syncUrlToRun's router.replace fires at all.
 *
 * This is a diagnostic spec, NOT part of the acceptance suite.
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

import {
  WORKTREE,
  RUN_ROOT,
  BACKEND_PORT,
  FRONTEND_PORT,
  FRONTEND_BASE,
  WS,
  EXEC_PROJECT_NAME,
  apiPostOrThrow,
  findProject,
  listVideos,
  getReskinConfig,
  getPackVersionId,
  ensureApproval,
  buildSubmitBody,
  submitRun,
  waitForRunStatus,
  launchIsolatedBackend,
  launchFrontend,
  stopLaunched,
  waitForBackendReady,
  waitForFrontendReady,
  assertPortFree,
  waitForPortListenerOwnedBy,
  type LaunchedBackend,
  type LaunchedFrontend,
} from "./api";

const EVIDENCE_DIR = path.join(RUN_ROOT, "probe-retry-url");
const state: { backend: LaunchedBackend | null; frontend: LaunchedFrontend | null } = {
  backend: null,
  frontend: null,
};

function log(line: string): void {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  fs.appendFileSync(path.join(EVIDENCE_DIR, "probe.log"), `${new Date().toISOString()} ${line}\n`, "utf-8");
}

test.describe("retry URL probe", () => {
  test("retry click updates URL to the new run identity", async ({ page }) => {
    await assertPortFree(BACKEND_PORT, 4000);
    state.backend = launchIsolatedBackend({ worktree: WORKTREE, runtimeRoot: RUN_ROOT, port: BACKEND_PORT });
    const backendPid = state.backend.proc.pid as number;
    await waitForBackendReady(page.request as never, BACKEND_PORT, 45000);
    await waitForPortListenerOwnedBy(BACKEND_PORT, backendPid, 10000);

    state.frontend = launchFrontend({
      worktree: WORKTREE,
      port: FRONTEND_PORT,
      backendPort: BACKEND_PORT,
      logFile: path.join(RUN_ROOT, `probe-frontend-${FRONTEND_PORT}.log`),
    });
    await waitForFrontendReady(FRONTEND_PORT, 90000);
    log("services-up backend_pid=" + backendPid + " frontend_pid=" + state.frontend.proc.pid);

    const consoleMsgs: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (m) => {
      if (["warning", "error"].includes(m.type())) consoleMsgs.push(`[${m.type()}] ${m.text()}`);
    });
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    const identity = await (async () => {
      const project = await findProject(page, EXEC_PROJECT_NAME);
      const videos = await listVideos(page, project.id);
      if (!videos.length) throw new Error(`project ${EXEC_PROJECT_NAME} has no videos`);
      const reskin = await getReskinConfig(page, project.id);
      const packVersionId = getPackVersionId(reskin.id);
      return {
        projectId: project.id,
        videoId: videos[0],
        reskinConfigId: reskin.id,
        packVersionId,
        structuralLockManifestId: reskin.structural_lock_manifest_id as string | null,
        lockPolicyVersion: reskin.lock_policy_version as string | null,
      };
    })();
    const approval = await ensureApproval(page, {
      projectId: identity.projectId,
      reskinConfigId: identity.reskinConfigId,
      packVersionId: identity.packVersionId,
      note: "S10-C6A retry-url probe",
      tag: "retry-probe",
    });
    // SLOW run: chunk_frames=5 → many chunks → wide cancel window.
    const body = buildSubmitBody({ projectId: identity.projectId, videoId: identity.videoId, approval, chunkFrames: 5, overlapFrames: 4 });
    const run = await submitRun(page, identity.projectId, body);
    log("run-created run_id=" + run.runId);

    const c = await apiPostOrThrow(page, `/full-apply/${encodeURIComponent(run.runId)}/cancel?workspace_id=${encodeURIComponent(WS)}&project_id=${encodeURIComponent(identity.projectId)}`, {});
    log("cancel-response cancelled=" + String(c.cancelled) + " status=" + String(c.status));
    await waitForRunStatus(page, run.runId, identity.projectId, (s) => s === "cancelled", 120000);
    log("predecessor-terminal-cancelled");

    await page.goto(`${FRONTEND_BASE}/apply?run_id=${run.runId}&project=${identity.projectId}`);
    await expect(page.getByTestId("apply-page-title")).toBeVisible({ timeout: 30000 });
    const retryBtn = page.getByTestId("apply-retry");
    await expect(retryBtn).toBeVisible({ timeout: 30000 });
    await expect(retryBtn).toBeEnabled({ timeout: 60000 });
    log("retry-btn-enabled url=" + page.url());

    const retryResp = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().includes(`/full-apply/${run.runId}/retry`),
      { timeout: 30000 },
    );
    await retryBtn.click();
    const resp = await retryResp;
    const body2 = (await resp.json()) as Record<string, unknown>;
    const newRunId = String(body2.run_id ?? "");
    log("retry-response http=" + resp.status() + " new_run_id=" + newRunId + " predecessor=" + String(body2.predecessor_run_id ?? ""));

    // URL timeline for 12s.
    for (let i = 0; i < 48; i++) {
      const u = page.url();
      const domRun = await page.getByTestId("apply-page-run-id").innerText().catch(() => "");
      log(`t+${i * 0.25}s url=${u} domRunId=${domRun.replace(/\s+/g, " ").slice(0, 60)}`);
      if (u.includes(`run_id=${newRunId}`)) break;
      await page.waitForTimeout(250);
    }

    log("console-msgs: " + JSON.stringify(consoleMsgs));
    log("page-errors: " + JSON.stringify(pageErrors));
    log("final-url=" + page.url());
    log("final-localStorage=" + (await page.evaluate(() => localStorage.getItem("s10:apply:lastRunId"))));

    // Truthful assertion so the probe fails loudly if the URL never updates.
    expect(page.url(), `URL must carry the new run id (console=${JSON.stringify(consoleMsgs)} pageErrors=${JSON.stringify(pageErrors)})`).toContain(`run_id=${newRunId}`);

    for (const h of [state.backend, state.frontend]) {
      if (h) await stopLaunched(h, { graceMs: 5000, killGraceMs: 3000 }).catch(() => undefined);
    }
    state.backend = null;
    state.frontend = null;
  });
});
