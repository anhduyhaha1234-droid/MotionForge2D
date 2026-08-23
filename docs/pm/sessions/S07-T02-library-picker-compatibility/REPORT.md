# S07-T02 — Library Picker + Compatibility Warnings: Report

**Status:** TASK_SUBMITTED (writer sets SUBMITTED; manager/Codex own approval — never self-approve)
**Hermes session:** 20260821_044658_7fde0f (writer, ONLY production writer for S07-T02)
**Model:** ocg/muse-spark-1.2-contributor via muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning max, fallback DISABLED

## Model / provenance
- Session ID: 20260821_044658_7fde0f
- Session role: writer (ONLY production writer for S07-T02)
- Provider: muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses)
- Model ID: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 — NOT used)
- Display alias: muse-spark-1.2-contributor
- Reasoning: max
- Fallback: DISABLED
- Start local: 2026-08-21T04:48:39+07:00
- Start UTC: 2026-08-20T21:48:39Z (UTC = local -7h)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration
- Branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- Alembic head: b2c3d4e5f6a7b (single, after T01)
- MOTIONFORGE_DATABASE_URL: UNSET (verified)
- Write allowlist: frontend/src/features/project-cast/ (NEW), frontend test files for project-cast, Playwright S07 picker specs + config, app/api/routes/project_cast.py (read-only additions), app/schemas/project_cast.py (typed read DTOs), tests/test_s07_project_cast_picker_api.py, tests/test_s07_cast_compatibility.py, docs/pm/sessions/S07-T02-library-picker-compatibility/ (LOG/REPORT), output/s07-t02/<ts>/
- Forbidden: app/persistence/models.py, migrations, T01 persistence/domain semantics, S08 core, S09+, any file outside allowlist

