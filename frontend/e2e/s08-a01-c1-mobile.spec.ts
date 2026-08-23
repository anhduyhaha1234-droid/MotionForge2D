import { test, expect, type Page } from "@playwright/test";

/**
 * S08-A01-C1 — 390px mobile suite (F4 source_overlay reclassify + F2
 * kind-safe merge source guard), fresh isolated project.
 *
 * Verifies at 390px: the source_overlay role exposes NO replacement/curation
 * actions but CAN be reclassified via the dedicated "Sửa phân loại" action,
 * and a different-kind merge source is disabled while a same-kind source is
 * enabled — without horizontal overflow.
 */

import {
  apiJson,
  createOccurrence,
  sceneIdsFromJob,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
  type ExtractionJobJson,
} from "./s08-t04-helpers";
import { KIND_VI } from "./s08-a01-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01-c1/20260819-s08a01c1-r1/screenshots";

async function noHorizontalOverflow(page: Page, label: string): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `${label} has no horizontal overflow`).toBeLessThanOrEqual(0);
}

async function seedRole(
  projectId: string,
  videoItemId: string,
  scenes: string[],
  kind: string,
  index: number,
): Promise<string> {
  const role = (await apiJson("/api/v2/object-intelligence/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      video_item_id: videoItemId,
      source_generation: "1",
      name: `M-C1-${kind}`,
      kind,
      status: "suggested",
      description: null,
    }),
  })) as { id: string };
  await createOccurrence(
    role.id,
    scenes[index % scenes.length],
    index,
    index * 1000,
    { x: 10 + index, y: 10, width: 40 + index, height: 40 },
    0.9,
  );
  return role.id;
}

test("390px: source_overlay reclassify + kind-safe merge without overflow", async ({ page }) => {
  const proj = await setupProject("a01-c1-mobile");
  const extraction = await submitExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const job = (await waitExtractionTerminal(extraction.job_id)) as unknown as ExtractionJobJson;
  expect(job.status).toBe("completed");
  const scenes = sceneIdsFromJob(job);
  expect(scenes.length).toBeGreaterThan(0);

  await seedRole(proj.projectId, proj.videoItemId, scenes, "source_overlay", 0);
  await seedRole(proj.projectId, proj.videoItemId, scenes, "character", 1);
  await seedRole(proj.projectId, proj.videoItemId, scenes, "character", 2);
  await seedRole(proj.projectId, proj.videoItemId, scenes, "background", 3);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(proj.projectId)}&video=${proj.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  await noHorizontalOverflow(page, "gallery (390px)");

  // F4: source_overlay has NO replacement/curation actions + reclassify present.
  await page.getByRole("button", { name: "Xem chi tiết vai trò M-C1-source_overlay" }).click();
  const detail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "M-C1-source_overlay" }),
  });
  await detail.waitFor({ state: "visible" });
  await expect(detail.getByTestId("removal-only-badge")).toContainText("Chỉ loại bỏ (lớp nguồn)");
  await expect(detail.getByText("Xác nhận vai trò")).not.toBeVisible();
  await expect(detail.getByText("Sửa tên/loại")).not.toBeVisible();
  await expect(detail.getByTestId("reclassify-source-overlay")).toBeVisible();
  await noHorizontalOverflow(page, "source_overlay detail (390px)");
  await page.screenshot({
    path: `${SHOT_DIR}/mobile-390px-source-overlay-f4.png`,
    fullPage: true,
  });

  // F4: reclassify through the correction dialog at 390px.
  await detail.getByTestId("reclassify-source-overlay").click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ state: "visible" });
  await dialog.locator("select").selectOption("background");
  await dialog.getByRole("button", { name: "Lưu chỉnh sửa" }).click();
  await expect(detail.getByTestId("reclassify-source-overlay")).not.toBeVisible({ timeout: 30_000 });
  await expect(detail.getByTestId("removal-only-badge")).not.toBeVisible();
  await expect(detail.getByText(KIND_VI.background)).toBeVisible();
  await noHorizontalOverflow(page, "after reclassify (390px)");

  // F2: different-kind source disabled, same-kind enabled.
  await page.getByRole("button", { name: "Xem chi tiết vai trò M-C1-character" }).first().click();
  const targetDetail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "M-C1-character" }),
  });
  await targetDetail.waitFor({ state: "visible" });
  await targetDetail.getByRole("radio", { name: "Vai trò đích" }).check();

  await page.getByRole("button", { name: "Xem chi tiết vai trò M-C1-background" }).click();
  const bgDetail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "M-C1-background" }),
  });
  await bgDetail.waitFor({ state: "visible" });
  await expect(bgDetail.getByRole("checkbox", { name: "Nguồn gộp" })).toBeDisabled();
  await page.screenshot({
    path: `${SHOT_DIR}/mobile-390px-f2-kind-safe-merge.png`,
    fullPage: true,
  });
  await noHorizontalOverflow(page, "F2 kind-safe merge (390px)");
});
