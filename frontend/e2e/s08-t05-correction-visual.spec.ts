import { test, type Page } from "@playwright/test";

/**
 * S08-T05 — visual QA screenshots (desktop project only; captures its own
 * 390px viewport via setViewportSize).  S08-T05-C2: expand-before-actions.
 *
 * Screenshots land under output/s08-sprint/20260817-s08t05-c2-r1/screenshots/.
 * All content is REAL backend data (deterministic extraction, real roles).
 */

import {
  createOccurrence,
  createRole,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
} from "./s08-t04-helpers";

test.describe.configure({ mode: "serial" });

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260817-s08t05-c2-r1/screenshots";

const state: { projectId: string; videoItemId: string; scenes: string[] } = {
  projectId: "",
  videoItemId: "",
  scenes: [],
};

test.beforeAll(async () => {
  const proj = await setupProject("t05-visual");
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
  const r1 = await createRole("Visual A", state.projectId, state.videoItemId);
  await createOccurrence(
    r1.id,
    state.scenes[0],
    10,
    10000,
    { x: 10, y: 10, width: 40, height: 40 },
    0.9,
  );
  const r2 = await createRole("Visual B", state.projectId, state.videoItemId);
  await createOccurrence(
    r2.id,
    state.scenes[1] ?? state.scenes[0],
    20,
    20000,
    { x: 12, y: 10, width: 40, height: 40 },
    0.9,
  );
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({
    path: `${SHOT_DIR}/${name}.png`,
    fullPage: true,
  });
}

async function expandRole(page: Page, roleName: string): Promise<void> {
  await page
    .getByRole("button", { name: `Xem chi tiết vai trò ${roleName}` })
    .first()
    .click();
  await page.getByTestId("role-detail").first().waitFor({ state: "visible" });
}

test("v1 - desktop gallery with correction actions + scope dialog", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Visual A");
  await page.getByTestId("role-detail").first().waitFor({ timeout: 60_000 });
  await shot(page, "desktop-gallery-correction-actions");

  const detail = page.getByTestId("role-detail").first();
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  await dialog.getByRole("radio", { name: /Visual B/ }).check();
  await dialog.getByTestId("correction-scope").waitFor();
  await shot(page, "desktop-correction-scope-dialog");
  await page.keyboard.press("Escape");
});

test("v2 - 390px correction scope dialog within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Visual A");
  await page.getByTestId("role-detail").first().waitFor({ timeout: 60_000 });
  const detail = page.getByTestId("role-detail").first();
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  await dialog.getByRole("radio", { name: /Visual B/ }).check();
  await dialog.getByTestId("correction-scope").waitFor();
  await shot(page, "mobile-390px-correction-scope-dialog");
});
