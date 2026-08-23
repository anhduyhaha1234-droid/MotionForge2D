import { test, expect, type Page } from "@playwright/test";

const API = "http://localhost:8002";

/* ── Helpers ────────────────────────────────────────────────────────────── */

async function createCharacter(page: Page, code: string, name: string) {
  const res = await page.request.post(`${API}/api/v2/characters`, {
    data: { name, code, character_type: "character", symmetry: "symmetric", description: "QA E2E" },
  });
  expect(res.status()).toBe(201);
  return (await res.json()) as { id: string; revision: number };
}

async function archiveCharacter(page: Page, id: string, revision: number) {
  const res = await page.request.post(`${API}/api/v2/characters/${id}/archive`, {
    data: { revision },
  });
  expect(res.status()).toBe(200);
}

/* ── Browse/search/filter/detail ───────────────────────────────────────── */

test.describe("Character Library — browse/search/filter/detail", () => {
  let createdId: string | null = null;
  let createdRevision = 1;

  test.beforeAll(async ({ request }) => {
    // Ensure at least one real character exists for deterministic assertions.
    const list = await request.get(`${API}/api/v2/characters`);
    const body = (await list.json()) as { total: number; characters: { code: string }[] };
    if (body.total === 0) {
      const res = await request.post(`${API}/api/v2/characters`, {
        data: { name: "E2E Seed", code: "e2e_seed" },
      });
      expect(res.status()).toBe(201);
    }
  });

  test("grid lists real characters with Vietnamese labels", async ({ page }) => {
    await page.goto("/characters");
    await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();
    // Loading → data (grid cards use aria-pressed)
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    const cards = await page.locator('.grid.content-start button[aria-pressed]').count();
    expect(cards).toBeGreaterThan(0);
  });

  test("search by code filters the grid; empty result is honest", async ({ page }) => {
    await page.goto("/characters");
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    const search = page.getByRole("searchbox", { name: "Tìm kiếm nhân vật" });
    await search.fill("boy_hacker");
    await expect(page.locator('.grid.content-start button[aria-pressed]')).toHaveCount(1);
    await expect(page.locator('.grid.content-start button[aria-pressed]').first()).toContainText("Boy Hacker");
    await search.fill("zzz_does_not_exist");
    await expect(page.getByText("Không tìm thấy nhân vật")).toBeVisible();
    await expect(page.locator('.grid.content-start button[aria-pressed]')).toHaveCount(0);
  });

  test("status filter narrows to ready characters", async ({ page }) => {
    await page.goto("/characters");
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    await page.getByRole("combobox", { name: "Lọc theo trạng thái" }).selectOption("ready");
    await page.waitForTimeout(400);
    const cards = await page.locator('.grid.content-start button[aria-pressed]').allInnerTexts();
    expect(cards.length).toBeGreaterThan(0);
    for (const c of cards) expect(c).toContain("Sẵn sàng");
  });

  test("detail shows six pose slots, validation, draft/published distinction", async ({ page }) => {
    await page.goto("/characters");
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    // Open a published character (Boy Hacker seeded as ready/default).
    const readyCard = page.locator('.grid.content-start button[aria-pressed]:has-text("Boy Hacker")').first();
    if ((await readyCard.count()) === 0) {
      test.skip(true, "requires a published seeded character");
      return;
    }
    await readyCard.click();
    const detail = page.getByRole("region", { name: /Chi tiết nhân vật/ });
    await expect(detail).toBeVisible();
    await expect(detail.getByText("6 TƯ THẾ BẮT BUỘC")).toBeVisible();
    // Published version is immutable + default badge.
    await expect(detail.getByText(/Đã xuất bản · Bất biến/)).toBeVisible();
    // Six pose tiles render.
    const tiles = await detail.locator("article").count();
    expect(tiles).toBeGreaterThanOrEqual(6);
  });

  test("draft pack surfaces missing-slot validation problems", async ({ page }) => {
    await page.goto("/characters");
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    const draftCard = page.locator('.grid.content-start button[aria-pressed]:has-text("Thỏ Cute")').first();
    if ((await draftCard.count()) === 0) {
      test.skip(true, "requires a draft character with missing slots");
      return;
    }
    await draftCard.click();
    const detail = page.getByRole("region", { name: /Chi tiết nhân vật/ });
    await expect(detail).toBeVisible();
    // Honest missing-image placeholder, never a false ready state.
    await expect(detail.getByText("Chưa có ảnh").first()).toBeVisible();
    await expect(detail.getByText(/Thiếu \d+ tư thế bắt buộc/)).toBeVisible();
  });

  test("created character appears, then archive hides it (honest cleanup)", async ({ page }) => {
    const code = `e2e_char_${Date.now()}`;
    const created = await createCharacter(page, code, "E2E Character");
    createdId = created.id;
    createdRevision = created.revision;

    await page.goto("/characters");
    await expect(page.locator('button[aria-pressed]').first()).toBeVisible({ timeout: 15_000 });
    await page.getByRole("searchbox", { name: "Tìm kiếm nhân vật" }).fill(code);
    await expect(page.locator('.grid.content-start button[aria-pressed]')).toHaveCount(1);
    await expect(page.locator('.grid.content-start button[aria-pressed]').first()).toContainText(code);

    // Detail of a character with no pack versions.
    await page.locator('.grid.content-start button[aria-pressed]').first().click();
    await expect(page.getByRole("region", { name: /Chi tiết nhân vật/ })).toContainText("chưa có phiên bản");

    // Archive → hidden from the default (non-archived) list.
    await archiveCharacter(page, created.id, createdRevision);
    await page.goto("/characters");
    await page.getByRole("searchbox", { name: "Tìm kiếm nhân vật" }).fill(code);
    await page.waitForTimeout(500);
    await expect(page.getByText("Không tìm thấy nhân vật")).toBeVisible();
  });

  test.afterAll(async ({ request }) => {
    if (createdId) {
      const res = await request.post(`${API}/api/v2/characters/${createdId}/archive`, {
        data: { revision: createdRevision },
      });
      // Best-effort cleanup; already archived in the last test is fine (200/404).
      if (res.status() === 404) return;
    }
  });
});
