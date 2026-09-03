# S11-T04B — Worker LOG (W10)

## Task identity

| Field | Value |
|---|---|
| Task ID | S11-T04B (serial sau W9 · T04A) |
| Branch | `codex/s11/t04b-0903w10` (local; KHÔNG push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `b9176544d3a6af5566c61fe67a5d545b407d404b` (porcelain 0 tại start) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t04b-0903w10` |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

> Ghi chú dispatch: worktree trong packet ghi `s11-t04b-t04b-0903w10` (typo);
> worktree ĐÃ ĐĂNG KÝ duy nhất khớp task là `s11-t04b-0903w10` (git worktree list)
> — dùng cái thật, HEAD=b917654 đúng WAVE_BASE.

## Required reading (đã đọc trước khi implement)

- [x] Authority: `output/s11-post-t01-readiness/r1/synthesis/S11_T02_T06_PRODUCTION_PLAN.md`
      (s08-integration, read-only) — W10 block L347-362; sha256sum
      `342479267086485ef6fd44cb8b3a5f94e6f7b1afcc4439afda2910068fc76f4f` KHỚP.
- [x] `app/schemas/object_correction.py` (CorrectionRequest/ImpactData/CorrectionConfirmRequest — consume surface)
- [x] `app/services/object_correction.py` + `app/persistence/object_correction.py` (compute_impact/create/confirm/successor — consume)
- [x] `app/api/routes/object_correction.py` (preview/POST/{id}/confirm/{id}/recompute/retry — consume, KHÔNG sửa)
- [x] T03G read authority: `app/workflow/qc_checks_handler.py` (submit_run_qc_checks, compose_check_run_args, fingerprints) + `app/api/routes/qc_check_runs.py` + `app/workflow/job_service.py` (worker registration)
- [x] T02B lifecycle: `app/persistence/qc_items.py` (create/acknowledge/recheck_*/transitions/statuses) + `app/api/routes/qc_items.py` (GET-only)
- [x] T04A consume: `app/services/qc_navigation.py` (KNOWN_KINDS, Decision E explain conventions, RENDERER_ROUTES contract)
- [x] T03F GAP-8: `app/services/qc_checks/orchestrator.py` (run_full_check_set, reopen_stale_evidence — hook SHARED với T04B)
- [x] Anchors: `app/persistence/structural_evidence.py` (supersede_segment, SegmentRecord), `app/persistence/structural_lock.py` (get_manifest, LockManifestRecord), `app/persistence/project_cast.py` (create/update_mapping), `app/persistence/reskin_config.py` (create/update_config — phủ định lane-A), models.py (RENDERER_ROUTES, ReskinConfig columns)
- [x] Test recipes: `tests/test_object_correction_api.py` (seed S08 + worker run_once), `tests/test_s11_t03g_qc_check_api.py` (attach evidence seed + audio band), `tests/test_s09_reskin_config_domain.py` (character/pack/assets seed), conftest `client` fixture

## Baseline

- `git status --porcelain` = 0 (trống) trước mọi thay đổi.
- HEAD = b9176544d3a6af5566c61fe67a5d545b407d404b (WAVE_BASE).
- RED gate: `git show WAVE_BASE:app/services/qc_correction_bridge.py` FAIL — module chưa tồn tại tại base (xem evidence/baseline.txt).

## Write-set (đúng allowlist — 3 file mới + docs)

1. `app/services/qc_correction_bridge.py` (NEW — sole owner mapping QCItem → correction request)
2. `tests/test_s11_t04b_correction_rerun.py` (NEW)
3. `tests/test_s11_t04b_stale_reopen.py` (NEW)
4. `docs/pm/sessions/S11-T04B/LOG.md`, `REPORT.md`, `evidence/*` (docs)

KHÔNG sửa: object_correction schemas/services/routes (CHỈ consume — diff 0),
qc_items repo/router (chỉ import lifecycle), models.py, migrations/**, frontend/**, MAIN.

## Trình tự thực hiện

1. Baseline + RED (ở trên).
2. Viết bridge (mapping + scope V1 + chain + stale-check), viết 2 test files.
3. Run 1: 8 passed / 13 failed — chẩn đoán từng lỗi:
   - `UnsafeRuntimeRootError`: stale-reopen tests thiếu `client` fixture (env patch conftest) → thêm dependency.
   - `_seed_video` bỏ qua pid/vid (chỉ dùng làm name) → FK fail trên project id — sửa seed dùng id thật.
   - `ManagedRoot.read_bytes` không tồn tại → `managed.resolve(path).read_bytes()`.
   - HTTP confirm sau occurrence-bump trả 500: route object_correction KHÔNG bắt `OccurrenceConflictError`
     (pre-existing S08 gap — NGOÀI allowlist, không sửa); test chuyển sang: HTTP 409 với stale
     CORRECTION revision (anchor còn nguyên) + bridge wrapper ROLE_CHANGED cho anchor-conflict.
   - Chain replay: sau correction thành công evidence item stale BY DESIGN → guard ROLE_CHANGED
     chặn chain lần 2 (không duplicate) — sửa kỳ vọng test.
   - `validate_manifest` (structural_lock) reject payload manifest tối thiểu → seed manifest
     contract-valid; bridge: anchor read fail-closed (SegmentNotFound/StructuralLockNotFound → STALE;
     payload corrupt → propagate, KHÔNG swallow).
   - Partial unique `uq_structural_lock_manifest_active` → supersede v1 TRƯỚC khi insert v2.
   - `superseded_by_id=uuid ngẫu nhiên` → FK fail (occurrence_segment) → dùng lineage bump.
   - Recheck evidence REPLACE payload item → terminal test seed phải giữ anchor keys.
   - candidate_edit occurrence bump OCCURRENCE revision (không bump role) — sửa assert.
4. GREEN: 21 passed × 3 fresh roots (23.35s / 23.04s / 23.04s, basetemp
   `C:/Users/Admin/AppData/Local/Temp/s11t04b_r*`, `-p no:cacheprovider`,
   `MOTIONFORGE_DATABASE_URL` unset).
5. ruff --select F: clean (sau khi dọn 14 findings F401/F841/F821).
6. py_compile: OK. Alembic head `f9a0b1c2d3e4` không đổi.
7. Regression: `test_s11_t02b_qc_repository_lifecycle.py` + `test_s11_t03g_qc_check_api.py` +
   `test_object_correction_api.py` = 52 passed (51.66s) — consume surfaces không vỡ.
8. Commit local + ghi SHA (xem dưới).

## Phát hiện ngoài scope (báo cáo, KHÔNG tự sửa)

- Route `POST /corrections/{id}/confirm` không bắt `OccurrenceConflictError` (chỉ bắt
  `OccurrenceNotFoundError`) → stale-OCCURRENCE confirm qua HTTP = 500 thay vì 409.
  Đây là hành vi pre-existing của S08-T05 (test S08 chỉ phủ stale CORRECTION revision).
  T04B forbidden không cho sửa route → bridge giữ guard ROLE_CHANGED ở service layer
  (không để conflict thoát dưới dạng 5xx qua bridge), ghi nhận cho manager.
- Plan W10 ghi "ReskinConfig KHÔNG có cột revision" — thực tế models.py L2231 có
  `ck_reskin_config_revision_positive` (ReskinConfig CÓ revision CAS). Không mâu thuẫn mục tiêu:
  bridge KHÔNG anchor trên ReskinConfig (test phủ định lane-A + source-grep đều xanh).

## Test coverage (21 = 12 rerun + 9 stale)

- Rerun: scope V1 4 anchor in / 7 out-of-scope explain-action; preview ZERO-writes real API;
  chain preview→confirm→RECOMPUTE (1 tx) + worker completes + item→recheck; replay không duplicate
  + ROLE_CHANGED guard; unaffected byte-identical (rows/sha256/bytes + manifest.affected_role_ids);
  retry qua EXISTING `/{id}/recompute/retry` (successor, predecessor immutable, OpenAPI path);
  ROLE_CHANGED pre-check + confirm-time mapping; NO whole-project rerun (source greps);
  orchestrator auto-resolve sau recheck (audio band thật, 2 phase evidence).
- Stale: 3 anchors thật (supersede_segment / manifest lifecycle active→superseded+voided /
  repin → cast revision) + lineage bump; ReskinConfig negative (bump revision thật → KHÔNG stale);
  bridge source không reference reskin; terminal item refuse fail-closed.

## Commit local

- `git add` CHỈ 3 file allowlist + docs/pm/sessions/S11-T04B/; commit; ghi SHA tại REPORT.

## Kết luận

TASK_SUBMITTED — acceptance 1-4 đều GREEN, evidence đầy đủ trong `evidence/`.