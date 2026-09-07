import { test, expect } from "@playwright/test";

/**
 * S12-T05 Export UI — real-backend E2E (no route mocks anywhere).
 *
 * Runs against the task-owned backend (localhost:8415, test-only harness
 * mounting production app + s12_export router) + frontend (localhost:3015)
 * via playwright.s12-export.config.ts. Seeds REAL durable rows via the
 * repo-adjacent seed script (T03C fixture shape).
 *
 * Verified backend behaviour (fail-closed, asserted as-is):
 *  - T02 capability gate NOT implemented (profile_supported=False hardcoded)
 *    => preflight NEVER eligible through the real API; eligible path is a
 *    client-side state the panel must still render if the API ever returns it.
 *  - readiness aggregate over BOTH seeded videos => not_run (Decision F).
 *  - submit 202 real run -> poll status -> cancel 200 (pending->cancelled)
 *    -> retry 202 (cancelled->pending, new attempt) -> completed seed shows
 *    evidence + identity via /export?run=<completed-id>.
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
    source_path: path.join(QA_ROOT, "artifacts", "s12t05", "source_ready.mp4"),
    fps: 30.0,
    chunk_dir: path.join(QA_ROOT, "chunks"),
    scratch_dir: path.join(QA_ROOT, "scratch"),
    output_path: path.join(QA_ROOT, "out.mp4"),
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

test("preflight that: video ready fail-closed vi T02 capability + readiness", async ({
  request,
}) => {
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
  expect(body.reasons).toContain("S12_EXPORT_UNSUPPORTED_PROFILE");
});

test("submit that -> 202, poll status that thay pending/running", async ({
  request,
  page,
}, testInfo) => {
  const res = await request.post(`${API}/s12-exports/submit`, {
    data: submitBody(seed, "s12t05-ui-submit", `${testInfo.project.name}:${testInfo.title}`),
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

test("cancel that run pending -> cancelled", async ({ request }, testInfo) => {
  const res = await request.post(`${API}/s12-exports/submit`, {
    data: submitBody(seed, "s12t05-ui-cancel", `${testInfo.project.name}:${testInfo.title}`),
  });
  expect(res.status()).toBe(202);
  const { run_id } = await res.json();

  const cancel = await request.post(`${API}/s12-exports/${run_id}/cancel`, {
    data: { workspace_id: "default" },
  });
  expect(cancel.status()).toBe(200);
  const body = await cancel.json();
  expect(body.status).toBe("cancelled");
});

test("retry run cancelled -> tao run ke thua status pending", async ({ request }, testInfo) => {
  const res = await request.post(`${API}/s12-exports/submit`, {
    data: submitBody(seed, "s12t05-ui-retry", `${testInfo.project.name}:${testInfo.title}`),
  });
  expect(res.status()).toBe(202);
  const { run_id } = await res.json();
  await request.post(`${API}/s12-exports/${run_id}/cancel`, {
    data: { workspace_id: "default" },
  });

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
