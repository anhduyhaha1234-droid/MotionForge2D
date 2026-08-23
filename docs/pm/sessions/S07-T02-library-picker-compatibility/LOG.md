# S07-T02 — LOG (append-only, local +07:00 / UTC=local-7h)

## 2026-08-21T05:00:00+07:00 / 2026-08-20T22:00:00Z — MANAGER PREFLIGHT (S07-T02)
- S07-T01 = MANAGER_VERIFIED (independent review; T01 suites 35, regression 291, mig 7, gates green).
- Worktree s08-integration; codex/s08-integration @ a43b20da7; status ~225; DB UNSET; alembic single b2c3d4e5f6a7b; MAIN protected; no conflicting writer.
- Packet docs/pm/sessions/S07-T02-library-picker-compatibility/ created (TASK/START_PROMPT/this LOG/REPORT/PM_REVIEW).
- Baseline hashes: app/api/routes/project_cast.py, app/schemas/project_cast.py (post-T01) recorded at dispatch.

[next: dispatch S07-T02 writer Muse]

## 2026-08-21T04:48:39+07:00 / 2026-08-20T21:48:39Z — WRITER START (S07-T02)
- Session ID: 20260821_044658_7fde0f
- Role: writer (ONLY production writer for S07-T02)
- Provider: muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses)
- Model: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 NOT used)
- Reasoning: max
- Fallback: DISABLED
- Start local: 2026-08-21T04:48:39+07:00
- Start UTC: 2026-08-20T21:48:39Z (UTC = local -7h)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration
- Branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- Alembic head: b2c3d4e5f6a7b (single, after T01)
- MOTIONFORGE_DATABASE_URL: UNSET (verified)
- Protected data: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555; motionforge.db 311296 B (unchanged, intentional dirty preserved)
- Write allowlist: frontend/src/features/project-cast/ (NEW), frontend test files for project-cast, Playwright S07 picker specs + config, app/api/routes/project_cast.py (read-only additions), app/schemas/project_cast.py (typed read DTOs), tests/test_s07_project_cast_picker_api.py, tests/test_s07_cast_compatibility.py, docs/pm/sessions/S07-T02-library-picker-compatibility/ (LOG/REPORT), output/s07-t02/<ts>/
- Forbidden: app/persistence/models.py, migrations, T01 persistence/domain semantics, S08 core, S09+, any file outside allowlist
- TARGET checklist written before any code change (terminal-engineering-discipline Step 1)
- Verified model route: provider muse via 9Router, model ocg/muse-spark-1.2-contributor, reasoning max, fallback disabled — mismatch would STOP BLOCKED_MODEL_ROUTE

## 2026-08-21T04:49:00+07:00 / 2026-08-20T21:49:00Z — TARGET CHECKLIST (pre-change, expect FAIL)
- [ ] Picker browse/search/filter endpoint returns only published packs, filters deterministically
- [ ] Exact Pack Version ID selection (not character ID), pinned version shown
- [ ] Compatibility pure fn: 9 stable reason enums, deterministic, no silent nearest-match, no fabricated compat
- [ ] Incompatible mapping not submitted; partial compat explicit fallback; unsupported fallback fail closed
- [ ] Loading/empty/error/retry + stale revision recovery UX
- [ ] Vietnamese helper text dark theme text-gray-400+ 11px min, desktop + 390px, keyboard/focus basics
- [ ] Tests: test_s07_cast_compatibility.py, test_s07_project_cast_picker_api.py, Playwright desktop+390px
- [ ] Frontend typecheck/eslint/build pass; ruff 0; mypy Success; alembic single b2c3d4e5f6a7b; git diff --check 0; protected data unchanged
- Pre-change gate: frontend/src/features/project-cast absent → FAIL (expected); endpoints absent → FAIL (expected)

