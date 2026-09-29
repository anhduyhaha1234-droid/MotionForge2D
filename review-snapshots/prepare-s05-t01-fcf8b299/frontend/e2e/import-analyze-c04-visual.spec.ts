import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

/**
 * S05-C04-R2 visual QA — desktop (1280x800) + 390px mobile screenshots
 * against the REAL isolated C04 backend (NEW temporary project
 * root/database under output/s05-c04-r2-evidence/backend-root; backend
 * on :8003 started as bare `uvicorn app.main:app` — the production
 * entrypoint the C04 wiring fix targets).
 *
 * This is a C04-specific copy of the C01 visual spec: screenshots land in
 * output/s05-c04-r2-evidence/screenshots/ (NEW C04 evidence dir) — the
 * existing C01 screenshots and C01 packet are never touched. Same real
 * chain states as the C01 spec: project setup (empty state), file
 * selected, real chain progress (mid-run), completed chain, preflight
 * failure — all against the approved T02→T03→T04 chain (no mock data).
 */

const FIXTURE_DIR = path.join(__dirname, "fixtures");
const VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-4s.mp4");
const LONG_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-import-60s.mp4");
const CORRUPT_VIDEO_PATH = path.join(FIXTURE_DIR, "s05t05-corrupt.mp4");
const API = "http://localhost:8003";
// NEW C04 evidence dir (worktree/output/s05-c04-r2-evidence/screenshots).
const SHOT_DIR = path.join(
  __dirname,
  "..",
  "..",
  "output",
  "s05-c04-r2-evidence",
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

test.describe("S05-C04-R2 visual QA (real isolated C04 backend)", () => {
  for (const viewport of [
    { name: "desktop", width: 1280, height: 800 },
    { name: "390px", width: 390, height: 844 },
  ]) {
    test(`project setup + file selected — ${viewport.name}`, async ({ browser }) => {
      const pid = await createProject(`S05C04R2 shot setup ${viewport.name}`);
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
      const pid = await createProject(`S05C04R2 shot progress ${viewport.name}`);
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
      await shot(page, `completed-${viewport.name}.png`);
      await page.close();
    });

    test(`preflight failure state — ${viewport.name}`, async ({ browser }) => {
      const pid = await createProject(`S05C04R2 shot fail ${viewport.name}`);
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
