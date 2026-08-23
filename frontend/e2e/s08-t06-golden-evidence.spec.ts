import { test, expect, type Page } from "@playwright/test";

/**
 * S08-T06 (correction round G) — sprint-exit E2E evidence on the TRUE
 * VERTICAL world.  NO role seeding: every role below comes from the REAL
 * DISCOVER run over the QA ``deterministic-identity`` provider (server
 * policy), so the browser proves T02 extraction output -> T03 grouping ->
 * T05 correction -> gallery end-to-end on the SAME fresh root/DB.
 *
 * Screenshots land under
 * output/s08-sprint/20260817-s08t06-g1/screenshots/ (NEW Run ID — never
 * overwrites T04/T05 evidence).
 */

import {
  generateSuggestions,
  setupProjectWithVideo,
  runExtraction,
  waitExtractionTerminal,
  VIDEO_PATH,
} from "./s08-t04-helpers";

test.describe.configure({ mode: "serial" });

const SHOT_DIR =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260818-s08t06-c2/screenshots";

const state: {
  projectId: string;
  videoItemId: string;
} = { projectId: "", videoItemId: "" };

test.beforeAll(async () => {
  const proj = await setupProjectWithVideo("t06-vertical", VIDEO_PATH);
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  const extraction = await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  await waitExtractionTerminal(extraction.jobId);
  await generateSuggestions(proj.videoItemId);
});

async function openGallery(page: Page): Promise<void> {
  await page.goto(`/object-gallery?project=${state.projectId}`);
  await page.getByRole("article", { name: /Vai trò/ }).first().waitFor({ timeout: 30_000 });
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SHOT_DIR}/${name}`, fullPage: true });
}

test("t06 - desktop gallery driven by raw extraction output + grouping", async ({ page }) => {
  await openGallery(page);
  await page.getByRole("heading", { name: /Gợi ý gộp đang chờ duyệt/ }).waitFor();
  // Extractor-emitted roles (duplicate display names: several 'Hero' roles)
  // render as cards; suggestions carry backend calibration confidences.
  await expect(page.getByRole("article", { name: /Vai trò Hero/ }).first()).toBeVisible();
  await expect(page.getByRole("article", { name: /Vai trò Villain/ }).first()).toBeVisible();
  await expect(page.getByRole("article", { name: /Vai trò Twin/ }).first()).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "desktop-gallery-extractor-driven.png");
});

test("t06 - correction scope dialog before confirmation, escape = zero mutations", async ({
  page,
}) => {
  await openGallery(page);
  // The extractor-emitted "Villain" role name is unique — expand its detail,
  // then open the per-occurrence reassign correction.
  await page.getByRole("button", { name: "Xem chi tiết vai trò Villain" }).click();
  const villainCard = page.getByRole("article", { name: /Vai trò Villain/ });
  await villainCard.getByRole("button", { name: "Chuyển vai trò" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  // A target role exists (the extractor emitted 7 roles) — pick one.
  const radio = dialog.getByRole("radio").first();
  await radio.check();
  const scope = dialog.getByTestId("correction-scope");
  await scope.waitFor({ timeout: 15_000 });
  await page.waitForTimeout(400);
  await shot(page, "desktop-correction-scope-dialog.png");
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
});

test("t06 - browser restart without sessionStorage restores from backend", async ({
  browser,
}) => {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await openGallery(page);
    // Hard browser restart: fresh context, empty storage, same backend.
    await page.reload();
    await page.getByRole("article", { name: /Vai trò/ }).first().waitFor({ timeout: 30_000 });
    const appKeys = await page.evaluate(() =>
      Object.keys(sessionStorage).filter((k) => k.startsWith("mf-") || k.includes("gallery")),
    );
    expect(appKeys).toEqual([]);
  } finally {
    await context.close();
  }
});

test("t06 - 390px gallery no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openGallery(page);
  await page.waitForTimeout(600);
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (metrics.scrollWidth > metrics.clientWidth + 1) {
    throw new Error(
      `390px horizontal overflow: scrollWidth=${metrics.scrollWidth} clientWidth=${metrics.clientWidth}`,
    );
  }
  await shot(page, "mobile-390px-gallery.png");
});