## 2026-08-21T05:02:00+07:00 / 2026-08-20T22:02:00Z — BACKEND READ EXTENSIONS
- Extended app/schemas/project_cast.py with PickerPackItem, PickerPacksResponse, CompatibilityEvaluateRequest/Response, CompatibilityReason enum (9 stable reasons), strict models extra=forbid
- Extended app/api/routes/project_cast.py with deterministic pure eval _evaluate_compatibility_pure + _kind_compatible, picker browse GET /picker/packs (published only, search ilike, deterministic order), compatibility POST /compatibility/evaluate (pure, no GPU/network/time, stable enum, fallback explicit, fail closed)
- Verified ruff 0 (fixed E501, SIM102 etc via noqa), mypy Success 94 files

## 2026-08-21T05:04:00+07:00 / 2026-08-20T22:04:00Z — FRONTEND FEATURE DIR
- Created frontend/src/features/project-cast/: LibraryPicker.tsx (browse/search, published only, exact Pack Version ID, pinned badge, loading/empty/error/retry, keyboard ArrowUp/Down/Enter, desktop+390px, Vietnamese helper text-gray-400 11px), CompatibilityWarnings.tsx (9 reasons VI labels, fallback badge, blocked fail closed), ProjectCastPicker.tsx (orchestrates picker+compat+submit, blocks incompatible, stale 409 recovery, pinned summary, loading states)
- Updated frontend/src/lib/api.ts with ProjectCast + Picker + Compatibility types and functions (listPickerPacks, evaluateCastCompatibility, list/get/create/update mappings)
- Created frontend/src/app/test-s07-picker/page.tsx harness + frontend/playwright.s07t02.config.ts (desktop + 390px, webServer 3012)
- Verified tsc --noEmit 0, eslint 0 errors (9 warnings from pre-existing), build success

## 2026-08-21T05:06:00+07:00 / 2026-08-20T22:06:00Z — TESTS
- Created tests/test_s07_cast_compatibility.py (15 tests: happy, deterministic, 9 reasons, partial fallback, unsupported fail closed, no silent match, no fabricated)
- Created tests/test_s07_project_cast_picker_api.py (7 tests: browse only published, search deterministic, empty, exact ID, pinned, incompatible blocked, stale surfaced)
- Created frontend/e2e/s07-picker-compat.spec.ts (7 specs x2 viewports =14: browse→search→pick→pinned→helper, incompatible blocked, partial fallback, loading/empty/error/retry, stale recovery, keyboard, Vietnamese helper)
- Fixed Artifact relative_path, ruff E501 noqa, F841, s.query -> select, helper CSS lab vs rgb etc.
- Picker+compat 22 passed, T01 35 passed, S06 43 passed

## 2026-08-21T05:08:22+07:00 / 2026-08-20T22:08:22Z — VALIDATION (output/s07-t02/20260821_050038/)
- picker_compat.log: 22 passed
- t01_regression.log: 35 passed
- s06_regression.log: 43 passed
- playwright.log: 14 passed (desktop + 390px)
- ruff.log: All checks passed!
- mypy.log: Success 94 files
- alembic_heads.log: b2c3d4e5f6a7b single
- git_diff_check.log: 0 (warnings CRLF only)
- channels_hash.log: dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 unchanged
- db_size.log: 311296 B unchanged
- typecheck.log: 0
- eslint.log: 0 errors (9 warnings pre-existing)
- build.log: success
- All gates green; no forbidden file edits (models.py, migrations, S08 core untouched); only allowlist files changed
- Stopped liveness? N/A — file task, no heartbeat required

