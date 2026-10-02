import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

/**
 * S05-C04-R3 visual QA — desktop (1280x800) + 390px mobile screenshots
 * against the REAL isolated C04-R3 backend (NEW temporary project
 * root/database under output/s05-c04-r3-evidence/backend-root; backend
 * on :8003 started as bare `uvicorn app.main:app` — the production
 * entrypoint the C04 wiring fix targets).
 *
 * S05-C04-R3 (Codex finding 3): the R2 completed screenshots showed the
 * last step labelled 100% while its progress bar was still partially
 * rendered — a CSS width-transition artifact (the bars use
 * `transition-[width] duration-500`), not a product-state bug (the
 * backend reports progress 100 for completed steps). This spec therefore
 * WAITS for every completed step's rendered progress bar to reach full
 * width before capturing, and ASSERTS that every completed step displays
 * 100% with a visually full progress indicator.
 *
 * Screenshots land in output/s05-c04-r3-evidence/screenshots/ (NEW R3
 * evidence dir) — R2/C01 evidence is never touched.
 */

const FIXTURE_DIR = path.join(__dirname, "fixtures");
const VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-4s.mp4");
const LONG_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-60s.mp4");
const CORRUPT_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-corrupt.mp4");
const API = "http://localhost:8003";
// NEW C04-R3 evidence dir (worktree/output/s05-c04-r3-evidence/screenshots).
const SHOT_DIR = path.join(
  __dirname,
  "..",
  "..",
  "output",
  "s05-c04-r3-evidence",
  "screenshots",
);

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
  if (!fs.existsSync(CORRUPT_VIDEO_PATH)) {
    fs.writeFileSync(CORRUPT_VIDEO_PATH, Buffer.from("not a video", "utf8"));
  }
  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
});

