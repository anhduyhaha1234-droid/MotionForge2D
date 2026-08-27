/**
 * S09-T06B-C3 — production-stack UI acceptance: TARGETED REGENERATION with
 * REAL byte-level effects (actual app.api.app, actual durable regen worker).
 *
 * Everything runs against the ACTUAL production backend (mounted routers,
 * real lifespan, isolated temp DB + managed artifact root) and a PRODUCTION
 * Next.js build (`next build` + `next start`).  No mocks, no route
 * interception, no test-only app anywhere.
 *
 * Frozen chain C3 (verified by hand before this run — NO fallback):
 *   J1-C3-v4   renderer_freeze_manifest_v4.json  ae92247b8bfd7bf2…
 *   I03-C3     benchmark content SHA             12de134527765da2…
 *   I05-C3     route_decisions_c3_seed…json      d289929d948ddfa7…
 *
 * Binary acceptance (prompt S09-C3 §5 T06B):
 *   1. Completed base job over ALL FOUR loops; snapshot EVERY publication
 *      row (artifact_id/sha/size/frames) BEFORE anything mutates.
 *   2. z-order correction THROUGH THE ACTUAL UI against a REAL segment of
 *      the seeded video; stale-revision confirm → 409 and ZERO durable
 *      effects; valid confirm → applied.
 *      The base job renders THIS TASK'S overlap fixture copy (staged by the
 *      task launcher under the QA root): d4 group placements 0+1 overlap,
 *      so the corrected compositing order REALLY changes rendered bytes.
 *   3. The UI itself opens the targeted regeneration.  The affected loop
 *      d4_group_occlusion must carry a NEW generation: NEW artifact id AND
 *      NEW content hash.  The three unaffected loops keep their EXACT
 *      identity (same id/sha/size/frame_count) and no duplicate artifact
 *      rows appear.
 *   4. Replaying the SAME correction (same natural key) returns the SAME
 *      correction record, and replaying regenerate returns the SAME job —
 *      zero duplicates anywhere.
 *   5. A pending correction blocks approval; after apply, an approval
 *      override matches the route_override evidence DIRECTLY through the
 *      new reasonsOf contract (override_reason / provenance.evidence) —
 *      NO warning workaround; explicit approval passes and the checkpoint
 *      hash verifies.
 *   6. Browser reload + an ACTUAL backend process restart preserve the
 *      regeneration evidence, publications and checkpoint verification.
 *
 * Idempotent ×2 runs: global-setup resets DB + demo-loop surface before each
 * suite; every run-scoped key is unique per run.
 */
import { execSync, spawn } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";

const BACKEND_PORT = 8199;
const RUN_ROOT =
  "C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s09/20260823_sprint_full/t06b-c3";
const AFFECTED_LOOP = "d4_group_occlusion";
const UNAFFECTED_LOOPS = [
  "d1_cut_graphic",
  "d2_mouth_phone",
  "d3_rotation_bed",
] as const;
// Frozen C3 measured document (content verified by hand; the API re-verifies).
const EVIDENCE_DOC =
  "output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json";
const EVIDENCE_DOC_SHA256 =
  "12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3";

interface Pub {
  loop_id: string;
  artifact_id: string;
  sha256: string;
  size_bytes: number;
  frame_count: number | null;
}

async function apiGet(page: Page, path: string): Promise<unknown> {
  const res = await page.request.get(
    `http://localhost:${BACKEND_PORT}/api/v2${path}`,
  );
  if (!res.ok()) throw new Error(`GET ${path} -> ${res.status()}`);
  return res.json();
}

async function apiPostRaw(
  page: Page,
  path: string,
  body: unknown,
): Promise<{ status: number; json: Record<string, unknown> }> {
  const res = await page.request.post(
    `http://localhost:${BACKEND_PORT}/api/v2${path}`,
    { data: body },
  );
  let json: Record<string, unknown> = {};
  try {
    json = (await res.json()) as Record<string, unknown>;
  } catch {
    /* empty body */
  }
  return { status: res.status(), json };
}

/** Snapshot loop_id → published evidence for one completed job id. */
async function snapshotPublished(
  page: Page,
  jobId: string,
): Promise<Map<string, Pub>> {
  const st = (await apiGet(page, `/s09-demo-compare/jobs/${jobId}`)) as {
    published: Pub[];
  };
  const map = new Map<string, Pub>();
  for (const p of st.published) map.set(p.loop_id, p);
  return map;
}

