// ============================================================================
// MOCKED UI TESTS — NOT end-to-end (S07-T03 correction C1, finding F-E).
//
// Every network interaction of the picker surface is fulfilled by
// page.route() mocks below; NO real backend is involved in this file. These
// tests verify UI rendering/UX states ONLY: browse/search, compatibility
// banners, blocked submit, stale-recovery UX, loading/error/empty/retry.
//
// The REAL end-to-end Scenario I (real Object Gallery route + real backend +
// real temp DB, ZERO project-cast mocking) lives in
// s07-t03-real-vertical.spec.ts and runs via playwright.s07t03.config.ts.
//
// The former /test-s07-t03 harness route was DELETED (F-E); these mocked
// tests now mount the production Object Gallery page and mock its API layer,
// never a deleted harness route.
// ============================================================================
import { test, expect, type Route } from "@playwright/test";

const MOCK_PACKS = [
  {
    id: "pack-s07t03-shared-1111-1111-1111-111111111111",
    character_id: "char-s07t03-shared-aaaa",
    workspace_id: "default",
    version: 1,
    status: "published",
    character_name: "Shared Hero",
    character_code: "shared",
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
    id: "pack-s07t03-new-2222-2222-2222-222222222222",
    character_id: "char-s07t03-shared-aaaa",
    workspace_id: "default",
    version: 2,
    status: "published",
    character_name: "Shared Hero",
    character_code: "shared",
    character_type: "character",
    symmetry: "symmetric",
    published_at: new Date().toISOString(),
    revision: 2,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    asset_count: 6,
    pose_slots: ["front", "three_quarter", "side", "back", "sitting", "walking"],
  },
  {
    id: "pack-s07t03-other-3333-3333-3333-333333333333",
    character_id: "char-other-bbbb",
    workspace_id: "default",
    version: 1,
    status: "published",
    character_name: "Other Prop",
    character_code: "other",
    character_type: "prop",
    symmetry: "symmetric",
    published_at: new Date().toISOString(),
    revision: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    asset_count: 6,
    pose_slots: ["front", "three_quarter", "side", "back", "sitting", "walking"],
  },
];

const PINNED_SHARED = MOCK_PACKS[0].id;
const MOCK_PROJECT_ID = "proj-s07t03-A";
const MOCK_ROLE_ID = "role-s07t03-A";

/** Gallery page URL for the mocked project/video pair. */
function galleryUrl(): string {
  return `/object-gallery?project=${MOCK_PROJECT_ID}&video=vid-s07t03-A`;
}

/**
 * Mock the gallery's backend gates so the production page renders roles:
 * chain state (completed), videos list, roles list + role detail. Without
 * these the page stops at the chain gate / role list and the picker under
 * test never mounts.
 */
async function mockGalleryGates(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/projects/*/analyze**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: MOCK_PROJECT_ID,
        video_item_id: "vid-s07t03-A",
        generation: "1",
        source_name: "mock.mp4",
        source_sha256: "a".repeat(64),
        chain_status: "completed",
        active_step: null,
        progress: 100,
        steps: {},
        source_artifact_id: null,
        proxy_artifact_id: null,
        scenes_count: 1,
      }),
    });
  });
  await page.route("**/api/v2/projects/*/videos**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: MOCK_PROJECT_ID,
        workspace_id: "default",
        active_only: true,
        videos: [
          {
            id: "vid-s07t03-A",
            project_id: MOCK_PROJECT_ID,
            title: "MockVid",
            position: 0,
            status: "objects_ready",
            archived_at: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            revision: 1,
          },
        ],
      }),
    });
  });
  await page.route("**/api/v2/object-intelligence/extraction/current**", async (route) => {
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "none" }) });
  });
  await page.route("**/api/v2/object-intelligence/grouping/policy**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        algorithm: "mock",
        calibration_version: "0",
        review_threshold: 0.5,
        advisory_only: true,
      }),
    });
  });
  await page.route("**/api/v2/object-intelligence/kinds**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        kinds: [{ name: "character", removal_only: false }, { name: "prop", removal_only: false }],
      }),
    });
  });
  const rolePayload = {
    id: MOCK_ROLE_ID,
    workspace_id: "default",
    project_id: MOCK_PROJECT_ID,
    video_item_id: "vid-s07t03-A",
    source_generation: "1",
    name: "MockHero",
    kind: "character",
    status: "confirmed",
    supersedes_role_id: null,
    legacy_object_id: null,
    legacy_scene_id: null,
    description: null,
    revision: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    occurrences: [],
    media: [],
    has_media_associations: false,
  };
  await page.route("**/api/v2/object-intelligence/roles**", async (route) => {
    if (route.request().url().includes(`/roles/${MOCK_ROLE_ID}`)) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rolePayload) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        workspace_id: "default",
        limit: 20,
        offset: 0,
        total: 1,
        scope: "current",
        current_generation: "1",
        roles: [rolePayload],
      }),
    });
  });
}

