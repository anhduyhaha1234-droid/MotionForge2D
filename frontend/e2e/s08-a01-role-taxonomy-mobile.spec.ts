import { test, expect, type Page } from "@playwright/test";

/**
 * S08-A01 — 390px mobile suite.
 *
 * Fresh isolated project (never touches the desktop suite's state).
 * Verifies: the seven-kind Vietnamese filter bar is reachable and usable at
 * 390px, the source_overlay removal-only badge/note render, and the gallery
 * (filter bar, summary cards, expanded source_overlay detail) has NO
 * horizontal overflow — the mobile-390 contract of the taxonomy bridge.
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
import { SEVEN_KINDS, KIND_VI } from "./s08-a01-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01/20260819-s08a01-r1/screenshots";

async function noHorizontalOverflow(page: Page, label: string): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `${label} has no horizontal overflow`).toBeLessThanOrEqual(0);
}

test("390px: taxonomy filter + removal-only without overflow", async ({ page }) => {
  const proj = await setupProject("a01-mobile");
  const extraction = await submitExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const job = (await waitExtractionTerminal(extraction.job_id)) as unknown as ExtractionJobJson;
  expect(job.status).toBe("completed");
  const scenes = sceneIdsFromJob(job);
  expect(scenes.length).toBeGreaterThan(0);

  // Seed one role of each of the seven kinds on REAL scenes.
  for (let i = 0; i < SEVEN_KINDS.length; i++) {
    const kind = SEVEN_KINDS[i];
    const role = (await apiJson("/api/v2/object-intelligence/roles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: proj.projectId,
        video_item_id: proj.videoItemId,
        source_generation: "1",
        name: `M-${kind}`,
        kind,
        status: "suggested",
        description: null,
      }),
    })) as { id: string };
    await createOccurrence(
      role.id,
      scenes[i % scenes.length],
      i,
      i * 1000,
      { x: 10, y: 10, width: 40, height: 40 },
      0.9,
    );
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(proj.projectId)}&video=${proj.videoItemId}`,
  );
  const bar = page.locator('[data-testid="kind-filter-bar"]');
  await bar.waitFor({ state: "visible" });
  for (const kind of SEVEN_KINDS) {
    await expect(bar.getByRole("button", { name: KIND_VI[kind] })).toBeVisible();
  }
  await expect(page.locator('[data-kind="source_overlay"][data-removal-only="true"]')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/mobile-390px-kind-filter-bar.png`, fullPage: true });
  await noHorizontalOverflow(page, "gallery with filter bar (390px)");

  // Expand the source_overlay summary -> removal-only note, no overflow.
  await page.getByRole("button", { name: "Xem chi tiết vai trò M-source_overlay" }).click();
  const detail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "M-source_overlay" }),
  });
  await detail.waitFor({ state: "visible" });
  await expect(detail.getByTestId("removal-only-badge")).toContainText("Chỉ loại bỏ (lớp nguồn)");
  await expect(detail.getByTestId("removal-only-note")).toBeVisible();
  await page.screenshot({
    path: `${SHOT_DIR}/mobile-390px-source-overlay-removal-only.png`,
    fullPage: true,
  });
  await noHorizontalOverflow(page, "source_overlay detail (390px)");

  // Filter to source_overlay at 390px: only the removal-only card remains.
  await bar.getByRole("button", { name: KIND_VI.source_overlay }).click();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò M-source_overlay" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò M-character" }),
  ).not.toBeVisible();
  await noHorizontalOverflow(page, "filtered gallery (390px)");

  // The seventh kind (Khác / other) also has a card here: filter shows it.
  await bar.getByRole("button", { name: KIND_VI.other }).click();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò M-other" }),
  ).toBeVisible();
  await noHorizontalOverflow(page, "other-filtered gallery (390px)");
});
