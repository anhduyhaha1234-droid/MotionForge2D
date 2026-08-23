import { test, expect } from "@playwright/test";

/**
 * S08-T04-C1 Object Gallery — 390px read-only suite (finding E #9: 390px
 * with NO horizontal overflow). Fresh isolated project + real extraction;
 * never touches desktop-mutated state.
 */
import { runExtraction, setupProject } from "./s08-t04-helpers";

test.describe.configure({ mode: "serial" });

const state: { projectId: string; videoItemId: string; sourceSha: string } = {
  projectId: "",
  videoItemId: "",
  sourceSha: "",
};

test.beforeAll(async () => {
  const proj = await setupProject("t04-c1-mobile");
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  state.sourceSha = proj.sourceSha;
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
});

test("m1 390px: gallery renders with NO horizontal overflow", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expect(
    page.getByRole("button", { name: /^Xem chi tiết vai trò subject_01$/ }),
  ).toBeVisible({ timeout: 60_000 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
  await expect(page.getByLabel("Công việc phát hiện đối tượng").getByText("Hoàn tất")).toBeVisible();
});

test("m2 390px: policy line + expand + media + merge controls stay in viewport", async ({ page }) => {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await expect(page.getByText(/Ngưỡng duyệt gộp: \d+%/)).toBeVisible();
  await page.getByRole("button", { name: "Xem chi tiết vai trò subject_01" }).click();
  const detail = page.getByTestId("role-detail").first();
  await expect(detail).toBeVisible();
  await expect(detail.getByLabel("Vai trò đích")).toBeVisible();
  await expect(detail.getByLabel("Nguồn gộp")).toBeVisible();
  const media = detail.locator("img[data-testid^='media-']").first();
  if ((await media.count()) > 0) {
    await expect(media).toBeVisible();
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
});

test("m3 390px: fresh browser with empty storage restores from the backend", async ({ browser }) => {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(`/object-gallery?project=${state.projectId}`);
    await expect(
      page.getByRole("button", { name: /^Xem chi tiết vai trò subject_01$/ }),
    ).toBeVisible({ timeout: 60_000 });
    const storage = await page.evaluate(() => ({
      ss: sessionStorage.getItem("mf-gallery-extraction-x") ?? null,
    }));
    expect(storage.ss).toBeNull();
  } finally {
    await context.close();
  }
});
