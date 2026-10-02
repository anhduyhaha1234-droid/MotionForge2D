/**
 * M1-01 — MF-END-10 · kho trống → tạo nhân vật → phiên bản nháp → reload còn nguyên.
 *
 * Spec này chạy trên CẶP QA đã pin và KHÔNG dùng config của repo:
 *   UI  http://127.0.0.1:3071   (Next 16.2.12 dev server của worktree M1-01)
 *   API http://127.0.0.1:8071   (uvicorn app.main:app, DB QA trống)
 *
 * Vì `playwright.config.ts` là file bị CẤM sửa và baseURL của nó là
 * localhost:3000, spec dùng URL tuyệt đối + chặn mọi request ra ngoài cặp QA
 * (assert danh sách host bị chặn = rỗng, nên lọt ra ngoài là FAIL).
 *
 * Bằng chứng ghi vào `M1_EVIDENCE_DIR` (evidence root của task), gồm screenshot,
 * network method+URL+status+ID và console. Không mock happy path: mọi thao tác
 * tạo dữ liệu đi qua public API thật.
 *
 * Spec phải BẮT ĐƯỢC revert patch: các assertion về CTA + 2 lời gọi POST thật
 * sẽ fail nếu thiếu CTA/caller. Test static-only không đủ nên không dùng.
 */

import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const UI = "http://127.0.0.1:3071";
const API = "http://127.0.0.1:8071";
const EV = process.env.M1_EVIDENCE_DIR ?? "C:/Users/Admin/AppData/Local/Temp/mfm1-01-20260930/probe";

mkdirSync(EV, { recursive: true });

interface NetRow {
  method: string;
  url: string;
  status: number;
  requestIds: Record<string, string>;
  test: string;
}

const net: NetRow[] = [];
const blocked: string[] = [];
const consoleRows: string[] = [];

function uniqueCode(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}

/** Cho phép duy nhất cặp QA; mọi host khác bị abort và ghi lại. */
async function pinQaPair(page: Page): Promise<void> {
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
    if (url.startsWith(UI) || url.startsWith(API)) return route.continue();
    blocked.push(url);
    return route.abort();
  });
}

function capture(page: Page, tag: string): void {
  page.on("console", (message) => consoleRows.push(`[${tag}] ${message.type()}: ${message.text()}`));
  page.on("response", async (response) => {
    const url = response.url();
    if (!url.startsWith(API)) return;
    const request = response.request();
    const ids: Record<string, string> = {};
    try {
      const body = await response.json();
      for (const key of ["id", "character_id", "version_id", "job_id"] as const) {
        if (body && typeof body === "object" && key in body) {
          ids[key] = String((body as Record<string, unknown>)[key]);
        }
      }
    } catch {
      /* body không phải JSON (ví dụ 204) — bỏ qua */
    }
    net.push({ method: request.method(), url, status: response.status(), requestIds: ids, test: tag });
  });
}

function flushEvidence(): void {
  writeFileSync(join(EV, "browser_network.jsonl"), net.map((r) => JSON.stringify(r)).join("\n") + "\n");
  writeFileSync(join(EV, "browser_console.txt"), consoleRows.join("\n") + "\n");
  writeFileSync(join(EV, "browser_blocked_hosts.json"), JSON.stringify(blocked, null, 1));
}

test.afterAll(() => flushEvidence());

async function step(page: Page, tag: string, name: string): Promise<void> {
  await page.screenshot({ path: join(EV, `shot_${tag}_${name}.png`), fullPage: true });
}

/**
 * Chờ React thực sự sở hữu node trước khi click.
 *
 * Đo được (probe_click.js): trên dev server, HTML được SSR trước khi bundle
 * hydrate xong, nên click đầu tiên rơi vào DOM chưa có listener và bị MẤT
 * (`before=0, afterFirst=0, afterSecond=1`). Đây là hành vi thật của dev;
 * harness phải chờ hydrate, nếu không sẽ báo lỗi giả ở AC1b/AC2/AC3.
 * Tiêu chí: node mang expando `__reactFiber$*` do React gắn khi hydrate.
 */
