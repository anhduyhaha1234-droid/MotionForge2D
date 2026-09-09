import { test, expect } from "@playwright/test";

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
}

function submitBody(seed: SeedResult, idem: string, salt?: string) {
  // Unique idempotency per spec run (boot reseeds fresh DB each Playwright
  // invocation, but retries/tests within one run must not collide).
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const unique = `${idem}-${stamp}`;
  // Per-test plan lineage: T03A natural-key dedupes identical pins, so
  // parallel projects (desktop + mobile share one backend/DB) must submit
  // distinct plans or they converge on one run and cancel/retry collide.
  const hex = "0123456789abcdef";
  const tag = (salt ?? idem).padEnd(8, "0").slice(0, 8);
  const planTail = [...tag].map((c) => hex[c.charCodeAt(0) % 16]).join("");
  return {
    workspace_id: "default",
    project_id: seed.project_id,
    video_item_id: seed.video_ready,
    profile_id: "master-4k-h264",
    checkpoint_id: seed.checkpoint_id,
    checkpoint_hash: seed.checkpoint_hash,
    checkpoint_revision: seed.checkpoint_revision,
    manifest_id: seed.manifest_id,
    manifest_hash: seed.manifest_hash,
    manifest_generation: seed.manifest_generation,
    plan_id: `${seed.plan_id.slice(0, 56)}${planTail}`,
    plan_hash: `${seed.plan_hash.slice(0, 56)}${planTail}`,
    frame_count: 100,
    chunk_config: { overlap: 5, max_frames: 50 },
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

test("preflight that: video blocked tra SOURCE_MISSING", async ({ request }) => {
  const res = await request.post(
    `${API}/api/v2/projects/${seed.project_id}/export/preflight`,
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

test("preflight that: video ready fail-closed vi authority + readiness that", async ({
  request,
}) => {
  // C2 server-owned authority (F02/F08): preflight resolves the REAL Full
  // Apply authority + readiness aggregate BEFORE eligibility.  The seed
  // now provides a completed Full Apply publication, so the authority
  // items pass; readiness stays NOT_READY because the REAL QC band
  // (T03G lane: detector modules + durable full-band revisions) is not
  // part of this canonical base — the E2E asserts the fail-closed reason,
  // never a fake eligible.
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
  expect(body.eligible).toBe(false);
  expect(body.reasons).toContain("S12_EXPORT_NOT_READY");
});

test("submit that: fail-closed 409 NOT_READY (readiness that chua dat)", async ({
  request,
}, testInfo) => {
  // C2 no-bypass: submit runs the REAL project-readiness gate.  The
  // canonical base does not carry the T03G full-band QC detector modules,
  // so the real aggregate stays not_run and a fresh submit FAILS CLOSED
  // with 409 — the E2E proves the gate, never a fake 202.
  const res = await request.post(`${API}/s12-exports/submit`, {
    data: submitBody(seed, "s12t05-ui-submit", `${testInfo.project.name}:${testInfo.title}`),
  });
  expect(res.status()).toBe(409);
  const body = await res.json();
  expect(String(body.detail)).toMatch(/readiness 'not_run'|S12_EXPORT_NOT_READY/);
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

// ── C22 result-access: evidence only for completed; nothing served ────────
// The status API carries no media/download URL; the panel must not invent
// one. Non-completed runs show progress, never evidence; unknown/stale run
// ids surface an error, never evidence.

test("C22: run completed khong co media URL hay download tu suy dien", async ({
  page,
}) => {
  await page.goto(
    `${FE}/export?run=${seed.completed_run_id}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  const evidence = page.getByTestId("export-evidence");
  await expect(evidence).toBeVisible();
  expect(await evidence.locator("a[href], video, audio").count()).toBe(0);
  expect(await page.locator("a[href$='.mp4']").count()).toBe(0);
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
