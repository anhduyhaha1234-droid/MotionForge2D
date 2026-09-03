import { test, expect } from "@playwright/test";

/**
 * S11-T04D Review Queue — real-backend E2E (Scenario D + queue contract).
 *
 * Runs against the task-owned backend (localhost:8413) + frontend
 * (localhost:3013) via playwright.s11t04.config.ts.  Seeds a REAL project:
 * video chain → deterministic extraction (DISCOVER roles) → QC items
 * inserted through QCItemRepository on the QA root DB (Decision A — the
 * HTTP surface is GET-only by construction).
 *
 * Scenario D (acceptance 1): queue → item → gallery frame f role R →
 * correction preview → confirm — WITHOUT ever opening the full timeline.
 */

import {
  apiJson,
  getRole,
  listRoles,
  postAnalyze,
  runExtraction,
  uploadVideo,
  waitChainCompleted,
  VIDEO_PATH,
} from "./s08-t04-helpers";
import { execFileSync } from "child_process";
import path from "path";

test.describe.configure({ mode: "serial" });

const FE = process.env.QA_FE_BASE ?? "http://localhost:3013";
const QA_ROOT =
  process.env.S11T04D_QA_ROOT ??
  "C:/Users/Admin/AppData/Local/Temp/s11t04d_root";

/**
 * Durable uuid project + legacy fs project.json so the REAL analyze chain
 * can run under the uuid id (legacy routes need the fs project file; the
 * QC queue routes require a uuid project id).
 */
async function setupUuidProject(name: string): Promise<{
  projectId: string;
  videoItemId: string;
  sourceSha: string;
}> {
  const durable = (await apiJson("/api/v2/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })) as { project_id: string };
  const projectId = durable.project_id;
  execFileSync(
    "python",
    [path.join(QA_ROOT, "fs_bootstrap.py")],
    {
      env: {
        ...process.env,
        MF_BACKEND_ROOT: path.join(__dirname, "..", ".."),
        MF_ROOT: QA_ROOT,
        MF_PROJECT_ID: projectId,
        MF_PROJECT_NAME: name,
      },
      encoding: "utf8",
    },
  );
  await uploadVideo(projectId, VIDEO_PATH);
  await postAnalyze(projectId);
  const chain = await waitChainCompleted(projectId);
  if (!chain.video_item_id) throw new Error("no video item after chain");
  return {
    projectId,
    videoItemId: chain.video_item_id,
    sourceSha: (chain.source_sha256 as string) ?? "",
  };
}

interface SeedState {
  projectId: string;
  videoItemId: string;
  roleId: string;
  roleName: string;
  occId: string;
  occRev: number;
  roleRev: number;
  frameIndex: number;
  sceneId: string;
  blockerFrameItemId: string;
  blockerExplainItemId: string;
  warningCount: number;
  emptyProjectId: string;
}

const state: Partial<SeedState> = {};

function seedQcItems(): void {
  // Seed script lives OUTSIDE the repo (task temp root) — the repo write-set
  // is allowlist-only; automation/ is forbidden for this task.
  const script = path.join(QA_ROOT, "s11t04d_seed_qc.py");
  const env = {
    ...process.env,
    MF_BACKEND_ROOT: path.join(__dirname, "..", ".."),
    MF_DB_PATH: path.join(QA_ROOT, "data", "motionforge.db"),
    MF_PROJECT_ID: state.projectId!,
    MF_VIDEO_ITEM_ID: state.videoItemId!,
    MF_ROLE_ID: state.roleId!,
    MF_OCC_ID: state.occId!,
    MF_OCC_REV: String(state.occRev!),
    MF_ROLE_REV: String(state.roleRev!),
    MF_FRAME_INDEX: String(state.frameIndex!),
    MF_SCENE_ID: state.sceneId!,
    MF_OUT_JSON: path.join(
      QA_ROOT,
      "seed_out.json",
    ),
  };
  const out = execFileSync("python", [script], { env, encoding: "utf8" });
  const parsed = JSON.parse(out.trim().split("\n").pop()!) as {
    blocker_frame: string;
    blocker_explain: string;
    warnings: number;
  };
  state.blockerFrameItemId = parsed.blocker_frame;
  state.blockerExplainItemId = parsed.blocker_explain;
  state.warningCount = parsed.warnings;
}

test.beforeAll(async () => {
  // Main review project: uuid durable id + REAL analyze chain + extraction.
  const proj = await setupUuidProject(`t04d-review-${Date.now()}`);
  state.projectId = proj.projectId;
  state.videoItemId = proj.videoItemId;
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const roles = await listRoles(proj.videoItemId);
  if (roles.length === 0) throw new Error("deterministic extraction produced no roles");
  // Scenario-D role R: first DISCOVER-produced role with occurrences.
  const role = roles[0];
  state.roleId = role.id;
  state.roleName = role.name;
  const detail = await getRole(role.id);
  const occ = (detail.occurrences ?? [])[0];
  if (!occ) throw new Error("scenario role has no occurrence");
  state.occId = occ.id;
  state.frameIndex = occ.frame_index;
  state.sceneId = occ.scene_id;
  // Revisions are read from the LIVE row (ROLE_CHANGED guard needs exact CAS).
  const live = await getRole(role.id);
  state.roleRev = live.revision;
  state.occRev = Number(
    (live.occurrences ?? []).find((o) => o.id === occ.id)?.revision ?? 1,
  );
  seedQcItems();

  // Empty project (no QC items) for the empty-state test.
  const empty = await setupUuidProject(`t04d-empty-${Date.now()}`);
  state.emptyProjectId = empty.projectId;
});

test("queue default blocker-first + warnings collapsible", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review`);
  await expect(page.getByTestId("queue-loading").or(page.getByTestId("qc-queue"))).toBeVisible();
  await expect(page.getByTestId("qc-queue")).toBeVisible();

  // Blockers first: the two blocker rows visible.
  await expect(page.getByTestId(`qc-row-${state.blockerFrameItemId}`)).toBeVisible();
  await expect(page.getByTestId(`qc-row-${state.blockerExplainItemId}`)).toBeVisible();

  // Warnings collapsed: only the count toggle, no warning row yet.
  const toggle = page.getByTestId("warnings-toggle");
  await expect(toggle).toContainText(`2 cảnh báo`);
  const warningRows = page.locator('[data-testid^="qc-row-"][data-severity="warning"]');
  await expect(warningRows).toHaveCount(0);

  // Expand → warning rows appear; collapse again.
  await toggle.click();
  await expect(warningRows).toHaveCount(2);
  await toggle.click();
  await expect(warningRows).toHaveCount(0);
});

test("queue empty state (real empty project)", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.emptyProjectId}/review`);
  await expect(page.getByTestId("queue-empty")).toBeVisible();
  await expect(page.getByTestId("queue-empty")).toHaveAttribute("role", "status");
});

