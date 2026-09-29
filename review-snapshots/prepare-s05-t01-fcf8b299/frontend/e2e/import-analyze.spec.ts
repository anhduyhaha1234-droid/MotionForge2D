import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

/**
 * S05-C01 Import/Analyze UI — interaction tests against the REAL backend.
 *
 * The UI now drives the approved durable chain T02 ANALYZE_MEDIA import →
 * T03 GENERATE_PROXY → T04 ANALYZE_MEDIA scene_detect through
 * POST/GET /api/projects/{id}/analyze, POST .../analyze/retry and POST
 * .../analyze/cancel — the legacy POST /api/projects/{id}/ingest is NOT
 * called anywhere in this flow. Every assertion reads the REAL backend
 * chain state (GET /analyze) or the durable job rows — no mock/fake
 * progress anywhere. The cancel test uses the atomic chain-cancel
 * endpoint (S05-C04-R3): the backend resolves the active durable job AT
 * CANCEL TIME, so the click is reliable even during step transitions.
 *
 * Environment (started separately):
 *   - Backend  : python output/s05t05_qa_backend.py 8003 (worktree QA root,
 *                durable worker running via the FastAPI lifespan).
 *   - Frontend : npm run dev -p 3011 with
 *                NEXT_PUBLIC_API_URL=http://localhost:8003
 *   - Config   : playwright.s05t05.config.ts (baseURL :3011)
 */

const FIXTURE_DIR = path.join(__dirname, "fixtures");
const VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-4s.mp4");
const LONG_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-60s.mp4");
const CORRUPT_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-corrupt.mp4");
// QA backend for THIS task runs on :8003.
const API = "http://localhost:8003";

function makeVideo(target: string, duration: string): void {
  if (fs.existsSync(target)) return;
  if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });
  try {
    execSync(
      `ffmpeg -y -f lavfi -i "testsrc=duration=${duration}:size=320x240:rate=30" -f lavfi -i "sine=frequency=440:duration=${duration}" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${target}"`,
      { stdio: "ignore" },
    );
  } catch {
    console.warn("ffmpeg not available — fixture video not created");
  }
}

/**
 * A LARGE 60s fixture (1280x720): the import copy + proxy encode keep each
 * chain step active for seconds, giving the cancel test a real window to
 * cancel a genuinely RUNNING step (the small 320x240 fixture completes the
 * whole T02→T03→T04 chain in ~3s and would make the cancel button already
 * terminal-disabled).
 */
function makeLongVideo(target: string): void {
  if (fs.existsSync(target)) return;
  if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });
  try {
    execSync(
      `ffmpeg -y -f lavfi -i "testsrc=duration=60:size=1280x720:rate=30" -f lavfi -i "sine=frequency=440:duration=60" -c:v libx264 -preset veryfast -b:v 2500k -pix_fmt yuv420p -c:a aac -shortest "${target}"`,
      { stdio: "ignore" },
    );
  } catch {
    console.warn("ffmpeg not available — long fixture video not created");
  }
}

test.beforeAll(() => {
  makeVideo(VIDEO_PATH, "4");
  makeLongVideo(LONG_VIDEO_PATH);
  // A corrupt "mp4" that passes the client-side extension check but fails
  // the backend probe — the honest preflight-failure path.
  if (!fs.existsSync(CORRUPT_VIDEO_PATH)) {
    if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });
    fs.writeFileSync(CORRUPT_VIDEO_PATH, Buffer.from("this is not a video file at all", "utf8"));
  }
});

async function apiJson(path: string): Promise<unknown> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`API ${res.status} for ${path}`);
  return res.json();
}

