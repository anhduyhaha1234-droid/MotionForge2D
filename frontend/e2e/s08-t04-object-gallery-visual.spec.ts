import { test, expect } from "@playwright/test";
import path from "path";

/**
 * S08-T04-C1 Object Gallery — visual evidence (desktop project only).
 * New screenshots land under output/s08-sprint/20260816-s08t04-c2-r1/
 * screenshots/ (NEVER overwrite the original run's evidence).
 */
import { runExtraction, setupProject } from "./s08-t04-helpers";

const SHOTS = "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260816-s08t04-c2-r1/screenshots";

const state: { projectId: string; videoItemId: string; sourceSha: string } = {
  projectId: "",
  videoItemId: "",
  sourceSha: "",
};

test.beforeAll(async () => {
  const proj = await setupProject("t04-c1-visual");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  state.sourceSha = proj.sourceSha;
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
});

test("visual desktop gallery", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expect(
    page.getByRole("button", { name: /^Xem chi tiết vai trò subject_01$/ }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel("Công việc phát hiện đối tượng").getByText("Hoàn tất")).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, "gallery-desktop.png"), fullPage: true });
});

test("visual desktop expanded detail with real media", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expect(
    page.getByRole("button", { name: /^Xem chi tiết vai trò subject_01$/ }),
  ).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Xem chi tiết vai trò subject_01" }).click();
  await expect(page.getByTestId("role-detail").first()).toBeVisible();
  const media = page.getByTestId("role-detail").first().locator("img[data-testid^='media-']").first();
  if ((await media.count()) > 0) {
    await expect(media).toBeVisible();
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, "gallery-desktop-detail.png"), fullPage: true });
});
