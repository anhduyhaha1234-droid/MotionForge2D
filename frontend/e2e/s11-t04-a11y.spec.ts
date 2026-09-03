import { test, expect } from "@playwright/test";

/**
 * S11-T04D — 8 a11y/mobile gates on the Review Queue UI (own project seed).
 *
 * Gates (each test = one gate; gate fail = scenario fail):
 *   1. keyboard-complete       — Tab/Enter drives queue→detail→dialog, no mouse
 *   2. dialog focus management — mẫu ConfirmDialog: focus in on open, trap,
 *                                Escape close, restore to trigger
 *   3. severity ≠ màu          — every severity badge has icon + text
 *   4. touch targets           — all buttons ≥ min-h-10 (40px)
 *   5. role="status"/"alert"   — loading status, error alert, progress status
 *   6. reduced-motion          — prefers-reduced-motion: no infinite animation
 *   7. zoom 200%               — no horizontal overflow, action reachable
 *   8. mobile 390px sheet      — no H-overflow, dialog fits the 390px sheet
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

/** Durable uuid project + legacy fs project.json (real analyze chain). */
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

const a11yState: {
  projectId: string;
  videoItemId: string;
  itemId: string;
  roleId: string;
  roleName: string;
  frameIndex: number;
} = {
  projectId: "",
  videoItemId: "",
  itemId: "",
  roleId: "",
  roleName: "",
  frameIndex: 0,
};

test.beforeAll(async () => {
  const proj = await setupUuidProject(`t04d-a11y-${Date.now()}`);
  a11yState.projectId = proj.projectId;
  a11yState.videoItemId = proj.videoItemId;
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const roles = await listRoles(proj.videoItemId);
  if (roles.length === 0) throw new Error("a11y seed: no roles");
  const role = roles[0];
  a11yState.roleId = role.id;
  a11yState.roleName = role.name;
  const detail = await getRole(role.id);
  const occ = (detail.occurrences ?? [])[0];
  if (!occ) throw new Error("a11y seed: no occurrence");
  a11yState.frameIndex = occ.frame_index;
  const occRev = Number(
    (detail.occurrences ?? []).find((o) => o.id === occ.id)?.revision ?? 1,
  );

  const script = path.join(QA_ROOT, "s11t04d_seed_qc.py");
  const env = {
    ...process.env,
    MF_BACKEND_ROOT: path.join(__dirname, "..", ".."),
    MF_DB_PATH: path.join(QA_ROOT, "data", "motionforge.db"),
    MF_PROJECT_ID: a11yState.projectId,
    MF_VIDEO_ITEM_ID: a11yState.videoItemId,
    MF_ROLE_ID: a11yState.roleId,
    MF_OCC_ID: occ.id,
    MF_OCC_REV: String(occRev),
    MF_ROLE_REV: String(detail.revision),
    MF_FRAME_INDEX: String(occ.frame_index),
    MF_SCENE_ID: occ.scene_id,
    MF_OUT_JSON: path.join(QA_ROOT, "seed_out_a11y.json"),
  };
  const out = execFileSync("python", [script], { env, encoding: "utf8" });
  const parsed = JSON.parse(out.trim().split("\n").pop()!) as { blocker_frame: string };
  a11yState.itemId = parsed.blocker_frame;
});

test("G1 keyboard-complete: queue → detail → dialog, all via keyboard", async ({ page }) => {
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();

  // Tab until the SPECIFIC (correctable) row is focused, then Enter.
  const targetTestId = `qc-row-${a11yState.itemId}`;
  await page.keyboard.press("Tab");
  for (let i = 0; i < 40; i++) {
    const testId = await page.evaluate(
      () => document.activeElement?.getAttribute("data-testid") ?? "",
    );
    if (testId === targetTestId) break;
    await page.keyboard.press("Tab");
  }
  await expect
    .poll(() =>
      page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? ""),
    )
    .toBe(targetTestId);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("qc-detail")).toBeVisible();

  // Tab to "Tạo correction" and open with Enter.
  await page.keyboard.press("Tab");
  for (let i = 0; i < 20; i++) {
    const testId = await page.evaluate(
      () => document.activeElement?.getAttribute("data-testid") ?? "",
    );
    if (testId === "correction-open") break;
    await page.keyboard.press("Tab");
  }
  await expect
    .poll(() =>
      page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? ""),
    )
    .toBe("correction-open");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("correction-dialog")).toBeVisible();
});