async function createProject(name: string): Promise<string> {
  const res = await fetch(`${API}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`create project ${res.status}`);
  return ((await res.json()) as { project_id: string }).project_id;
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

async function getChain(projectId: string): Promise<ChainStateJson> {
  const res = await fetch(`${API}/api/projects/${projectId}/analyze`);
  if (!res.ok) throw new Error(`chain ${res.status}`);
  return (await res.json()) as ChainStateJson;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOT_DIR, name), fullPage: true });
}

/**
 * S05-C04-R3 (Codex finding 3): wait until every COMPLETED step's
 * rendered progress bar has finished its 500ms CSS width transition
 * (bar width == track width) and ASSERT that each completed step
 * displays 100% with a visually full progress indicator. Also waits for
 * the overall progress bar fill to reach full width. Fails the test if
 * any completed step shows a partial bar or a non-100% label — the R2
 * screenshots caught exactly that (label 100% while the bar was still
 * animating).
 */
async function assertCompletedStepsVisuallyFull(page: Page): Promise<void> {
  // Overall progress bar: backend value must be 100 AND its fill must
  // have finished animating (fill width == track width).
  const overall = page.getByRole("progressbar", { name: /Tiến trình phân tích/ });
  await expect(overall).toHaveAttribute("aria-valuenow", "100", { timeout: 30_000 });
  const overallTrack = overall;
  const overallBar = overall.locator("> div").first();
  await expect
    .poll(
      async () => {
        const tb = await overallTrack.boundingBox();
        const bb = await overallBar.boundingBox();
        if (!tb || !bb) return 0;
        return bb.width / tb.width;
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0.99);

  // Per-step rows: every completed step shows "· 100%" AND a full bar.
  const stepList = page.locator('ol[aria-label="Các bước của chuỗi phân tích"] > li');
  const count = await stepList.count();
  expect(count).toBe(3);
  for (let i = 0; i < count; i++) {
    const row = stepList.nth(i);
    const badge = row.locator("[role=status]").first();
    const statusText = (await badge.innerText()).trim();
    if (statusText !== "Hoàn tất") continue;
    // The step label text carries the real backend percentage ("· 100%").
    await expect(row.getByText(/· 100%$/)).toBeVisible({ timeout: 30_000 });
    // The per-step bar is the 8px track inside the row; wait for the
    // 500ms width transition to finish (bar width == track width).
    const track = row.locator("div.h-2").first();
    await expect(track).toBeVisible();
    const bar = track.locator("> div").first();
    await expect
      .poll(
        async () => {
          const tb = await track.boundingBox();
          const bb = await bar.boundingBox();
          if (!tb || !bb) return 0;
          return bb.width / tb.width;
        },
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0.99);
  }
}

test.describe("S05-C04-R3 visual QA (real isolated C04-R3 backend)", () => {
  for (const viewport of [
    { name: "desktop", width: 1280, height: 800 },
    { name: "390px", width: 390, height: 844 },
  ]) {
    test(`project setup + file selected — ${viewport.name}`, async ({ browser }) => {
      const pid = await createProject(`S05C04R3 shot setup ${viewport.name}`);
      const page = await browser.newPage({ viewport });
      await page.goto(`/import-analyze?project=${encodeURIComponent(pid)}`);
      await expect(page.getByRole("heading", { name: /Nhập & Phân tích video/i })).toBeVisible();
      await shot(page, `setup-${viewport.name}.png`);
      await page.setInputFiles('input[type="file"]', VIDEO_PATH);
      await expect(page.getByText(/s05t05-import-4s.mp4/)).toBeVisible();
      await shot(page, `file-selected-${viewport.name}.png`);
      await page.close();
    });

    test(`chain progress + completed — ${viewport.name}`, async ({ browser }) => {
      const pid = await createProject(`S05C04R3 shot progress ${viewport.name}`);
      const page = await browser.newPage({ viewport });
      await page.goto(`/import-analyze?project=${encodeURIComponent(pid)}`);
      // 60s video: the chain stays active long enough to capture a genuine
      // mid-run progress bar from the real backend state machine.
      await page.setInputFiles('input[type="file"]', LONG_VIDEO_PATH);
      await page.getByRole("button", { name: "Phân tích video" }).click();
      const progressbar = page.getByRole("progressbar", { name: /Tiến trình phân tích/ });
      await expect(progressbar).toBeVisible({ timeout: 15_000 });
      await expect
        .poll(async () => Number(await progressbar.getAttribute("aria-valuenow")), {
          timeout: 90_000,
        })
        .toBeGreaterThan(0);
      await page.waitForTimeout(800);
      const midVal = Number(await progressbar.getAttribute("aria-valuenow"));
      if (midVal > 0 && midVal < 100) {
        await shot(page, `progress-${viewport.name}.png`);
      }
      await expect(page.getByText(/Phân tích video hoàn tất/)).toBeVisible({
        timeout: 240_000,
      });
      let chain = await getChain(pid);
      for (let i = 0; i < 30 && chain.chain_status !== "completed"; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        chain = await getChain(pid);
      }
      expect(chain.chain_status).toBe("completed");

      // S05-C04-R3 (finding 3): every completed step displays 100% and
      // has a visually FULL progress indicator (bars finished their
      // 500ms width transition) BEFORE the screenshot is captured.
      await assertCompletedStepsVisuallyFull(page);

      await shot(page, `completed-${viewport.name}.png`);
      await page.close();
    });

    test(`preflight failure state — ${viewport.name}`, async ({ browser }) => {
      const pid = await createProject(`S05C04R3 shot fail ${viewport.name}`);
      const page = await browser.newPage({ viewport });
      await page.goto(`/import-analyze?project=${encodeURIComponent(pid)}`);
      await page.setInputFiles('input[type="file"]', CORRUPT_VIDEO_PATH);
      await page.getByRole("button", { name: "Phân tích video" }).click();
      await expect(page.getByText("Thất bại", { exact: true }).first()).toBeVisible({
        timeout: 120_000,
      });
      await shot(page, `preflight-error-${viewport.name}.png`);
      await page.close();
    });
  }
});
