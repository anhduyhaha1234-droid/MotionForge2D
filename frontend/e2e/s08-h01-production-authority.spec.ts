/**
 * S08-H01 (finding F — production authority) desktop E2E.
 *
 * Real error paths only: 404 not-found against the real API; connection
 * refused by killing/restarting the real QA backend. No mock interception.
 */

import { test, expect, type Page } from "@playwright/test";
import {
  SHOT_DIR,
  ensureBackendUp,
  killBackend,
  setupSuite,
  startBackend,
  type Suite,
} from "./s08-h01-helpers";

test.describe.configure({ mode: "serial" });

const state: { suite: Suite | null } = { suite: null };

test.beforeAll(async () => {
  state.suite = await setupSuite();
});

test.afterAll(async () => {
  await ensureBackendUp();
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SHOT_DIR}/${name}`, fullPage: true });
}

test("01 unknown project → honest not-found (real backend 404)", async ({ page }) => {
  // durable UUID that does not exist → durable 404 → legacy 404 → not-found
  await page.goto("/projects/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: "Không tìm thấy dự án" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Về danh sách dự án/ })).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/desktop-not-found-uuid.png`, fullPage: true });
  // non-uuid legacy-style unknown id → same honest state
  await page.goto("/projects/__missing__");
  await expect(page.getByRole("heading", { name: "Không tìm thấy dự án" })).toBeVisible();
  await expect(page.getByText(/đã kiểm tra cả workspace bền vững/)).toBeVisible();
});

test("02 durable project detail: real rows + explicit gallery selection via URL", async ({ page }) => {
  const suite = state.suite!;
  const d = suite.durable;
  await page.goto(`/projects/${d.projectId}`);
  await expect(page.getByRole("heading", { name: d.name })).toBeVisible();
  await expect(page.getByText("ID: " + d.projectId)).toBeVisible();
  // real v2 video rows (backend truth — the payload key is `videos`, not `items`)
  await expect(page.getByText("H01 video 1.mp4")).toBeVisible();
  await expect(page.getByText("H01 video 2.mp4")).toBeVisible();
  await shot(page, "desktop-detail-durable.png");
  const rows = page.getByRole("link", { name: /Xem chi tiết →/ });
  await expect(rows).toHaveCount(2);
  // explicit selection at click time: URL carries project + video ids
  await rows.nth(1).click();
  await page.waitForURL(
    new RegExp(`/object-gallery\\?project=${d.projectId}[^&]*&video=${d.videoB}`),
  );
  expect(page.url()).toContain(`video=${d.videoB}`);
});

test("03 multi-video gallery: URL preserves selection across refresh + explicit switch", async ({ page }) => {
  const suite = state.suite!;
  const l = suite.legacy;
  await page.goto(`/object-gallery?project=${l.projectId}&video=${l.videoB}`);
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_01/ })
    .waitFor({ timeout: 90_000 });
  // F5 must keep the selection: URL carries the video id, content stays B
  await page.reload();
  expect(page.url()).toContain(`video=${l.videoB}`);
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_01/ })
    .waitFor({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: /Xem chi tiết vai trò subject_02/ })).toHaveCount(0);
  await shot(page, "desktop-gallery-video-b.png");
  // explicit per-video switch via URL (no ambient store)
  await page.goto(`/object-gallery?project=${l.projectId}&video=${l.videoA}`);
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_02/ })
    .waitFor({ timeout: 90_000 });
  // video A carries its OWN full role set (subject_01..04) — never B's data
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_04/ })
    .waitFor({ timeout: 30_000 });
  await shot(page, "desktop-gallery-video-a.png");
});

test("04 detail → processing → gallery: selection passed explicitly at each hop", async ({ page }) => {
  const suite = state.suite!;
  const l = suite.legacy;
  await page.goto(`/projects/${l.projectId}`);
  // detail resolves the legacy project from backend truth (chain video row)
  await page.getByRole("link", { name: /Tiếp tục xử lý/ }).waitFor({ timeout: 30_000 });
  await page.getByRole("link", { name: /Tiếp tục xử lý/ }).click();
  await page.waitForURL(new RegExp(`/import-analyze\\?project=${l.projectId}`));
  // processing terminal (real chain) → explicit gallery link carries the video
  await page.getByRole("status", { name: "Phân tích hoàn tất" }).waitFor({ timeout: 45_000 });
  await shot(page, "desktop-processing-completed.png");
  await page.getByRole("button", { name: "Xem thư viện đối tượng" }).click();
  await page.waitForURL(
    new RegExp(`/object-gallery\\?project=${l.projectId}[^&]*&video=${l.videoB}`),
  );
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_01/ })
    .waitFor({ timeout: 90_000 });
  expect(page.url()).toContain(`video=${l.videoB}`);
});

test("05 API failure → honest error; retry works after backend restart", async ({ page }) => {
  const suite = state.suite!;
  const d = suite.durable;
  killBackend();
  await page.goto(`/projects/${d.projectId}`);
  // honest error state — real connection-refused, never a fabricated row
  await expect(page.getByRole("heading", { name: "Không thể tải dự án" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Dự án 2D/)).toHaveCount(0);
  await shot(page, "desktop-honest-error.png");
  await startBackend();
  await page.getByRole("button", { name: "Thử lại" }).click();
  await expect(page.getByRole("heading", { name: d.name })).toBeVisible({ timeout: 30_000 });
  await shot(page, "desktop-retry-recovered.png");
});

test("06 LegacyWorkspace: backend-down hydrate error; retry validates before store write", async ({ page }) => {
  const suite = state.suite!;
  const l = suite.legacy;
  killBackend();
  await page.goto(`/?project=${l.projectId}`);
  // honest hydrate error banner (never silent, never a fabricated project)
  await expect(page.getByText("Không thể mở dự án từ địa chỉ")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Không thể kết nối máy chủ/)).toBeVisible();
  await shot(page, "desktop-home-hydrate-error.png");
  await startBackend();
  await page.getByRole("button", { name: /Thử lại/ }).click();
  // valid durable id → store commits only after backend validation
  await page.getByRole("button", { name: "✨ Tạo Dự Án Mới" }).waitFor({ timeout: 30_000 });
  await expect(page.getByText("Không thể mở dự án từ địa chỉ")).toHaveCount(0);
  await shot(page, "desktop-home-recovered.png");
});
