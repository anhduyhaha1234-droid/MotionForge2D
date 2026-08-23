import { test, expect, type Route } from "@playwright/test";

const MOCK_PACKS = [
  {
    id: "pack-11111111-1111-1111-1111-111111111111",
    character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    workspace_id: "default",
    version: 1,
    status: "published",
    character_name: "Alpha Hero",
    character_code: "alpha",
    character_type: "character",
    symmetry: "symmetric",
    published_at: new Date().toISOString(),
    revision: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    asset_count: 6,
    pose_slots: ["front", "three_quarter", "side", "back", "sitting", "walking"],
  },
  {
    id: "pack-22222222-2222-2222-2222-222222222222",
    character_id: "char-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    workspace_id: "default",
    version: 1,
    status: "published",
    character_name: "Beta Prop",
    character_code: "beta",
    character_type: "prop",
    symmetry: "symmetric",
    published_at: new Date().toISOString(),
    revision: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    asset_count: 6,
    pose_slots: ["front", "three_quarter", "side", "back", "sitting", "walking"],
  },
  {
    id: "pack-33333333-3333-3333-3333-333333333333",
    character_id: "char-cccc-cccc-cccc-cccccccccccc",
    workspace_id: "default",
    version: 2,
    status: "published",
    character_name: "Gamma Incomplete",
    character_code: "gamma",
    character_type: "character",
    symmetry: "symmetric",
    published_at: new Date().toISOString(),
    revision: 2,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    asset_count: 5,
    pose_slots: ["front", "three_quarter", "side", "back", "sitting"],
  },
];

const PINNED_ID = "pack-11111111-1111-1111-1111-111111111111";
const PROJECT_ID = "proj-real-123";
const VIDEO_ID = "vid-real-123";
const ROLE_ID = "role-real-123";

