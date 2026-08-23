import { test, expect, type Page } from "@playwright/test";

/**
 * S08-T04-C1 Object Gallery — interaction suite (correction round, finding E)
 * against the REAL isolated QA backend (localhost:8025), deterministic
 * provider selected via env.
 *
 * Finding E coverage:
 *   - media/grouping by STABLE role ids only (backend newest-valid media via
 *     object_role_artifact associations — no name matching),
 *   - REAL bytes via the contained content endpoint; tests assert the
 *     DECODED naturalWidth/naturalHeight of the actual image,
 *   - fresh browser with EMPTY sessionStorage restores roles/extraction/
 *     media from the backend (/extraction/current — no storage as truth),
 *   - source replacement never shows previous-generation media,
 *   - explicit project video selector (multi-video projects),
 *   - confidence/review thresholds from backend /grouping/policy (the
 *     legacy 0.65 hardcode would flag subject_01@0.62; the backend 0.35
 *     must NOT — asserted below),
 *   - pagination / infinite-load of role summaries + lazy detail on expand,
 *   - correction media refresh (merge → recompute → newest-valid media)
 *     durable across app/browser restart.
 *
 * Curation scenarios use DEDICATED roles so no test depends on another's
 * mutated state: same-name "Hero" roles (deterministic grouping pairs) and a
 * distinct-name "Warrior" pair for manual merge / 409 / split.
 */
import {
  createOccurrence,
  createRole,
  generateSuggestions,
  getCurrentExtractionApi,
  getGroupingPolicyApi,
  getRole,
  getRoleWithStatus,
  listAllSuggestions,
  listRoles,
  listRolesGeneration,
  listRolesMeta,
  listRolesPaged,
  mergeRolesApi,
  postAnalyze,
  runExtraction,
  sceneIdsFromJob,
  setupProject,
  setupProjectWithVideo,
  uploadVideo,
  VIDEO_PATH,
  VIDEO_PATH_2,
  waitChainCompleted,
} from "./s08-t04-helpers";

test.describe.configure({ mode: "serial" });

const state: {
  projectId: string;
  videoItemId: string;
  sourceSha: string;
  extractionJobId: string;
  scenes: string[];
  /** Dedicated curation roles (real T01 rows on real scene ids). */
  hero2: string;
  hero3: string;
  warriorA: string;
  warriorB: string;
} = {
  projectId: "",
  videoItemId: "",
  sourceSha: "",
  extractionJobId: "",
  scenes: [],
  hero2: "",
  hero3: "",
  warriorA: "",
  warriorB: "",
};

test.beforeAll(async () => {
  const proj = await setupProject("t04-c1-gallery");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  state.sourceSha = proj.sourceSha;
  const { jobId, job } = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  state.extractionJobId = jobId;
  state.scenes = sceneIdsFromJob(job);
  if (state.scenes.length < 2) throw new Error("expected >=2 real scenes");
  const s0 = state.scenes[0];
  const s1 = state.scenes[1];

  // Same-name "Hero" roles with matching spatial footprints -> deterministic
  // grouping suggestions (role fingerprint by id, not by name uniqueness).
  const hero1 = await createRole("Hero", proj.projectId, proj.videoItemId);
  await createOccurrence(hero1.id, s0, 0, 0, { x: 10, y: 10, width: 40, height: 40 }, 0.9);
  const hero2 = await createRole("Hero", proj.projectId, proj.videoItemId);
  await createOccurrence(hero2.id, s1, 5, 1000, { x: 12, y: 12, width: 40, height: 40 }, 0.9);
  const hero3 = await createRole("Hero", proj.projectId, proj.videoItemId);
  await createOccurrence(hero3.id, s0, 8, 2000, { x: 14, y: 14, width: 40, height: 40 }, 0.8);
  state.hero2 = hero2.id;
  state.hero3 = hero3.id;

  // Distinct-name pair for the manual merge / external-writer 409 / split flows.
  const warriorA = await createRole("WarriorA", proj.projectId, proj.videoItemId);
  await createOccurrence(warriorA.id, s0, 10, 3000, { x: 50, y: 50, width: 30, height: 30 }, 0.95);
  const warriorB = await createRole("WarriorB", proj.projectId, proj.videoItemId);
  await createOccurrence(warriorB.id, s1, 14, 4000, { x: 52, y: 52, width: 30, height: 30 }, 0.9);
  state.warriorA = warriorA.id;
  state.warriorB = warriorB.id;
});

