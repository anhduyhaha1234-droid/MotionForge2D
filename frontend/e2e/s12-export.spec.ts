import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * S12-T05 Export UI — real-backend E2E (no route mocks anywhere).
 *
 * Runs against the production backend (localhost:8415 — the T03C router
 * is now production-mounted on the canonical app, so no test-only router
 * include anywhere; the harness boots `app.api.app` as-is) + frontend
 * (localhost:3015) via playwright.s12-export.config.ts. Seeds REAL durable
 * rows via the repo-adjacent seed script (T03C fixture shape).
 *
 * Verified backend behaviour (fail-closed, asserted as-is):
 *  - server-owned authority (C2 F02): client never supplies filesystem
 *    paths; submit body is FLAT checkpoint/manifest pins + profile/plan.
 *  - preflight resolves the REAL Full Apply authority + readiness first, so
 *    a fixture without completed Full Apply publication fails closed
 *    (S12_EXPORT_FULL_APPLY_MISSING / NOT_READY) — never a fake eligible.
 *  - submit 202 real run -> poll status -> cancel 200 (pending->cancelled)
 *    -> retry 202 (cancelled->pending, new attempt) -> completed seed shows
 *    evidence + identity via /export?run=<completed-id>.
 *  - C22 access: a VALID completed result is reachable through the server's
 *    owned endpoints; no client-invented media URL is ever constructed.
 */
import fs from "fs";
import path from "path";

test.describe.configure({ mode: "serial" });

const FE = process.env.QA_FE_BASE ?? "http://localhost:3015";
const API = process.env.QA_API_BASE ?? "http://localhost:8415";
const QA_ROOT =
  process.env.S12T05_QA_ROOT ??
  "C:/Users/Admin/AppData/Local/Temp/s12t05_root";

interface SeedResult {
  case: string;
  project_id: string;
  project_blocked_id: string;
  workspace_id: string;
  video_ready: string;
  video_blocked: string;
  checkpoint_id: string;
  checkpoint_hash: string;
  checkpoint_revision: number;
  manifest_id: string;
  manifest_hash: string;
  manifest_generation: string;
  plan_id: string;
  plan_hash: string;
  pending_run_id: string;
  cancel_run_id: string;
  retry_base_run_id: string;
  completed_run_id: string;
  tampered_run_id: string;
}

async function submitBody(request: APIRequestContext, seed: SeedResult, idem: string) {
  // Unique idempotency per spec run (boot reseeds fresh DB each Playwright
  // invocation, but retries/tests within one run must not collide).
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const unique = `${idem}-${stamp}`;
  const contextResponse = await request.get(
    `${API}/api/v2/projects/${seed.project_id}/export/context?video_item_id=${seed.video_ready}`,
  );
  expect(contextResponse.status()).toBe(200);
  const context = await contextResponse.json();
  return {
    workspace_id: "default",
    project_id: seed.project_id,
    video_item_id: seed.video_ready,
    profile_id: "master-4k-h264",
    checkpoint_id: context.checkpoint.checkpoint_id,
    checkpoint_hash: context.checkpoint.checkpoint_hash,
    checkpoint_revision: context.checkpoint.checkpoint_revision,
    manifest_id: context.lock.manifest_id,
    manifest_hash: context.lock.manifest_hash,
    manifest_generation: context.lock.source_generation,
    plan_id: context.plan.plan_id,
    plan_hash: context.plan.plan_hash,
    frame_count: context.plan.frame_count,
    context_revision: context.context_revision,
    idempotency_key: unique,
  };
}

let seed: SeedResult;

test.beforeAll(() => {
  // The config's backend webServer already booted + seeded once and wrote
  // seed.json — read it instead of seeding again (artifact rows are unique
  // per workspace, a second seed would clash).
  const raw = fs.readFileSync(path.join(QA_ROOT, "seed.json"), "utf8");
  seed = JSON.parse(raw) as SeedResult;
  expect(seed.project_id).toBeTruthy();
  expect(seed.completed_run_id).not.toEqual(seed.pending_run_id);
});

