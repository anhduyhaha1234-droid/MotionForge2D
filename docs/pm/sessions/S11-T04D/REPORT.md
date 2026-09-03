# S11-T04D — Worker REPORT (W12)

## 1. Task identity

| Field | Value |
|---|---|
| Task ID | S11-T04D |
| Wave | W12 (song song T05A — FRONTEND; backend không đụng) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t04d-0903w12` |
| Branch | `codex/s11/t04d-0903w12` (local; không push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `a146034d2282d2857fb9aee6d0ca4af3c178efb5` (porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

## 2. Verdict per acceptance criterion (ALL GREEN — 4/4)

**AC1 — Playwright spec xanh: luồng Scenario D mức UI (queue→item→gallery frame f role R→correction preview→confirm) KHÔNG mở full timeline.**
- `s11-t04-review.spec.ts` (9 tests) + `s11-t04-a11y.spec.ts` (8 gates) =
  **17 passed (43.8s)** trên backend/frontend QA RIÊNG (8413/3013, root
  `%TEMP%/s11t04d_root`, output `%TEMP%/s11t04d_pw`).
- Scenario D thật: queue blocker-first → click item (URL `?item=`) → deep
  link `/object-gallery?project&video&frame=<f>&role=<R>` → gallery tự mở
  đúng role (ObjectGalleryPanel additive effect) → correction preview
  (ImpactData) → confirm (create+confirm qua HTTP surface thật) — history
  khẳng định KHÔNG URL nào chứa `/timeline` hoặc `/apply`.
- Queue = API thật (severity=blocker mặc định), warnings collapsible
  ("Xem 2 cảnh báo"), row click → URL/query khớp item (G13), long-job
  recompute progress (RecomputeStateData) hiển thị role="status" và KHÔNG
  chặn điều hướng (nav-deeplink enabled + click được ngay sau applied).

**AC2 — 8 a11y/mobile gates pass từng cái; gate fail = scenario fail.**
1. G1 keyboard-complete — Tab→Enter điều khiển queue→detail→dialog (1.5s)
2. G2 dialog focus management mẫu ConfirmDialog — focus vào, trap, Escape,
   restore về trigger (1.5s)
3. G3 severity ≠ màu — mọi badge có svg + text (1.3s)
4. G4 touch targets — mọi button visible ≥ min-h-10 (40px) (1.5s)
5. G5 role="status"/"alert" — loading status, error alert, progress status (2.4s)
6. G6 reduced-motion — prefers-reduced-motion: 0 infinite animation (1.3s)
7. G7 zoom 200% — không H-overflow, nav-deeplink reachable (1.3s)
8. G8 mobile 390px sheet — không H-overflow, dialog trong viewport + scroll
   nội bộ (1.4s)

**AC3 — Zero accepted-exception control trong DOM (Decision G).**
- Source grep + DOM scan (test 17): 0 khớp
  `accepted_exception|chấp nhận rủi ro|accept[ed]?[ _-]?risk`.

**AC4 — Copy VN verbatim preflightErrors convention; helper VI dưới mọi button đạt contrast đã đo.**
- Copy VN: severity "Chặn/Cảnh báo/Thông tin", reason labels 10 category
  chuẩn, helper text `text-[11px] text-gray-400` dưới MỌI button review
  (24 chỗ); tựa pattern CorrectionScope/preflightErrors (verbatim từ
  backend EXPLAIN_REASONS khi explain).

## 3. Files (allowlist chính xác — git status chỉ gồm 11 file + docs)

| File | Trạng thái | Ghi chú |
|---|---|---|
| `frontend/src/app/(app)/projects/[id]/review/page.tsx` | NEW | queue page: fetch blockers+warnings thật, ?item= deep link, poll non-blocking |
| `frontend/src/app/(app)/projects/[id]/page.tsx` | additive patch | link level-2 "Hàng đợi QC (Review)" (G14 ✓) — baseline `4defd30` → `e98ae7a` |
| `frontend/src/components/review/ReviewQueueList.tsx` | NEW | blocker-first rows, warnings collapsible, progress strip |
| `frontend/src/components/review/ReviewItemDetail.tsx` | NEW | canonical location, evidence, nav action (deep-link/explain), correction entry |
| `frontend/src/components/review/ReviewCorrectionPanel.tsx` | NEW | two-phase dialog (preview→confirm), focus mgmt mẫu ConfirmDialog |
| `frontend/src/components/review/ReviewQueueStates.tsx` | NEW | loading/empty/error/refresher + severity taxonomy (icon+text) |
| `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` | additive patch | effect đọc `?frame=&role=` → expand đúng role + scroll — baseline `8b63165` → `a1fae0a` |
| `frontend/src/lib/api.ts` | additive patch | listQcItems/getQcItem/getQcNavigation/buildQcCorrectionRequest — baseline `ddf23be` → `fcfaa51` |
| `frontend/playwright.s11t04.config.ts` | NEW | ports/roots riêng, outputDir task-owned |
| `frontend/e2e/s11-t04-review.spec.ts` | NEW | Scenario D + states + Decision G |
| `frontend/e2e/s11-t04-a11y.spec.ts` | NEW | 8 gates |

Không glob nào khác bị đụng: backend app/** = 0, AppNav/globals.css/
ConfirmDialog/CorrectionScope = untouched (consume pattern only), MAIN/s08/s11-integration = read-only.

## 4. Evidence (raw)

- `frontend/`: `npx tsc --noEmit` → exit 0 (sạch).
- `npx eslint` (11 file scope) → exit 0 (0 error, 0 warning).
- `npx next build --webpack` → `✓ Compiled successfully in 9.1s`, TypeScript
  pass, routes gồm `ƒ /projects/[id]/review`.
- Playwright `-c playwright.s11t04.config.ts` → **17 passed (43.8s)**,
  stdout raw lưu terminal (xem LOG + final_run.txt task-owned).
- Binary scans: accept-exception grep = 0; `data-severity` badges có svg+text;
  helper text 24 chỗ `text-[11px] text-gray-400`.
- Isolation: backend QA root `%TEMP%/s11t04d_root` (DB riêng), ports
  8413/3013 riêng, output `%TEMP%/s11t04d_pw`; KHÔNG ghi `frontend/test-results`;
  node_modules chỉ đọc; `.next` nằm trong worktree task (git-ignored).

## 5. Isolation flags

`--basetemp`/outputDir = `%TEMP%/s11t04d_pw`; backend `MOTIONFORGE_QA_MODE=1`
+ `MOTIONFORGE_ROOT=%TEMP%/s11t04d_root` (bắt buộc explicit), extraction
deterministic, CORS 3013 (pattern S08 run-qa-backend). Frontend `--webpack`
(junction node_modules — Turbopack panic, xem LOG). Seed scripts NẰM NGOÀI
repo (`%TEMP%/s11t04d_root/`) — không đụng `automation/`.

## 6. Ngoài scope (báo manager — KHÔNG tự sửa)

1. `GET /api/v2/projects/{project_id}/qc-items` ràng buộc `{project_id:uuid}`;
   project tạo qua legacy API có id 12-char → không có hàng đợi QC. Review
   UI chỉ phục vụ durable-uuid projects (durable POST /api/v2/projects).
   E2E seed dùng durable uuid + fs project.json bootstrap (legacy chain thật).
2. Turbopack (dev+prod default) panic với junction node_modules của worktree
   → mọi frontend task sau cần `--webpack` (hoặc manager đổi cách share
   node_modules).

## 7. Verdict

ALL GREEN — TASK_SUBMITTED. Commit local duy nhất trên `codex/s11/t04d-0903w12`
(SHA ghi trong LOG + session registry manager nhé).