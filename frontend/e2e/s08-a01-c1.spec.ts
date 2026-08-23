import { test, expect } from "@playwright/test";

/**
 * S08-A01-C1 (F4 + F2) — source_overlay reclassification + kind-safe merge.
 *
 * Runs against the REAL isolated QA backend (localhost:8027 default,
 * QA_API_BASE override) with the deterministic extraction provider — the
 * production path is never involved and no data is fabricated.
 *
 * F4 - a misclassified source_overlay role:
 *   - shows NO replacement/curation surface (no merge source/target, no
 *     confirm, no split/edit/reassign) — unchanged A01 guarantee;
 *   - BUT exposes the dedicated "Sửa phân loại" (fix classification) action
 *     that reclassifies it through the existing correction preview + confirm
 *     + CAS flow (candidate_edit with role_kind).
 *
 * F2 - kind-safe manual merge in the UI:
 *   - only roles whose kind equals the selected target's kind can be picked
 *     as merge sources (different-kind checkbox disabled with a hint);
 *   - changing the target clears any incompatible source selection.
 */

import {
  apiJson,
  createOccurrence,
  sceneIdsFromJob,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
  type ExtractionJobJson,
  type RoleJson,
} from "./s08-t04-helpers";
import { KIND_VI } from "./s08-a01-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01-c1/20260819-s08a01c1-r1/screenshots";

const state: {
  projectId: string;
  videoItemId: string;
  scenes: string[];
  roles: RoleJson[];
} = { projectId: "", videoItemId: "", scenes: [], roles: [] };

async function createRoleKind(
  name: string,
  projectId: string,
  videoItemId: string,
  kind: string,
): Promise<RoleJson> {
  return (await apiJson("/api/v2/object-intelligence/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      video_item_id: videoItemId,
      source_generation: "1",
      name,
      kind,
      status: "suggested",
      description: null,
    }),
  })) as RoleJson;
}

async function seedRoleAndOccurrence(
  kind: string,
  index: number,
): Promise<RoleJson> {
  const role = await createRoleKind(
    `C1-${kind}`,
    state.projectId,
    state.videoItemId,
    kind,
  );
  const scene = state.scenes[index % state.scenes.length];
  await createOccurrence(
    role.id,
    scene,
    index,
    index * 1000,
    { x: 10 + index, y: 10, width: 40 + index, height: 40 },
    0.9,
  );
  return role;
}

test.describe.configure({ mode: "serial" });

test("seed real project + roles incl. a source_overlay and a character pair", async () => {
  const proj = await setupProject("a01-c1");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  const extraction = await submitExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const job = (await waitExtractionTerminal(extraction.job_id)) as unknown as ExtractionJobJson;
  expect(job.status).toBe("completed");
  state.scenes = sceneIdsFromJob(job);
  expect(state.scenes.length).toBeGreaterThan(0);

  // source_overlay (F4 target), plus two characters for a same-kind merge and
  // one background to prove the kind-safe source guard (F2).
  state.roles.push(await seedRoleAndOccurrence("source_overlay", 0));
  state.roles.push(await seedRoleAndOccurrence("character", 1));
  state.roles.push(await seedRoleAndOccurrence("character", 2));
  state.roles.push(await seedRoleAndOccurrence("background", 3));
});

test("F4: source_overlay shows NO replacement/curation actions", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  const summary = page.getByRole("button", { name: "Xem chi tiết vai trò C1-source_overlay" });
  await summary.click();
  const detail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "C1-source_overlay" }),
  });
  await detail.waitFor({ state: "visible" });
  // Removal-only badge + note.
  await expect(detail.getByTestId("removal-only-badge")).toContainText("Chỉ loại bỏ (lớp nguồn)");
  // NO replacement/curation actions.
  await expect(detail.getByText("Nguồn gộp")).not.toBeVisible();
  await expect(detail.getByText("Vai trò đích")).not.toBeVisible();
  await expect(detail.getByText("Xác nhận vai trò")).not.toBeVisible();
  await expect(detail.getByText("Tách vai trò đã gộp")).not.toBeVisible();
  await expect(detail.getByText("Sửa tên/loại")).not.toBeVisible();
  await expect(detail.getByText("Chuyển vai trò")).not.toBeVisible();
  // The dedicated reclassify action IS present (F4).
  await expect(detail.getByTestId("reclassify-source-overlay")).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/desktop-source-overlay-f4.png`, fullPage: true });
});

test("F4: source_overlay CAN be safely reclassified via correction flow", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Xem chi tiết vai trò C1-source_overlay" }).click();
  const detail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "C1-source_overlay" }),
  });
  await detail.waitFor({ state: "visible" });
  await detail.getByTestId("reclassify-source-overlay").click();

  // The correction dialog opens (candidate_edit) with the kind selector.
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ state: "visible" });
  const kindSelect = dialog.locator("select");
  // Reclassify to 'background' (kind values = canonical machine kinds).
  await kindSelect.selectOption("background");
  await dialog.getByRole("button", { name: "Lưu chỉnh sửa" }).click();

  // The apply flow (preview -> create -> confirm) completes; the durable
  // role is reclassified away from source_overlay (no recompute needed for a
  // kind-only edit, so no long job to poll).
  await expect(detail.getByTestId("reclassify-source-overlay")).not.toBeVisible({ timeout: 30_000 });
  await expect(detail.getByTestId("removal-only-badge")).not.toBeVisible();
  // The badge now shows the new kind label.
  await expect(detail.getByText(KIND_VI.background)).toBeVisible();
});

test("F2: kind-safe merge — different-kind source is disabled, same-kind enabled", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  const targetSummary = page.getByRole("button", { name: "Xem chi tiết vai trò C1-character" });
  const targetDetail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "C1-character" }),
  });
  // Expand the FIRST character card and select it as the merge TARGET.
  // (Two characters exist; we pick the first card to keep the test stable.)
  await targetSummary.first().click();
  await targetDetail.waitFor({ state: "visible" });
  await targetDetail.getByRole("radio", { name: "Vai trò đích" }).check();

  // A background role's merge-source checkbox is DISABLED (different kind).
  const bgSummary = page.getByRole("button", { name: "Xem chi tiết vai trò C1-background" });
  await bgSummary.click();
  const bgDetail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "C1-background" }),
  });
  await bgDetail.waitFor({ state: "visible" });
  const bgSourceInput = bgDetail.getByRole("checkbox", { name: "Nguồn gộp" });
  await expect(bgSourceInput).toBeDisabled();
  await expect(bgDetail.getByText("(khác loại với đích — chỉ gộp cùng loại)")).toBeVisible();

  // A same-kind (character) role CAN be picked as a merge source: expand the
  // second character card (single-expand panel → exactly one role-detail in
  // the DOM at a time) and select its checkbox.
  const otherCharSummary = page
    .getByRole("button", { name: "Xem chi tiết vai trò C1-character" })
    .nth(1);
  await otherCharSummary.click();
  const otherCharDetail = page
    .getByTestId("role-detail")
    .filter({ has: page.getByRole("heading", { name: "C1-character" }) });
  await otherCharDetail.waitFor({ state: "visible" });
  const charSourceInput = otherCharDetail.getByRole("checkbox", { name: "Nguồn gộp" });
  await expect(charSourceInput).toBeEnabled();
  await charSourceInput.check();
  await expect(otherCharDetail.getByText("Đang chọn làm nguồn gộp")).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/desktop-f2-kind-safe-merge.png`, fullPage: true });
});