test("G2 dialog focus management (mẫu ConfirmDialog): trap + Escape + restore", async ({ page }) => {
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await page.getByTestId(`qc-row-${a11yState.itemId}`).click();
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  await page.getByTestId("correction-open").click();
  const dialog = page.getByTestId("correction-dialog");
  await expect(dialog).toBeVisible();
  // Wait for the ready phase — during preview the footer buttons are all
  // disabled, so the trap has no focusables yet.
  await expect(dialog.getByTestId("correction-confirm")).toBeEnabled();

  // Focus moves INTO the dialog.
  await expect
    .poll(() =>
      page.evaluate(() => {
        const el = document.activeElement;
        return el?.closest('[data-testid="correction-dialog"]') ? "inside" : "outside";
      }),
    )
    .toBe("inside");

  // Tab trap: from the LAST focusable, Tab wraps to the FIRST inside the dialog.
  const wrap = await page.evaluate(() => {
    const d = document.querySelector('[data-testid="correction-dialog"]')!;
    const focusables = Array.from(
      d.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hasAttribute("disabled"));
    (focusables[focusables.length - 1] as HTMLElement).focus();
    // Dispatch on the dialog node (inside the React root) so React's
    // delegated keydown listener sees the synthetic event.
    d.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    return document.activeElement === focusables[0];
  });
  expect(wrap).toBe(true);

  // Escape closes and focus RESTORES to the trigger.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect
    .poll(() =>
      page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? ""),
    )
    .toBe("correction-open");
});

test("G3 severity ≠ màu: icon + text in every severity badge", async ({ page }) => {
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  const badges = page.getByTestId("severity-badge");
  const count = await badges.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const badge = badges.nth(i);
    await expect(badge.locator("svg")).toBeVisible();
    await expect(badge).not.toHaveText("");
  }
});

test("G4 touch targets: every visible button ≥ min-h-10 (40px)", async ({ page }) => {
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await page.getByTestId(`qc-row-${a11yState.itemId}`).click();
  await page.getByTestId("correction-open").click();
  await expect(page.getByTestId("correction-dialog")).toBeVisible();

  const undersized = await page.evaluate(() => {
    const bad: string[] = [];
    for (const b of Array.from(document.querySelectorAll<HTMLElement>("button"))) {
      if (b.offsetParent === null) continue;
      const style = getComputedStyle(b);
      const minH = parseFloat(style.minHeight) || 0;
      const h = parseFloat(style.height) || 0;
      const rect = b.getBoundingClientRect();
      if ((minH < 40 && h < 40) || rect.height < 40) {
        const label =
          (b.textContent ?? "").trim().slice(0, 40) || b.getAttribute("data-testid") || "";
        bad.push(label || b.className);
      }
    }
    return bad;
  });
  expect(undersized).toEqual([]);
});

test("G5 role=status / role=alert present for loading/error/progress", async ({ page }) => {
  await page.route("**/api/v2/projects/**/qc-items**", async (route) => {
    await new Promise((r) => setTimeout(r, 700));
    await route.continue();
  });
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("queue-loading")).toHaveAttribute("role", "status");
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  await page.unroute("**/api/v2/projects/**/qc-items**");

  await page.route("**/api/v2/projects/**/qc-items**", (route) => route.abort());
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("queue-error")).toHaveAttribute("role", "alert");
  await page.unroute("**/api/v2/projects/**/qc-items**");

  // Progress strip (after a confirm starts a recompute) is a status region.
  await page.goto(`${FE}/projects/${a11yState.projectId}/review?item=${a11yState.itemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  await page.getByTestId("correction-open").click();
  await expect(page.getByTestId("correction-scope")).toBeVisible();
  await page.getByTestId("correction-confirm").click();
  await expect(page.getByTestId("correction-progress")).toHaveAttribute("role", "status");
});

test("G6 reduced-motion: no infinite animations under prefers-reduced-motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  const reduced = await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  expect(reduced).toBe(true);
  const infinite = await page.evaluate(() => {
    let n = 0;
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const s = getComputedStyle(el);
      if (s.animationIterationCount === "infinite" && s.animationName !== "none") n++;
    }
    return n;
  });
  expect(infinite).toBe(0);
});

test("G7 zoom 200%: no horizontal overflow, primary action reachable", async ({ page }) => {
  await page.goto(`${FE}/projects/${a11yState.projectId}/review?item=${a11yState.itemId}`);
  await expect(page.getByTestId("qc-detail")).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollW: doc.scrollWidth,
      clientW: doc.clientWidth,
    };
  });
  expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  const link = page.getByTestId("nav-deeplink");
  await expect(link).toBeVisible();
  const box = await link.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(0);
});

test("G8 mobile 390px sheet: no H-overflow, dialog fits viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${FE}/projects/${a11yState.projectId}/review`);
  await expect(page.getByTestId("qc-queue")).toBeVisible();
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return { scrollW: doc.scrollWidth, clientW: doc.clientWidth };
  });
  expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);

  await page.getByTestId(`qc-row-${a11yState.itemId}`).click();
  await page.getByTestId("correction-open").click();
  const dialog = page.getByTestId("correction-dialog");
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390 + 1);
  // Inner scroll: the dialog content must scroll instead of overflowing.
  const innerOk = await page.evaluate(() => {
    const d = document.querySelector('[data-testid="correction-dialog"]');
    if (!d) return false;
    const s = getComputedStyle(d);
    return s.overflowY === "auto" || s.overflowY === "scroll";
  });
  expect(innerOk).toBe(true);
});