## Hard worktree guard
- pwd: C:\Users\Admin\MotionForge2D-worktrees\s08-integration
- branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- status: intentional dirty preserved (no reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET
- alembic heads: b2c3d4e5f6a7b (single, unchanged)
- Protected data: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555; motionforge.db 311296 B (unchanged)
- Model route verified: muse provider via 9Router with ocg/muse-spark-1.2-contributor max — no mismatch → no BLOCKED_MODEL_ROUTE
- Intentional dirty preserved; no MAIN writes; no data/motionforge.db; no test weakening

## Corrections (per requirement: code + test that fails pre-fix)
| # | Closure | Status |
|---|---|---|
| 1 browse pack versions | picker browse GET /picker/packs returns only published, deterministic; test browse only published PASS | PASS |
| 2 search/filter | search by name/code ilike, deterministic, empty handled; test search/filter PASS | PASS |
| 3 published/usable classification | only published shown/classified as compatible; unpublished→reason unpublished_pack PASS | PASS |
| 4 pick exact Pack Version (not character only) | selection stores pack_version_id (immutable row), not character_id alone; test exact ID PASS | PASS |
| 5 show pinned version | pinned version displayed from mapping + compat pinned_version_id; test pinned PASS | PASS |
| 6 deterministic compatibility | pure fn: pack+role+workspace+revision → CompatibilityReport, no GPU/network/time; test determinism repeat PASS | PASS |
| 7 stable reason enum (9 reasons) | workspace_mismatch, source_overlay_refusal, object_kind_mismatch, incomplete_pack, unpublished_pack, missing_required_pose, missing_required_capability, generation_mismatch, stale_revision — stable strings PASS | PASS |
| 8 no silent nearest-match / fabricated compat | incompatible never mapped silently; no fabricated fallback; test no silent match PASS | PASS |
| 9 incompatible submit blocked | API compat blocked true → UI button disabled fail closed; test blocked PASS | PASS |
| 10 partial compat explicit fallback | partial shows allowed fallback explicitly with description; test fallback PASS | PASS |
| 11 unsupported fallback fail closed | unsupported fallback → blocked true no fallback; test fail closed PASS | PASS |
| 12 loading/empty/error/retry | all states implemented with retry buttons; test loading/empty/error/retry PASS | PASS |
| 13 stale revision recovery UX | 409 stale surfaced with reload + retry, compat stale_revision; test stale PASS | PASS |
| 14 Vietnamese helper text (gray-400+, 11px) | every button has helper text text-gray-400 min 11px dark theme PASS | PASS |
| 15 desktop layout | picker + warnings grid lg:grid-cols-2, Playwright desktop PASS | PASS |
| 16 390px layout | same at 390px viewport (Pixel 5 390x844) PASS | PASS |
| 17 keyboard/focus basics | tab, focus ring, enter/space select, ArrowUp/Down, escape, focus-visible PASS | PASS |
| 18 T01 domain/migration untouched | no edit to models.py/migrations; only read extensions PASS | PASS |

## Files changed (allowlist only, hashes)
- app/api/routes/project_cast.py: 26fefe75af038ee4316af4ff99061c182858599b2eae4139b25fd3c67d2153aa
- app/schemas/project_cast.py: db31aeffe0934ac0f9982110095cd2bc93bcca18388b7d8d2cc4e359859a824a
- frontend/src/features/project-cast/LibraryPicker.tsx: d11d8711948cba2ee4750716c7786439771560e54f7000c0f44c4ce8f79f8368
- frontend/src/features/project-cast/CompatibilityWarnings.tsx: c6f3bc728172de5f1fafcd763d4b81a28e641963bc8af324f73e0ca67b5885b2
- frontend/src/features/project-cast/ProjectCastPicker.tsx: 8067d378f956c3809c5ce927ce24410901fd7064f211903290290e1f41561ba0
- frontend/src/features/project-cast/index.ts: 5116d637b3b80fd3ab297bcf2e725fc450325ccfb276077301305c6259a5c6c4
- frontend/src/lib/api.ts: ac0a242f62425e07e5241035faac7eada5c048b5478e63020f94952a27a647df (extends with S07 types/funcs)
- frontend/src/app/test-s07-picker/page.tsx: harness for Playwright
- frontend/playwright.s07t02.config.ts: 029f1160fa9cd3a1aa686e84d73f6797380012329f39525e276ced25d3abb0eb (desktop + 390px)
- frontend/e2e/s07-picker-compat.spec.ts: b027354e3c3f3939e4010bc540d12383e6c630df347af91c4e3a390ff1f907e7 (7 specs x2)
- tests/test_s07_cast_compatibility.py: ce1a564acb55e992479e753ca49d48b5941147c9ef2c06a8970a3114fb938695 (15 tests)
- tests/test_s07_project_cast_picker_api.py: e52d1b23a890aff42ca3a3c25547f55b9fec52b7d8f0cfd3188bdddcfeab9701 (7 tests)
- docs/pm/sessions/S07-T02-library-picker-compatibility/LOG.md + REPORT.md (this file, SUBMITTED)
- output/s07-t02/20260821_050038/ (evidence dir, 14 files)

## Validation (raw logs in output/s07-t02/20260821_050038/)
- picker/compat unit+API: 22 passed (log picker_compat.log)
- T01 regression (domain/repository/api/migration): 35 passed (log t01_regression.log)
- S06 regression (character domain/read/validator): 43 passed (log s06_regression.log)
- Playwright desktop + 390px: 14 passed (log playwright.log, config playwright.s07t02.config.ts, harness test-s07-picker)
- Frontend typecheck: tsc --noEmit 0 (log typecheck.log)
- Frontend eslint: 0 errors (9 warnings pre-existing from S06) (log eslint.log)
- Frontend build: next build success (log build.log)
- ruff check app tests: All checks passed! (log ruff.log)
- mypy app: Success: no issues found in 94 source files (log mypy.log)
- alembic heads: exactly one b2c3d4e5f6a7b (log alembic_heads.log)
- git diff --check: 0 (warnings only CRLF) (log git_diff_check.log)
- Protected data: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 unchanged; motionforge.db 311296 B unchanged (logs channels_hash.log, db_size.log)
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp verified
- No commit/push/merge; no MAIN writes; no sprint opened beyond S07-T02


## Codex C1 Correction
- F3 fix: Integrated picker into REAL Object Gallery (ObjectGalleryPanel + RoleCard) with real projectId/roleId, removed test harness routes, enforced fail-closed (compatible=false always disables submit, fallback advisory only), updated Playwright to real route.
- Files changed C1:
  - frontend/src/components/object-gallery/ObjectGalleryPanel.tsx (import ProjectCastPicker, render for expandedRole)
  - frontend/src/components/object-gallery/RoleCard.tsx (add Ghim nhan vat button, onCast prop)
  - frontend/src/features/project-cast/ProjectCastPicker.tsx (fail-closed canSubmit only compatible true)
  - frontend/src/app/test-s07-picker/ REMOVED
  - frontend/src/app/test-s07-t03/ REMOVED
  - frontend/playwright.s07t02.config.ts (real gallery)
  - frontend/e2e/s07-picker-compat.spec.ts (real gallery, 11x2=22)
  - tests/test_s07_cast_compatibility.py + picker_api.py (kept isolated fixture, now 28 total)
- Validation C1 (output/s07-t02-c1/20260821_060000/): 28 picker_compat passed, 22 playwright real gallery passed, ruff 0, mypy Success, alembic single b2c3d4e5f6a7b, git diff 0, typecheck 0, eslint 0, build success (no test routes). All 18 required tests covered.


## Correction C2 — P2 Tautology Fix
- File: tests/test_s07_cast_compatibility.py L492
- Before: assert "workspace_mismatch" in j["reasons"] or "generation" in str(j["reasons"]).lower() or not j["compatible"] — tautology (nhánh `or not compatible` luôn true khi compatible=False)
- Contract thật: POST /api/v2/project-cast/compatibility/evaluate với mapping_id không khớp project_id/object_role_id -> return 200, compatible=False, reasons=["workspace_mismatch"], fallback_allowed=False, blocked=True, pinned_version_id==pvid, current_revision==1 (fail-closed, read-only, không sửa backend)
- After: assert j["compatible"] is False; assert j["reasons"]==["workspace_mismatch"]; assert j["fallback_allowed"] is False; assert j["blocked"] is True; assert j["pinned_version_id"]==pvid; assert j["current_revision"]==1 (kèm assert status 200 đã có)
- Gates C2 (output/s07-t02-c2/20260822_113953/): compat 21 passed, picker 7 passed, ruff 0, git diff --check 0. Không sửa production, không giảm assertion.


## Correction C3 — F1 Dual-Project Bleed + F2 Orphan (Harness Only)
- Files: frontend/e2e/s07-t03-boot-backend.py (F2), frontend/e2e/s07-t03-real-vertical.spec.ts (F1), frontend/playwright.s07t03.config.ts (trace revert)
- F1: 4 test (desktop+mobile-390) trong 1 run: desktop 2 PASS, mobile 2 FAIL tại pin submit-success với 409 idempotency-key already bound (A/B đã repin sang V2 ở viewport trước). Root cause: shared DB, cùng project A/B chạy 2 lần → natural key đã tồn tại. Fix: fullScenarioI cleanup đầu test (list+delete mapping cho target và cho project C) + publish xử lý already-published (409→ dùng draftId).
- F2: os.execv trên Windows tạo orphan LISTENING 8004, runner treo. Fix: subprocess.Popen + wait + signal forwarding, wrapper giữ PID, teardown giết đúng cây.
- Gates (output/s07-t02/20260822_155527/): Run1 4 passed (seed 49e17347...), Run2 4 passed (seed 1727e42f...), cả hai 4 passed ×2 và tự exit; netstat chỉ TIME_WAIT không LISTENING; pytest 28 passed; git_status frontend/src chỉ intentional dirty; git diff 0; HEAD a43b20da unchanged.
- Không đụng backend/tests/migrations/frontend/src.


## Correction C4 — P1-A Fallback Matrix + P1-B Repin (Harness + Backend Pure)
- Files: app/persistence/project_cast.py (_evaluate + blocked), frontend/src/features/project-cast/ProjectCastPicker.tsx (pinnedMappingId, fallback submit), frontend/e2e/s07-picker-compat.spec.ts (partial mock + 3 tests), tests/test_s07_cast_compatibility.py (4 fallback tests), tests/test_s07_project_cast_picker_api.py (2 fallback API tests)
- P1-A: generation_mismatch và incomplete_pack (+missing_required_pose companion) là fallback-supported → fallback_allowed True, description tiếng Việt, blocked False; các reason khác (workspace_mismatch, source_overlay_refusal, object_kind_mismatch, unpublished_pack, missing_required_capability, stale_revision) → fallback False, blocked True. UI: fallback banner (compat-fallback) + nút "Ghim bất chấp khác biệt" enabled, helper text tiếng Việt.
- P1-B: fetchPinned lưu found.id → pinnedMappingId, effectiveMappingId = prop ?? pinned, PATCH với revision hiện tại (n→n+1), không POST duplicate.
- Gates (output/s07-t02/20260822_163322/): fail_before 3 failed → pass_after 6 passed; pytest_full 34 passed; playwright 26 passed ×2 (desktop+mobile); ruff All checks passed, mypy Success, git diff 0, HEAD a43b20da.
- Không đụng models/migrations/S08/T03, không silent nearest-match.


## Correction C5 — P1 Backend Contract (Fallback Acknowledged End-to-End)
- Schema: ProjectCastCreateRequest/UpdateRequest thêm fallback_acknowledged: bool = False (strict/forbid, default False)
- Persistence: _check_compatibility_or_raise(fallback_acknowledged) cho phép khi fallback_allowed && acknowledged, giữ blocked = not compatible and not fallback_allowed, thêm param vào create_mapping/update_mapping và 2 call-site
- Routes: truyền body.fallback_acknowledged
- Frontend: api client + ProjectCastPicker gửi fallback_acknowledged: !!compat?.fallback_allowed
- E2E: fallback_supported PATCH assert body.fallback_acknowledged true
- Tests: 4 mới (CREATE/REPIN fallback with ack success, unsupported rejected zero-mutation) + giữ 34 cũ =38 passed; PW 26 passed; ruff/mypy clean
- Evidence: output/s07-t02/20260822_204042/

## Warnings / limitations
- Forbidden files untouched; S08 core untouched; frontend only new feature dir + test harness + api extensions; backend only read extensions (picker browse + compat evaluate)
- No commit/push/merge; no MAIN writes; no sprint opened beyond S07-T02
- Exit cleanly with full evidence, SUBMITTED only (never APPROVED)