/** Create a legacy project via the approved API (project.json on disk). */
async function createProject(name: string): Promise<string> {
  const res = await fetch(`${API}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`create project ${res.status}`);
  const data = (await res.json()) as { project_id: string };
  return data.project_id;
}

/** Upload a video via the approved upload endpoint. */
async function uploadVideo(projectId: string, videoPath: string): Promise<void> {
  const buf = fs.readFileSync(videoPath);
  const form = new FormData();
  form.append("file", new Blob([buf]), path.basename(videoPath));
  const res = await fetch(`${API}/api/projects/${projectId}/video`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`upload ${res.status}`);
}

interface ChainStepJson {
  step: string;
  job_id: string | null;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  error_code: string | null;
  predecessor_job_id: string | null;
}

interface ChainStateJson {
  project_id: string;
  video_item_id: string | null;
  chain_status: string;
  active_step: string | null;
  progress: number;
  steps: Record<string, ChainStepJson>;
  scenes_count: number | null;
  [key: string]: unknown;
}

/** GET the backend-owned chain state — the ground truth for UI assertions. */
async function getChain(projectId: string): Promise<ChainStateJson> {
  return (await apiJson(`/api/projects/${projectId}/analyze`)) as ChainStateJson;
}

/** GET the durable job row (step ground truth). */
async function getJob(jobId: string): Promise<Record<string, unknown>> {
  return (await apiJson(`/api/jobs/${jobId}`)) as Record<string, unknown>;
}

async function openImportPage(page: Page, projectId: string): Promise<void> {
  await page.goto(`/import-analyze?project=${encodeURIComponent(projectId)}`);
  await expect(page.getByRole("heading", { name: /Nhập & Phân tích video/i })).toBeVisible();
}

/** Submit via the UI (file dropzone → analyze) and await the chain POST. */
async function submitViaUi(page: Page, videoPath: string): Promise<string> {
  await page.setInputFiles('input[type="file"]', videoPath);
  const submitResponse = page.waitForResponse(
    (r) => r.url().includes("/analyze") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Phân tích video" }).click();
  const resp = await submitResponse;
  expect(resp.status()).toBe(200);
  const chain = (await resp.json()) as ChainStateJson;
  expect(chain.steps.import.job_id).toBeTruthy();
  return chain.steps.import.job_id ?? "";
}

test.describe("S05-C01 Import/Analyze UI — approved chain T02→T03→T04", () => {
  test("empty state: dominant action disabled with a visible reason until a file is chosen", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 empty state");
    await openImportPage(page, pid);

    const submit = page.getByRole("button", { name: "Phân tích video" });
    await expect(submit).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(
      page.getByText(/Chọn tệp video MP4 trước — nút sẽ được bật sau khi bạn chọn tệp/),
    ).toBeVisible();

    // After selecting a file the action becomes enabled.
    await page.setInputFiles('input[type="file"]', VIDEO_PATH);
    await expect(submit).toBeEnabled();
  });

  test("real progress: ONE submission → chain T02→T03→T04 completed with real per-step state", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 real progress");
    await openImportPage(page, pid);

    const importJobId = await submitViaUi(page, VIDEO_PATH);

    // UI shows the real progressbar with a value from the backend chain state.
    const progressbar = page.getByRole("progressbar", { name: /Tiến trình phân tích/ });
    await expect(progressbar).toBeVisible({ timeout: 15_000 });

    // Terminal completed — the UI renders the backend chain status.
    await expect(page.getByText("Hoàn tất", { exact: true })).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText(/Phân tích video hoàn tất/)).toBeVisible({ timeout: 30_000 });

    // Backend ground truth: all three durable jobs completed in order.
    const chain = await getChain(pid);
    expect(chain.chain_status).toBe("completed");
    expect(chain.steps.import.status).toBe("completed");
    expect(chain.steps.proxy.status).toBe("completed");
    expect(chain.steps.scene_detect.status).toBe("completed");
    expect(chain.steps.scene_detect.progress).toBe(100);
    expect(chain.scenes_count).toBeGreaterThan(0);
    // The import job row is a real ANALYZE_MEDIA durable job.
    const row = await getJob(importJobId);
    expect(row["status"]).toBe("completed");
    expect(row["job_type"]).toBe("ANALYZE_MEDIA");
    // UI rendered the SAME real chain progress as the backend.
    await expect(page.getByText("100%", { exact: true })).toBeVisible();
    // All three per-step rows are rendered with real states.
    await expect(page.getByText(/1\. Nhập nguồn \(import\)/)).toBeVisible();
    await expect(page.getByText("2. Tạo proxy")).toBeVisible();
    await expect(page.getByText("3. Phát hiện cảnh")).toBeVisible();
  });

  test("cancel: atomic chain cancel resolves the ACTIVE step → chain cancelled, retry offered, no successor/orphan", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 cancel");
    await uploadVideo(pid, LONG_VIDEO_PATH); // 60s video → steps stay active
    await openImportPage(page, pid);

    const importJobId = await submitViaUi(page, LONG_VIDEO_PATH);

    // S05-C04-R3: the backend resolves the currently active durable job
    // AT CANCEL TIME via POST /analyze/cancel — never a polled client
    // snapshot — so the click cannot target a stale job even during an
    // import→proxy→scene transition (the R2 failure: zero /cancel
    // requests reached the backend because the snapshot was stale).
    const cancelButton = page.getByRole("button", { name: "Hủy công việc" });
    await expect(cancelButton).toBeEnabled({ timeout: 20_000 });
    const cancelResponse = page.waitForResponse(
      (r) => r.url().includes("/analyze/cancel") && r.request().method() === "POST",
    );
    await cancelButton.click({ timeout: 30_000 });
    const cancelResp = await cancelResponse;
    expect(cancelResp.status()).toBe(200);
    const cancelBody = (await cancelResp.json()) as { status: string; job_id: string };
    expect(cancelBody.status).toBe("cancel_requested");
    expect(cancelBody.job_id).toBeTruthy();
    const cancelledJobId = cancelBody.job_id;

    // Durable evidence: the backend-resolved job row reaches cancelling/cancelled.
    const cancelledRow = await getJob(cancelledJobId);
    expect(["cancelling", "cancelled"].includes(cancelledRow["status"] as string)).toBe(true);

    // The UI shows the backend truth: cancelling or terminal cancelled.
    await expect(
      page.locator("[role=status]", { hasText: /Đang hủy|Đã hủy/ }).first(),
    ).toBeVisible({ timeout: 60_000 });

    // Backend chain state reaches terminal cancelled.
    let chain = await getChain(pid);
    for (let i = 0; i < 120 && chain.chain_status !== "cancelled"; i++) {
      await new Promise((r) => setTimeout(r, 500));
      chain = await getChain(pid);
    }
    expect(chain.chain_status).toBe("cancelled");
    const cancelledStepName = ["import", "proxy", "scene_detect"].find(
      (s) => chain.steps[s]?.job_id === cancelledJobId,
    );
    expect(cancelledStepName).toBeTruthy();
    expect(chain.steps[cancelledStepName!].status).toBe("cancelled");

    // No successor/orphan effect: the cancel never materialized a later
    // step (scene_detect stays not_created) and no successor was created.
    expect(chain.steps.scene_detect.job_id).toBeNull();
    expect(chain.steps.scene_detect.status).toBe("not_created");

    // Retry remains available for the cancelled step (successor path).
    await expect(
      page.getByRole("button", { name: /Thử lại bước thất bại/ }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(cancelButton).toBeDisabled();

    // The import job row still exists and is not falsely completed.
    const row = await getJob(importJobId);
    expect(["cancelling", "cancelled", "completed"].includes(row["status"] as string)).toBe(true);
  });

  test("successor retry: failed step retried via POST /analyze/retry creates a NEW job (no 500), retry works", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 successor retry");
    await openImportPage(page, pid);

    // Corrupt source → the import step fails with a REAL backend error.
    const firstImportJobId = await submitViaUi(page, CORRUPT_VIDEO_PATH);

    await expect(page.getByText("Thất bại", { exact: true }).first()).toBeVisible({
      timeout: 120_000,
    });
    await expect(page.getByText(/Không thể import/)).toBeVisible();

    // Retry via the successor endpoint — must NOT 500.
    const retryButton = page.getByRole("button", { name: "Thử lại bước thất bại" });
    await expect(retryButton).toBeVisible();
    const retryResponse = page.waitForResponse(
      (r) => r.url().includes("/analyze/retry") && r.request().method() === "POST",
    );
    await retryButton.click();
    const retryResp = await retryResponse;
    expect(retryResp.status()).toBe(200);

    // Backend ground truth: a successor Job was created (new id, same key,
    // predecessor linked — contract §8.5); the predecessor row is immutable.
    const chain = await getChain(pid);
    const importStep = chain.steps.import;
    expect(importStep.job_id).not.toBe(firstImportJobId);
    expect(importStep.predecessor_job_id).toBe(firstImportJobId);
    expect(importStep.status).toMatch(/queued|running|failed/);
    const pred = await getJob(firstImportJobId);
    expect(pred["status"]).toBe("failed"); // terminal rows are immutable

    // The successor re-runs and fails honestly with the same real error.
    await expect(page.getByText("Thất bại", { exact: true }).first()).toBeVisible({
      timeout: 120_000,
    });
    const chain2 = await getChain(pid);
    expect(chain2.steps.import.job_id).toBe(importStep.job_id);
    expect(chain2.steps.import.error).toBeTruthy();
  });

  test("resume: page reload rehydrates the SAME chain from the backend (no duplicate submission)", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 resume");
    await openImportPage(page, pid);

    const importJobId = await submitViaUi(page, VIDEO_PATH);

    await expect(page.getByText("Hoàn tất", { exact: true })).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText(/Phân tích video hoàn tất/)).toBeVisible({ timeout: 30_000 });

    // Resume via refresh: the chain is backend-owned per project, so the
    // panel rehydrates from GET /analyze — no re-submission.
    await page.reload();
    await expect(page.getByText(/Phân tích video hoàn tất/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(`#${importJobId.slice(0, 8)}`, { exact: true })).toBeVisible();

    // No duplicate: exactly one import job exists for the chain's video item.
    const chain = await getChain(pid);
    expect(chain.steps.import.job_id).toBe(importJobId);
    expect(chain.chain_status).toBe("completed");
  });

  test("API-level successor retry honesty: retry on a failed chain returns 200 + successor; duplicate retry reuses it", async ({
    page,
  }) => {
    const pid = await createProject("S05C01 retry honesty");
    await openImportPage(page, pid);
    await page.setInputFiles('input[type="file"]', CORRUPT_VIDEO_PATH);
    const submitResponse = page.waitForResponse(
      (r) => r.url().includes("/analyze") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Phân tích video" }).click();
    await submitResponse;

    // Wait for terminal failed.
    let chain = await getChain(pid);
    for (let i = 0; i < 120 && chain.chain_status === "running"; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      chain = await getChain(pid);
    }
    expect(chain.chain_status).toBe("failed");
    const failedJobId = chain.steps.import.job_id;

    // Retry via the successor endpoint: 200 + a NEW successor job.
    const retry = await fetch(`${API}/api/projects/${pid}/analyze/retry?generation=1`, {
      method: "POST",
    });
    expect(retry.status).toBe(200);
    const after = (await retry.json()) as ChainStateJson;
    expect(after.steps.import.job_id).not.toBe(failedJobId);
    expect(after.steps.import.predecessor_job_id).toBe(failedJobId);

    // Duplicate retry: idempotent — the SAME successor is reused (never a
    // 409/500 without a path).
    const retry2 = await fetch(`${API}/api/projects/${pid}/analyze/retry?generation=1`, {
      method: "POST",
    });
    expect(retry2.status).toBe(200);
    const after2 = (await retry2.json()) as ChainStateJson;
    expect(after2.steps.import.job_id).toBe(after.steps.import.job_id);
  });
});
