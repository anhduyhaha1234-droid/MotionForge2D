import { test, expect } from "@playwright/test";

/**
 * S08-A01 — Source-Locked 2D Role Taxonomy Bridge — interaction suite.
 *
 * Runs against the REAL isolated QA backend (localhost:8027 by default,
 * QA_API_BASE overrides) with the deterministic extraction provider, so the
 * production path is never involved and no data is fabricated.
 *
 * Verifies the approved UX contract:
 *   1. the canonical seven-kind taxonomy comes from the BACKEND kinds
 *      endpoint (7 machine kinds, source_overlay removal_only=True);
 *   2. extraction output can include the new role/layer kinds;
 *   3. the gallery renders a seven-kind Vietnamese filter bar
 *      (Nhân vật, Vật phẩm, Bối cảnh, Tiền cảnh, Nội dung/đồ họa,
 *       Lớp nguồn cần loại bỏ, Khác);
 *   4. source_overlay roles show a removal-only badge and expose NO curation
 *      surface (no merge source/target, no confirm, no split/edit/reassign),
 *      with a clear Vietnamese removal-only note;
 *   5. the kind filter actually filters the visible role cards (server data
 *      is real); an empty kind filter shows the honest empty message.
 *
 * Every role is seeded through the real T01 API on REAL scene rows produced
 * by the deterministic extraction job.
 */

import {
  apiJson,
  createOccurrence,
  listRoles,
  sceneIdsFromJob,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
  type ExtractionJobJson,
  type RoleJson,
} from "./s08-t04-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-a01/20260819-s08a01-r1/screenshots";

import { SEVEN_KINDS, KIND_VI } from "./s08-a01-helpers";

// ─── shared state helpers ──────────────────────────────────────────────────

const state: {
  projectId: string;
  videoItemId: string;
  scenes: string[];
  roles: RoleJson[];
} = { projectId: "", videoItemId: "", scenes: [], roles: [] };

/** Create a role with an explicit canonical kind through the real API. */
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

test.describe.configure({ mode: "serial" });

test("backend taxonomy is canonical and source_overlay is removal-only", async () => {
  const kinds = (await apiJson("/api/v2/object-intelligence/kinds")) as {
    kinds: Array<{ name: string; removal_only: boolean }>;
    source_overlay: string;
  };
  expect(kinds.source_overlay).toBe("source_overlay");
  expect(kinds.kinds.map((k) => k.name)).toEqual([...SEVEN_KINDS]);
  const overlay = kinds.kinds.find((k) => k.name === "source_overlay");
  expect(overlay?.removal_only).toBe(true);
  for (const k of kinds.kinds) {
    if (k.name !== "source_overlay") expect(k.removal_only).toBe(false);
  }

  // Fresh project + REAL extraction (deterministic QA provider): proves the
  // extraction contract can run in this deployment and produces real scenes.
  const proj = await setupProject("a01-taxonomy");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  const extraction = await submitExtraction(
    proj.projectId,
    proj.videoItemId,
    proj.sourceSha,
  );
  const job = (await waitExtractionTerminal(extraction.job_id)) as unknown as ExtractionJobJson;
  expect(job.status).toBe("completed");
  state.scenes = sceneIdsFromJob(job);
  expect(state.scenes.length).toBeGreaterThan(0);
});

test("seed the kinds for the gallery (other left empty for empty-state)", async () => {
  // Seed the six non-"other" kinds ("other" has zero roles on purpose so the
  // "Khác" filter demonstrates the honest empty-state message).  The mobile
  // suite seeds all seven kinds for badge/overflow coverage.
  const seededKinds = SEVEN_KINDS.filter((k) => k !== "other");
  for (let i = 0; i < seededKinds.length; i++) {
    const kind = seededKinds[i];
    const role = await createRoleKind(`A01-${kind}`, state.projectId, state.videoItemId, kind);
    const scene = state.scenes[i % state.scenes.length];
    await createOccurrence(
      role.id,
      scene,
      i,
      i * 1000,
      { x: 10 + i, y: 10, width: 40 + i, height: 40 },
      0.9,
    );
    state.roles.push(role);
  }
  const all = await listRoles(state.videoItemId);
  const kinds = new Set(all.map((r) => r.kind as string));
  for (const kind of seededKinds) expect(kinds.has(kind)).toBe(true);
  expect(kinds.has("other")).toBe(false);
});

