import { test, expect } from "@playwright/test";

/**
 * S11-T05B Readiness UI — real-backend E2E (E2E-02 full UI).
 *
 * Runs against the task-owned backend (localhost:8414) + frontend
 * (localhost:3014) via playwright.s11t05.config.ts.  Seeds REAL durable
 * rows (project/video/check-run/QCItem) through the repository/SQL seed
 * script — the exact fixture shape of the T05A backend tests (JobRepository
 * completion evidence = the T03F orchestrator block; QC items via
 * QCItemRepository; Decision A: no public POST for QC items).
 *
 * The "fix qua correction → auto-ready" journey applies the WS-07 recheck
 * evidence through `recheck_resolved` — THE SAME repository call the
 * orchestrator makes after a fresh run confirms the issue gone
 * (app/services/qc_checks/orchestrator.py:_apply_recheck).  The UI has NO
 * manual "đánh dấu đã sửa" button: readiness flips automatically on the
 * next refresh, and the binary DOM scan proves zero accepted-exception
 * controls (Decision G).
 */

import { execFileSync } from "child_process";
import path from "path";

test.describe.configure({ mode: "serial" });

const FE = process.env.QA_FE_BASE ?? "http://localhost:3014";
const QA_ROOT =
  process.env.S11T05B_QA_ROOT ??
  "C:/Users/Admin/AppData/Local/Temp/s11t05b_root";

interface SeedResult {
  case: string;
  project_id: string;
  blocker_frame?: string;
  blocker_audio?: string;
  video_a?: string;
  video_b?: string;
  video?: string;
  video_never?: string;
  video_failed?: string;
  video_clean?: string;
  video_running?: string;
  warnings?: number;
}

function seedCase(caseName: string, extraEnv: Record<string, string> = {}): SeedResult {
  const script = path.join(QA_ROOT, "s11t05b_seed_readiness.py");
  const env = {
    ...process.env,
    MF_BACKEND_ROOT: path.join(__dirname, "..", ".."),
    MF_DB_PATH: path.join(QA_ROOT, "data", "motionforge.db"),
    ...extraEnv,
  };
  const out = execFileSync("python", [script, caseName], { env, encoding: "utf8" });
  const line = out.trim().split("\n").pop()!;
  return JSON.parse(line) as SeedResult;
}

const state: {
  blocked: SeedResult | null;
  ready: SeedResult | null;
  notrun: SeedResult | null;
  running: SeedResult | null;
} = { blocked: null, ready: null, notrun: null, running: null };

test.beforeAll(async () => {
  state.blocked = seedCase("blocked");
  state.ready = seedCase("ready");
  state.notrun = seedCase("notrun");
  state.running = seedCase("running");
});