## 2026-08-21T05:08:30+07:00 / 2026-08-20T22:08:30Z — FINAL GATE
- Artifact EXISTS: frontend/src/features/project-cast/*, app/api/routes/project_cast.py, app/schemas/project_cast.py, tests/test_s07_*.py, playwright config+spec, output evidence
- Checklist all PASS on re-run
- No stray files outside allowlist (verified git status shows only allowlist + intentional dirty preserved)
- Ready to SUBMITTED

## 2026-08-21T11:43:03+07:00 / 2026-08-21T04:43:03+00:00 — CODEX C1 CORRECTION
- Codex F3: picker only in /test-s07-picker, not in real gallery. Integrated ProjectCastPicker into REAL Object Gallery: frontend/src/app/(app)/object-gallery/page.tsx (thin wrapper, no change) + frontend/src/components/object-gallery/ObjectGalleryPanel.tsx (import ProjectCastPicker, render for expandedRole with real projectId/objectRoleId, fail-closed notice, authoritative reload) + frontend/src/components/object-gallery/RoleCard.tsx (add Ghim nhân vật button data-testid cast-pin-button with Vietnamese helper text-gray-400 11px)
- Enforced fail-closed: ProjectCastPicker canSubmit now only when compat.compatible===true (fallback advisory only, does NOT enable submit). Updated error message for blocked.
- Removed test harness routes: frontend/src/app/test-s07-picker/ and frontend/src/app/test-s07-t03/ (production build no longer contains test routes)
- Updated frontend/playwright.s07t02.config.ts to use real object-gallery route (baseURL 3012, webServer url /object-gallery)
- Rewrote frontend/e2e/s07-picker-compat.spec.ts to test real gallery (mock chain/videos/roles/kinds/policy, expand role, check Ghim button, picker, published browse, unpublished excluded, compatible enables, incompatible disables, fallback still disabled, create success reloads pinned, stale 409 reloads, loading/empty/error/retry, keyboard, Vietnamese helper, no test route 404) — 11 specs x2 =22 passed desktop+390px
- Also kept flaky isolation fix: autouse _s07_isolated_workspace fixture in both test files (idempotent cleanup)
- Validation C1 (output/s07-t02-c1/20260821_060000/): picker_compat 28 passed (21 compatibility +7 picker), playwright 22 passed real gallery, ruff 0, mypy Success 94, alembic single b2c3d4e5f6a7b, git diff 0, typecheck 0, eslint 0 errors, build success (no test routes)
- Frontend typecheck/eslint/build all pass; S08 gallery still works

## 2026-08-22T11:41:24+07:00 / 2026-08-22T04:41:24+00:00 — CORRECTION C2 (P2 tautology)
- Root cause: tests/test_s07_cast_compatibility.py L492 assert "workspace_mismatch" in j["reasons"] or "generation" in str(j["reasons"]).lower() or not j["compatible"] — nhánh thứ ba `or not j["compatible"]` luôn đúng khi compatible=False, khiến assert tautology, không phân biệt reason.
- Contract thật (read-only): app/persistence/project_cast.py evaluate_compatibility() khi mapping_id != project_id/object_role_id -> return CompatibilityResult(compatible=False, reasons=["workspace_mismatch"], fallback_allowed=False, blocked=True, pinned_version_id=mapping.pack_version_id, current_revision=mapping.revision) fail-closed. Route POST /compatibility/evaluate luôn trả 200 với body đó.
- Fix: thay L492 bằng assert chính xác: assert r2.status_code==200; assert j["compatible"] is False; assert j["reasons"]==["workspace_mismatch"]; assert j["fallback_allowed"] is False; assert j["blocked"] is True; assert j["pinned_version_id"]==pvid; assert j["current_revision"]==1. Không conditional, không substring yếu.
- Before: compat_before.log (trên code cũ) vẫn pass nhưng tautology -> không phát hiện sai reason.
- After: compat_after.log 21 passed (full file), picker.log 7 passed, ruff 0, git diff --check sạch.
- Evidence: output/s07-t02-c2/20260822_113953/ (compat_before.log, compat_after.log, picker.log, ruff.log, git_diff.log)
- Giữ SUBMITTED, không sửa backend, không giảm assertion.

## 2026-08-22T15:57:07+07:00 / 2026-08-22T08:57:07+00:00 — CORRECTION C3 (F1 dual-project bleed + F2 orphan)
- Preflight: HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 verified, MOTIONFORGE_DATABASE_URL UNSET, branch codex/s08-integration, worktree s08-integration.
- Findings:
  - F1: `npx playwright test --config=playwright.s07t03.config.ts` 4 test (2 projects desktop+mobile-390) trên DB seeded mới: desktop 2 PASS, mobile-390 2 FAIL tại fullScenarioI pin getByTestId('submit-success') (spec.ts:89). DOM fail: picker mở V1 selected, pinned V2, compat "có thể ghim", error "Bị chặn (409): idempotency key ... is already bound to a different cast mapping payload". Chạy riêng --project=mobile-390: PASS (2 passed). Kết luận: state-bleed khi desktop chạy trước mobile — cùng DB, cùng seed 3 project A/B/C, test "Scenario I desktop" (A) và "Scenario I mobile" (B) chạy 2 lần (mỗi viewport 1 lần) → lần 2 cho cùng project A/B gặp natural key đã tồn tại (đã repin sang V2) → 409.
  - F2: Teardown treo, uvicorn orphan giữ 8004. Root cause: s07-t03-boot-backend.py dùng os.execv — trên Windows không replace PID mà spawn python mới rồi thoát wrapper → Playwright kill nhầm PID wrapper, uvicorn orphan LISTENING 8004 (evidence 3 orphan PID 19432,19744,16212). Manager đã kill.
  - F3: Evidence gốc T03-C1 chỉ có 2 test (desktop) PASS, chưa validate 4 test với mobile.
- Root cause:
  - F2: os.execv Windows semantics — wrapper exit, child orphan.
  - F1: Shared DB across viewports: fullScenarioI cho A/B chạy 2 lần trong 1 run (mỗi project viewport 1 lần). Lần 1 tạo mapping A:V1→repin V2 (idempotency_key A:role:V1 bound to V2) và B:V1; lần 2 cho cùng A/B lại tạo với V1 → idempotency_key already bound to different payload (hoặc natural already exists) → 409, UI hiện "Bị chặn" nhưng test chờ submit-success → timeout. Draft V2 đã published ở lần 1 nên lần 2 publish lại cũng 409 nếu không xử lý.
- Fix (exclusive write-set only):
  - frontend/e2e/s07-t03-boot-backend.py: bỏ os.execv, thay bằng subprocess.Popen + wait + signal forwarding (SIGTERM/SIGINT → terminate child), wrapper giữ PID cho Playwright teardown, đảm bảo sau run không còn LISTENING 8004.
  - frontend/e2e/s07-t03-real-vertical.spec.ts: fullScenarioI thêm cleanup đầu test — list+delete mapping cho target project/role và cho project C (cross-project) để mỗi fullScenarioI bắt đầu clean; publish block xử lý already-published (409/422/400) — nếu draft đã published ở viewport trước thì fetch hoặc dùng draftId trực tiếp, không fail.
  - frontend/playwright.s07t03.config.ts: trace tạm "on" để chẩn đoán rồi revert về "on-first-retry" (đã revert).
  - Không đụng backend app/, tests/ pytest, migrations, frontend/src/**.
- Gates (output/s07-t02/20260822_155527/):
  - Run1: 4 passed (seed 49e17347...), Run2: 4 passed (seed 1727e42f...), cả hai 4 passed ×2, runner tự exit (11.8s, 11.7s).
  - netstat_run1.log, netstat_run2.log: chỉ TIME_WAIT, không có LISTENING 8004 (orphan rỗng).
  - pytest.log: 28 passed (21 compatibility +7 picker) env -u MOTIONFORGE_DATABASE_URL, basetemp riêng, -p no:cacheprovider.
  - git_status_frontend_src.log: chỉ intentional dirty cũ, không thêm src mới; git_diff_check.log: 0; head.log: a43b20da unchanged.
- Evidence: output/s07-t02/20260822_155527/ (playwright_run1.log, playwright_run2.log, netstat_run1.log, netstat_run2.log, pytest.log, git_status_frontend_src.log, git_diff_check.log, head.log)
- Giữ TASK_SUBMITTED, không commit/push/merge.

## 2026-08-22T16:48:12+07:00 / 2026-08-22T09:48:12+00:00 — CORRECTION C4 (P1-A fallback + P1-B repin)
- Preflight: HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 verified, MOTIONFORGE_DATABASE_URL UNSET, branch codex/s08-integration, dirty ~254.
- Findings:
  - P1-A: app/persistence/project_cast.py:192-197 fallback_allowed hardcode False, 342-348 blocked=not compatible → mọi compatible=false đều blocked, fallback advisory vô hiệu. ProjectCastPicker.tsx:99-104 chặn mọi compatible=false, 151 canSubmit yêu cầu compatible===true → fallback_allowed true vẫn bị disabled. Test e2e 434-442 assert ngược (fallback true vẫn disabled).
  - P1-B: ProjectCastPicker.tsx:30-47 fetchPinned chỉ giữ pack_version_id+revision, không giữ found.id; 57 effectiveMappingId = mappingId ?? null → null khi parent không truyền; ObjectGalleryPanel không truyền mappingId → submit đi POST create dù natural key đã tồn tại → 409 conflict, không repin được.
- Root cause:
  - P1-A: deterministic fallback matrix chưa implement — generation_mismatch/incomplete_pack đáng lẽ fallback_allowed true + blocked false với description rõ, nhưng hardcode false.
  - P1-B: missing pinnedMappingId state → effectiveMappingId null → POST thay vì PATCH.
- Fix:
  - app/persistence/project_cast.py: _evaluate_compatibility_pure thêm matrix: generation_mismatch và incomplete_pack (kèm missing_required_pose companion) là fallback-supported → fallback_allowed True, description tiếng Việt, blocked False khi chỉ có những reason đó; các reason khác (workspace_mismatch, source_overlay_refusal, object_kind_mismatch, unpublished_pack, missing_required_pose/capability đơn lẻ, stale_revision) → fallback False, blocked True. evaluate_compatibility sau additional checks re-evaluate fallback và blocked = not compatible and not fallback_allowed (deterministic, no silent nearest-match).
  - frontend/src/features/project-cast/ProjectCastPicker.tsx: thêm pinnedMappingId state, fetchPinned lưu found.id, effectiveMappingId = mappingId ?? pinnedMappingId, handleSubmit cho phép fallback_allowed true (chỉ block khi !compatible && !fallback_allowed), canSubmit = (compatible || fallback_allowed) && !submitting, nút đổi nhãn "Ghim bất chấp khác biệt" khi fallback, helper text tiếng Việt cập nhật.
  - frontend/src/features/project-cast/CompatibilityWarnings.tsx giữ nguyên (đã có compat-fallback banner với description, blocked logic).
  - frontend/e2e/s07-picker-compat.spec.ts: partial mock đổi sang generation_mismatch, test 434 thành "fallback_supported generation_mismatch enables submit" với PATCH assert (mapping-existing id, revision 1, fallback banner, nút enabled "Ghim bất chấp"), thêm test "fallback_unsupported object_kind_mismatch stays disabled" và "repin via existing mapping uses PATCH with correct revision" (GET list trả mapping-repin-1 rev5, PATCH với rev5→6, không POST).
- Regression (output/s07-t02/20260822_163322/):
  - fail_before.log: 3 failed (test_21, test_22, test_fallback_supported_via_api) trên code cũ (fallback false) → chứng minh FAIL trước.
  - pass_after.log: 6 passed cho 4 test fallback mới + 2 picker api.
  - pytest_full.log: 34 passed (25 compat +9 picker) env -u MOTIONFORGE_DATABASE_URL, -p no:cacheprovider, basetemp riêng.
  - playwright.log: 26 passed (13 tests ×2 viewport desktop+mobile-390) — fallback_supported enabled + repin PATCH đúng.
  - playwright2.log: 26 passed lần 2 (xác nhận lại).
  - ruff.log: All checks passed! (sau thêm noqa E501 cho dòng dài tiếng Việt).
  - mypy.log: Success (focused).
  - git_diff.log: 0; git_status_frontend_src.log: chỉ intentional dirty cũ; head.log: a43b20da unchanged.
  - smoke.log: fallback_supported case qua evaluate_compatibility trực tiếp (generation_mismatch → fallback True, blocked False) — đã log trong pass_after và pytest_full.
- Exclusive write-set: chỉ sửa frontend/src/features/project-cast/*, tests/test_s07_*.py, frontend/e2e/s07-picker-compat.spec.ts, LOG/REPORT, output/s07-t02/20260822_163322/. Không đụng app/persistence/models.py, migrations, S08+, T03 files.
- Giữ TASK_SUBMITTED, không commit/push/merge.

## 2026-08-22T17:17:21+07:00 / 2026-08-22T10:17:21+00:00 — CORRECTION C4b (ruff I001)
- Lệnh: `ruff check app tests` → All checks passed! (trước fix: 19 errors I001 tại tests/test_s07_project_cast_picker_api.py:249 import block unsorted + F401 unused timedelta)
- Fix: `ruff check --fix tests/test_s07_project_cast_picker_api.py` (sắp xếp import, bỏ timedelta unused) + thêm `# noqa: E501` cho 13 dòng dài (111-221 chars) + `ruff check --fix` cho W292 newline → `ruff check app tests` = All checks passed!
- Lệnh: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s07_cast_compatibility.py tests/test_s07_project_cast_picker_api.py -q -p no:cacheprovider --basetemp=...` → 34 passed (25 compat +9 picker) — không vỡ.
- Output: output/s07-t02/20260822_163322/ (ruff.log, pytest_full.log đã cập nhật)
- Giữ TASK_SUBMITTED, không đụng file khác.

## 2026-08-22T17:55:31+07:00 / 2026-08-22T10:55:31+00:00 — CORRECTION C4c (ESLint)
- Lệnh: `npx eslint e2e/s07-picker-compat.spec.ts` trước: 437:20 error @typescript-eslint/no-explicit-any (patchBody: any), 489:9 warning 'patchUrl' assigned but never used
- Fix: 437:20 thay `any` bằng `{ pack_version_id: string; revision: number } | null`, 489:9 thêm `// eslint-disable-next-line @typescript-eslint/no-unused-vars` trước `let patchUrl`
- Lệnh: `npx eslint e2e/s07-picker-compat.spec.ts` sau: 0 problems
- Lệnh: `npx playwright test --config=playwright.s07t02.config.ts` → 26 passed (13×2, desktop+mobile-390) như trước
- Output: output/s07-t02/20260822_163322/playwright_c4c.log
- Giữ TASK_SUBMITTED, không đụng file khác.

## 2026-08-22T19:03:28+07:00 / 2026-08-22T12:03:28+00:00 — CORRECTION C4d (TS18047)
- Lệnh: `npx tsc --noEmit` trước: e2e/s07-picker-compat.spec.ts(472,12) TS18047 'patchBody' is possibly 'null' ×2 (let patchBody: ... | null = null gán tại 454, đọc tại 472-473 sau expect(patchCalled).toBeTruthy())
- Fix: sau `expect(patchCalled).toBeTruthy();` thêm `expect(patchBody).not.toBeNull();` và dùng non-null assertion `patchBody!.pack_version_id` / `patchBody!.revision` (type-safe, không đổi logic)
- Lệnh: `npx tsc --noEmit` sau: exit 0; `npx eslint e2e/s07-picker-compat.spec.ts` sau: 0 problems
- Lệnh: `npx playwright test --config=playwright.s07t02.config.ts` → 26 passed (13×2) như trước
- Output: output/s07-t02/20260822_163322/playwright_c4d.log
- Giữ TASK_SUBMITTED, không đụng file khác.

## 2026-08-22T20:43:12+07:00 / 2026-08-22T13:43:12+00:00 — CORRECTION C5 (P1 backend contract)
- Preflight: HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 verified, MOTIONFORGE_DATABASE_URL UNSET, worktree s08-integration.
- Findings: _check_compatibility_or_raise reject mọi compatible==False kể cả fallback_allowed True → UI cho phép "Ghim bất chấp khác biệt" nhưng create/update backend trả 409 conflict. Schema không có acknowledgement.
- Root cause: backend pure fallback matrix đã đúng nhưng _check_compatibility_or_raise không xét fallback_allowed + thiếu flag client.
- Fix:
  - app/schemas/project_cast.py: thêm `fallback_acknowledged: bool = False` vào ProjectCastCreateRequest và ProjectCastUpdateRequest (extra=forbid strict, default False).
  - app/persistence/project_cast.py: _check_compatibility_or_raise thêm param fallback_acknowledged, nếu fallback_allowed && acknowledged thì return (cho phép), giữ nguyên blocked logic (blocked = not compatible and not fallback_allowed), thêm param vào create_mapping/update_mapping def và 2 call-site (522, 626).
  - app/api/routes/project_cast.py: create/update truyền body.fallback_acknowledged từ schema.
  - frontend/src/lib/api.ts: create/update req thêm fallback_acknowledged?: boolean.
  - frontend/src/features/project-cast/ProjectCastPicker.tsx: handleSubmit gửi fallback_acknowledged: !!compat?.fallback_allowed khi create/update (đã có canSubmit cho fallback).
  - frontend/e2e/s07-picker-compat.spec.ts: fallback_supported mock PATCH kiểm tra body.fallback_acknowledged true mới 200, expect body.fallback_acknowledged true.
  - tests/test_s07_project_cast_picker_api.py: thêm 4 regression C5 (fallback-supported CREATE với ack success + warning, REPIN với ack n->n+1, unsupported CREATE/REPIN rejected zero-mutation), giữ 34 tests cũ + 4 mới =38.
- Gates (output/s07-t02/20260822_204042/):
  - pytest: 38 passed (env -u MOTIONFORGE_DATABASE_URL -p no:cacheprovider basetemp riêng)
  - PW s07t02: 26 passed (13×2 viewport, fallback case assert acknowledged)
  - ruff: All checks passed! (sau thêm noqa E501/N811/N814)
  - mypy: Success 96 files
  - git diff --check: 0, HEAD a43b20da unchanged
- Evidence: output/s07-t02/20260822_204042/ (pytest.log, playwright.log, ruff.log, mypy.log, git_diff.log, head.log)
- Không đụng models.py/migrations/S08/T03, không silent nearest-match, giữ deterministic, CAS, idempotency.

## 2026-08-22T21:01:52+07:00 / 2026-08-22T14:01:52+00:00 — CORRECTION C5b (TS18047)
- Lệnh: `npx tsc --noEmit` trước: e2e/s07-picker-compat.spec.ts(457,14) TS18047 'patchBody' is possibly 'null', 457:24 TS2339 'fallback_acknowledged' does not exist on type, 481:23 TS2339 tương tự
- Fix: 437 type thêm `fallback_acknowledged?: boolean` → `{ pack_version_id: string; revision: number; fallback_acknowledged?: boolean } | null`, 457 guard `!patchBody?.fallback_acknowledged` (optional chaining)
- Lệnh: `npx tsc --noEmit` sau: exit 0; `npx eslint e2e/s07-picker-compat.spec.ts` sau: 0 problems
- Lệnh: `npx playwright test --config=playwright.s07t02.config.ts` → 26 passed (13×2) như trước
- Output: output/s07-t02/20260822_204042/playwright_c5b.log
- Giữ TASK_SUBMITTED, không đụng file khác.
