import { test, expect, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";

/**
 * MF-P1-UI-BUILD — the three product P1 UI states against the REAL stack.
 *
 * blocked / success / reopen. Real HTTP only: the canonical production backend
 * (app.api.app) with the repo's own seed contract applied to an ISOLATED temp
 * root (MF-P1-UI-BUILD never touches the user DB), and this tree's production
 * build (`next start`) served on loopback. The seed rows are created by the
 * repo's own frontend/e2e/s12-export-seed.py (repo/domain code + real ffmpeg
 * media), not by SQL written here.
 */

const FE = process.env.P1UI_FE_BASE ?? "http://127.0.0.1:3111";
const ISO_ROOT =
  process.env.P1UI_ISO_ROOT ?? "C:/Users/Admin/AppData/Local/Temp/mf_p1ui_iso";

interface Seed {
  case: string;
  project_id: string;
  project_blocked_id: string;
  video_ready: string;
  video_blocked: string;
  pending_run_id: string;
  completed_run_id: string;
}

test.describe.configure({ mode: "serial" });

let seed: Seed;

test.beforeAll(() => {
  seed = JSON.parse(
    fs.readFileSync(path.join(ISO_ROOT, "seed.json"), "utf8"),
  ) as Seed;
  expect(seed.project_id).toBeTruthy();
  expect(seed.completed_run_id).not.toEqual(seed.pending_run_id);
});

/** The pre-fix failure mode must not appear in the browser console either. */
function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  return errors;
}

function expectNoSuspenseBailout(errors: string[]): void {
  const bailout = errors.filter((text) =>
    /useSearchParams|missing-suspense-with-csr-bailout/i.test(text),
  );
  expect(bailout, `useSearchParams/Suspense bailout errors: ${JSON.stringify(bailout)}`).toEqual([]);
}

/** AppNav (the component that owns the new Suspense boundary) hydrated. */
async function expectNavHydrated(page: Page): Promise<void> {
  await expect(page.getByRole("navigation", { name: "Điều hướng chính" })).toBeVisible();
}

test("state BLOCKED — real server refusals, no authority => fail-closed, nothing submittable", async ({
  page,
  request,
}) => {
  const errors = watchConsole(page);

  // Server truth first: the blocked project really is refused by the API.
  const ctx = await request.get(
    `${process.env.P1UI_API_BASE ?? "http://127.0.0.1:8888"}/api/v2/projects/${seed.project_blocked_id}/export/context?video_item_id=${seed.video_blocked}`,
  );
  expect(ctx.status()).toBe(200);
  const ctxBody = (await ctx.json()) as { reasons: string[]; checkpoint: unknown; full_apply_run_id: string | null };
  expect(ctxBody.reasons).toContain("S12_EXPORT_FULL_APPLY_MISSING");
  expect(ctxBody.checkpoint).toBeNull();
  expect(ctxBody.full_apply_run_id).toBeNull();

  await page.goto(
    `${FE}/export?project=${seed.project_blocked_id}&video=${seed.video_blocked}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  const reasons = page.getByTestId("export-context-reasons");
  await expect(reasons).toBeVisible();
  await expect(reasons).toContainText("S12_EXPORT_FULL_APPLY_MISSING");
  // Fail-closed: without server authority neither preflight nor submit is reachable.
  await expect(page.getByTestId("export-preflight")).toBeDisabled();
  await expect(page.getByTestId("export-submit")).toBeDisabled();
  // Fail-closed: without server authority the panel never offers an eligible
  // export — no ELIGIBLE marker anywhere in the panel.
  await expect(page.getByTestId("export-panel")).not.toContainText("ELIGIBLE");

  await expectNavHydrated(page);
  expectNoSuspenseBailout(errors);
});

test("state SUCCESS — completed run renders server-owned evidence and identity", async ({
  page,
}) => {
  const errors = watchConsole(page);
  const runId = seed.completed_run_id;

  await page.goto(
    `${FE}/export?run=${runId}&project=${seed.project_id}&video=${seed.video_ready}`,
  );
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(runId.slice(0, 8));

  const evidence = page.getByTestId("export-evidence");
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText(/COMPLETED/i);
  await expect(page.getByTestId("export-progress")).toBeVisible();

  await expectNavHydrated(page);
  expectNoSuspenseBailout(errors);
});

test("state REOPEN — reload and a wiped localStorage keep the SAME server-owned run", async ({
  page,
}) => {
  const errors = watchConsole(page);
  const runId = seed.pending_run_id;
  const url = `${FE}/export?run=${runId}&project=${seed.project_id}&video=${seed.video_ready}`;

  await page.goto(url);
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(runId.slice(0, 8));
  await expect(page.getByTestId("export-progress")).toBeVisible();

  // reopen #1 — plain reload
  await page.reload();
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(runId.slice(0, 8));
  await expect(page.getByTestId("export-progress")).toBeVisible();

  // reopen #2 — localStorage is pointer-only: wiping it then reopening the same
  // URL must still resolve the SAME server run (no local authority, no fork).
  await page.evaluate(() => localStorage.clear());
  await page.goto(url);
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(runId.slice(0, 8));

  // reopen #3 — deep link with NO run pointer at all: the panel falls back to
  // the persisted last selection (localStorage pointer written by reopen #2)
  // and must show that SAME run — never a forked or empty panel, and never a
  // client-invented run id.
  await page.goto(`${FE}/export?project=${seed.project_id}&video=${seed.video_ready}`);
  await expect(page.getByTestId("export-panel")).toBeVisible();
  await expect(page.getByTestId("export-run-id")).toContainText(runId.slice(0, 8));

  await expectNavHydrated(page);
  expectNoSuspenseBailout(errors);
});