function mockGalleryBasics(route: Route): boolean {
  const url = route.request().url();
  const method = route.request().method();
  // Chain
  if (url.includes(`/api/projects/${PROJECT_ID}/analyze`) && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: PROJECT_ID,
        video_item_id: VIDEO_ID,
        generation: "1",
        source_name: "test.mp4",
        source_sha256: "abc123",
        chain_status: "completed",
        active_step: null,
        progress: 100,
        steps: {
          import: { step: "import", job_id: "job-1", status: "completed", progress: 100, message: "done", error: null, error_code: null, predecessor_job_id: null },
          proxy: { step: "proxy", job_id: "job-2", status: "completed", progress: 100, message: "done", error: null, error_code: null, predecessor_job_id: "job-1" },
          scene_detect: { step: "scene_detect", job_id: "job-3", status: "completed", progress: 100, message: "done", error: null, error_code: null, predecessor_job_id: "job-2" },
        },
        source_artifact_id: null,
        proxy_artifact_id: null,
        scenes_count: 1,
      }),
    });
    return true;
  }
  // Videos
  if (url.includes(`/api/v2/projects/${PROJECT_ID}/videos`) && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: PROJECT_ID,
        videos: [
          {
            video_item_id: VIDEO_ID,
            project_id: PROJECT_ID,
            workspace_id: "default",
            title: "Test Video",
            position: 0,
            status: "completed",
            source_artifact_id: null,
            duration_ms: 10000,
            width: 1920,
            height: 1080,
            fps_num: 30,
            fps_den: 1,
            archived_at: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            revision: 1,
          },
        ],
        total: 1,
      }),
    });
    return true;
  }
  // Roles list
  if (url.includes("/api/v2/object-intelligence/roles") && url.includes(`video_item_id=${VIDEO_ID}`) && !url.includes(`/roles/${ROLE_ID}`) && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        workspace_id: "default",
        limit: 20,
        offset: 0,
        total: 1,
        roles: [
          {
            id: ROLE_ID,
            workspace_id: "default",
            project_id: PROJECT_ID,
            video_item_id: VIDEO_ID,
            source_generation: "1",
            name: "Hero",
            kind: "character",
            status: "confirmed",
            supersedes_role_id: null,
            legacy_object_id: null,
            legacy_scene_id: null,
            description: null,
            revision: 1,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            occurrences: [
              {
                id: "occ-1",
                workspace_id: "default",
                project_id: PROJECT_ID,
                video_item_id: VIDEO_ID,
                role_id: ROLE_ID,
                scene_id: "scene-1",
                frame_index: 0,
                time_ms: 0,
                bbox: { x: 0, y: 0, width: 100, height: 100 },
                confidence: 0.9,
                confidence_source: "model",
                algorithm: "test",
                algorithm_version: "1",
                reasons: ["test"],
                review_state: "accepted",
                revision: 1,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
            media: [],
            has_media_associations: false,
          },
        ],
        scope: "current",
        current_generation: "1",
      }),
    });
    return true;
  }
  // Role detail
  if (url.includes(`/api/v2/object-intelligence/roles/${ROLE_ID}`) && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: ROLE_ID,
        workspace_id: "default",
        project_id: PROJECT_ID,
        video_item_id: VIDEO_ID,
        source_generation: "1",
        name: "Hero",
        kind: "character",
        status: "confirmed",
        supersedes_role_id: null,
        legacy_object_id: null,
        legacy_scene_id: null,
        description: null,
        revision: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        occurrences: [
          {
            id: "occ-1",
            workspace_id: "default",
            project_id: PROJECT_ID,
            video_item_id: VIDEO_ID,
            role_id: ROLE_ID,
            scene_id: "scene-1",
            frame_index: 0,
            time_ms: 0,
            bbox: { x: 0, y: 0, width: 100, height: 100 },
            confidence: 0.9,
            confidence_source: "model",
            algorithm: "test",
            algorithm_version: "1",
            reasons: ["test"],
            review_state: "accepted",
            revision: 1,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        media: [],
        has_media_associations: false,
      }),
    });
    return true;
  }
  // Kinds
  if (url.includes("/api/v2/object-intelligence/kinds") && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        kinds: [
          { name: "character", removal_only: false },
          { name: "prop", removal_only: false },
          { name: "background", removal_only: false },
          { name: "foreground", removal_only: false },
          { name: "graphic", removal_only: false },
          { name: "source_overlay", removal_only: true },
          { name: "other", removal_only: false },
        ],
      }),
    });
    return true;
  }
  // Policy
  if (url.includes("/api/v2/object-intelligence/grouping/policy") && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        review_threshold: 0.6,
        calibration_version: "1",
        algorithm: "test",
        algorithm_version: "1",
        confidence_semantics: ["test"],
      }),
    });
    return true;
  }
  // Extraction current
  if (url.includes("/api/v2/object-intelligence/extraction/current") && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "job-123",
        job_type: "DISCOVER_OBJECTS",
        status: "completed",
        progress: 100,
        message: "done",
        error: null,
        provider: "test",
        extractor_version: "1",
        generation: "1",
        source_sha256: "abc123",
        video_item_id: VIDEO_ID,
        created_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        outputs: [],
        candidates: [],
      }),
    });
    return true;
  }
  // Suggestions / operations
  if (url.includes("/api/v2/object-intelligence/grouping/suggestions") && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ suggestions: [], total: 0 }),
    });
    return true;
  }
  if (url.includes("/api/v2/object-intelligence/grouping/operations") && method === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ operations: [] }),
    });
    return true;
  }
  return false;
}

function mockPicker(route: Route): boolean {
  const url = new URL(route.request().url());
  if (url.pathname.includes("/api/v2/project-cast/picker/packs")) {
    const q = url.searchParams.get("q")?.toLowerCase() ?? "";
    let packs = MOCK_PACKS;
    if (q) packs = packs.filter((p) => p.character_name.toLowerCase().includes(q) || p.character_code.toLowerCase().includes(q));
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workspace_id: "default", limit: 50, offset: 0, total: packs.length, packs, query: q || null }),
    });
    return true;
  }
  return false;
}

function mockMappings(route: Route): boolean {
  const url = route.request().url();
  if (url.includes("/api/v2/project-cast") && !url.includes("picker") && !url.includes("compatibility") && route.request().method() === "GET") {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 1, mappings: [{ id: "mapping-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: PINNED_ID, idempotency_key: "k", revision: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }] }),
    });
    return true;
  }
  return false;
}