function mockPicker(route: Route): boolean {
  const url = new URL(route.request().url());
  if (url.pathname.includes("/api/v2/project-cast/picker/packs")) {
    const q = url.searchParams.get("q")?.toLowerCase() ?? "";
    let packs = MOCK_PACKS;
    if (q)
      packs = packs.filter(
        (p) =>
          p.character_name.toLowerCase().includes(q) ||
          p.character_code.toLowerCase().includes(q),
      );
    void (async () => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          workspace_id: "default",
          limit: 50,
          offset: 0,
          total: packs.length,
          packs,
          query: q || null,
        }),
      });
    })();
    return true;
  }
  return false;
}

function compatBody(scenario: "compatible" | "incompatible" | "stale"): string {
  if (scenario === "compatible")
    return JSON.stringify({ compatible: true, reasons: [], fallback_allowed: false, fallback_description: null, blocked: false, pinned_version_id: PINNED_SHARED, current_revision: 1, workspace_id: "default" });
  if (scenario === "incompatible")
    return JSON.stringify({ compatible: false, reasons: ["object_kind_mismatch"], fallback_allowed: false, fallback_description: null, blocked: true, pinned_version_id: PINNED_SHARED, current_revision: 1, workspace_id: "default" });
  return JSON.stringify({ compatible: false, reasons: ["stale_revision"], fallback_allowed: false, fallback_description: null, blocked: true, pinned_version_id: PINNED_SHARED, current_revision: 2, workspace_id: "default" });
}

async function fulfillCompat(route: Route, scenario: "compatible" | "incompatible" | "stale"): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: compatBody(scenario),
  });
}