test("blocked: panel phản chiếu payload T05A + blocker row icon+code+location+action", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.blocked!.project_id}`);
  await expect(page.getByTestId("readiness-panel")).toBeVisible();

  const status = page.getByTestId("readiness-status");
  await expect(status).toHaveAttribute("data-status", "blocked");
  await expect(status).toContainText("Bị chặn");
  await expect(status).toHaveAttribute("role", "status");

  // Blocker rows: navigate (frame) + explain (audio) — both rows present.
  const rowFrame = page.getByTestId(`blocker-row-${state.blocked!.blocker_frame}`);
  await expect(rowFrame).toBeVisible();
  await expect(rowFrame).toHaveAttribute("data-code", "edge_halo");
  const rowAudio = page.getByTestId(`blocker-row-${state.blocked!.blocker_audio}`);
  await expect(rowAudio).toBeVisible();
  await expect(rowAudio).toHaveAttribute("data-code", "audio_missing");

  // icon + text severity (G3), code, structured location.
  await expect(rowFrame.locator("svg")).toBeVisible();
  await expect(rowFrame).toContainText("Chặn");
  await expect(rowFrame).toContainText("edge_halo");
  await expect(rowFrame.getByTestId(`blocker-location-${state.blocked!.blocker_frame}`)).toContainText("Khung 42");
  await expect(rowFrame.getByTestId(`blocker-location-${state.blocked!.blocker_frame}`)).toContainText("Cảnh 7");
  // reason + action VI from the payload.
  await expect(rowFrame).toContainText("Viền sáng quanh đối tượng");
  await expect(rowFrame).toContainText("mask");
  // navigate action → gallery deep link (G13: frame f + role R, no timeline).
  const action = rowFrame.getByTestId(`blocker-action-${state.blocked!.blocker_frame}`);
  await expect(action).toBeVisible();
  const href = await action.getAttribute("href");
  expect(href).toContain("/object-gallery");
  expect(href).toContain(`project=${encodeURIComponent(state.blocked!.project_id)}`);
  expect(href).toContain(`video=${encodeURIComponent(state.blocked!.video_a!)}`);
  expect(href).toContain("frame=42");
  expect(href).toContain(`role=${encodeURIComponent("role-t05b-a")}`);

  // explain action → action_vi + explain code (missing_job_id), NO dead link.
  const explain = rowAudio.getByTestId(`blocker-explain-${state.blocked!.blocker_audio}`);
  await expect(explain).toBeVisible();
  await expect(explain).toContainText("missing_job_id");
  await expect(explain).toContainText("audio/video");
  // reason code chip still on the row (icon+code, G3).
  await expect(rowAudio).toContainText("audio_missing");
  await expect(rowAudio.locator(`[data-testid^="blocker-action-"]`)).toHaveCount(0);

  // warnings only counted, never listed as blockers.
  await expect(page.getByTestId("readiness-panel")).toContainText("2 cảnh báo");

  // per-video evidence chips: A blocked (2 open blockers), B clean.
  await expect(page.getByTestId(`readiness-video-${state.blocked!.video_a}`)).toHaveAttribute("data-run-state", "completed");
  await expect(page.getByTestId(`readiness-video-${state.blocked!.video_a}`)).toContainText("2 blocker");
  await expect(page.getByTestId(`readiness-video-${state.blocked!.video_b}`)).toHaveAttribute("data-run-state", "completed");
});

test("blocked cũng hiển thị trên review page (nhúng 2 nơi)", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.blocked!.project_id}/review`);
  await expect(page.getByTestId("readiness-panel")).toBeVisible();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "blocked");
});

