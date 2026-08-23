import { test, expect, type Page } from "@playwright/test";

/**
 * S08-T05 Targeted Object Correction — interaction suite against the REAL
 * isolated QA backend.  The correction workflow is two-phase: the UI shows
 * the pre-confirmation impacted-scope report (pure preview read), the
 * confirmation applies the targeted mutation + supersession + the durable
 * RECOMPUTE_OBJECTS job, and the recompute strip reports the HONEST terminal
 * outcome.  Unaffected roles are verified untouched through the real API.
 *
 * S08-T05-C2 (repair + isolate): the gallery renders collapsible role cards —
 * every test EXPANDS the card (aria-expanded toggle) BEFORE locating
 * correction actions, and assertions are semantic (data-testid / role /
 * state / API) instead of brittle display copy.
 */

import {
  apiJson,
  createOccurrence,
  createRole,
  generateSuggestions,
  listRoles,
  setupProject,
  submitExtraction,
  waitExtractionTerminal,
} from "./s08-t04-helpers";

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260817-s08t05-c2-r1/screenshots";

interface RoleMediaJson {
  artifact_id: string;
  purpose: string;
  sha256: string;
  source_job_id: string;
  source_generation: string;
}

/** Expand the role card (collapsible) and wait for the real detail card. */
async function expandRole(page: Page, roleName: string): Promise<void> {
  await page
    .getByRole("button", { name: `Xem chi tiết vai trò ${roleName}` })
    .first()
    .click();
  await page.getByTestId("role-detail").first().waitFor({ state: "visible" });
}

/** The expanded detail card of a role (stable id + purpose testids). */
function roleDetail(page: Page, roleName: string) {
  return page
    .getByTestId("role-detail")
    .filter({ has: page.getByRole("heading", { name: roleName }) })
    .first();
}

/** role id -> current media (newest valid associations) via the real API. */
/** HTTP status of the contained content endpoint for one artifact. */
async function contentStatus(jobId: string, artifactId: string): Promise<number> {
  const res = await fetch(
    `http://localhost:8014/api/v2/object-intelligence/extraction/${jobId}/artifacts/${artifactId}/content`,
  );
  return res.status;
}

async function mediaOf(
  videoItemId: string,
  roleIds: string[],
): Promise<Map<string, RoleMediaJson[]>> {
  const data = (await apiJson(
    `/api/v2/object-intelligence/roles?video_item_id=${encodeURIComponent(videoItemId)}&limit=200`,
  )) as { roles: Array<{ id: string; media?: RoleMediaJson[] }> };
  const out = new Map<string, RoleMediaJson[]>();
  for (const role of data.roles) {
    if (roleIds.includes(role.id)) out.set(role.id, role.media ?? []);
  }
  return out;
}

test.describe.configure({ mode: "serial" });

const state: {
  projectId: string;
  videoItemId: string;
  scenes: string[];
  shiftA: string;
  shiftB: string;
  shiftOccId: string;
  pairTarget: string;
  pairSource: string;
  editMe: string;
} = {
  projectId: "",
  videoItemId: "",
  scenes: [],
  shiftA: "",
  shiftB: "",
  shiftOccId: "",
  pairTarget: "",
  pairSource: "",
  editMe: "",
};

test.beforeAll(async () => {
  const proj = await setupProject("t05-correction");
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

  const mk = async (
    name: string,
    scene: string,
    frame: number,
    bbox: { x: number; y: number; width: number; height: number },
  ) => {
    const role = await createRole(name, state.projectId, state.videoItemId);
    const occ = await createOccurrence(
      role.id,
      scene,
      frame,
      frame * 1000,
      bbox,
      0.9,
    );
    return { roleId: role.id, occurrence: occ as unknown as { id: string } };
  };

  const s0 = state.scenes[0];
  const s1 = state.scenes[1] ?? state.scenes[0];

  const a = await mk("Shift A", s0, 10, { x: 10, y: 10, width: 40, height: 40 });
  state.shiftA = a.roleId;
  state.shiftOccId = a.occurrence.id;
  const b = await mk("Shift B", s1, 20, { x: 12, y: 10, width: 40, height: 40 });
  state.shiftB = b.roleId;

  const p1 = await mk("Pair X", s0, 11, { x: 20, y: 20, width: 30, height: 30 });
  const p2 = await mk("Pair X", s1, 21, { x: 22, y: 20, width: 30, height: 30 });
  state.pairTarget = p1.roleId;
  state.pairSource = p2.roleId;

  const e = await mk("Edit Me", s0, 12, { x: 30, y: 30, width: 20, height: 20 });
  state.editMe = e.roleId;

  await generateSuggestions(state.videoItemId);
});

