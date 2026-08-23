import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "fs";
import path from "path";

/**
 * S06-T05 visual QA — captures the Pack Review & Publish UX at desktop and
 * 390px mobile widths into output/qa-s06-t05/ (gitignored QA evidence).
 * Uses the same real seeded QA data as the interaction spec.
 */

const OUT = path.resolve(__dirname, "../../output/qa-s06-t05");

async function openCharacter(page: Page, code: string) {
  await page.goto("/characters");
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();
  const search = page.getByPlaceholder("Tìm theo tên hoặc mã nhân vật...");
  await search.fill(code);
  const card = page.getByRole("button", { name: new RegExp(`Xem chi tiết.*\\(${code}\\)`) });
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.click();
}

async function capture(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function scrollToText(page: Page, text: string | RegExp) {
  await page.getByText(text).last().scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
}

test.beforeAll(() => {
  mkdirSync(OUT, { recursive: true });
});

test("desktop visual QA: review, problems and published states", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  // Eligible draft with real six-pose previews + publish panel.
  await openCharacter(page, "co_gai");
  await expect(page.getByText("Đầy đủ 6 tư thế — sẵn sàng xuất bản.")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("button", { name: "Xuất bản", exact: true })).toBeEnabled();
  await scrollToText(page, "Xuất bản phiên bản v1");
  await page.waitForTimeout(600); // let pose previews settle
  await capture(page, "desktop-cogai-review.png");

  // Incomplete pack: authoritative validation problems + disabled publish.
  await openCharacter(page, "tho_cute");
  await expect(page.getByText("Thiếu 3 tư thế bắt buộc.")).toBeVisible({ timeout: 15_000 });
  await scrollToText(page, "Xuất bản phiên bản v1");
  await page.waitForTimeout(400);
  await capture(page, "desktop-thocute-problems.png");

  // Published immutable state.
  await openCharacter(page, "boy_hacker");
  await expect(page.getByText("Đã xuất bản · Bất biến")).toBeVisible({ timeout: 15_000 });
  await scrollToText(page, "6 tư thế bắt buộc");
  await page.waitForTimeout(400);
  await capture(page, "desktop-boyhacker-published.png");
});

test("390px mobile visual QA: review, problems and published states", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  await openCharacter(page, "co_gai");
  await expect(page.getByText("Đầy đủ 6 tư thế — sẵn sàng xuất bản.")).toBeVisible({
    timeout: 15_000,
  });
  await scrollToText(page, "Xuất bản phiên bản v1");
  await page.waitForTimeout(600);
  await capture(page, "mobile390-cogai-review.png");

  await openCharacter(page, "tho_cute");
  await expect(page.getByText("Thiếu 3 tư thế bắt buộc.")).toBeVisible({ timeout: 15_000 });
  await scrollToText(page, "Xuất bản phiên bản v1");
  await page.waitForTimeout(400);
  await capture(page, "mobile390-thocute-problems.png");

  await openCharacter(page, "boy_hacker");
  await expect(page.getByText("Đã xuất bản · Bất biến")).toBeVisible({ timeout: 15_000 });
  await scrollToText(page, "6 tư thế bắt buộc");
  await page.waitForTimeout(400);
  await capture(page, "mobile390-boyhacker-published.png");
});