/** Đưa runtime về "kho trống" bằng route archive thật (không đụng SQL). */
async function archiveAllVisible(page: Page): Promise<void> {
  const list = await page.request.get(`${API}/api/v2/characters?limit=200`);
  expect(list.status()).toBe(200);
  const body = (await list.json()) as {
    characters: { id: string; revision: number }[];
  };
  for (const character of body.characters) {
    const archived = await page.request.post(
      `${API}/api/v2/characters/${character.id}/archive`,
      { data: { revision: character.revision } },
    );
    expect(archived.status()).toBe(200);
  }
}

async function waitForHydration(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="create-character-cta"]');
    if (el === null) return false;
    return Object.keys(el).some((key) => key.startsWith("__reactFiber$"));
  }, null, { timeout: 20_000 });
}

/* ── AC1a: precondition "kho trống" (reproduce của defect thiếu CTA) ─────── */

test("AC1a · DB trống → trạng thái rỗng trung thực + CTA tạo nhân vật", async ({ page }) => {
  await pinQaPair(page);
  capture(page, "AC1a");

  // Khôi phục precondition "kho trống" bằng PUBLIC API (không seed SQL): lưu
  // trữ mọi nhân vật còn hiển thị. Nhờ vậy row này lặp lại được trên cùng một
  // runtime thay vì phụ thuộc thứ tự chạy.
  await archiveAllVisible(page);

  const before = await page.request.get(`${API}/api/v2/characters`);
  expect(before.status()).toBe(200);
  const beforeBody = (await before.json()) as { total: number };
  // Tiền đề "kho trống" của M1-01. Trên bản CHƯA patch, khối rỗng này chỉ có
  // câu "Nhân vật và bộ tư thế sẽ xuất hiện tại đây sau khi được tạo" và KHÔNG
  // có nút nào — hai assertion CTA ngay dưới là thứ bắt được revert đó.
  expect(beforeBody.total).toBe(0);

  await page.goto(`${UI}/characters`, { waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();

  // Kho trống → copy trung thực + CTA chính (revert patch làm 2 dòng này đỏ).
  await expect(page.getByText("Chưa có nhân vật nào")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("create-character-cta")).toBeVisible();
  await expect(page.getByTestId("create-character-empty-cta")).toBeVisible();
  await step(page, "AC1a", "01_empty_with_cta");

  expect(blocked).toEqual([]);
});

/* ── AC1b: identity → draft → đúng ID → reload (không cần DB trống) ──────── */

test("AC1b · tạo identity + phiên bản nháp, chọn đúng ID, reload còn nguyên", async ({ page }) => {
  await pinQaPair(page);
  capture(page, "AC1b");

  await page.goto(`${UI}/characters`, { waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();

  const cta = page.getByTestId("create-character-cta");
  await expect(cta).toBeVisible();
  await cta.click();
  const dialog = page.getByTestId("create-character-dialog");
  await expect(dialog).toBeVisible();
  await step(page, "AC1b", "02_dialog_open");

  const code = uniqueCode("m1a1");
  const name = "Nhân vật M1 AC1";
  await page.getByTestId("create-character-name").fill(name);
  await page.getByTestId("create-character-code").fill(code);
  await page.getByTestId("create-character-description").fill("tạo qua UI, không dùng shell");

  const identityCall = page.waitForResponse(
    (r) => r.url() === `${API}/api/v2/characters` && r.request().method() === "POST",
  );
  await page.getByTestId("create-character-submit").click();
  const identityResponse = await identityCall;
  expect(identityResponse.status()).toBe(201);
  const identity = (await identityResponse.json()) as { id: string; code: string };
  expect(identity.code).toBe(code);

  await expect(page.getByTestId("create-character-identity-id")).toContainText(identity.id);
  await step(page, "AC1b", "03_identity_created");

  const versionCall = page.waitForResponse(
    (r) => r.url() === `${API}/api/v2/characters/${identity.id}/versions`,
  );
  await page.getByTestId("create-version-submit").click();
  const versionResponse = await versionCall;
  expect(versionResponse.status()).toBe(201);
  const version = (await versionResponse.json()) as { id: string; version: number };
  expect(version.id).toBeTruthy();

  await expect(page.getByTestId("create-version-id")).toContainText(version.id);
  await step(page, "AC1b", "04_version_created");

  // Hộp thoại CHỦ ĐỘNG không tự đóng để người dùng đọc lại ID; đóng bằng nút Xong.
  await expect(dialog).toBeVisible();
  await page.getByTestId("create-character-done").click();
  await expect(dialog).toHaveCount(0);

  // Hiển thị ĐÚNG ID vừa tạo (không đoán versions[0]).
  const result = page.getByTestId("created-result");
  await expect(result).toBeVisible();
  await expect(page.getByTestId("created-character-id")).toContainText(identity.id);
  await expect(page.getByTestId("created-version-id")).toContainText(version.id);
  const detail = page.getByRole("region", { name: `Chi tiết nhân vật ${name}` });
  await expect(detail).toBeVisible();
  await step(page, "AC1b", "05_selected_created");

  // Reload: identity + version còn nguyên, đọc lại từ server.
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();
  const search = page.getByRole("searchbox", { name: "Tìm kiếm nhân vật" });
  await search.fill(code);
  const card = page.locator(".grid.content-start button[aria-pressed]");
  await expect(card).toHaveCount(1);
  await expect(card.first()).toContainText(name);
  await card.first().click();
  await expect(detail).toBeVisible();
  await expect(
    detail.getByRole("button", { name: new RegExp(`^Phiên bản v${version.version}`) }),
  ).toBeVisible();
  await step(page, "AC1b", "06_after_reload");

  // DB read-only postcheck qua public API.
  const listed = await page.request.get(`${API}/api/v2/characters/${identity.id}/versions`);
  const versions = (await listed.json()) as { id: string }[];
  expect(versions.some((v) => v.id === version.id)).toBe(true);

  expect(blocked).toEqual([]);
});

/* ── AC2: lỗi / retry / double-submit / reconcile ───────────────────────── */

test("AC2 · validate, 409 giữ input, pending chặn double submit, version lỗi giữ character", async ({
  page,
}) => {
  await pinQaPair(page);
  capture(page, "AC2");

  await page.goto(`${UI}/characters`, { waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await page.getByTestId("create-character-cta").click();
  const dialog = page.getByTestId("create-character-dialog");
  await expect(dialog).toBeVisible();

  // (a) field bắt buộc rỗng → lỗi rõ, không gọi API
  const postsBefore = net.filter((n) => n.method === "POST").length;
  await page.getByTestId("create-character-submit").click();
  await expect(page.getByTestId("name-error")).toBeVisible();
  await expect(page.getByTestId("code-error")).toBeVisible();
  await expect.poll(() => net.filter((n) => n.method === "POST").length).toBe(postsBefore);
  await step(page, "AC2", "01_required_errors");

  // (b) mã sai định dạng → lỗi hướng dẫn
  await page.getByTestId("create-character-name").fill("Nhân vật AC2");
  await page.getByTestId("create-character-code").fill("MÃ SAI!");
  await page.getByTestId("create-character-submit").click();
  await expect(page.getByTestId("code-error")).toContainText("chữ thường");
  await step(page, "AC2", "02_bad_code_format");

  // (c) 409 duplicate code → hiện lỗi và KHÔNG mất input
  const dup = uniqueCode("m1dup");
  const seeded = await page.request.post(`${API}/api/v2/characters`, {
    data: { name: "Seeded dup", code: dup },
  });
  expect(seeded.status()).toBe(201);
  const seededId = ((await seeded.json()) as { id: string }).id;
  await page.getByTestId("create-character-code").fill(dup);
  await page.getByTestId("create-character-submit").click();
  const identityError = page.getByTestId("create-character-identity-error");
  await expect(identityError).toBeVisible();
  await expect(identityError).toContainText("đã tồn tại");
  await expect(page.getByTestId("create-character-name")).toHaveValue("Nhân vật AC2");
  await expect(page.getByTestId("create-character-code")).toHaveValue(dup);
  await step(page, "AC2", "03_duplicate_409_keeps_input");

  // (d) mã mới → 201; nút bị khoá ngay khi pending (chặn double submit)
  const code = uniqueCode("m1a2");
  await page.getByTestId("create-character-code").fill(code);
  const identityPostsBefore = net.filter(
    (n) => n.url === `${API}/api/v2/characters` && n.method === "POST",
  ).length;
  const identityCall = page.waitForResponse(
    (r) => r.url() === `${API}/api/v2/characters` && r.request().method() === "POST",
  );
  await page.getByTestId("create-character-submit").click();
  const identityResponse = await identityCall;
  expect(identityResponse.status()).toBe(201);
  const identity = (await identityResponse.json()) as { id: string };
  await expect(page.getByTestId("create-character-submit")).toBeDisabled();
  // Bấm lại nút đã khoá không sinh POST thứ hai (so DELTA, không so tổng —
  // tổng còn tính lần POST 409 ở bước (c)).
  await page.getByTestId("create-character-submit").click({ force: true }).catch(() => undefined);
  await expect
    .poll(() =>
      net.filter((n) => n.url === `${API}/api/v2/characters` && n.method === "POST").length,
    )
    .toBe(identityPostsBefore + 1);
  await step(page, "AC2", "04_identity_locked_no_double_post");

  // (e) FAULT INJECTION (có nhãn, KHÔNG tính là happy-path proof): version POST
  // trả lỗi mạng → UI phải vào trạng thái "uncertain" và KHÔNG tự retry.
  await page.route(`${API}/api/v2/characters/${identity.id}/versions`, (route) =>
    route.abort("connectionfailed"),
  );
  await page.getByTestId("create-version-submit").click();
  const uncertain = page.getByTestId("create-version-uncertain");
  await expect(uncertain).toBeVisible();
  // character vẫn còn (không mất, không tạo lại)
  await expect(page.getByTestId("create-character-identity-id")).toContainText(identity.id);
  // không tự retry: đúng 1 lần thử version
  const attempts = net.filter(
    (n) => n.url === `${API}/api/v2/characters/${identity.id}/versions` && n.method === "POST",
  ).length;
  expect(attempts).toBe(0); // bị abort ⇒ chưa có response nào được ghi
  await step(page, "AC2", "05_version_uncertain_no_autoretry");

  // Reconcile: đọc lại versions (0 hoặc 1 tuỳ server) TRƯỚC khi cho retry.
  await page.unroute(`${API}/api/v2/characters/${identity.id}/versions`);
  const listCall = page.waitForResponse(
    (r) =>
      r.url() === `${API}/api/v2/characters/${identity.id}/versions` &&
      r.request().method() === "GET",
  );
  await page.getByTestId("create-version-reconcile").click();
  const listResponse = await listCall;
  expect(listResponse.status()).toBe(200);
  await expect(page.getByTestId("create-version-reconciled")).toBeVisible();
  await step(page, "AC2", "06_reconciled_before_retry");

  // Retry version sau reconcile → 201, character GIỮ NGUYÊN id
  const versionCall = page.waitForResponse(
    (r) =>
      r.url() === `${API}/api/v2/characters/${identity.id}/versions` &&
      r.request().method() === "POST",
  );
  await page.getByTestId("create-version-submit-after-reconcile").click();
  const versionResponse = await versionCall;
  expect(versionResponse.status()).toBe(201);
  const version = (await versionResponse.json()) as { id: string };
  await expect(page.getByTestId("create-version-id")).toContainText(version.id);
  await page.getByTestId("create-character-done").click();
  await expect(page.getByTestId("created-character-id")).toContainText(identity.id);
  await step(page, "AC2", "07_retry_kept_character");

  // Không tạo character trùng: tổng số character tăng đúng 2 (dup seed + AC2).
  const all = await page.request.get(`${API}/api/v2/characters`);
  const allBody = (await all.json()) as { total: number; characters: { id: string }[] };
  const matches = allBody.characters.filter((c) => c.id === identity.id);
  expect(matches.length).toBe(1);
  expect(allBody.characters.filter((c) => c.id === seededId).length).toBe(1);

  expect(blocked).toEqual([]);
});

/* ── AC3: keyboard/focus + narrow layout + hồi quy browse/search/detail ──── */

test("AC3 · keyboard + trả focus + narrow 390px + hồi quy read/search/detail", async ({ page }) => {
  await pinQaPair(page);
  capture(page, "AC3");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${UI}/characters`, { waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await expect(page.getByRole("heading", { name: "Thư viện nhân vật" }).last()).toBeVisible();

  const cta = page.getByTestId("create-character-cta");
  await expect(cta).toBeVisible();

  // Mở bằng bàn phím, focus vào dialog
  await cta.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByTestId("create-character-dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("create-character-name")).toBeFocused();
  await step(page, "AC3", "01_keyboard_open_focus_in");

  // Escape đóng + TRẢ focus về CTA
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(cta).toBeFocused();
  await step(page, "AC3", "02_escape_returns_focus");

  // Narrow: không tràn ngang
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  // Dialog ở narrow cũng không tràn
  await cta.click();
  await expect(dialog).toBeVisible();
  const dialogOverflow = await page.evaluate(() => {
    const panel = document.querySelector('[data-testid="create-character-dialog"] > div');
    if (!panel) return Number.NaN;
    return (panel as HTMLElement).scrollWidth - (panel as HTMLElement).clientWidth;
  });
  expect(dialogOverflow).toBeLessThanOrEqual(1);
  await step(page, "AC3", "03_narrow_no_overflow");
  await page.getByTestId("create-character-close").click();
  await expect(dialog).toHaveCount(0);
  await expect(cta).toBeFocused(); // đóng bằng nút X cũng trả focus

  // Desktop + hồi quy browse/search/detail (assertion tương đương spec cũ,
  // KHÔNG chạy spec cũ vì nó hardcode localhost:8002 + fixture đã seed).
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await expect(page.locator(".grid.content-start button[aria-pressed]").first()).toBeVisible({
    timeout: 15_000,
  });

  const search = page.getByRole("searchbox", { name: "Tìm kiếm nhân vật" });
  const cards = page.locator(".grid.content-start button[aria-pressed]");

  // (b) từ khoá rác → trạng thái rỗng TRUNG THỰC
  await search.fill("zzz_khong_ton_tai_m1");
  await expect(page.getByText("Không tìm thấy nhân vật")).toBeVisible();
  await expect(cards).toHaveCount(0);
  await step(page, "AC3", "04_search_empty_honest");

  // (c) lọc theo mã thật của một fixture CÓ NHÃN (tạo qua public API, không
  // thay thế happy-path DB trống ở AC1)
  const code = uniqueCode("m1reg");
  const created = await page.request.post(`${API}/api/v2/characters`, {
    data: { name: "Fixture hồi quy M1", code },
  });
  expect(created.status()).toBe(201);
  const createdBody = (await created.json()) as { id: string };
  const versionResponse = await page.request.post(`${API}/api/v2/characters/${createdBody.id}/versions`);
  expect(versionResponse.status()).toBe(201);

  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForHydration(page);
  await search.fill(code);
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Fixture hồi quy M1");
  await cards.first().click();
  const detail = page.getByRole("region", { name: "Chi tiết nhân vật Fixture hồi quy M1" });
  await expect(detail).toBeVisible();
  await expect(
    detail.getByRole("button", { name: /^Phiên bản v1/ }),
  ).toBeVisible();
  await expect(detail.getByRole("heading", { name: "Các phiên bản" })).toBeVisible();
  await step(page, "AC3", "05_search_detail_regression");

  // Lọc theo trạng thái vẫn hoạt động (select có nhãn)
  const status = page.getByLabel("Lọc theo trạng thái");
  await status.selectOption("ready");
  await expect(page.getByText("Không tìm thấy nhân vật")).toBeVisible();
  await status.selectOption("all");
  await expect(cards.first()).toBeVisible();
  await step(page, "AC3", "06_status_filter_regression");

  const desktopOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(desktopOverflow).toBeLessThanOrEqual(1);

  expect(blocked).toEqual([]);
});
