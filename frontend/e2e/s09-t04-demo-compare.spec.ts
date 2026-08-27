/**
 * S09-T04 demo comparison e2e — REAL flow against the QA backend (:8099)
 * and the Next dev server (:3014).
 *
 * Contract (no mocks, no route.fulfill, no fabricated data):
 *   1. Open /demo-compare → capabilities + loop list load from the REAL
 *      benchmark document and REAL fixture manifests.
 *   2. Click "Tạo job so sánh" → the UI POSTs /jobs; the backend runs the
 *      deterministic demo-loop pipeline to completion.
 *   3. The completed state exposes per-loop comparison viewers fed by
 *      published artifact URLs + original source-content URLs.
 *   4. Every comparison mode is exercised on real <video> elements.
 *   5. Helper text: every interactive control has Vietnamese helper text
 *      directly beneath it (dark-theme UX contract).
 */
import { expect, test, type Page } from "@playwright/test";

const API = process.env.QA_API_BASE ?? "http://localhost:8099";

test.describe("S09-T04 demo comparison", () => {
  // The pipeline render can take a couple of minutes on first run (fixture
  // encode + publish); keep generous timeouts but poll the UI actively.
  test("full flow: meta loads → submit → completes → compare modes work", async ({
    page,
  }) => {
    test.setTimeout(240_000);

    await page.goto("/demo-compare");
    const panel = page.getByTestId("demo-compare-panel");
    await expect(panel).toBeVisible();

    // ── Phase 1: capabilities from the frozen measured document ──────────
    const caps = page.getByTestId("demo-capabilities");
    await expect(caps).toBeVisible({ timeout: 30_000 });
    // Capabilities are keyed by RISK CLASS (not loop id): every measured
    // class exposes its smallest passing route.  The FROZEN C2 evidence
    // (t00-i03-c2 run_A) measures hard_cut's smallest PASSING route as
    // sprite_affine — pose_swap is CONTRACT_REJECTED_BY_FROZEN_CONTRACT
    // for that fixture, so the API (correctly) reports sprite_affine.
    await expect(caps.getByTestId("cap-hard_cut")).toContainText(
      "hard_cut → sprite_affine",
    );
    const capItems = caps.locator("li");
    await expect(capItems).toHaveCount(6);
    // Frozen evidence hash rendered verbatim (no fabrication).
    await expect(caps).toContainText(/frozen_content_sha256:\s*[0-9a-f]{64}/);

    // Loop list shows all four fixture loops with locked structure.
    for (const loopId of [
      "d1_cut_graphic",
      "d2_mouth_phone",
      "d3_rotation_bed",
      "d4_group_occlusion",
    ]) {
      await expect(
        page.getByTestId(`demo-loop-meta-${loopId}`),
      ).toBeHidden(); // not rendered pre-completion
    }
    // ── Phase 2: submit the comparison job ───────────────────────────────
    const submit = page.getByTestId("demo-submit");
    await expect(submit).toBeEnabled();
    // Helper text sits beneath the button (VN dark-theme contract).
    await expect(submit.locator("xpath=following-sibling::p[1]")).toContainText(
      "Gửi toàn bộ loop",
    );
    await submit.click();

    // Running indicator appears while the durable job executes.
    await expect(page.getByTestId("demo-running")).toBeVisible({
      timeout: 20_000,
    });

    // ── Phase 3: wait for completion (real render) ───────────────────────
    const completed = page.getByTestId("demo-completed");
    await expect(completed).toBeVisible({ timeout: 200_000 });
    await expect(completed).toContainText(/artifact đã xuất/);

    // Mode picker now visible with helper text under it.
    const modeSelect = page.getByTestId("demo-mode-select");
    await expect(modeSelect).toBeVisible();
    await expect(page.getByTestId("demo-mode-helper")).not.toBeEmpty();

    // ── Phase 4: compare viewer on the active loop ───────────────────────
    const loopSelect = page.getByTestId("demo-loop-select");
    await expect(loopSelect).toBeVisible();
    const activeLoop = (await loopSelect.inputValue()) as string;
    expect(activeLoop.length).toBeGreaterThan(0);
    const origVideo = page.getByTestId(`video-original-${activeLoop}`);
    const resultVideo = page.getByTestId(`video-result-${activeLoop}`);
    await expect
      .poll(
        async () =>
          (await origVideo.evaluate((el: HTMLVideoElement) => el.readyState)),
        { timeout: 30_000 },
      )
      .toBeGreaterThanOrEqual(1);
    await expect
      .poll(
        async () =>
          (await resultVideo.evaluate((el: HTMLVideoElement) => el.readyState)),
        { timeout: 30_000 },
      )
      .toBeGreaterThanOrEqual(1);

    // Result video bytes come from the backend content endpoint.
    const resultSrc = (await resultVideo.getAttribute("src")) as string;
    expect(resultSrc).toContain("/api/v2/s09-demo-compare/content/");
    // Original comes from the contained source-content endpoint.
    const origSrc = (await origVideo.getAttribute("src")) as string;
    expect(origSrc).toContain("/api/v2/s09-demo-compare/source-content/");

    // Both media URLs actually resolve over HTTP with video/mp4 bytes.
    for (const src of [origSrc, resultSrc]) {
      const abs = src.startsWith("http") ? src : `${API}${src}`;
      const head = await fetch(abs);
      expect(head.status).toBe(200);
      expect(head.headers.get("content-type") ?? "").toContain("video/mp4");
    }

    // ── Phase 5: exercise every comparison mode ──────────────────────────
    // wipe → draggable divider appears
    await modeSelect.selectOption("wipe");
    const handle = page.getByTestId(`wipe-handle-${activeLoop}`);
    await expect(handle).toBeVisible();
    await handle.focus();
    await page.keyboard.press("ArrowRight");
    await expect(handle).toHaveAttribute("aria-valuenow", "55");

    // blink → mode note explains cadence
    await modeSelect.selectOption("blink");
    await expect(
      page.getByTestId(`viewer-mode-note-${activeLoop}`),
    ).toContainText("Blink");

    // original → only the original layer visible
    await modeSelect.selectOption("original");
    await expect(origVideo).toBeVisible();
    await expect(resultVideo).toBeHidden();

    // result → only the result layer visible
    await modeSelect.selectOption("result");
    await expect(resultVideo).toBeVisible();
    await expect(origVideo).toBeHidden();

    // back to split → side-by-side figures (split renders two <figure>
    // blocks with independent players; no overlay stage in this mode).
    await modeSelect.selectOption("split");
    await expect(
      page.getByTestId(`video-original-${activeLoop}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`video-result-${activeLoop}`),
    ).toBeVisible();
    await expect(
      page.getByText("Gốc — video nguồn chưa thay thế."),
    ).toBeVisible();
    await expect(
      page.getByText("Kết quả — video đã render thay thế."),
    ).toBeVisible();
  });

  test("mobile 390px: read-only render without horizontal overflow", async ({
    page,
  }, testInfo) => {
    if (!testInfo.project.name.includes("mobile")) {
      test.skip(true, "desktop project does not run the mobile check");
    }
    await page.goto("/demo-compare");
    const panel = page.getByTestId("demo-compare-panel");
    await expect(panel).toBeVisible();
    await expect(capsOrError(page)).toBeVisible({ timeout: 30_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

/** Capabilities section or an honest error/empty state — never a blank void. */
function capsOrError(page: Page) {
  return page
    .getByTestId("demo-capabilities")
    .or(page.getByTestId("demo-error"))
    .or(page.getByTestId("demo-empty"));
}
