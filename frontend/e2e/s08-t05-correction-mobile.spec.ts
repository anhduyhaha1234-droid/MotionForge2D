import { test, expect, type Page } from "@playwright/test";

/**
 * S08-T05 — 390px mobile suite.  Runs in its own Playwright project
 * (mobile-390px, testMatch s08-t05-*.mobile.spec.ts) against its OWN
 * isolated QA project (never touches desktop-mutated state).  S08-T05-C2:
 * expand-before-actions (collapsible role cards) + semantic assertions.
 */

import {
  createOccurrence,
  createRole,
  listRoles,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
} from "./s08-t04-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260817-s08t05-c2-r1/screenshots";

test.describe.configure({ mode: "serial" });

const state: { projectId: string; videoItemId: string; scenes: string[] } = {
  projectId: "",
  videoItemId: "",
  scenes: [],
};

test.beforeAll(async () => {
  const proj = await setupProject("t05-mobile");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  const extraction = await submitExtraction(
    proj.projectId,
    proj.videoItemId,
    proj.sourceSha,
  );
  const job = await waitExtractionTerminal(extraction.job_id);
  state.scenes = job.candidates
    .flatMap((c) => c.occurrences as Array<{ scene_id: string }>)
    .map((o) => o.scene_id)
    .filter((id, index, all) => all.indexOf(id) === index);

  const r1 = await createRole("Mobile A", state.projectId, state.videoItemId);
  await createOccurrence(
    r1.id,
    state.scenes[0],
    10,
    10000,
    { x: 10, y: 10, width: 40, height: 40 },
    0.9,
  );
  const r2 = await createRole("Mobile B", state.projectId, state.videoItemId);
  await createOccurrence(
    r2.id,
    state.scenes[1] ?? state.scenes[0],
    20,
    20000,
    { x: 12, y: 10, width: 40, height: 40 },
    0.9,
  );
});

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
}

/** Expand the role card and wait for the detail card. */
async function expandRole(page: Page, roleName: string): Promise<void> {
  await page
    .getByRole("button", { name: `Xem chi tiết vai trò ${roleName}` })
    .first()
    .click();
  await page.getByTestId("role-detail").first().waitFor({ state: "visible" });
}

test("m1 - gallery renders at 390px with the correction actions and no overflow", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  const expand = page.getByRole("button", { name: "Xem chi tiết vai trò Mobile A" });
  await expect(expand).toBeVisible({ timeout: 60_000 });
  await expand.click();
  const detail = page.getByTestId("role-detail").first();
  await expect(detail).toBeVisible();
  await expect(detail.getByRole("button", { name: "Chuyển vai trò" })).toBeVisible();
  await expect(detail.getByRole("button", { name: "Sửa tên/loại" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("m2 - correction dialog with the scope report stays within the 390px viewport", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Mobile A");
  const detail = page.getByTestId("role-detail").first();
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: /Mobile B/ }).check();
  const scope = dialog.getByTestId("correction-scope");
  await expect(scope).toBeVisible();
  await expect(scope.getByTestId("scope-reassign-role-count")).toContainText("2");

  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  const viewport = page.viewportSize();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual((viewport?.width ?? 390) + 1);
  await expectNoHorizontalOverflow(page);

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

test("m3 - edit dialog renders at 390px with no overflow", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Mobile A");
  const detail = page.getByTestId("role-detail").first();
  await detail.getByRole("button", { name: "Sửa tên/loại" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Tên vai trò")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

test("m4 - regenerated media after a correction refresh renders at 390px (no overflow)", async ({
  page,
}) => {
  // Real DISCOVER roles carry associations; the correction replaces their
  // media links and the refreshed gallery must render them at 390px.
  const roles = await listRoles(state.videoItemId);
  const s1 = roles.find((r) => r.name === "subject_01");
  const s2 = roles.find((r) => r.name === "subject_02");
  expect(s1, "subject_01 DISCOVER role").toBeTruthy();
  expect(s2, "subject_02 DISCOVER role").toBeTruthy();

  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "subject_01");
  const detail = page.getByTestId("role-detail").first();
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: /subject_02/ }).check();
  await dialog.getByTestId("correction-scope").waitFor();
  await dialog.getByRole("button", { name: "Chuyển vai trò" }).click();

  const strip = page.getByTestId("recompute-strip");
  await expect(strip).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(async () => strip.getAttribute("data-state"), { timeout: 60_000 })
    .toBe("completed");

  // The regenerated media renders inside the TARGET role's expanded detail
  // card at 390px; the emptied source shows the honest no-current-media state.
  await expect(page.getByTestId("no-current-media").first()).toBeVisible({ timeout: 30_000 });
  await expandRole(page, "subject_02");
  const targetDetail = page
    .getByTestId("role-detail")
    .filter({ hasText: "subject_02" })
    .first();
  await expect(targetDetail.getByTestId("media-regenerated").first()).toBeVisible({
    timeout: 30_000,
  });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: `${SHOT_DIR}/mobile-390px-regenerated-media.png` });

  // Restart: reload keeps the regenerated media at 390px (re-expand target).
  await page.reload();
  await expandRole(page, "subject_02");
  await expect(
    page.getByTestId("role-detail").filter({ hasText: "subject_02" }).first()
      .getByTestId("media-regenerated").first(),
  ).toBeVisible({ timeout: 30_000 });
  await expectNoHorizontalOverflow(page);
});