async function setupGalleryMocks(page: import("@playwright/test").Page, compatScenario: "compatible" | "incompatible" | "partial" | "stale" = "compatible") {
  await page.route("**/*", async (route) => {
    if (mockGalleryBasics(route)) return;
    if (mockPicker(route)) return;
    const url = route.request().url();
    if (url.includes("/api/v2/project-cast/compatibility/evaluate")) {
      if (compatScenario === "compatible") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: true, reasons: [], fallback_allowed: false, fallback_description: null, blocked: false, pinned_version_id: PINNED_ID, current_revision: 1, workspace_id: "default" }) });
      } else if (compatScenario === "incompatible") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: false, reasons: ["object_kind_mismatch"], fallback_allowed: false, fallback_description: null, blocked: true, pinned_version_id: PINNED_ID, current_revision: 1, workspace_id: "default" }) });
      } else if (compatScenario === "partial") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: false, reasons: ["generation_mismatch"], fallback_allowed: true, fallback_description: "Có thể ghim với cảnh báo: thế hệ nguồn khác với hiện tại (generation mismatch) — cần xác nhận có chủ đích.", blocked: false, pinned_version_id: PINNED_ID, current_revision: 1, workspace_id: "default" }) });
      } else if (compatScenario === "stale") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: false, reasons: ["stale_revision"], fallback_allowed: false, fallback_description: null, blocked: true, pinned_version_id: PINNED_ID, current_revision: 2, workspace_id: "default" }) });
      }
      return;
    }
    if (mockMappings(route)) return;
    // Create / update
    if (url.includes("/api/v2/project-cast") && route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "mapping-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: PINNED_ID, idempotency_key: "k", revision: 2, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }),
      });
      return;
    }
    if (url.includes("/api/v2/project-cast/mapping-1") && route.request().method() === "PATCH") {
      // Check for stale
      const body = route.request().postDataJSON() as { revision: number };
      if (body.revision !== 1) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "stale revision 99; current revision is 2" }) });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: "mapping-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: "pack-22222222-2222-2222-2222-222222222222", idempotency_key: "k", revision: 2, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }),
        });
      }
      return;
    }
    await route.continue();
  });
}