test("queue loading + error + retry", async ({ page }) => {
  // Loading state (slow the qc-items response).
  await page.route("**/api/v2/projects/**/qc-items**", async (route) => {
    await new Promise((r) => setTimeout(r, 900));
    await route.continue();
  });
  await page.goto(`${FE}/projects/${state.projectId}/review`);
  await expect(page.getByTestId("queue-loading")).toBeVisible();
  await expect(page.getByTestId("queue-loading")).toHaveAttribute("role", "status");
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await page.unroute("**/api/v2/projects/**/qc-items**");

  // Error state (abort) + retry path.
  await page.route("**/api/v2/projects/**/qc-items**", (route) => route.abort());
  await page.goto(`${FE}/projects/${state.projectId}/review`);
  await expect(page.getByTestId("queue-error")).toBeVisible();
  await expect(page.getByTestId("queue-error")).toHaveAttribute("role", "alert");
  await page.unroute("**/api/v2/projects/**/qc-items**");
  await page.getByTestId("queue-retry").click();
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await expect(page.getByTestId(`qc-row-${state.blockerFrameItemId}`)).toBeVisible();
});

test("click item → URL/query khớp item + detail renders canonical info", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await page.getByTestId(`qc-row-${state.blockerFrameItemId}`).click();
  await expect(page).toHaveURL(new RegExp(`[?&]item=${state.blockerFrameItemId}`));
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  // Canonical location + evidence from the REAL navigation payload.
  await expect(page.getByTestId("detail-frame-index")).toContainText(String(state.frameIndex));
  await expect(page.getByTestId("qc-evidence")).toBeVisible();
});