test.describe("S07-T03 Scenario I — MOCKED UI states (NOT end-to-end)", () => {
  test("MOCKED: picker browse/search/select renders on the production gallery route", async ({ page }) => {
    await mockGalleryGates(page);
    await page.route("**/*", async (route) => {
      if (mockPicker(route)) return;
      if (route.request().url().includes("compatibility/evaluate")) {
        await fulfillCompat(route, "compatible");
        return;
      }
      if (route.request().url().includes("/api/v2/project-cast?") && route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            workspace_id: "default",
            project_id: MOCK_PROJECT_ID,
            limit: 50,
            offset: 0,
            total: 1,
            mappings: [
              {
                id: "mapping-s07t03-A",
                workspace_id: "default",
                project_id: MOCK_PROJECT_ID,
                object_role_id: MOCK_ROLE_ID,
                character_id: "char-s07t03-shared-aaaa",
                pack_version_id: PINNED_SHARED,
                idempotency_key: "k-A",
                revision: 1,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(galleryUrl());
    const firstPicker = page.getByTestId("project-cast-picker").first();
    await expect(firstPicker.getByTestId("library-picker")).toBeVisible({ timeout: 15000 });
    await expect(firstPicker.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await expect(firstPicker.getByTestId(`picker-item-${MOCK_PACKS[0].id}`)).toBeVisible();

    // Pinned summary comes from the mocked mappings list
    await expect(firstPicker.getByTestId("pinned-summary")).toBeVisible({ timeout: 15000 });
    await expect(firstPicker.getByTestId("pinned-summary")).toContainText(PINNED_SHARED);

    // Search narrows to the prop pack, clearing restores the shared pack
    await firstPicker.getByTestId("picker-search-input").fill("other");
    await firstPicker.getByTestId("picker-search-input").press("Enter");
    await expect(firstPicker.getByTestId(`picker-item-${MOCK_PACKS[2].id}`)).toBeVisible({
      timeout: 10000,
    });
    await firstPicker.getByTestId("picker-search-input").fill("");
    await firstPicker.getByTestId("picker-search-input").press("Enter");
    await expect(firstPicker.getByTestId(`picker-item-${MOCK_PACKS[0].id}`)).toBeVisible({
      timeout: 10000,
    });

    await firstPicker.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(firstPicker.getByTestId("compat-compatible")).toBeVisible({ timeout: 10000 });
    await expect(firstPicker.getByTestId("selected-summary")).toContainText(MOCK_PACKS[0].id);
    await expect(firstPicker.getByTestId("cast-submit")).toBeEnabled({ timeout: 10000 });

    // Keyboard navigation hint (UI copy contract)
    await expect(page.getByText("Điều hướng bàn phím").first()).toBeVisible();
  });

  test("MOCKED: incompatible pack blocks submit (fail-closed UX)", async ({ page }) => {
    await mockGalleryGates(page);
    await page.route("**/*", async (route) => {
      if (mockPicker(route)) return;
      if (route.request().url().includes("compatibility/evaluate")) {
        await fulfillCompat(route, "incompatible");
        return;
      }
      if (route.request().url().includes("/api/v2/project-cast?") && route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            workspace_id: "default",
            project_id: MOCK_PROJECT_ID,
            limit: 50,
            offset: 0,
            total: 1,
            mappings: [
              {
                id: "mapping-s07t03-A",
                workspace_id: "default",
                project_id: MOCK_PROJECT_ID,
                object_role_id: MOCK_ROLE_ID,
                character_id: "char-s07t03-shared-aaaa",
                pack_version_id: PINNED_SHARED,
                idempotency_key: "k-A",
                revision: 1,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(galleryUrl());
    const firstPicker = page.getByTestId("project-cast-picker").first();
    await expect(firstPicker.getByTestId("library-picker")).toBeVisible({ timeout: 15000 });
    await expect(firstPicker.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await firstPicker.getByTestId(`picker-item-${MOCK_PACKS[2].id}`).click();
    await expect(firstPicker.getByTestId("compat-warnings")).toBeVisible({ timeout: 10000 });
    await expect(firstPicker.getByTestId("cast-submit")).toBeDisabled();
    await expect(firstPicker.getByText("Chỉ pack tương thích mới được ghim").first()).toBeVisible();
  });

  test("MOCKED: stale revision recovery UX", async ({ page }) => {
    await mockGalleryGates(page);
    await page.route("**/*", async (route) => {
      if (mockPicker(route)) return;
      if (route.request().url().includes("compatibility/evaluate")) {
        await fulfillCompat(route, "stale");
        return;
      }
      if (route.request().url().includes("/api/v2/project-cast?") && route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            workspace_id: "default",
            project_id: MOCK_PROJECT_ID,
            limit: 50,
            offset: 0,
            total: 1,
            mappings: [
              {
                id: "mapping-s07t03-A",
                workspace_id: "default",
                project_id: MOCK_PROJECT_ID,
                object_role_id: MOCK_ROLE_ID,
                character_id: "char-s07t03-shared-aaaa",
                pack_version_id: PINNED_SHARED,
                idempotency_key: "k-A",
                revision: 1,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(galleryUrl());
    const firstPicker = page.getByTestId("project-cast-picker").first();
    await expect(firstPicker.getByTestId("library-picker")).toBeVisible({ timeout: 15000 });
    await expect(firstPicker.getByTestId("picker-list")).toBeVisible({ timeout: 15000 });
    await firstPicker.getByTestId(`picker-item-${MOCK_PACKS[0].id}`).click();
    await expect(firstPicker.getByTestId("stale-recovery")).toBeVisible({ timeout: 10000 });
    await expect(firstPicker.getByTestId("stale-reload")).toBeVisible();
    await expect(firstPicker.getByText("Phiên bản đã cũ").first()).toBeVisible();
  });

  test("MOCKED: picker error -> retry -> empty states", async ({ page }) => {
    let first = true;
    await mockGalleryGates(page);
    await page.route("**/*", async (route) => {
      const url = route.request().url();
      if (url.includes("/picker/packs")) {
        if (first) {
          first = false;
          await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "server error" }) });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ workspace_id: "default", limit: 50, offset: 0, total: 0, packs: [], query: null }),
        });
        return;
      }
      if (url.includes("compatibility/evaluate")) {
        await fulfillCompat(route, "compatible");
        return;
      }
      if (url.includes("/api/v2/project-cast?") && route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            workspace_id: "default",
            project_id: MOCK_PROJECT_ID,
            limit: 50,
            offset: 0,
            total: 0,
            mappings: [],
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(galleryUrl());
    const firstPicker = page.getByTestId("project-cast-picker").first();
    await expect(firstPicker.getByTestId("picker-error")).toBeVisible({ timeout: 10000 });
    await firstPicker.getByTestId("picker-error-retry").click();
    await expect(firstPicker.getByTestId("picker-empty")).toBeVisible({ timeout: 10000 });
  });
});
