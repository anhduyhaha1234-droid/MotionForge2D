/**
 * S08-H01 (finding F — production authority) MOBILE 390px E2E.
 *
 * Mirrors the desktop coverage at 390px + asserts NO horizontal overflow on
 * every honest state (error / not-found / gallery selector / recoveries).
 * Real error paths only — no mock interception.
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

/** Assert the document does not overflow the 390px viewport. */
async function noHorizontalOverflow(page: Page): Promise<void> {
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(scrollWidth, `scrollWidth=${scrollWidth} × 390px viewport`).toBeLessThanOrEqual(392);
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SHOT_DIR}/${name}`, fullPage: true });
}

test("m01 unknown project → honest not-found, no horizontal overflow", async ({ page }) => {
  await page.goto("/projects/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: "Không tìm thấy dự án" })).toBeVisible();
  await noHorizontalOverflow(page);
  await shot(page, "mobile-not-found.png");
});

test("m02 durable project detail: real rows + explicit gallery URL selection", async ({ page }) => {
  const suite = state.suite!;
  const d = suite.durable;
  await page.goto(`/projects/${d.projectId}`);
  await expect(page.getByRole("heading", { name: d.name })).toBeVisible();
  await expect(page.getByText("H01 video 1.mp4")).toBeVisible();
  await expect(page.getByText("H01 video 2.mp4")).toBeVisible();
  await noHorizontalOverflow(page);
  await shot(page, "mobile-detail-durable.png");
  const rows = page.getByRole("link", { name: /Xem chi tiết →/ });
  await expect(rows).toHaveCount(2);
  await rows.nth(1).click();
  await page.waitForURL(
    new RegExp(`/object-gallery\\?project=${d.projectId}[^&]*&video=${d.videoB}`),
  );
  expect(page.url()).toContain(`video=${d.videoB}`);
});

test("m03 multi-video gallery: refresh preserves selection, no overflow", async ({ page }) => {
  const suite = state.suite!;
  const l = suite.legacy;
  await page.goto(`/object-gallery?project=${l.projectId}&video=${l.videoB}`);
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_01/ })
    .waitFor({ timeout: 90_000 });
  await noHorizontalOverflow(page);
  await page.reload();
  expect(page.url()).toContain(`video=${l.videoB}`);
  await page
    .getByRole("button", { name: /Xem chi tiết vai trò subject_01/ })
    .waitFor({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: /Xem chi tiết vai trò subject_02/ })).toHaveCount(0);
  await shot(page, "mobile-gallery-video-b.png");
});

test("m04 API failure → honest error; retry recovers after backend restart", async ({ page }) => {
  const suite = state.suite!;
  const d = suite.durable;
  killBackend();
  await page.goto(`/projects/${d.projectId}`);
  await expect(page.getByRole("heading", { name: "Không thể tải dự án" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Dự án 2D/)).toHaveCount(0);
  await noHorizontalOverflow(page);
  await shot(page, "mobile-honest-error.png");
  await startBackend();
  await page.getByRole("button", { name: "Thử lại" }).click();
  await expect(page.getByRole("heading", { name: d.name })).toBeVisible({ timeout: 30_000 });
  await shot(page, "mobile-retry-recovered.png");
});

test("m05 LegacyWorkspace: hydrate error + retry validates before store write", async ({ page }) => {
  const suite = state.suite!;
  const l = suite.legacy;
  killBackend();
  await page.goto(`/?project=${l.projectId}`);
  await expect(page.getByText("Không thể mở dự án từ địa chỉ")).toBeVisible({ timeout: 15_000 });
  await noHorizontalOverflow(page);
  await shot(page, "mobile-home-hydrate-error.png");
  await startBackend();
  await page.getByRole("button", { name: /Thử lại/ }).click();
  await page.getByRole("button", { name: "✨ Tạo Dự Án Mới" }).waitFor({ timeout: 30_000 });
  await expect(page.getByText("Không thể mở dự án từ địa chỉ")).toHaveCount(0);
});
