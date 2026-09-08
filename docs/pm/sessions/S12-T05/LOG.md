# S12-T05 LOG — Export UI (preflight → submit → status → cancel/retry → evidence)

Task: S12-T05 | Worktree: `s12-s12-t05-0907a` | Branch: `codex/s12/s12-t05-0907a`
Baseline: `16598ea` (W4: T03C merged, gate 133 passed) | Date: 2026-09-07
Owner: T05 duy nhất | Backend T03C read-only (không sửa 1 dòng production).

## Writes (allowlist frontend-only, 11 files +2158/-1, commit 030553b)

1. `frontend/src/lib/s12-export-api.ts` (423 dòng)
   - Typed client cho preflight/submit/status/cancel/retry + status/payload
     types (run, chunks, evidence). Không mock, gọi real API qua
     `NEXT_PUBLIC_API_URL`.
2. `frontend/src/components/export/ExportPanel.tsx` (486 dòng)
   - Full flow: preflight → submit → poll status → cancel/retry →
     evidence. Helper tiếng Việt dưới mọi button (text-gray-400+),
     testids `export-panel`, `export-run-id`, `export-submit`.
3. `frontend/src/components/export/ExportProgress.tsx` (235 dòng)
   - Hiển thị run status + chunks + actions cancel/retry, testid
     `export-progress`.
4. `frontend/src/components/export/ExportEvidence.tsx` (118 dòng)
   - Chỉ render khi status server là `completed`; không suy diễn media URL
     từ file path; testid `export-evidence`.
5. `frontend/src/app/(app)/export/page.tsx` (88 dòng)
   - Route `/export`: đọc storage (lazy `useState(()=>readStorage())` theo
     pattern apply — không `set-state-in-effect`), query-string override,
     empty state khi thiếu params (`export-title` + `export-empty`).
6. `frontend/src/components/layout/AppNav.tsx` (+1 entry)
   - Thêm `{ href: "/export", label: "Xuất 4K", icon: Clapperboard }`.
     StageRail đã có entry Export sẵn — không sửa.
7. E2E real-API (0 route mocks): `e2e/s12-export.spec.ts` (249 dòng, 8 tests)
   + `e2e/s12-export-seed.py` (339) + `e2e/s12-export-boot.py` (117)
   + `e2e/s12-export-harness.py` (23, test-only mount router T03C unmounted
   trên port riêng) + `playwright.s12-export.config.ts` (78, ports 8415/3015,
   output `%TEMP%/s12t05_pw`, QA root `%TEMP%/s12t05_root`).

## C1 correction (owner 20260907_184514_67a9b5, W5 rows C20/C21/C22)

- P1: Đọc full `HERMES_AUTOPILOT_RULES.md` (277 dòng, SHA256
  `c9b068b2…8f`) trong lượt làm việc — RULES_LOADED, không dùng memory.
- P2: Tip `4a3630a` + porcelain sạch đã verify trước mọi sửa đổi.
- P4: Fetch read-only W4 `9a91e18` (mount router + handler registration);
  `merge-base --is-ancestor` = NOT in branch history → GIỮ harness mount
  test-only, không merge/rebase.
- P5: Scope C1 S5 đúng allowlist (spec + docs T05 + evidence C1 root);
  0 file `app/` backend production.
- C20 project-export: đã phủ bởi 8 tests base (không xóa case nào).
- C21 durable-refresh (+1 test): active run → reload → cùng run + progress;
  xóa localStorage → reopen cùng URL → cùng server run (pointer-only).
- C22 result-access (+3 tests): completed → 0 media/download URL suy diễn;
  pending → progress only; stale id → role=alert, không evidence.
- P6: Playwright full 23 passed + 1 skip (deliberate mobile-nav) + T03C
  regression 15/15 tại tree + `tsc --noEmit` exit 0 + `ruff --select F`
  touched scope + `diff-check` 0 + porcelain allowlist-only.

- F1: Router T03C `s12_export` (submit/status/cancel/retry) UNMOUNTED trên
  production app — chỉ `s12_export_preflight` mount. E2E bắt buộc harness
  test-only mount router trên port riêng (pattern S07-boot + S11-seed).
- F2: Preflight profile gate fail-closed cứng (`profile_supported=False`) —
  spec dùng blocked-case (`S12_EXPORT_NOT_READY`) + eligible-case qua pins
  checked; không seed readiness giả.
- F3: T03A natural-key dedupe làm desktop/mobile projects (chung 1 backend/DB)
  collide khi cùng pins → salt lineage theo `project:title` + plan_tail hex
  để mỗi test submit lineage riêng.
- F4: Retry cùng pins converge về winner cũ (`created=False`, trả terminal
  state `cancelled`) — đúng thiết kế T03A; spec assert predecessor linkage
  + status ∈ {pending, cancelled} thay vì `pending` cứng.
- F5: AppNav `hidden md:flex` (desktop-only đúng thiết kế) — nav-link test
  skip trên mobile, route test trực tiếp.
- F6: Thiếu testids phát hiện qua E2E fail thật: `export-title`,
  `export-empty`, `export-run-id` — đã thêm vào page/panel.
- F7: Bg worker pattern chết sau ~15-20' (Claude/Codex 4 lần exit/timeout
  trắng) — page.tsx + AppNav viết inline, E2E viết inline từ recon.
- F8: eslint repo dùng `.eslintrc` cũ, ESLint v9 không đọc (báo migration,
  exit 0) — TSC + Playwright cover chất lượng TS thay thế.