test("nav entry di toi /export va thay tieu de", async ({ page, isMobile }) => {
  // AppNav is desktop-only by design (hidden md:flex) — on mobile the
  // /export route (StageRail "Xuất 4K") is reached directly; layout stays
  // responsive with no overflow.
  test.skip(!!isMobile, "AppNav desktop-only (hidden md:flex); route covered below");
  await page.goto(`${FE}/projects/${seed.project_id}`);
  const nav = page.getByRole("link", { name: /Xuất 4K|Xuat 4K|Export/i }).first();
  await expect(nav).toBeVisible();
  await expect(nav).toHaveAttribute("href", /\/export/);
  await nav.click();
  await expect(page).toHaveURL(/\/export/);
  await expect(page.getByTestId("export-title")).toBeVisible();
});

test("trang trong hien trang thai rong tieng Viet", async ({ page }) => {
  await page.goto(`${FE}/export`);
  await expect(page.getByTestId("export-empty")).toBeVisible();
  await expect(page.getByTestId("export-panel")).toBeHidden();
});

test("C20/C21: project-video entry point -> context -> submit updates scoped run pointer", async ({ page, isMobile }) => {
  await page.goto(`${FE}/object-gallery?project=${seed.project_id}&video=${seed.video_ready}`);
  const exportLink = page.getByRole("link", { name: /Xuất 4K|Xuat 4K|Export/i }).first();
  if (!isMobile) await exportLink.click();
  else await page.goto(`${FE}/export?project=${seed.project_id}&video=${seed.video_ready}`);
  await expect(page).toHaveURL(/\/export\?[^#]*(project|video)/);
  await expect(page.getByTestId("export-context")).toBeVisible();
  await expect(page.getByTestId("export-server-authority")).toBeVisible();
  await expect(page.locator('input[name="checkpoint_hash"], input[name="manifest_hash"], input[name="plan_hash"], input[name="source_path"]')).toHaveCount(0);
  await page.getByTestId("export-preflight").click();
  await expect(page.getByTestId("export-preflight-result")).toBeVisible();
  await expect(page.getByTestId("export-submit")).toBeEnabled();
  await page.getByTestId("export-submit").click();
  await expect(page).toHaveURL(new RegExp(`project=${seed.project_id}.*video=${seed.video_ready}.*run=`));
  const runText = await page.getByTestId("export-run-id").textContent();
  expect(runText).toContain("run ");
  await page.reload();
  await expect(page.getByTestId("export-run-id")).toContainText(runText?.replace("run ", "") ?? "run");
});

test("preflight that: video blocked tra SOURCE_MISSING", async ({ request }) => {
  const res = await request.post(
    `${API}/api/v2/projects/${seed.project_blocked_id}/export/preflight`,
    {
      data: {
        video_item_id: seed.video_blocked,
        profile_id: "master-4k-h264",
        aspect_handling: "letterbox",
        checkpoint: {
          checkpoint_id: seed.checkpoint_id,
          checkpoint_hash: seed.checkpoint_hash,
          checkpoint_revision: seed.checkpoint_revision,
        },
        lock: {
          manifest_id: seed.manifest_id,
          manifest_hash: seed.manifest_hash,
          source_generation: seed.manifest_generation,
        },
      },
    },
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.eligible).toBe(false);
  expect(body.reasons).toContain("S12_EXPORT_SOURCE_MISSING");
});

test("preflight that: video ready eligible that (authority + readiness real)", async ({
  request,
}) => {
  // C2 server-owned authority + readiness: seed cung cấp completed Full
  // Apply publication + completed FULL QC band run (T03G band registered
  // production) => preflight phải eligible TRÊN API THẬT (positive path).
  const res = await request.post(
    `${API}/api/v2/projects/${seed.project_id}/export/preflight`,
    {
      data: {
        video_item_id: seed.video_ready,
        profile_id: "master-4k-h264",
        aspect_handling: "letterbox",
        checkpoint: {
          checkpoint_id: seed.checkpoint_id,
          checkpoint_hash: seed.checkpoint_hash,
          checkpoint_revision: seed.checkpoint_revision,
        },
        lock: {
          manifest_id: seed.manifest_id,
          manifest_hash: seed.manifest_hash,
          source_generation: seed.manifest_generation,
        },
      },
    },
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.eligible).toBe(true);
  expect(body.reasons).toContain("S12_EXPORT_OK");
});

test("submit that -> 202 real (readiness+authority ready)", async ({
  request,
  page,
}) => {
  // C2 base fb59215: T03G band + Full Apply authority đều sẵn sàng, submit
  // qua API THẬT phải 202 và run pending/running (worker real có thể claim).
  const res = await request.post(`${API}/s12-exports/submit`, {
    data: await submitBody(request, seed, "s12t05-ui-submit"),
  });
  expect(res.status()).toBe(202);
  const created = await res.json();
  expect(created.run_id).toBeTruthy();

  const st = await request.get(
    `${API}/s12-exports/${created.run_id}?workspace_id=default`,
  );
  expect(st.status()).toBe(200);
  const statusBody = await st.json();
  expect(["pending", "running"]).toContain(statusBody.status);
  expect(Array.isArray(statusBody.chunks)).toBe(true);

  await page.goto(
    `${FE}/export?run=${created.run_id}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-progress")).toBeVisible();
});

test("cancel that run pending -> cancelled", async ({ request, isMobile }) => {
  // State-changing: the desktop project owns this API test (the seeded DB
  // is shared between projects; cancel is terminal so one project runs it).
  test.skip(!!isMobile, "state-changing API test runs once (desktop)");
  // Runs against the SEED cancel run (repo-created, no durable job, so
  // the production worker never claims it mid-test): cancel over the real
  // API must 200 → cancelled.
  const run_id = seed.cancel_run_id;
  const cancel = await request.post(`${API}/s12-exports/${run_id}/cancel`, {
    data: { workspace_id: "default" },
  });
  expect(cancel.status()).toBe(200);
  const body = await cancel.json();
  expect(body.status).toBe("cancelled");
});

test("retry run cancelled -> tao run ke thua status pending", async ({ request, isMobile }) => {
  // State-changing (same rationale as cancel): desktop only.
  test.skip(!!isMobile, "state-changing API test runs once (desktop)");
  // The SEED retry base run is already cancelled WITH its real durable job
  // (job row in cancelling) so retry inherits render pins from the real
  // job manifest through the real submit path (202) — the assert is the
  // predecessor linkage, never a fake happy path.
  const run_id = seed.retry_base_run_id;
  const retry = await request.post(`${API}/s12-exports/${run_id}/retry`, {
    data: { workspace_id: "default" },
  });
  expect(retry.status()).toBe(202);
  const body = await retry.json();
  expect(body.predecessor_run_id).toBe(run_id);
  // T03A retry converges on the lineage winner via natural-key backstop:
  // same pins => same run row (created=false), so the returned status is
  // the predecessor's terminal state. The gate is predecessor linkage.
  expect(["pending", "cancelled"]).toContain(body.status);
});

test("run completed seed hien evidence + dinh danh + tieng Viet", async ({
  page,
}) => {
  await page.goto(
    `${FE}/export?run=${seed.completed_run_id}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  const evidence = page.getByTestId("export-evidence");
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText(/COMPLETED/);
  await expect(evidence).toContainText(/đã xác minh|da xac minh|xác minh|Có/i);
  await expect(page.getByTestId("export-run-id")).toContainText(
    seed.completed_run_id.slice(0, 8),
  );
});

// ── C21 durable-refresh: active run → refresh/reopen → same run ──────────
// Server owns the run; localStorage keeps only pointers. Refresh must show
// the SAME run with live status — never a forked/empty local copy.

test("C21: refresh giu nguyen run dang active, khong tao run moi", async ({
  request,
  page,
}) => {
  // Server owns the run; localStorage keeps only pointers.  The seed
  // pending run is repo-created (no durable job) so it stays active for
  // the whole spec; refresh/reopen must show the SAME run with live
  // status — never a forked/empty local copy.
  const run_id = seed.pending_run_id;
  const url =
    `${FE}/export?run=${run_id}&project=${seed.project_id}&video=${seed.video_ready}`;
  await page.goto(url);
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(run_id.slice(0, 8));

  await page.reload();
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(run_id.slice(0, 8));
  await expect(page.getByTestId("export-progress")).toBeVisible();

  // localStorage is pointer-only: wiping it then reopening the same URL
  // must still resolve the SAME server run (no local authority).
  await page.evaluate(() => localStorage.clear());
  await page.goto(url);
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(run_id.slice(0, 8));
});

// ── C22 result-access: completed run plays/downloads via server URL ─────
// C22-part backend (T03C addendum fb59215): GET /s12-exports/{run}/result
// returns server-owned media_url; GET /media streams the REAL video bytes
// ONLY for completed + owned runs with matching sidecar.  The UI uses that
// server URL verbatim — never an invented path.

test("C22: run completed -> result media_url server-owned + UI player/download", async ({
  page,
}) => {
  await page.goto(
    `${FE}/export?run=${seed.completed_run_id}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  const evidence = page.getByTestId("export-evidence");
  await expect(evidence).toBeVisible();
  const player = page.getByTestId("export-result-player");
  await expect(player).toBeVisible();
  const src = await player.getAttribute("src");
  expect(src).toContain(`/s12-exports/${seed.completed_run_id}/media`);
  const download = page.getByTestId("export-result-download");
    await expect(download).toBeVisible();
    await expect(download).toHaveAttribute(
      "href",
      new RegExp(`/s12-exports/${seed.completed_run_id}/media`),
    );
    await expect(download).toContainText(/export_master\.mp4/);
});

test("C22: result metadata that + media tra dung video/mp4 bytes that", async ({
  request,
}) => {
  const res = await request.get(
    `${API}/s12-exports/${seed.completed_run_id}/result?workspace_id=default`,
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.status).toBe("completed");
  expect(body.media_url).toBe(`/s12-exports/${seed.completed_run_id}/media`);
  expect(body.mime).toBe("video/mp4");
  expect(body.size_bytes).toBeGreaterThan(1024);

  const media = await request.get(
    `${API}${body.media_url}?workspace_id=default`,
  );
  expect(media.status()).toBe(200);
  expect(media.headers()["content-type"]).toMatch(/video\/mp4/);
  const bytes = await media.body();
  expect(bytes.length).toBe(body.size_bytes);
  // mp4 ftyp atom — playable container, không phải stub/empty
  const magic = bytes.subarray(4, 12).toString("latin1");
  expect(magic).toContain("ftyp");
});

test("C22: pending/failed run -> result bi tu choi (409, khong media)", async ({
  request,
}) => {
  const res = await request.get(
    `${API}/s12-exports/${seed.pending_run_id}/result?workspace_id=default`,
  );
  expect(res.status()).toBe(409);
  const media = await request.get(
    `${API}/s12-exports/${seed.pending_run_id}/media?workspace_id=default`,
  );
  expect(media.status()).toBe(409);
});

test("C22: cross-project run -> 404 (khong lo result cua project khac)", async ({
  request,
}) => {
  const res = await request.get(
    `${API}/s12-exports/${seed.completed_run_id}/result?workspace_id=default&project_id=other-project`,
  );
  expect(res.status()).toBe(404);
});

test("C22: tampered artifact -> 403 (byte identity mismatch, khong serve)", async ({
  request,
}) => {
  const res = await request.get(
    `${API}/s12-exports/${seed.tampered_run_id}/result?workspace_id=default`,
  );
  expect(res.status()).toBe(403);
  const media = await request.get(
    `${API}/s12-exports/${seed.tampered_run_id}/media?workspace_id=default`,
  );
  expect(media.status()).toBe(403);
});

test("C22: run pending chi thay progress, khong thay evidence", async ({
  page,
}) => {
  await page.goto(
    `${FE}/export?run=${seed.pending_run_id}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-progress")).toBeVisible();
  await expect(page.getByTestId("export-evidence")).toBeHidden();
});

test("C22: run id la hien loi, khong hien evidence", async ({ page }) => {
  await page.goto(
    `${FE}/export?run=00000000-0000-4000-8000-000000000000&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(page.getByTestId("export-evidence")).toBeHidden();
});