test("blocked → fix (WS-07 recheck resolve) → auto-ready, KHÔNG nút tay", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.blocked!.project_id}`);
  const panel = page.getByTestId("readiness-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "blocked");

  // NO manual "đánh dấu đã sửa" control exists anywhere in the panel.
  const manual = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll("button")).map(
      (b) => (b.textContent ?? "").trim(),
    );
    const text = (document.body.textContent ?? "").toLowerCase();
    return {
      markButtons: buttons.filter((t) => /đánh dấu|mark.*fixed|đã sửa xong/i.test(t)),
      markCopy: /đánh dấu đã sửa|đánh dấu.*xong|mark.*as.*fixed/i.test(text),
    };
  });
  expect(manual.markButtons).toEqual([]);
  expect(manual.markCopy).toBe(false);

  // Fix qua correction: WS-07 recheck evidence (orchestrator _apply_recheck call)
  // — BOTH blockers must be cleared by recheck evidence; one stays blocked
  // (fail-closed, the panel never overrides).
  seedCase("resolve", {
    MF_PROJECT_ID: state.blocked!.project_id,
    MF_ITEM_ID: state.blocked!.blocker_frame!,
  });
  seedCase("resolve", {
    MF_PROJECT_ID: state.blocked!.project_id,
    MF_ITEM_ID: state.blocked!.blocker_audio!,
  });

  // Auto-ready on refresh — no manual state flip in the UI.
  await page.getByTestId("readiness-refresh").click();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "ready");
  await expect(page.getByTestId("readiness-status")).toContainText("Sẵn sàng");
  await expect(page.getByTestId("readiness-ready")).toContainText("Không còn blocker nào.");
  // Evidence pass: số lượt kiểm tra QC đã chạy (both videos completed).
  await expect(page.getByTestId("readiness-ready-evidence")).toContainText(
    `Tất cả 2/2 video đã chạy kiểm tra QC`,
  );
  await expect(page.getByTestId("readiness-ready-evidence")).toContainText("chính sách v");
  // No blocker rows remain.
  await expect(page.getByTestId("readiness-blockers")).toHaveCount(0);
});

test("not_run hiển thị trung thực 'Chưa chạy kiểm tra' — KHÔNG xanh", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.notrun!.project_id}`);
  await expect(page.getByTestId("readiness-panel")).toBeVisible();
  const status = page.getByTestId("readiness-status");
  await expect(status).toHaveAttribute("data-status", "not_run");
  await expect(status).toContainText("Chưa chạy kiểm tra");
  // NOT green: no emerald tone on the status badge.
  await expect(status).not.toHaveClass(/emerald/);
  await expect(page.getByTestId("readiness-notrun")).toContainText("Chưa chạy kiểm tra");

  // Per-video honest detail: never-run + failed chips.
  await expect(page.getByTestId(`readiness-video-${state.notrun!.video_never}`)).toHaveAttribute(
    "data-run-state",
    "never_run",
  );
  await expect(page.getByTestId(`readiness-video-${state.notrun!.video_never}`)).toContainText(
    "Chưa chạy kiểm tra",
  );
  await expect(page.getByTestId(`readiness-video-${state.notrun!.video_failed}`)).toHaveAttribute(
    "data-run-state",
    "failed",
  );
  await expect(page.getByTestId(`readiness-video-${state.notrun!.video_failed}`)).toContainText(
    "Kiểm tra thất bại",
  );
});

test("long-job 'Đang xử lý lại…' không chặn điều hướng", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.running!.project_id}`);
  await expect(page.getByTestId("readiness-panel")).toBeVisible();

  // Running recheck → long-job status strip (role=status), aggregate stays not_run.
  const longjob = page.getByTestId("readiness-longjob");
  await expect(longjob).toBeVisible();
  await expect(longjob).toHaveAttribute("role", "status");
  await expect(longjob).toContainText("Đang xử lý lại…");
  await expect(page.getByTestId(`readiness-video-${state.running!.video_running}`)).toHaveAttribute(
    "data-run-state",
    "running",
  );

  // Navigation is NOT blocked: the review queue link stays enabled and works.
  const reviewLink = page.getByTestId("project-go-review");
  await expect(reviewLink).toBeEnabled();
  await reviewLink.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${state.running!.project_id}/review`));
  await expect(page.getByTestId("readiness-panel")).toBeVisible();
});

test("error: 'Chưa tính được readiness' + Thử lại phục hồi", async ({ page }) => {
  // Fresh blocked project (the auto-ready test above resolved the shared one).
  const errProj = seedCase("blocked");
  await page.route("**/api/v2/projects/**/readiness", (route) => route.abort());
  await page.goto(`${FE}/projects/${errProj.project_id}`);
  const error = page.getByTestId("readiness-error");
  await expect(error).toBeVisible();
  await expect(error).toHaveAttribute("role", "alert");
  await expect(error).toContainText("Chưa tính được readiness");
  await expect(page.getByTestId("readiness-retry")).toBeVisible();
  await page.unroute("**/api/v2/projects/**/readiness");

  // Retry recovers to a live status.
  await page.getByTestId("readiness-retry").click();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "blocked");
});