test("t01 - reassign reports impacted scope BEFORE confirmation; unaffected roles untouched", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Shift A");
  const detail = roleDetail(page, "Shift A");
  // The evidence list shows exactly 1 occurrence with a reassign action.
  await expect(detail.getByRole("button", { name: "Chuyển vai trò" })).toBeVisible();
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const confirmButton = dialog.getByRole("button", { name: "Chuyển vai trò" });
  // Confirmation is disabled until a target role is selected.
  await expect(confirmButton).toBeDisabled();

  await dialog.getByRole("radio", { name: /Shift B/ }).check();
  const scope = dialog.getByTestId("correction-scope");
  await expect(scope).toBeVisible();
  // Semantic state assertions on the impacted-scope report.
  await expect(scope.getByTestId("scope-reassign-role-count")).toContainText("2");
  await expect(scope.getByTestId("scope-reassign-occurrence-count")).toContainText("1");

  await confirmButton.click();
  // State proof via the real API (recompute regenerates the invalidated
  // (Shift A, Shift B) cross-name suggestion).
  await expect
    .poll(
      async () => (await listRoles(state.videoItemId)).find((r) => r.id === state.shiftB)?.occurrences.length ?? 0,
      { timeout: 30_000 },
    )
    .toBe(2);
  const roles = await listRoles(state.videoItemId);
  const a = roles.find((r) => r.id === state.shiftA);
  const b = roles.find((r) => r.id === state.shiftB);
  expect(a?.occurrences.length).toBe(0);
  const moved = b?.occurrences.find((o) => o.id === state.shiftOccId);
  expect(moved).toBeTruthy();
  // Unaffected Pair X roles untouched (one occurrence each).
  const p1 = roles.find((r) => r.id === state.pairTarget);
  const p2 = roles.find((r) => r.id === state.pairSource);
  expect(p1?.occurrences.length).toBe(1);
  expect(p2?.occurrences.length).toBe(1);
});

