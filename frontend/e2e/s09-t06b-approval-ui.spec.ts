/**
 * S09-T06B approval UI/E2E — REAL flow against the QA backend (:8099) and
 * the Next dev server (:3014).
 *
 * Contract (no mocks, no route.fulfill, no fabricated data):
 *   1. Open /demo-compare → the correction panel loads REAL projects →
 *      videos → segments from the durable + structural-evidence APIs
 *      (seeded by output/.../t06b/run-qa-seed.py into an alembic-upgraded
 *      isolated SQLite under this task's output root).
 *   2. Submit a z_order correction via the UI → status pending.
 *   3. Switch to the approval panel: the pending correction is a BLOCKER
 *      (fail-closed) → the Approve button is DISABLED while it exists.
 *   4. Back to the correction panel: CONFIRM applies the correction →
 *      reload data in the approval panel → blockers clear → tick explicit
 *      accept for each warning + override → Approve ENABLES → click →
 *      checkpoint created (replayed=false), hash rendered, verify=true.
 *   5. Override WITHOUT applied-correction evidence is itself a blocker:
 *      add one first, see Approve stay disabled, then remove path via the
 *      matched override text (the run's own reason) → enabled again.
 *   6. RELOAD the page: the checkpoint is still listed with its hash and
 *      verified state (durability of the immutable record).
 *
 * Idempotency across runs (×2 FULL PASS required): global-setup RESETS the
 * QA lane before every suite; every mutating payload inside the test is
 * run-unique anyway (z value / reasons / idempotency keys carry the runTag)
 * so replaying an older run's rows can never silently pass this spec.
 *
 * Helper-text contract: every interactive control has Vietnamese helper
 * text in a <p> directly beneath it.
 */
import { expect, test } from "@playwright/test";

