# S11-T04A — Worker LOG (W9)

## Mandatory reading checklist

- [x] SESSION_PROTOCOL.md (docs/pm/SESSION_PROTOCOL.md)
- [x] Binding task block W9 · T04A (S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA 34247926... — via manager packet; full W9 block verbatim in task prompt)
- [x] lane-c REVIEW_QUEUE_CONTRACT §2 (s08-integration output, mapping table navigation issue → đích)
- [x] lane-c API_UI_GAP_MATRIX G2/G12/G13 (navigation shape)
- [x] lane-a DEPENDENCY_MATRIX mục 4 (route ORM [NEW-DURING-AUDIT], consume vế MISSING — renderer route qua structural_lock contract)
- [x] overlay docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md §S11 L372 ("Review Queue jumps directly to the failing layer and renderer route")
- [x] Consumed contracts (import-only): app/schemas/qc_items.py (QCItemData), app/persistence/qc_items.py (QCItemRepository/QCItemNotFoundError), app/persistence/models.py (RENDERER_ROUTES — đọc enum, KHÔNG sửa), deps.SessionDep

## Protected / baseline

- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s11-t04a-0903w9 (task packet ghi `s11-t04a-t04a-0903w9` — directory thật theo pattern chuẩn là `s11-t04a-0903w9`)
- Branch: codex/s11/t04a-0903w9 (local; KHÔNG push/merge/rebase/reset/clean/stash/force)
- WAVE_BASE: b2501598078c702d875f57ac0a17a78e3e40237b (HEAD tại start, porcelain = 0)
- baseline app/api/app.py sha256: cccb80cdfa70f00184bb9a5086a43a91587530deba6a62339db391c2ed001f28

## Nhật ký thực thi (chronological)

1. Verify start state: porcelain 0, HEAD = b250159..., branch đúng, app.py baseline hash capture.
2. Khảo sát contract read-only: QCItemData fields (layer_ref_type/layer_ref_id/segment_row_id/segment_logical_id/evidence), QCItemRepository.create/get, routes thật (frames.py serve_frame, jobs.py GET /api/jobs/{job_id}, projects.py gallery/scenes/project, structural_evidence.py segments/current/{segment_id}, object_intelligence roles/{role_id}/occurrences, object_extraction segments).
3. Đọc authority: REVIEW_QUEUE_CONTRACT §2 bảng mapping (frame→serve_frame, audio→job info, scene/segment→segments endpoint, render/project→project page), DEPENDENCY_MATRIX mục 4 (renderer route qua structural_lock RENDERER_ROUTES), overlay §S11 L372.
4. RED: viết 2 test files trước; chạy → collection error `ModuleNotFoundError: No module named 'app.services.qc_navigation'` (RED confirmed).
5. Implement:
   - app/schemas/qc_navigation.py (NEW) — CanonicalLocationData/NavigationActionData/QcNavigationData/QcNavigationErrorData, extra=forbid.
   - app/services/qc_navigation.py (NEW) — resolver: 7 canonical kinds + video_item, canonical location từ STRUCTURED evidence keys/QCItem fields (không parse text tự do, không coerce sai kiểu), explain-action Decision E, NavigationResolutionError unknown_kind.
   - app/api/routes/qc_navigation.py (NEW) — GET /api/v2/qc-navigation/{item_id} duy nhất, 404 fail-closed ownership, 500 fail-closed unknown_kind.
   - app/api/app.py (EXT) — +1 import qc_navigation, +1 include_router(qc_navigation.router) (tổng +2 dòng; đúng 1 dòng include_router — grep count = 1).
6. GREEN loop (real failures → fix):
   - Fix 1: seeding API test dùng cùng video_item.id cho 2 workspace → UNIQUE violation → dùng V2 cho WS2.
   - Fix 2: resolver test qc_session thiếu `_patch_project_root` → deps trỏ MAIN tree → UnsafeRuntimeRootError → thêm dependency fixture.
   - Fix 3: `_registered_templates()` đọc app.routes top-level — FastAPI bản mới bọc router trong `_IncludedRouter` (path rỗng) → chuyển sang `app.openapi()["paths"]` (272 paths, đủ 9 template target).
   - Fix 4: explain-case fixtures ghi layer_ref_id="video_item" literal, resolver so với video_item_id thật → dùng V1 (uuid thật) cho các case "no anchor".
7. GREEN x2 fresh roots: 37 passed (39.16s / 38.88s / 39.29s — r3..r7 logs), regression T02B 40 passed, ruff --select F clean (6 files), py_compile OK (4 prod files), alembic head f9a0b1c2d3e4 không đổi.
8. Self-review diff scope = đúng allowlist (5 file mới + app.py 2 dòng additive); porcelain chỉ allowlist + docs/S11-T04A.
9. Evidence ghi docs/pm/sessions/S11-T04A/evidence/*.txt; LOG/REPORT; stage allowlist + docs; commit local; ghi SHA; TASK_SUBMITTED.

## Isolation flags (mọi run)

- Runner: `--basetemp=C:/Users/Admin/AppData/Local/Temp/s11t04a_*` (SHORT Windows-native unique), `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`
- `env -u MOTIONFORGE_DATABASE_URL` — KHÔNG dùng env DB; mỗi test DB SQLite tạm riêng qua alembic upgrade head (conftest `_patch_project_root` + `deps.get_job_service().session_factory`)
- Không test nào viết vào canonical tree; project root/artifacts trong tmp_path

## Write-set compliance (final porcelain)

```
 M app/api/app.py                                  (EXT: import + 1 include_router — 2 dòng)
?? app/api/routes/qc_navigation.py                 (NEW)
?? app/schemas/qc_navigation.py                    (NEW)
?? app/services/qc_navigation.py                   (NEW)
?? tests/test_s11_t04a_navigation_api.py           (NEW)
?? tests/test_s11_t04a_navigation_resolver.py      (NEW)
?? docs/pm/sessions/S11-T04A/**                    (evidence — task session)
```

Forbidden verified UNCHANGED: app/schemas/qc_items.py, app/persistence/qc_items.py, app/api/routes/qc_items.py, corrections schemas/services, app/persistence/models.py, migrations/**, frontend/**, MAIN. `git status --porcelain` chỉ chứa allowlist + docs.

Kết thúc: TASK_SUBMITTED (chi tiết verdict REPORT.md).