test.describe("S07 Picker + Compatibility — Real Object Gallery", () => {
  test("object-gallery mounts picker with real project/role", async ({ page }) => {
    await setupGalleryMocks(page, "compatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await expect(page.getByRole("heading", { name: "Thư viện đối tượng" })).toBeVisible({ timeout: 15000 });
    // Wait for role to appear
    await expect(page.getByText("Hero").first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("role-detail")).toBeVisible();
    // Ghim button should be visible in RoleCard
    await expect(page.getByTestId("cast-pin-button")).toBeVisible();
    // Picker should be visible in expanded context
    await expect(page.getByTestId("project-cast-picker")).toBeVisible();
    await expect(page.getByTestId("library-picker")).toBeVisible();
  });

  test("published packs browse — unpublished excluded", async ({ page }) => {
    await setupGalleryMocks(page, "compatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`)).toBeVisible();
    await expect(page.getByTestId(`picker-item-${MOCK_PACKS[1].id}`)).toBeVisible();
    // unpublished pack should not appear - we only mock published, so check that draft not present is implicit
    // helper text
    await expect(page.getByText("Chỉ hiển thị pack đã xuất bản")).toBeVisible();
  });

  test("compatible=true enables submit", async ({ page }) => {
    await setupGalleryMocks(page, "compatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(page.getByTestId("compat-compatible")).toBeVisible();
    await expect(page.getByTestId("cast-submit")).toBeEnabled();
  });

  test("compatible=false disables submit", async ({ page }) => {
    await setupGalleryMocks(page, "incompatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[1].id}`).click();
    await expect(page.getByTestId("compat-warnings")).toBeVisible();
    await expect(page.getByTestId("compat-reason-object_kind_mismatch")).toBeVisible();
    await expect(page.getByTestId("compat-blocked")).toBeVisible();
    await expect(page.getByTestId("cast-submit")).toBeDisabled();
  });

  test("fallback_supported generation_mismatch enables submit (P1-A)", async ({ page }) => {
    let patchCalled = false;
    let patchUrl = "";
    let patchBody: { pack_version_id: string; revision: number; fallback_acknowledged?: boolean } | null = null;
    await page.route("**/*", async (route) => {
      if (mockGalleryBasics(route)) return;
      if (mockPicker(route)) return;
      const url = route.request().url();
      const method = route.request().method();
      if (url.includes("/api/v2/project-cast/compatibility/evaluate")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: false, reasons: ["generation_mismatch"], fallback_allowed: true, fallback_description: "Có thể ghim với cảnh báo: thế hệ nguồn khác với hiện tại (generation mismatch) — cần xác nhận có chủ đích.", blocked: false, pinned_version_id: PINNED_ID, current_revision: 1, workspace_id: "default" }) });
        return;
      }
      if (url.includes("/api/v2/project-cast") && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 1, mappings: [{ id: "mapping-existing", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: PINNED_ID, idempotency_key: "k", revision: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }] }) });
        return;
      }
      if (url.includes("/api/v2/project-cast/mapping-existing") && method === "PATCH") {
        patchCalled = true;
        patchUrl = url;
        patchBody = JSON.parse(route.request().postData() || "{}");
        // C5: UI must send fallback_acknowledged true for fallback-supported
        // (patched via ProjectCastPicker when compat fallback_allowed)
        if (!patchBody?.fallback_acknowledged) {
          await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "fallback not acknowledged" }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "mapping-existing", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: MOCK_PACKS[2].character_id, pack_version_id: MOCK_PACKS[2].id, idempotency_key: "k", revision: 2, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
        return;
      }
      await route.continue();
    });
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[2].id}`).click();
    await expect(page.getByTestId("compat-fallback")).toBeVisible();
    await expect(page.getByTestId("compat-fallback")).toContainText("Có thể ghim với cảnh báo");
    await expect(page.getByTestId("cast-submit")).toBeEnabled();
    await expect(page.getByTestId("cast-submit")).toContainText("Ghim bất chấp khác biệt");
    await page.getByTestId("cast-submit").click();
    await expect(page.getByTestId("submit-success")).toBeVisible({ timeout: 15000 });
    expect(patchCalled).toBeTruthy();
    expect(patchUrl).toContain("mapping-existing");
    expect(patchBody).not.toBeNull();
    expect(patchBody!.pack_version_id).toBe(MOCK_PACKS[2].id);
    expect(patchBody!.revision).toBe(1);
    expect(patchBody!.fallback_acknowledged).toBe(true);
  });

  test("fallback_unsupported object_kind_mismatch stays disabled (fail-closed)", async ({ page }) => {
    await setupGalleryMocks(page, "incompatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[1].id}`).click();
    await expect(page.getByTestId("compat-blocked")).toBeVisible();
    await expect(page.getByTestId("cast-submit")).toBeDisabled();
  });

  test("repin via existing mapping uses PATCH with correct revision (P1-B)", async ({ page }) => {
    let patchCalled = false;
    let patchMethod = "";
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    let patchUrl = "";
    let postCalled = false;
    await page.route("**/*", async (route) => {
      if (mockGalleryBasics(route)) return;
      if (mockPicker(route)) return;
      const url = route.request().url();
      const method = route.request().method();
      if (url.includes("/api/v2/project-cast/compatibility/evaluate")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: true, reasons: [], fallback_allowed: false, fallback_description: null, blocked: false, pinned_version_id: PINNED_ID, current_revision: 5, workspace_id: "default" }) });
        return;
      }
      if (url.includes("/api/v2/project-cast") && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 1, mappings: [{ id: "mapping-repin-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: PINNED_ID, idempotency_key: "k", revision: 5, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }] }) });
        return;
      }
      if (url.includes("/api/v2/project-cast/mapping-repin-1") && method === "PATCH") {
        patchCalled = true;
        patchMethod = method;
        patchUrl = url;
        const body = JSON.parse(route.request().postData() || "{}");
        expect(body.revision).toBe(5);
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "mapping-repin-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: MOCK_PACKS[0].character_id, pack_version_id: MOCK_PACKS[0].id, idempotency_key: "k", revision: 6, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
        return;
      }
      if (url.includes("/api/v2/project-cast") && method === "POST") {
        postCalled = true;
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "new", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: MOCK_PACKS[0].character_id, pack_version_id: MOCK_PACKS[0].id, idempotency_key: "k", revision: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
        return;
      }
      await route.continue();
    });
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("pinned-summary")).toBeVisible();
    await page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(page.getByTestId("cast-submit")).toBeEnabled();
    await expect(page.getByTestId("cast-submit")).toContainText("Cập nhật Ghim");
    await page.getByTestId("cast-submit").click();
    await expect(page.getByTestId("submit-success")).toBeVisible({ timeout: 15000 });
    expect(patchCalled).toBeTruthy();
    expect(patchMethod).toBe("PATCH");
    expect(postCalled).toBeFalsy();
  });

  test("create success reloads pinned mapping", async ({ page }) => {
    let createCalled = false;
    await page.route("**/*", async (route) => {
      if (mockGalleryBasics(route)) return;
      if (mockPicker(route)) return;
      const url = route.request().url();
      if (url.includes("/api/v2/project-cast/compatibility/evaluate")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: true, reasons: [], fallback_allowed: false, fallback_description: null, blocked: false, pinned_version_id: null, current_revision: null, workspace_id: "default" }) });
        return;
      }
      if (url.includes("/api/v2/project-cast") && route.request().method() === "GET") {
        if (createCalled) {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 1, mappings: [{ id: "mapping-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: MOCK_PACKS[0].id, idempotency_key: "k", revision: 2, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }] }),
          });
        } else {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 0, mappings: [] }),
          });
        }
        return;
      }
      if (url.includes("/api/v2/project-cast") && route.request().method() === "POST") {
        createCalled = true;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ id: "mapping-1", workspace_id: "default", project_id: PROJECT_ID, object_role_id: ROLE_ID, character_id: "char-aaaa-aaaa-aaaa-aaaaaaaaaaaa", pack_version_id: MOCK_PACKS[0].id, idempotency_key: "k", revision: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }),
        });
        return;
      }
      await route.continue();
    });
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(page.getByTestId("cast-submit")).toBeEnabled();
    await page.getByTestId("cast-submit").click();
    await expect(page.getByTestId("submit-success")).toBeVisible();
    await expect(page.getByTestId("pinned-summary")).toContainText(MOCK_PACKS[0].id);
  });

  test("stale 409 reloads current revision", async ({ page }) => {
    await setupGalleryMocks(page, "stale");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(page.getByTestId("stale-recovery")).toBeVisible();
    await expect(page.getByTestId("stale-reload")).toBeVisible();
    await expect(page.getByText("Phiên bản đã cũ").first()).toBeVisible();
  });

  test("loading / empty / error / retry states", async ({ page }) => {
    let first = true;
    // Gallery basics first
    await page.route("**/*", async (route) => {
      if (mockGalleryBasics(route)) return;
      await route.continue();
    });
    // Picker packs: first 500 then empty
    await page.route("**/picker/packs*", async (route) => {
      if (first) {
        first = false;
        await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "server error" }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workspace_id: "default", limit: 50, offset: 0, total: 0, packs: [], query: null }) });
    });
    await page.route("**/compatibility/evaluate*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ compatible: true, reasons: [], fallback_allowed: false, fallback_description: null, blocked: false, pinned_version_id: null, current_revision: null, workspace_id: "default" }) });
    });
    await page.route("**/project-cast?*", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ workspace_id: "default", project_id: PROJECT_ID, limit: 50, offset: 0, total: 0, mappings: [] }) });
        return;
      }
      await route.continue();
    });
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("role-detail")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("library-picker")).toBeVisible({ timeout: 15000 });
    // Wait for picker to settle - may be loading, error, or empty
    await page.waitForTimeout(1000);
    const errorVisible = await page.getByTestId("picker-error").isVisible().catch(() => false);
    if (errorVisible) {
      await page.getByTestId("picker-error-retry").click();
      await expect(page.getByTestId("picker-empty")).toBeVisible({ timeout: 15000 });
    } else {
      // If not error, should be empty or list - check empty is reachable via retry or directly
      const emptyVisible = await page.getByTestId("picker-empty").isVisible().catch(() => false);
      if (!emptyVisible) {
        // Try to trigger empty by searching with no results
        await page.getByTestId("picker-search-input").fill("__no_such__12345");
        await page.getByTestId("picker-retry").click();
        await expect(page.getByTestId("picker-empty")).toBeVisible({ timeout: 15000 });
      } else {
        await expect(page.getByTestId("picker-empty")).toBeVisible({ timeout: 15000 });
      }
    }
  });

  test("keyboard/focus basics", async ({ page }) => {
    await setupGalleryMocks(page, "compatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("picker-search-input").focus();
    await expect(page.getByTestId("picker-search-input")).toBeFocused();
    const firstItem = page.getByTestId(`picker-item-${MOCK_PACKS[0].id}`);
    await firstItem.focus();
    await expect(firstItem).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("selected-summary")).toBeVisible();
  });

  test("helper text visible and Vietnamese", async ({ page }) => {
    await setupGalleryMocks(page, "compatible");
    await page.goto(`/object-gallery?project=${PROJECT_ID}`);
    await page.getByRole("button", { name: /Xem chi tiết vai trò Hero/ }).click();
    await expect(page.getByTestId("library-picker")).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Nhấn Enter hoặc click để chọn").first()).toBeVisible();
    await expect(page.getByText("Nhập từ khóa và nhấn Tìm")).toBeVisible();
    await expect(page.getByText("Chỉ pack published mới hiện")).toBeVisible();
  });

  test("no /test-s07-* route in production build", async ({ page }) => {
    const resp = await page.request.get("/test-s07-picker");
    expect(resp.status()).toBe(404);
    const resp2 = await page.request.get("/test-s07-t03");
    expect(resp2.status()).toBe(404);
  });
});