test("t02 - candidate edit shows scope; no recompute needed for API-seeded roles", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Edit Me");
  const detail = roleDetail(page, "Edit Me");
  await detail.getByRole("button", { name: "Sửa tên/loại" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Tên vai trò").fill("Edited Name");
  const scope = dialog.getByTestId("correction-scope");
  await expect(scope).toBeVisible();
  await expect(scope.getByTestId("scope-candidate_edit-role-count")).toContainText("1");
  await expect(scope.getByTestId("recompute-not-needed-candidate_edit")).toBeVisible();

  await dialog.getByRole("button", { name: "Lưu chỉnh sửa" }).click();
  await expect
    .poll(
      async () => (await listRoles(state.videoItemId)).find((r) => r.id === state.editMe)?.name,
      { timeout: 30_000 },
    )
    .toBe("Edited Name");
});

test("t03 - suggestion merge reports scope and the recompute strip reaches a terminal outcome", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  const suggestion = page
    .getByRole("article", { name: /Gợi ý gộp/ })
    .filter({ hasText: "90%" })
    .first();
  await expect(suggestion).toBeVisible();
  await suggestion.getByRole("button", { name: "Gộp hai vai trò" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const scope = dialog.getByTestId("correction-scope");
  await expect(scope).toBeVisible();
  await expect(scope.getByTestId("scope-merge-role-count")).toContainText("2");
  await expect(scope.getByTestId("scope-merge-suggestion-count")).toContainText("1");

  await dialog.getByRole("button", { name: "Gộp vai trò" }).click();
  const strip = page.getByTestId("recompute-strip");
  await expect(strip).toBeVisible({ timeout: 30_000 });
  // Terminal outcome is asserted via the semantic state attribute, not copy.
  await expect
    .poll(async () => strip.getAttribute("data-state"), { timeout: 60_000 })
    .toBe("completed");

  // The merged pair's source is superseded and traceable.
  await expect(page.getByText("Vai trò đã thay thế (1)", { exact: false })).toBeVisible();
});

test("t04 - split through correction shows scope and restores the original role", async ({
  page,
}) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Pair X");
  const detail = roleDetail(page, "Pair X");
  await detail.getByRole("button", { name: "Tách vai trò đã gộp" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("correction-scope")).toBeVisible();
  await dialog.getByRole("button", { name: "Tách vai trò" }).click();

  // State proof: the original role is restored as a new suggested role.
  await expect
    .poll(
      async () =>
        (await listRoles(state.videoItemId)).filter(
          (r) => r.name === "Pair X" && r.status === "suggested" && r.id !== state.pairTarget,
        ).length,
      { timeout: 30_000 },
    )
    .toBe(1);
});

test("t05 - escape on the correction dialog performs ZERO mutations", async ({ page }) => {
  const before = await listRoles(state.videoItemId);
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "Shift B");
  const detail = roleDetail(page, "Shift B");
  await detail.getByRole("button", { name: "Chuyển vai trò" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  const after = await listRoles(state.videoItemId);
  expect(after.map((r) => `${r.id}:${r.occurrences.length}`)).toEqual(
    before.map((r) => `${r.id}:${r.occurrences.length}`),
  );
});

test("t06 - corrected media becomes canonical: regenerated media after completion AND after reload", async ({
  page,
}) => {
  // The REAL DISCOVER roles (deterministic provider) each carry exactly one
  // occurrence + durable media associations.  Moving the SOURCE role's only
  // evidence to the TARGET role empties the source — so:
  //   - the TARGET resolves regenerated media (recomputed geometry),
  //   - the EMPTIED source resolves NO current media (never stale),
  //   - the old artifacts stay servable (auditable, not deleted).
  const roles = await listRoles(state.videoItemId);
  const s1 = roles.find((r) => r.name === "subject_01");
  const s2 = roles.find((r) => r.name === "subject_02");
  expect(s1, "subject_01 DISCOVER role").toBeTruthy();
  expect(s2, "subject_02 DISCOVER role").toBeTruthy();
  expect(s1!.occurrences.length).toBe(1);
  const before = await mediaOf(state.videoItemId, [s1!.id, s2!.id]);
  expect(before.get(s1!.id)?.length ?? 0).toBeGreaterThan(0);
  const oldSourceJob = before.get(s1!.id)![0].source_job_id;
  const oldArtifact = before.get(s1!.id)![0].artifact_id;

  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expandRole(page, "subject_01");
  const detail = roleDetail(page, "subject_01");
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

  // Media tiles live inside the EXPANDED detail cards.  The emptied source
  // (subject_01) honestly shows "no current media"; the target (subject_02)
  // shows the REGENERATED current media.
  await expect(page.getByTestId("no-current-media").first()).toBeVisible({ timeout: 30_000 });
  await expandRole(page, "subject_02");
  const targetDetail = page.getByTestId("role-detail").filter({ hasText: "subject_02" }).first();
  await expect(targetDetail.getByTestId("media-regenerated").first()).toBeVisible({
    timeout: 30_000,
  });
  await page.screenshot({ path: `${SHOT_DIR}/desktop-regenerated-media.png`, fullPage: false });

  // App/browser RESTART: a fresh page load still resolves the regenerated
  // media (backend-persisted, never browser storage).  The emptied source
  // must also still show the honest no-current-media state after the reload.
  await page.reload();
  await expandRole(page, "subject_01");
  await expect(page.getByTestId("no-current-media").first()).toBeVisible({ timeout: 30_000 });
  await expandRole(page, "subject_02");
  await expect(
    page.getByTestId("role-detail").filter({ hasText: "subject_02" }).first()
      .getByTestId("media-regenerated").first(),
  ).toBeVisible({ timeout: 30_000 });

  // API: the TARGET resolves regenerated (recompute-job) media; the EMPTIED
  // source resolves NO current media; the replaced old artifact stays
  // servable via its DISCOVER job (auditable, never deleted).
  const after = await mediaOf(state.videoItemId, [s1!.id, s2!.id]);
  const sourceMedia = after.get(s1!.id) ?? [];
  expect(sourceMedia.length).toBe(0); // not current
  const targetMedia = after.get(s2!.id) ?? [];
  expect(targetMedia.length).toBeGreaterThan(0);
  for (const m of targetMedia) {
    expect(m.source_job_id).not.toBe(oldSourceJob);
    expect(await contentStatus(m.source_job_id, m.artifact_id)).toBe(200);
  }
  expect(await contentStatus(oldSourceJob, oldArtifact)).toBe(200);
});