test("zero accepted-exception (Decision G) + helper text VI dưới mọi button", async ({ page }) => {
  await page.goto(`${FE}/projects/${state.blocked!.project_id}`);
  await expect(page.getByTestId("readiness-panel")).toBeVisible();

  const scan = await page.evaluate(() => {
    const text = document.body.textContent ?? "";
    const acceptMatches = text.match(/chấp nhận rủi ro|accept(?:ed)?\s*risk/i);
    const buttons = Array.from(document.querySelectorAll("button"))
      .map((b) => b.textContent ?? "")
      .filter((t) => /chấp nhận|accept/i.test(t));
    const buttonsWithoutHelper = Array.from(document.querySelectorAll("button"))
      .filter((b) => b.offsetParent !== null && b.getBoundingClientRect().width > 0)
      .map((b) => {
        const parent = b.parentElement;
        const hint = parent
          ? Array.from(parent.querySelectorAll("p, span")).find((el) => {
              const t = (el.textContent ?? "").trim();
              const fs = parseFloat(getComputedStyle(el).fontSize) || 0;
              const cls = el.className.toString();
              return (
                t.length > 8 &&
                fs >= 11 &&
                (cls.includes("text-gray-400") ||
                  cls.includes("text-gray-300") ||
                  cls.includes("text-gray-200") ||
                  cls.includes("text-zinc-400") ||
                  cls.includes("text-zinc-300") ||
                  cls.includes("text-[var(--text-muted)]"))
              );
            })
          : null;
        return hint ? null : { text: (b.textContent ?? "").trim().slice(0, 40) };
      })
      .filter((x) => x !== null);
    return { acceptMatches: acceptMatches ? acceptMatches[0] : null, acceptButtons: buttons, buttonsWithoutHelper };
  });

  expect(scan.acceptMatches).toBeNull();
  expect(scan.acceptButtons).toEqual([]);
  expect(scan.buttonsWithoutHelper).toEqual([]);
});

test("a11y gates tái dùng bộ T04D (panel readiness)", async ({ page }) => {
  // Fresh blocked project — blocker rows + status blocked (serial state isolation).
  const a11yProj = seedCase("blocked");
  await page.goto(`${FE}/projects/${a11yProj.project_id}`);
  const panel = page.getByTestId("readiness-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "blocked");

  // 1) keyboard-complete: Tab reaches the panel's refresh button.
  await page.keyboard.press("Tab");
  for (let i = 0; i < 60; i++) {
    const active = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? el.getAttribute("data-testid") : null;
    });
    if (active === "readiness-refresh") break;
    await page.keyboard.press("Tab");
  }
  await expect
    .poll(() =>
      page.evaluate(() => {
        const el = document.activeElement;
        return el ? el.getAttribute("data-testid") : null;
      }),
    )
    .toBe("readiness-refresh");

  // 2) touch targets: every visible panel button is ≥40px tall.
  const touch = await page.evaluate(() => {
    const panelEl = document.querySelector('[data-testid="readiness-panel"]');
    if (!panelEl) return { bad: ["no panel"] };
    return Array.from(panelEl.querySelectorAll("button"))
      .filter((b) => b.offsetParent !== null && b.getBoundingClientRect().height > 0)
      .map((b) => ({ h: b.getBoundingClientRect().height, t: (b.textContent ?? "").trim().slice(0, 24) }))
      .filter((r) => r.h < 40);
  });
  expect(touch).toEqual([]);

  // 3) severity ≠ màu: blocker badge has icon + text.
  await expect(panel.locator(`[data-testid="blocker-row-${a11yProj.blocker_frame}"] svg`)).toBeVisible();

  // 4) reduced-motion: no infinite pulse visible after the panel settles.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(panel.locator(".animate-pulse")).toHaveCount(0);

  // 5) zoom 200%: no horizontal overflow.
  await page.evaluate(() => {
    document.body.style.zoom = "2";
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});

test("mobile 390px: panel không tràn ngang", async ({ page }) => {
  // Fresh blocked project (serial isolation — shared blocked was resolved).
  const mobProj = seedCase("blocked");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${FE}/projects/${mobProj.project_id}`);
  const panel = page.getByTestId("readiness-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("readiness-status")).toHaveAttribute("data-status", "blocked");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
});