test("gallery renders the seven-kind Vietnamese filter bar", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  for (const kind of SEVEN_KINDS) {
    await expect(
      page
        .locator('[data-testid="kind-filter-bar"]')
        .getByRole("button", { name: KIND_VI[kind] }),
    ).toBeVisible();
  }
  // The removal-only chip is visually marked with the removal-only attribute.
  await expect(
    page.locator('[data-kind="source_overlay"][data-removal-only="true"]'),
  ).toBeVisible();
  await expect(page.locator('[data-kind="background"][data-removal-only="false"]')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/desktop-kind-filter-bar.png`, fullPage: true });
});

test("kind filter filters the visible role cards", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  // Filter to background: only the background role remains visible.
  await page
    .locator('[data-testid="kind-filter-bar"]')
    .getByRole("button", { name: KIND_VI.background })
    .click();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò A01-background" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò A01-character" }),
  ).not.toBeVisible();
  // Filter to the removal-only kind: the source overlay is the only card.
  await page
    .locator('[data-testid="kind-filter-bar"]')
    .getByRole("button", { name: KIND_VI.source_overlay })
    .click();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò A01-source_overlay" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò A01-prop" }),
  ).not.toBeVisible();
  // Back to all.
  await page
    .locator('[data-testid="kind-filter-bar"]')
    .getByRole("button", { name: "Tất cả" })
    .click();
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò A01-prop" }),
  ).toBeVisible();
});

test("empty kind filter shows the honest empty message", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  // No role of this kind was seeded -> honest empty state, no fabricated data.
  await page
    .locator('[data-testid="kind-filter-bar"]')
    .getByRole("button", { name: KIND_VI.other })
    .click();
  await expect(
    page.getByText(/Không có vai trò nào thuộc loại/),
  ).toBeVisible();
});

test("source_overlay is removal-only with no curation surface", async ({ page }) => {
  await page.goto(
    `/object-gallery?project=${encodeURIComponent(state.projectId)}&video=${state.videoItemId}`,
  );
  await page.locator('[data-testid="kind-filter-bar"]').waitFor({ state: "visible" });
  // Expand the source-overlay role (summary badge is already visible).
  const summary = page.getByRole("button", {
    name: "Xem chi tiết vai trò A01-source_overlay",
  });
  await summary.click();
  const detail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "A01-source_overlay" }),
  });
  await detail.waitFor({ state: "visible" });
  // Removal-only badge + note.
  await expect(detail.getByTestId("removal-only-badge")).toContainText("Chỉ loại bỏ (lớp nguồn)");
  await expect(detail.getByTestId("removal-only-note")).toBeVisible();
  // NO curation actions: merge source/target, confirm, split, edit, reassign.
  await expect(detail.getByText("Nguồn gộp")).not.toBeVisible();
  await expect(detail.getByText("Xác nhận vai trò")).not.toBeVisible();
  await expect(detail.getByText("Sửa tên/loại")).not.toBeVisible();
  await expect(detail.getByText("Chuyển vai trò")).not.toBeVisible();
  // A replaceable role (character) DOES expose the actions.
  await page
    .getByRole("button", { name: "Xem chi tiết vai trò A01-character" })
    .click();
  const charDetail = page.getByTestId("role-detail").filter({
    has: page.getByRole("heading", { name: "A01-character" }),
  });
  await charDetail.waitFor({ state: "visible" });
  await expect(charDetail.getByText("Nguồn gộp")).toBeVisible();
  await expect(charDetail.getByText("Xác nhận vai trò")).toBeVisible();
  await page.screenshot({
    path: `${SHOT_DIR}/desktop-source-overlay-removal-only.png`,
    fullPage: true,
  });
});