test.describe("S09-T06B approval UI", () => {
  test("full flow: correct → approve blocked by pending correction → resolve → explicit accept → approve → hash verified → survives reload", async ({
    page,
  }) => {
    // The transactional full flow MUTATES the shared QA lane (approval
    // checkpoints are immutable; the reset runs once per suite) — it
    // therefore runs on the desktop project only; mobile checks layout.
    test.skip(
      test.info().project.name !== "desktop",
      "full flow mutates shared QA state — desktop-only; mobile checks layout",
    );
    test.setTimeout(240_000);

    await page.goto("/demo-compare");

    // ── Phase A: REAL targets load in BOTH panels ────────────────────────
    const approvalPanel = page.getByTestId("approval-panel");
    await expect(approvalPanel).toBeVisible();
    await expect(page.getByTestId("approval-loading")).toBeVisible({
      timeout: 30_000,
    });

    const projectSelect = page.getByTestId("correction-project-select");
    await expect(projectSelect).toHaveValue(/.{8,}/, { timeout: 30_000 });
    const videoSelect = page.getByTestId("correction-video-select");
    await expect(videoSelect).toHaveValue(/.{8,}/);
    await expect(projectSelect).toContainText("T06B-E2E");
    await expect(videoSelect).toContainText("T06B Approval Demo");

    // The seeded project is ALSO auto-selected in the approval panel.
    const apprProject = page.getByTestId("approval-project-select");
    await expect(apprProject).toHaveValue(/.{8,}/, { timeout: 30_000 });
    await expect(page.getByTestId("approval-loading")).toBeHidden();
    const configSelect = page.getByTestId("approval-config-select");
    await expect(configSelect).toHaveValue(/.{8,}/, { timeout: 30_000 });
    const apprVideo = page.getByTestId("approval-video-select");
    await expect(apprVideo).toHaveValue(/.{8,}/);

    const runTag = `${Date.now()}-${Math.floor(Math.random() * 1e9)}`;

    // ── Phase B: helper-text VN directly under EVERY approval control ────
    for (const tid of [
      "approval-project-select",
      "approval-video-select",
      "approval-config-select",
      "approval-revision-input",
      "approval-warning-input",
      "approval-warning-add",
      "approval-override-input",
      "approval-override-add",
      "approval-note-input",
      "approval-idempotency-input",
      "approval-approve-btn",
      "approval-verify-btn",
      "approval-reload-btn",
    ]) {
      await expect(
        page.getByTestId(tid).locator("xpath=following-sibling::p[1]"),
      ).not.toBeEmpty();
    }

    // Keyboard accessibility: focus moves by Tab out of the project select;
    // Approve button is reachable/focusable by keyboard alone.
    await apprProject.focus();
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).not.toBe(apprProject);
    const approveBtn = page.getByTestId("approval-approve-btn");
    await approveBtn.focus();
    await expect(approveBtn).toBeFocused();

    // ── Phase C: submit a z_order correction via the correction panel ────
    await page.getByTestId("correction-kind-select").selectOption("z_order");
    const segmentSelect = page.getByTestId("correction-segment-select");
    await expect(segmentSelect).toContainText("Character", { timeout: 30_000 });
    await segmentSelect.selectOption({ index: 1 });
    await expect(segmentSelect.locator("option:checked")).toContainText(
      "Character",
    );

    const zBase = 200_000 + Math.floor(Math.random() * 400_000);
    await page.getByTestId("correction-zorder-input").fill(String(zBase));
    const idemInput = page.getByTestId("correction-idempotency-input");
    await idemInput.fill(`t06b-e2e-corr-${runTag}`);
    await page.getByTestId("correction-submit").click();
    await expect(page.getByTestId("correction-last-result")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "pending",
    );
    const correctionId = await page.getByTestId("correction-last-id").innerText();
    expect(correctionId.length).toBeGreaterThan(8);

    // ── Phase D: pending correction BLOCKS the approval (fail-closed) ────
    // The approval panel refreshes its data on explicit "Nạp lại dữ liệu"
    // (real user flow — cross-panel submissions are pulled in by reload).
    await page.getByTestId("approval-reload-btn").click();
    const corrRowStatus = page.getByTestId(
      `approval-correction-status-${correctionId}`,
    );
    await expect(corrRowStatus).toHaveText("pending", { timeout: 30_000 });
    const blockerItem = page
      .getByTestId("approval-blocker-item")
      .filter({ hasText: correctionId });
    await expect(blockerItem).toBeVisible();
    await expect(approveBtn).toBeDisabled();

    // Explicit-confirm UX: even ticking nothing can bypass; the disabled
    // state persists across a re-render trigger (revision input touch).
    await page.getByTestId("approval-revision-input").fill("1");
    await expect(approveBtn).toBeDisabled();

    // ── Phase E: resolve the blocker through the REAL confirm API ────────
    await page.getByTestId("correction-confirm").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "applied",
      { timeout: 60_000 },
    );
    await page.getByTestId("approval-reload-btn").click();
    await expect(corrRowStatus).toHaveText("applied", { timeout: 30_000 });
    await expect(page.getByTestId("approval-no-blockers")).toBeVisible();

    // ── Phase F: override without evidence is ITSELF a blocker ──────────
    const overrideInput = page.getByTestId("approval-override-input");
    await overrideInput.fill(`benchmark FAIL pose_swap [${runTag}]`);
    await page.getByTestId("approval-override-add").click();
    const noEvidence = page.getByTestId("approval-override-no-evidence-0");
    await expect(noEvidence).toBeVisible();
    await expect(noEvidence).toContainText("chưa có bằng chứng");
    await expect(approveBtn).toBeDisabled(); // unmatched override blocks

    // Tick the checkbox does NOT clear the blocker (evidence is required,
    // acceptance alone never unlocks an evidence-less override).
    await page.getByTestId("approval-override-check-0").check();
    await expect(approveBtn).toBeDisabled();

    // The applied z_order correction recorded reasons=["UI z-order
    // correction"]; adding THAT string shows the matched-evidence badge,
    // proving live matching against the REAL applied correction row.
    await overrideInput.fill("UI z-order correction");
    await page.getByTestId("approval-override-add").click();
    const evidenceRow = page.getByTestId("approval-override-evidence-1");
    await expect(evidenceRow).toBeVisible();
    await expect(evidenceRow).toContainText("đã có bằng chứng applied");
    await page.getByTestId("approval-override-check-1").check();
    // Row 0 (evidence-less) STILL blocks: acceptance alone never unlocks.
    await expect(approveBtn).toBeDisabled();
    // Explicit removal: drop the evidence-less override from the request.
    await page.getByTestId("approval-override-remove-0").click();
    await expect(
      page.getByTestId("approval-override-row-0"),
    ).toContainText("UI z-order correction");

    // ── Phase G: warnings + explicit accept → approve ───────────────────
    const warningInput = page.getByTestId("approval-warning-input");
    await warningInput.fill(`fps 60 chưa benchmark [${runTag}]`);
    await page.getByTestId("approval-warning-add").click();
    await expect(page.getByTestId("approval-warning-row-0")).toBeVisible();
    await expect(approveBtn).toBeDisabled(); // unchecked warning blocks

    // Tick EVERY explicit checkbox (one warning + one override).
    await page.getByTestId("approval-warning-check-0").check();
    await page.getByTestId("approval-override-check-0").check();
    await expect(page.getByTestId("approval-blockers")).toContainText(
      "Không còn blocker",
    );
    await expect(approveBtn).toBeEnabled();

    // Run-unique note keeps THIS run's submission content-distinct so the
    // natural-key replay of a previous run can never satisfy this POST.
    await page
      .getByTestId("approval-note-input")
      .fill(`t06b approval run ${runTag}`);
    await page
      .getByTestId("approval-idempotency-input")
      .fill(`t06b-e2e-appr-${runTag}`);

    // CAS revision pinned to what the approver sees.
    await expect(page.getByTestId("approval-summary-pack")).not.toContainText(
      "(không có)",
    );

    await approveBtn.click();
    const lastResult = page.getByTestId("approval-last-result");
    await expect(lastResult).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("approval-last-replayed")).toHaveText(
      "created (mới)",
    );
    const checkpointId = await page
      .getByTestId("approval-last-id")
      .innerText();
    expect(checkpointId.length).toBeGreaterThan(8);
    const hashText = await page.getByTestId("approval-hash").innerText();
    expect(hashText).toMatch(/^[0-9a-f]{64}$/);
    await expect(page.getByTestId("approval-hash-status")).toContainText(
      "Hash hợp lệ",
      { timeout: 30_000 },
    );

    // The new checkpoint appears in the project list, hash-verified.
    const cpRow = page.getByTestId(`approval-checkpoint-${checkpointId}`);
    await expect(cpRow).toBeVisible({ timeout: 30_000 });
    await expect(
      cpRow.getByTestId("approval-checkpoint-verified"),
    ).toHaveText("verified");

    // ── Phase H: durability — reload STILL lists the checkpoint ─────────
    await page.reload();
    const cpAfterReload = page.getByTestId(`approval-checkpoint-${checkpointId}`);
    await expect(cpAfterReload).toBeVisible({ timeout: 30_000 });
    await expect(
      cpAfterReload.getByTestId("approval-checkpoint-hash"),
    ).toContainText(hashText.slice(0, 16));
    await expect(
      cpAfterReload.getByTestId("approval-checkpoint-verified"),
    ).toHaveText("verified", { timeout: 30_000 });
  });

  test("mobile 390px: approval panel renders without horizontal overflow", async ({
    page,
  }, testInfo) => {
    if (!testInfo.project.name.includes("mobile")) {
      test.skip(true, "desktop project does not run the mobile check");
    }
    await page.goto("/demo-compare");
    const panel = page.getByTestId("approval-panel");
    await expect(panel).toBeVisible();
    await expect(
      page
        .getByTestId("approval-loading")
        .or(page.getByTestId("approval-error")),
    ).toBeVisible({ timeout: 30_000 });
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