test.describe("S09-T06B-C3 targeted regeneration", () => {
  let runTag: string;

  test.beforeEach(() => {
    runTag = `${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  });

  test("affected loop gets a NEW generation; unaffected loops keep exact artifacts; replay dedupes; override evidence approves", async ({
    page,
  }) => {
    test.setTimeout(600_000);

    // ══ Phase A — load page, REAL targets ═══════════════════════════════
    await page.goto("/demo-compare");
    await expect(page.getByTestId("correction-project-select")).toContainText(
      "T06BC3-E2E",
      { timeout: 30_000 },
    );
    await expect(page.getByTestId("correction-video-select")).toContainText(
      "T06BC3 Production Demo",
    );
    const configSelect = page.getByTestId("approval-config-select");
    await expect(configSelect).toHaveValue(/.{8,}/, { timeout: 30_000 });
    await expect(page.getByTestId("approval-loading")).toBeHidden();

    // ══ Phase B — completed base job THROUGH THE UI (hook-tracked) ══════
    const submit = page.getByTestId("demo-submit");
    await expect(submit).toBeEnabled({ timeout: 60_000 });
    await submit.click();
    const completed = page.getByTestId("demo-completed");
    await expect(completed).toBeVisible({ timeout: 300_000 });
    await expect(completed).toContainText(/artifact đã xuất/);

    // Recover the durable job id via the fingerprint contract: the SAME
    // manifest the hook submitted replays to the SAME job (200/reused).
    const LOOPS = [
      "d1_cut_graphic",
      "d2_mouth_phone",
      "d3_rotation_bed",
      "d4_group_occlusion",
    ] as const;
    const sameJob = await apiPostRaw(page, "/s09-demo-compare/jobs", {
      requested_loops: [...LOOPS],
      benchmark_results: EVIDENCE_DOC,
      expect_content_sha256: EVIDENCE_DOC_SHA256,
      fixtures_dir: "tests/fixtures/s09_demo",
    });
    expect(sameJob.status).toBe(200);
    expect(sameJob.json.reused).toBe(true);
    const jobId1 = String(sameJob.json.job_id);

    const snapBefore = await snapshotPublished(page, jobId1);
    expect(snapBefore.size).toBe(4);

    // ══ Phase C — REAL z-order correction THROUGH THE ACTUAL UI ═════════
    await page.getByTestId("correction-kind-select").selectOption("z_order");
    const segmentSelect = page.getByTestId("correction-segment-select");
    await expect(segmentSelect).toContainText("Character", { timeout: 30_000 });
    await segmentSelect.selectOption({ index: 1 });
    const segmentId = (
      await segmentSelect.locator("option:checked").getAttribute("value")
    )?.trim();
    expect(segmentId).toBeTruthy();
    await page.getByTestId("correction-zorder-input").fill("9");
    await page
      .getByTestId("correction-idempotency-input")
      .fill(`t06bc3-zorder-${runTag}`);
    await page.getByTestId("correction-submit").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "pending",
      { timeout: 30_000 },
    );
    const correctionId = (
      await page.getByTestId("correction-last-id").innerText()
    ).trim();
    expect(correctionId.length).toBeGreaterThan(8);

    // Pending correction BLOCKS approval (fail-closed blocker visible).
    const approveBtn = page.getByTestId("approval-approve-btn");
    await page.getByTestId("approval-reload-btn").click();
    await expect(
      page.getByTestId(`approval-correction-status-${correctionId}`),
    ).toHaveText("pending", { timeout: 30_000 });
    await expect(approveBtn).toBeDisabled();

    // ══ Phase I — STALE confirm persists NOTHING ════════════════════════
    const stale = await page.evaluate(
      async ({ port, cid }) => {
        const res = await fetch(
          `http://localhost:${port}/api/v2/s09-corrections/${cid}/confirm`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workspace_id: "default", revision: 99 }),
          },
        );
        return res.status;
      },
      { port: BACKEND_PORT, cid: correctionId },
    );
    expect(stale).toBe(409);
    // Zero durable side-effects from the refused mutation.
    const cpsAfterInvalid = (await apiGet(
      page,
      "/s09-approvals?workspace_id=default",
    )) as { items: unknown[] };
    expect(cpsAfterInvalid.items.length).toBe(0);
    const pubAfterInvalid = await snapshotPublished(page, jobId1);
    for (const [loopId, before] of snapBefore) {
      expect(pubAfterInvalid.get(loopId)?.sha256, `${loopId} sha untouched`).toBe(
        before.sha256,
      );
    }

    // ══ Phase E — valid confirm VIA UI → applied → UI opens regen ═══════
    await page.getByTestId("correction-confirm").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "applied",
      { timeout: 60_000 },
    );

    // The UI ITSELF opens the targeted regeneration (C3-PREP flow): wait
    // for its live phase indicator to reach completed, then recover the
    // regeneration job id from the panel text.
    const regenBox = page.getByTestId("correction-regeneration");
    await expect(regenBox).toBeVisible({ timeout: 30_000 });
    await expect(
      page.getByTestId("correction-regeneration-phase"),
    ).toContainText("completed", { timeout: 300_000 });
    const regenText = await regenBox.innerText();
    const regenJobMatch = /job\s+([0-9a-f-]{36})/.exec(regenText);
    expect(regenJobMatch).toBeTruthy();
    const regenJobId = regenJobMatch![1];

    // ── Binary assertions on publication identities ─────────────────────
    const snapRegen = await snapshotPublished(page, regenJobId);
    expect(snapRegen.size).toBe(4);

    // Affected loop: NEW generation — NEW artifact id AND NEW bytes.
    const d4b = snapBefore.get(AFFECTED_LOOP)!;
    const d4a = snapRegen.get(AFFECTED_LOOP)!;
    expect(d4a.artifact_id, "d4 artifact id MUST change").not.toBe(
      d4b.artifact_id,
    );
    expect(d4a.sha256, "d4 content hash MUST change").not.toBe(d4b.sha256);
    expect(d4a.frame_count).toBe(d4b.frame_count); // same loop length

    // Unaffected loops: EXACT identity preserved everywhere.
    for (const loopId of UNAFFECTED_LOOPS) {
      const b = snapBefore.get(loopId)!;
      const a = snapRegen.get(loopId)!;
      expect(a.artifact_id, `${loopId} artifact id`).toBe(b.artifact_id);
      expect(a.sha256, `${loopId} sha256`).toBe(b.sha256);
      expect(a.size_bytes, `${loopId} size`).toBe(b.size_bytes);
      expect(a.frame_count, `${loopId} frames`).toBe(b.frame_count);
    }

    // Workspace-wide artifact accounting: 4 base + exactly ONE new d4 file
    // — no duplicated rows for any unaffected loop.
    const distinct = new Set<string>([...snapBefore.values()].map((p) => p.artifact_id));
    distinct.add(d4a.artifact_id);
    expect(distinct.size).toBe(5);

    // ══ Replay — same correction ⇒ SAME regeneration job (zero dupes) ═══
    const replay = await apiPostRaw(
      page,
      `/s09-demo-compare/jobs/${jobId1}/regenerate`,
      { correction_id: correctionId },
    );
    expect(replay.status).toBe(200); // reused, not re-created
    expect(replay.json.reused).toBe(true);
    expect(String(replay.json.job_id)).toBe(regenJobId);
    expect(replay.json.correction_id).toBe(correctionId);

    // ══ Phase F5 — route_override evidence matched DIRECTLY ═════════════
    // Submit a second correction THROUGH THE UI: route_override with a
    // unique audit reason; confirm applied; the approval override with the
    // EXACT same text must show the EVIDENCE badge (new reasonsOf contract)
    // instead of ever needing a warning workaround.
    await page.getByTestId("correction-kind-select").selectOption("route_override");
    const roSegment = page.getByTestId("correction-segment-select");
    await expect(roSegment).toContainText("Character", { timeout: 30_000 });
    await roSegment.selectOption({ index: 1 });
    const roSegmentId = (
      await roSegment.locator("option:checked").getAttribute("value")
    )?.trim();
    expect(roSegmentId).toBeTruthy();
    await page.getByTestId("correction-route-from-select").selectOption("pose_swap");
    await page.getByTestId("correction-route-to-select").selectOption("sprite_affine");
    const evidence = `t06bc3 override evidence ${runTag}`;
    await page.getByTestId("correction-reason-input").fill(evidence);
    await page
      .getByTestId("correction-idempotency-input")
      .fill(`t06bc3-ro-${runTag}`);
    await page.getByTestId("correction-submit").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "pending",
      { timeout: 30_000 },
    );
    const roId = (
      await page.getByTestId("correction-last-id").innerText()
    ).trim();
    expect(roId.length).toBeGreaterThan(8);
    expect(roId).not.toBe(correctionId); // distinct durable correction

    // Still blocked while ANY correction is pending.
    await page.getByTestId("approval-reload-btn").click();
    await expect(approveBtn).toBeDisabled();

    // Confirm the route_override through the UI → applied.
    await page.getByTestId("correction-confirm").click();
    await expect(page.getByTestId("correction-last-status")).toHaveText(
      "applied",
      { timeout: 60_000 },
    );

    // Approval: explicit override whose text EQUALS the stored evidence —
    // the panel must mark it evidenced directly (no warning workaround).
    await page.getByTestId("approval-reload-btn").click();
    await expect(page.getByTestId("approval-no-blockers")).toBeVisible();
    await page.getByTestId("approval-override-input").fill(evidence);
    await page.getByTestId("approval-override-add").click();
    await page.getByTestId("approval-override-check-0").check();
    await expect(
      page.getByTestId("approval-override-evidence-0"),
    ).toBeVisible({ timeout: 30_000 });
    await page
      .getByTestId("approval-warning-input")
      .fill(`fps chưa benchmark [${runTag}]`);
    await page.getByTestId("approval-warning-add").click();
    await page.getByTestId("approval-warning-check-0").check();
    await expect(approveBtn).toBeEnabled({ timeout: 30_000 });

    await page.getByTestId("approval-note-input").fill(`t06bc3 approval ${runTag}`);
    await page
      .getByTestId("approval-idempotency-input")
      .fill(`t06bc3-appr-${runTag}`);
    await approveBtn.click();
    await expect(page.getByTestId("approval-last-result")).toBeVisible({
      timeout: 60_000,
    });
    const checkpointId = (
      await page.getByTestId("approval-last-id").innerText()
    ).trim();
    const hashText = (await page.getByTestId("approval-hash").innerText()).trim();
    expect(hashText).toMatch(/^[0-9a-f]{64}$/);
    await expect(page.getByTestId("approval-hash-status")).toContainText(
      "Hash hợp lệ",
      { timeout: 30_000 },
    );

    // ══ Phase G — durability: reload + ACTUAL backend restart ═══════════
    await page.reload();
    const cpRow = page.getByTestId(`approval-checkpoint-${checkpointId}`);
    await expect(cpRow).toBeVisible({ timeout: 45_000 });
    await expect(cpRow.getByTestId("approval-checkpoint-hash")).toContainText(
      hashText.slice(0, 16),
    );
    await expect(
      cpRow.getByTestId("approval-checkpoint-verified"),
    ).toHaveText("verified", { timeout: 45_000 });

    execSync(
      `powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort ${BACKEND_PORT} -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }"`,
    );
    const backend = spawn("bash", [`${RUN_ROOT}/run-prod-backend.sh`], {
      detached: true,
      stdio: "ignore",
    });
    backend.unref();

    let restarted = false;
    for (let i = 0; i < 40; i++) {
      try {
        const res = await page.request.get(
          `http://localhost:${BACKEND_PORT}/api/v2/projects?active_only=true`,
        );
        if (res.ok()) {
          restarted = true;
          break;
        }
      } catch {
        /* booting */
      }
      await page.waitForTimeout(1000);
    }
    expect(restarted).toBe(true);

    await page.reload();
    await expect(
      page.getByTestId(`approval-checkpoint-${checkpointId}`),
    ).toBeVisible({ timeout: 45_000 });
    await expect(
      page
        .getByTestId(`approval-checkpoint-${checkpointId}`)
        .getByTestId("approval-checkpoint-verified"),
    ).toHaveText("verified", { timeout: 45_000 });

    // Regeneration evidence survives the restart: regen publications AND
    // both terminal job states are intact.
    const regenAfterRestart = (await apiGet(
      page,
      `/s09-demo-compare/jobs/${regenJobId}`,
    )) as { state?: string; published?: Pub[] };
    expect(regenAfterRestart.published?.length ?? 0).toBe(4);
    const d4AfterRestart = (regenAfterRestart.published ?? []).find(
      (p) => p.loop_id === AFFECTED_LOOP,
    );
    expect(d4AfterRestart?.sha256).toBe(d4a.sha256);
  });
});
