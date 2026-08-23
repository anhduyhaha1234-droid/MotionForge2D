import { test, expect, type Page, type Route } from "@playwright/test";
import { readFileSync } from "fs";
import path from "path";

/**
 * S06-T05 focused frontend interaction tests — Pack Review & Publish UX.
 *
 * Runs against the real QA backend (:8002, output/qa-root seeded with real
 * characters via the approved importer) and the real frontend dev server
 * (:3010).  Error paths (422/409) are exercised at the network boundary with
 * route interception so the UI's honest surfacing is verifiable without
 * corrupting the shared QA data; success/confirmation/immutability use real
 * backend mutations.
 */

/** Fresh per-run success target written by output/qa-seed-s06-t05.py. */
const SEED_STATE = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../output/s08-p00-integration/20260805-223518/seed-state.json"), "utf8"),
) as { successCode: string };

/* ── Helpers ────────────────────────────────────────────────────────────── */

async function openCharacter(page: Page, code: string) {
  await page.goto("/characters");
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();
  const search = page.getByPlaceholder("Tìm theo tên hoặc mã nhân vật...");
  await search.fill(code);
  const card = page.getByRole("button", { name: new RegExp(`Xem chi tiết.*\\(${code}\\)`) });
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.click();
}

async function waitReadyToPublish(page: Page) {
  // The authoritative validation box reports completeness before the publish
  // button becomes eligible.
  await expect(
    page.getByText("Đầy đủ 6 tư thế — sẵn sàng xuất bản."),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Xuất bản", exact: true })).toBeEnabled();
}

async function confirmPublish(page: Page) {
  await page.getByRole("button", { name: "Xuất bản", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Xác nhận xuất bản" }).click();
}

function countPublishPosts(page: Page, counter: { n: number }) {
  page.on("request", (req) => {
    if (req.method() === "POST" && /\/api\/v2\/characters\/versions\/[^/]+\/publish$/.test(req.url())) {
      counter.n += 1;
    }
  });
}

function countVersionsGets(page: Page, counter: { n: number }) {
  page.on("request", (req) => {
    if (req.method() === "GET" && /\/api\/v2\/characters\/[^/]+\/versions$/.test(req.url())) {
      counter.n += 1;
    }
  });
}

/* ── Tests ──────────────────────────────────────────────────────────────── */

test.describe("Pack Review & Publish UX", () => {
  test("incomplete pack: publish disabled with authoritative problems shown", async ({ page }) => {
    await openCharacter(page, "tho_cute");

    // Authoritative validation state (from the approved read API).
    await expect(page.getByText("Thiếu 3 tư thế bắt buộc.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Thiếu: .*(Ba phần tư|Sau lưng|Ngồi)/)).toBeVisible();

    // Publish is only offered for eligible versions: disabled + explanation.
    const publish = page.getByRole("button", { name: "Xuất bản", exact: true });
    await expect(publish).toBeDisabled();
    await expect(
      page.getByText("Cần đầy đủ 6 tư thế hợp lệ để xuất bản (đang thiếu 3 tư thế)."),
    ).toBeVisible();
  });

  test("confirmation: cancel keeps the draft and sends no publish call", async ({ page }) => {
    const posts = { n: 0 };
    countPublishPosts(page, posts);

    await openCharacter(page, "co_gai");
    await waitReadyToPublish(page);

    await page.getByRole("button", { name: "Xuất bản", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Xuất bản phiên bản v1?")).toBeVisible();
    // Explicit immutability warning in the confirmation.
    await expect(dialog.getByText(/bất biến/)).toBeVisible();

    await dialog.getByRole("button", { name: "Hủy" }).click();
    await expect(dialog).toHaveCount(0);

    // No mutation was issued; the version is still a draft.
    expect(posts.n).toBe(0);
    const row = page.getByRole("button", { name: /Phiên bản v1/ });
    await expect(row.getByText("Nháp", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Xuất bản", exact: true })).toBeEnabled();
  });

  test("422: validation failure is surfaced honestly with missing slots and errors", async ({ page }) => {
    const posts = { n: 0 };
    countPublishPosts(page, posts);

    await page.route("**/api/v2/characters/versions/*/publish", async (route: Route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            message: "Cannot publish pack version: validation failed",
            missing_slots: ["sitting", "walking"],
            errors: [
              "Pose slot 'sitting' artifact file missing on disk",
              "Pose slot 'walking' artifact file missing on disk",
            ],
          },
        }),
      });
    });

    await openCharacter(page, "co_gai");
    await waitReadyToPublish(page);
    await confirmPublish(page);

    // Honest 422 surfacing: the server's message + typed detail lists.
    const status = page.getByRole("status");
    await expect(status.getByText("Cannot publish pack version: validation failed")).toBeVisible({
      timeout: 15_000,
    });
    await expect(status.getByText(/Thiếu: Ngồi, Đi bộ/)).toBeVisible();
    await expect(status.getByText("Pose slot 'sitting' artifact file missing on disk")).toBeVisible();
    await expect(status.getByText("Pose slot 'walking' artifact file missing on disk")).toBeVisible();

    // Exactly one attempt — no silent retry; version stays draft.
    expect(posts.n).toBe(1);
    const row = page.getByRole("button", { name: /Phiên bản v1/ });
    await expect(row.getByText("Nháp", { exact: true })).toBeVisible();
  });

  test("409: stale revision shows conflict, refreshes state, never retries", async ({ page }) => {
    const posts = { n: 0 };
    countPublishPosts(page, posts);
    const versionGets = { n: 0 };
    countVersionsGets(page, versionGets);

    await page.route("**/api/v2/characters/versions/*/publish", async (route: Route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "CAS revision mismatch: expected 2, got 1" }),
      });
    });

    await openCharacter(page, "co_gai");
    await waitReadyToPublish(page);
    const getsBefore = versionGets.n;

    await confirmPublish(page);

    // Conflict surfaced honestly.
    const status = page.getByRole("status");
    await expect(status.getByText(/Xung đột phiên bản/)).toBeVisible({ timeout: 15_000 });

    // Current state was refreshed (a fresh versions fetch happened).
    await expect
      .poll(() => versionGets.n, { timeout: 15_000 })
      .toBeGreaterThan(getsBefore);

    // Exactly one mutation attempt — no silent retry.
    await page.waitForTimeout(1000);
    expect(posts.n).toBe(1);
  });

  test("success: publish refetches and shows the immutable published state", async ({ page }) => {
    await openCharacter(page, SEED_STATE.successCode);
    await waitReadyToPublish(page);
    await confirmPublish(page);

    // Success feedback after refetch.
    const status = page.getByRole("status");
    await expect(status.getByText(/Đã xuất bản phiên bản v1/)).toBeVisible({ timeout: 20_000 });

    // Versions list refetched: row now shows the immutable published badge.
    await expect(page.getByText("Đã xuất bản · Bất biến")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Phiên bản đã xuất bản không thể chỉnh sửa")).toBeVisible();

    // No publish control on a published version.
    await expect(page.getByRole("button", { name: "Xuất bản", exact: true })).toHaveCount(0);
  });

  test("published version is immutable with no asset mutation controls", async ({ page }) => {
    await openCharacter(page, "boy_hacker");

    // Pre-published seed: immutable badge + lock note.
    await expect(page.getByText("Đã xuất bản · Bất biến")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Phiên bản đã xuất bản không thể chỉnh sửa")).toBeVisible();

    // No publish action, no attach/upload/mutation controls at all.
    await expect(page.getByRole("button", { name: "Xuất bản", exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /(Tải lên|Upload|Gắn kèm|Đính kèm|artifact|Artifact)/i }),
    ).toHaveCount(0);
  });
});