function galleryUrl(projectId: string, videoItemId?: string): string {
  return `/object-gallery?project=${projectId}${
    videoItemId ? `&video=${encodeURIComponent(videoItemId)}` : ""
  }`;
}

/** Expand a role summary card (lazy detail) and wait for the detail card. */
async function expandRole(page: Page, roleName: string): Promise<void> {
  await page
    .getByRole("button", { name: `Xem chi tiết vai trò ${roleName}` })
    .first()
    .click();
  await page.getByTestId("role-detail").first().waitFor({ state: "visible" });
}

test("01 empty state + start extraction (real durable job)", async ({ page }) => {
  const proj = await setupProject("t04-c1-empty");
  await page.goto(galleryUrl(proj.projectId));
  await expect(
    page.getByRole("heading", { name: "Chưa có đối tượng nào" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Phát hiện đối tượng" }).click();
  // Real job progress strip appears, then roles land from the backend.
  await expect(page.getByLabel("Công việc phát hiện đối tượng")).toBeVisible();
  await expect(
    page.getByRole("article", { name: /^Vai trò subject_01$/ }),
  ).toBeVisible({ timeout: 120_000 });
});

test("02 roles + extraction strip reflect REAL backend state", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  const strip = page.getByLabel("Công việc phát hiện đối tượng");
  await expect(strip).toBeVisible();
  await expect(strip.getByText("Hoàn tất")).toBeVisible();
  // Four deterministic candidates → four role cards (stable role ids).
  for (const name of ["subject_01", "subject_02", "subject_03", "subject_04"]) {
    await expect(
      page.getByRole("button", { name: `Xem chi tiết vai trò ${name}` }),
    ).toBeVisible();
  }
  // Honest generation provenance in the strip.
  await expect(strip.getByText("thế hệ 1")).toBeVisible();
  const job = await getCurrentExtractionApi(state.videoItemId, "1");
  expect(job?.job_id).toBe(state.extractionJobId);
});

test("03 media is REAL bytes — decoded naturalWidth/naturalHeight match", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  const role = (await listRoles(state.videoItemId)).find(
    (r) => r.media.length > 0 && r.media[0].width && r.media[0].height,
  );
  expect(role).toBeTruthy();
  const media = role!.media[0];
  await expandRole(page, role!.name);
  const img = page
    .getByTestId("role-detail")
    .first()
    .locator(`img[data-testid="media-${media.purpose}"]`);
  await expect(img).toBeVisible();
  // Wait for the REAL bytes to decode (naturalWidth becomes non-zero).
  await expect
    .poll(async () => img.evaluate((el: HTMLImageElement) => el.naturalWidth))
    .toBeGreaterThan(0);
  const dims = await img.evaluate((el: HTMLImageElement) => ({
    naturalWidth: el.naturalWidth,
    naturalHeight: el.naturalHeight,
  }));
  expect(dims.naturalWidth).toBe(media.width);
  expect(dims.naturalHeight).toBe(media.height);
  // The src is the contained content endpoint of the CURRENT media job.
  const src = await img.getAttribute("src");
  expect(src).toContain(`/extraction/${media.source_job_id}/artifacts/${media.artifact_id}/content`);
});

test("04 fresh browser with EMPTY sessionStorage restores from the backend", async ({
  browser,
}) => {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(galleryUrl(state.projectId));
    // No storage seeding — the backend /extraction/current is the authority.
    for (const name of ["subject_01", "subject_02", "subject_03", "subject_04"]) {
      await expect(
        page.getByRole("button", { name: `Xem chi tiết vai trò ${name}` }),
      ).toBeVisible();
    }
    await expect(page.getByLabel("Công việc phát hiện đối tượng").getByText("Hoàn tất")).toBeVisible();
    // Media renders for a role WITHOUT any client-stored extraction id.
    await expandRole(page, "subject_01");
    await expect(
      page.getByTestId("role-detail").first().locator("img[data-testid^='media-']").first(),
    ).toBeVisible();
    const storage = await page.evaluate(() => ({
      ss: sessionStorage.length,
      // The GALLERY must never persist/resume via browser storage — the app's
      // own namespace stays empty (the remaining entry is the Next dev client).
      appKeys: Object.keys(sessionStorage).filter((k) => k.startsWith("mf-") || k.includes("gallery")),
    }));
    expect(storage.appKeys).toEqual([]);
  } finally {
    await context.close();
  }
});