test("Scenario D: queue→item→gallery frame f role R (no full timeline)", async ({ page }) => {
  const navigated: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) navigated.push(frame.url());
  });

  await page.goto(`${FE}/projects/${state.projectId}/review?item=${state.blockerFrameItemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();

  // Navigation deep-link → gallery at frame f + role R.
  const link = page.getByTestId("nav-deeplink");
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  expect(href).toContain("/object-gallery");
  expect(href).toContain(`project=${encodeURIComponent(state.projectId!)}`);
  expect(href).toContain(`video=${encodeURIComponent(state.videoItemId!)}`);
  expect(href).toContain(`frame=${state.frameIndex}`);
  expect(href).toContain(`role=${state.roleId}`);

  await link.click();
  await expect(page).toHaveURL(/\/object-gallery\?.*frame=.*role=/);
  await expect(page.getByTestId("role-detail")).toBeVisible();
  await expect(page.getByTestId("role-detail")).toContainText(state.roleName!);

  // KHÔNG mở full timeline anywhere in the voyage.
  expect(navigated.some((u) => u.includes("/timeline"))).toBe(false);
  expect(navigated.some((u) => u.includes("/apply"))).toBe(false);
});

test("correction dialog hiện ImpactData TRƯỚC confirm", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review?item=${state.blockerFrameItemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();

  await page.getByTestId("correction-open").click();
  const dialog = page.getByTestId("correction-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("role", "dialog");
  await expect(dialog).toHaveAttribute("aria-modal", "true");

  // ImpactData visible BEFORE the confirm button is actionable.
  await expect(dialog.getByTestId("correction-scope")).toBeVisible();
  const confirm = dialog.getByTestId("correction-confirm");
  await expect(confirm).toBeEnabled();
  // Scope report shows the exact affected sets (real backend preview).
  await expect(dialog.getByTestId("correction-scope")).toContainText("Vai trò bị ảnh hưởng");
});

test("confirm → applied + recompute progress không chặn điều hướng", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review?item=${state.blockerFrameItemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  await page.getByTestId("correction-open").click();
  await expect(page.getByTestId("correction-scope")).toBeVisible();
  await page.getByTestId("correction-confirm").click();

  // Applied state inside the dialog.
  await expect(page.getByTestId("correction-applied")).toBeVisible();

  // The queue/detail progress strip (RecomputeStateData) — status region.
  const progress = page.getByTestId("correction-progress");
  await expect(progress).toHaveAttribute("role", "status");

  // Close the modal (backdrop is intentionally modal), then verify the
  // navigation link is enabled and navigates — the long-job progress NEVER
  // blocks navigation (the strip is informational only).
  await page.getByTestId("correction-close").click();
  await expect(page.getByTestId("correction-dialog")).toBeHidden();
  const link = page.getByTestId("nav-deeplink");
  await expect(link).toBeEnabled();
  await link.click();
  await expect(page).toHaveURL(/\/object-gallery\?.*frame=/);
});

test("refresher reloads queue", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  const before = await page.getByTestId("refresher-status").textContent();
  await page.getByTestId("refresh-button").click();
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await expect(page.getByTestId(`qc-row-${state.blockerFrameItemId}`)).toBeVisible();
  await expect(page.getByTestId("refresher-status")).not.toHaveText(before ?? "");
});

test("zero accepted-exception controls (Decision G) + helper text VI under buttons", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.projectId}/review?item=${state.blockerFrameItemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  await page.getByTestId("correction-open").click();
  await expect(page.getByTestId("correction-dialog")).toBeVisible();

  const scan = await page.evaluate(() => {
    const text = document.body.textContent ?? "";
    // Decision G: no button/API copy "chấp nhận rủi ro / accept risk".
    const acceptMatches = text.match(/chấp nhận rủi ro|accept(?:ed)?\s*risk/i);
    const buttons = Array.from(document.querySelectorAll("button"))
      .map((b) => b.textContent ?? "")
      .filter((t) => /chấp nhận|accept/i.test(t));
    return {
      acceptMatches: acceptMatches ? acceptMatches[0] : null,
      acceptButtons: buttons,
      // Helper text under every button (≥11px, gray-400+): buttons must have a
      // following sibling paragraph or be inside a column with an 11px hint.
      buttonsWithoutHelper: Array.from(document.querySelectorAll("button"))
        .filter((b) => b.offsetParent !== null && b.getBoundingClientRect().width > 0)
        .map((b) => {
          const parent = b.parentElement;
          const hint = parent
            ? Array.from(parent.querySelectorAll("p, span")).find((el) => {
                const t = (el.textContent ?? "").trim();
                const fs = parseFloat(getComputedStyle(el).fontSize) || 0;
                const cls = el.className.toString();
                return t.length > 8 && fs >= 11 && (cls.includes("text-gray-400") || cls.includes("text-gray-300") || cls.includes("text-gray-200") || cls.includes("text-zinc-400") || cls.includes("text-zinc-300") || cls.includes("text-[var(--text-muted)]"));
              })
            : null;
          return hint ? null : { text: (b.textContent ?? "").trim().slice(0, 40) };
        })
        .filter((x) => x !== null),
    };
  });

  expect(scan.acceptMatches).toBeNull();
  expect(scan.acceptButtons).toEqual([]);
  expect(scan.buttonsWithoutHelper).toEqual([]);
});