test("05 confidence/review thresholds come from the BACKEND policy", async ({ page }) => {
  const policy = await getGroupingPolicyApi();
  expect(policy.review_threshold).toBeGreaterThan(0);
  await page.goto(galleryUrl(state.projectId));
  // The policy line renders the backend value (35% in the QA calibration).
  await expect(
    page.getByText(`Ngưỡng duyệt gộp: ${Math.round(policy.review_threshold * 100)}%`),
  ).toBeVisible();
  await expect(page.getByText(/hiệu chuẩn .*\(chính sách từ máy chủ/)).toBeVisible();
  // Semantics come from the backend too.
  await page.getByText("Ý nghĩa các mức độ tin cậy (chính sách gộp từ máy chủ)").click();
  await expect(page.getByText(policy.confidence_semantics[0])).toBeVisible();
  // subject_01@0.62: ABOVE the backend 0.35 but BELOW the legacy hardcoded
  // 0.65 — no low-confidence badge proves the hardcode is gone.
  await expandRole(page, "subject_01");
  const detail = page.getByTestId("role-detail").first();
  await expect(detail.getByText("Độ tin cậy trung bình")).toBeVisible();
  await expect(detail.getByText("Độ tin cậy thấp")).toHaveCount(0);
});

test("06 role summaries paginate; heavy detail loads lazily on expand", async ({ page }) => {
  const proj = await setupProject("t04-c1-pagination");
  const { job } = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const scenes = sceneIdsFromJob(job);
  for (let i = 0; i < 40; i++) {
    const role = await createRole(`PageRole${String(i).padStart(2, "0")}`, proj.projectId, proj.videoItemId);
    await createOccurrence(
      role.id,
      scenes[i % scenes.length],
      i,
      i * 1000,
      { x: 10, y: 10, width: 40, height: 40 },
      0.9,
    );
  }
  const paged = await listRolesPaged(proj.videoItemId, 16, 0);
  expect(paged.total).toBeGreaterThanOrEqual(44); // 4 extraction + 40 seeded
  await page.goto(galleryUrl(proj.projectId));
  // Page 1: 16 summaries only — occurrence DETAIL is NOT rendered eagerly.
  const summaryButtons = page.getByRole("button", { name: /^Xem chi tiết vai trò PageRole/ });
  await expect(summaryButtons).toHaveCount(16);
  // No occurrence rows before expand (lazy contract).
  await expect(page.getByTestId("role-detail")).toHaveCount(0);
  const loadMore = page.getByRole("button", { name: "Tải thêm vai trò" });
  // Infinite load: page 2 (32 of 44) — the control and counter stay honest.
  await loadMore.click();
  await expect(summaryButtons).toHaveCount(32);
  await expect(page.getByText(/Đã hiển thị 32\/44/)).toBeVisible();
  await expect(loadMore).toBeVisible();
  // Page 3: everything loaded — the control and counter disappear together.
  await loadMore.click();
  await expect(summaryButtons).toHaveCount(40);
  await expect(loadMore).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Vai trò của video (44)" })).toBeVisible();
  // Expand now fetches the authoritative detail (lazy) and renders it.
  const detailRequest = page.waitForRequest(
    (req) => req.url().includes("/api/v2/object-intelligence/roles/") && !req.url().includes("?"),
  );
  await page.getByRole("button", { name: /^Xem chi tiết vai trò PageRole00$/ }).click();
  await detailRequest;
  await expect(page.getByTestId("role-detail").first()).toBeVisible();
  await expect(page.getByTestId("role-detail").first().getByText(/Lý do tin cậy/)).toBeVisible();
});

test("07 explicit video selector — per-video isolation (multi-video project)", async ({ page }) => {
  // Same project, two real videos (source replacement) → two video items
  // with fully isolated gallery data.
  const proj = await setupProjectWithVideo("t04-c1-multivideo", VIDEO_PATH);
  const { jobId: jobA } = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const videoA = proj.videoItemId;
  const videoAroles = await listRoles(videoA);
  expect(videoAroles.length).toBe(4);

  // Source replacement: a DIFFERENT real video in the SAME project.
  await uploadVideo(proj.projectId, VIDEO_PATH_2);
  await postAnalyze(proj.projectId);
  const chain = await waitChainCompleted(proj.projectId);
  expect(chain.video_item_id).not.toBe(videoA);
  const videoB = chain.video_item_id!;
  const { jobId: jobB } = await runExtraction(proj.projectId, videoB, chain.source_sha256 as string);
  const videoBroles = await listRoles(videoB);
  expect(videoBroles.length).toBe(1);

  // The selector control renders (explicit video selection surface).
  await page.goto(galleryUrl(proj.projectId, videoB));
  const selector = page.getByLabel("Chọn video của dự án");
  await expect(selector).toBeVisible();

  // Backend truth per video: B's current extraction is jobB — NEVER jobA.
  expect((await getCurrentExtractionApi(videoB, chain.generation as string))?.job_id).toBe(jobB);
  expect((await getCurrentExtractionApi(videoA, "1"))?.job_id).toBe(jobA);

  // B's role media comes from B's generation/job — no previous-generation media.
  const bRole = videoBroles[0];
  expect(bRole.media.length).toBeGreaterThan(0);
  for (const m of bRole.media) expect(m.source_job_id).toBe(jobB);

  // Explicit selection by stable video_item_id switches the whole gallery.
  await page.goto(galleryUrl(proj.projectId, videoA));
  await expect(page.getByRole("button", { name: "Xem chi tiết vai trò subject_02" })).toBeVisible();
  await page.goto(galleryUrl(proj.projectId, videoB));
  await expect(page.getByRole("button", { name: "Xem chi tiết vai trò subject_01" })).toBeVisible();
  // Only ONE role for video B — no leakage from video A.
  await expect(page.getByRole("button", { name: "Xem chi tiết vai trò subject_02" })).toHaveCount(0);
});

test("08 confirm a role (explicit dialog, audit operation)", async ({ page }) => {
  const proj = await setupProject("t04-c1-confirm");
  const { job } = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const scenes = sceneIdsFromJob(job);
  const role = await createRole("Confirmable", proj.projectId, proj.videoItemId);
  await createOccurrence(role.id, scenes[0], 0, 0, { x: 9, y: 9, width: 30, height: 30 }, 0.92);
  await page.goto(galleryUrl(proj.projectId));
  await expandRole(page, "Confirmable");
  await page.getByRole("button", { name: "Xác nhận vai trò" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Xác nhận vai trò" }).click();
  await expect(page.getByText(/Đã xác nhận vai trò "Confirmable"/).last()).toBeVisible();
  const fresh = await getRole(role.id);
  expect(fresh.status).toBe("confirmed");
});

test("09 suggestion merge runs through the correction workflow (scope preview)", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  await page.getByRole("button", { name: "Tạo gợi ý gộp" }).click();
  // Same-name Hero roles produce deterministic suggestions.
  const suggestionCard = page.getByLabel(/^Gợi ý gộp Hero và Hero/).first();
  await expect(suggestionCard).toBeVisible({ timeout: 30_000 });
  await suggestionCard.getByRole("button", { name: "Gộp hai vai trò" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // Pre-confirmation impacted-scope report from the REAL preview endpoint.
  await expect(dialog.getByTestId("correction-scope")).toBeVisible();
  await expect(dialog.getByText(/Vai trò bị ảnh hưởng/)).toBeVisible();
  await dialog.getByRole("button", { name: "Gộp vai trò" }).click();
  await expect(page.getByText(/Đã gộp 1 vai trò vào/).last()).toBeVisible();
  const suggestions = await listAllSuggestions(state.videoItemId);
  expect(suggestions.some((s) => s.status === "applied")).toBe(true);
});

test("10 manual merge + stale revision surfaces the real 409 conflict", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  await expandRole(page, "WarriorA");
  await page.getByTestId("role-detail").first().getByLabel("Vai trò đích").check();
  await expandRole(page, "WarriorB");
  await page.getByTestId("role-detail").last().getByLabel("Nguồn gộp").check();
  await page.getByRole("button", { name: "Gộp các vai trò đã chọn" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // External writer bumps the target revision between dialog-open and confirm.
  const target = (await listRoles(state.videoItemId)).find((r) => r.id === state.warriorA)!;
  const source = (await listRoles(state.videoItemId)).find((r) => r.id === state.warriorB)!;
  await mergeRolesApi(target.id, state.videoItemId, target.revision, [source.id]);
  await dialog.getByRole("button", { name: "Gộp vai trò" }).click();
  await expect(page.getByText(/xung đột phiên bản/).last()).toBeVisible();
  await expect(page.getByText("Dữ liệu đã thay đổi ở nơi khác").last()).toBeVisible();
});

test("11 split a merged role (explicit original selection)", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  // WarriorB was merged into WarriorA by the external writer in test 10.
  const target = (await listRoles(state.videoItemId)).find((r) => r.id === state.warriorA)!;
  expect(target.occurrences.length).toBeGreaterThan(1);
  await expandRole(page, target.name);
  await page.getByRole("button", { name: "Tách vai trò đã gộp" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio").first().check();
  await dialog.getByRole("button", { name: "Tách vai trò" }).click();
  await expect(page.getByText(/Đã tách vai trò/).last()).toBeVisible();
});

test("12 dismiss a suggestion (explicit rejection)", async ({ page }) => {
  await page.goto(galleryUrl(state.projectId));
  await page.getByRole("button", { name: "Tạo gợi ý gộp" }).click();
  const suggestionCard = page.getByLabel(/^Gợi ý gộp .* và .*/).first();
  await expect(suggestionCard).toBeVisible({ timeout: 30_000 });
  await suggestionCard.getByRole("button", { name: "Từ chối gợi ý" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Từ chối gợi ý" }).click();
  await expect(page.getByText("Đã từ chối gợi ý gộp").last()).toBeVisible();
  const suggestions = await listAllSuggestions(state.videoItemId);
  expect(suggestions.some((s) => s.status === "dismissed")).toBe(true);
});

test("13 correction media refresh — newest-valid media durable across restart", async ({
  page,
  browser,
}) => {
  // Isolated project: extraction roles carry CURRENT media; a merge correction
  // triggers recompute which re-publishes + supersedes artifact associations.
  const proj = await setupProject("t04-c1-correct");
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const roles = await listRoles(proj.videoItemId);
  const candidates = roles.filter((r) => r.status === "suggested" && r.media.length > 0);
  expect(candidates.length).toBeGreaterThanOrEqual(2);
  const target = candidates[0];
  const source = candidates[1];
  const oldMediaJob = target.media[0].source_job_id;

  // UI merge correction (recompute_needed) with real impacted-scope preview.
  await page.goto(galleryUrl(proj.projectId));
  await expandRole(page, target.name);
  await page.getByTestId("role-detail").first().getByLabel("Vai trò đích").check();
  await expandRole(page, source.name);
  await page.getByTestId("role-detail").last().getByLabel("Nguồn gộp").check();
  await page.getByRole("button", { name: "Gộp các vai trò đã chọn" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("correction-scope")).toBeVisible();
  await expect(dialog.getByText(/Ảnh mẫu\/mặt nạ cần tạo lại/)).toBeVisible();
  await dialog.getByRole("button", { name: "Gộp vai trò" }).click();

  // The durable recompute job runs; its completion refreshes the gallery.
  await expect(page.getByTestId("recompute-strip")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("recompute-strip").getByText("Hoàn tất")).toBeVisible({
    timeout: 120_000,
  });

  // The surviving target's CURRENT media now comes from the recompute job.
  const refreshed = await getRole(target.id);
  expect(refreshed.media.length).toBeGreaterThan(0);
  const newMediaJob = refreshed.media[0].source_job_id;
  expect(newMediaJob).not.toBe(oldMediaJob);

  // FRESH browser (no session storage, no cached state): the gallery still
  // resolves the newest-valid media after correction + restart.
  const context = await browser.newContext();
  try {
    const fresh = await context.newPage();
    await fresh.goto(galleryUrl(proj.projectId));
    await expandRole(fresh, refreshed.name);
    const img = fresh.getByTestId("role-detail").first().locator("img[data-testid^='media-']").first();
    await expect(img).toBeVisible();
    const src = await img.getAttribute("src");
    expect(src).toContain(newMediaJob);
    expect(src).not.toContain(oldMediaJob);
    // The recompute provenance is shown honestly.
    await expect(
      fresh.getByTestId("role-detail").first().getByText("đã tính lại sau chỉnh sửa").first(),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});


test("14 C2 generation isolation — stale generation roles/suggestions never render or act", async ({
  page,
}) => {
  // Real project + real gen-1 extraction; current generation is backend-authoritative.
  const proj = await setupProject("t04-c2-stale");
  const { job } = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const scenes = sceneIdsFromJob(job);
  const meta = await listRolesMeta(proj.videoItemId);
  expect(meta.scope).toBe("current");
  expect(meta.current_generation).toBe("1");
  expect(meta.total).toBe(4);

  // A STALE-generation role is created through the REAL T01 API (generation 2
  // while the backend current is 1).
  const stale = await createRole("StaleGen2", proj.projectId, proj.videoItemId, "2");
  await createOccurrence(stale.id, scenes[0], 0, 0, { x: 5, y: 5, width: 30, height: 30 }, 0.9);

  // Backend current-default list EXCLUDES the stale role; explicit gen-2 view
  // still reaches it as historical; default detail 404s (fail closed).
  const after = await listRolesMeta(proj.videoItemId);
  expect(after.roles.some((r) => r.id === stale.id)).toBe(false);
  const hist = await listRolesGeneration(proj.videoItemId, "2");
  expect(hist.scope).toBe("historical");
  expect(hist.roles.some((r) => r.id === stale.id)).toBe(true);
  expect((await getRoleWithStatus(stale.id)).status).toBe(404);
  expect((await getRoleWithStatus(stale.id, "2")).status).toBe(200);

  // Suggestions are CURRENT-generation only: generate for gen "2" fails closed,
  // generate for the current gen "1" succeeds and lists only pending cur.
  await expect(
    generateSuggestions(proj.videoItemId, "2"),
  ).rejects.toThrow(/API 4\d\d/);
  await generateSuggestions(proj.videoItemId, "1");

  // UI: only the 4 CURRENT roles render — the stale role has no card and thus
  // ZERO action controls (merge/split/confirm/correct require a role row).
  await page.goto(galleryUrl(proj.projectId));
  for (const name of ["subject_01", "subject_02", "subject_03", "subject_04"]) {
    await expect(page.getByRole("button", { name: `Xem chi tiết vai trò ${name}` })).toBeVisible();
  }
  await expect(
    page.getByRole("button", { name: "Xem chi tiết vai trò StaleGen2" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Vai trò của video").getByRole("article")).toHaveCount(4);
  // The header displays the BACKEND-authoritative current generation.
  await expect(
    page.getByText("Thế hệ nguồn hiện tại (máy chủ): 1"),
  ).toBeVisible();
});

test("15 C2 source replacement — generation-1 data never leaks; RQ slices are per video+generation", async ({
  page,
}) => {
  // Same project, two real videos (source replacement): video A (4 roles) is
  // a DIFFERENT source generation unit than video B (1 role).
  const proj = await setupProjectWithVideo("t04-c2-replace", VIDEO_PATH);
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const videoA = proj.videoItemId;
  await uploadVideo(proj.projectId, VIDEO_PATH_2);
  await postAnalyze(proj.projectId);
  const chain = await waitChainCompleted(proj.projectId);
  const videoB = chain.video_item_id!;
  await runExtraction(proj.projectId, videoB, chain.source_sha256 as string);
  expect(videoB).not.toBe(videoA);

  // Backend authority: each video item has its OWN current generation; video B's
  // roles contain NONE of video A's generation-1 data.
  expect((await listRolesMeta(videoA)).current_generation).toBe("1");
  expect((await listRolesMeta(videoB)).current_generation).toBe("1");
  expect((await listRoles(videoB)).length).toBe(1);

  // RQ cache isolation: navigating A -> B fires DISTINCT roles requests (the
  // React Query key embeds video_item_id + generation), so no stale slice from
  // A is ever reused for B.
  const reqA = page.waitForRequest((r) =>
    r.url().includes("/api/v2/object-intelligence/roles") && r.url().includes(encodeURIComponent(videoA)),
  );
  await page.goto(galleryUrl(proj.projectId, videoA));
  await reqA;
  await expect(page.getByRole("heading", { name: "Vai trò của video (4)" })).toBeVisible();

  const reqB = page.waitForRequest((r) =>
    r.url().includes("/api/v2/object-intelligence/roles") && r.url().includes(encodeURIComponent(videoB)),
  );
  await page.goto(galleryUrl(proj.projectId, videoB));
  await reqB;
  await expect(page.getByRole("heading", { name: "Vai trò của video (1)" })).toBeVisible();
  // Generation-1 (video A) roles NEVER appear in the generation-2 gallery.
  await expect(page.getByRole("button", { name: "Xem chi tiết vai trò subject_02" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Xem chi tiết vai trò subject_01" })).toBeVisible();
  // Header shows the backend current generation of the SELECTED video.
  await expect(page.getByText(/Thế hệ nguồn hiện tại \(máy chủ\): 1/)).toBeVisible();
});
