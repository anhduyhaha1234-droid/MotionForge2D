# S09-T01 — Reskin Mapping Contract (ReskinConfig pin + SOLE migration owner)

**Task ID:** S09-T01
**State:** READY (Wave 1)
**Owning session:** (điền khi dispatch) — alpha @ provider custom (9Router http://127.0.0.1:20128/v1), reasoning max, fallback disabled, Hermes CLI
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204
**Sprint contract:** docs/pm/sprints/S09-SPRINT_CONTRACT.md · Planning package normative: output/s09-p00-readiness/20260822_052954_cf4196/TASK_MAP.md (mục T01)

## Outcome

Durable ReskinConfig pin (project, object_role) → ProjectCastMapping/immutable PackVersion cùng pose/anchor/scale/fit/clip/offset/rotation/opacity contract, revision CAS và idempotency:

1. Chỉ chấp nhận PackVersion `status='published'`, compatible, đủ CORE_POSE_SLOTS — tái sử dụng `evaluate_compatibility` (app/persistence/project_cast.py) chứ không viết lại policy.
2. Contract parameter lưu JSON validation-fail-closed: anchor {x,y} ∈ [0,1], scale > 0, fit_mode ∈ contain|cover|stretch, clip_mode ∈ asset_alpha|original_mask|intersection, offset, rotation_offset_deg, opacity.
3. Revision CAS: PATCH revision stale → 409, zero mutation.
4. Idempotency: replay cùng idempotency_key + payload tương đương → trả existing; payload khác → 409 conflict.
5. Publish version mới KHÔNG mutate version đã pin (version isolation giữ nguyên hành vi S07).
6. **MIGRATION DECISION A (FROZEN): T01 là SOLE migration owner của toàn Sprint S09.** TẠO ĐÚNG MỘT migration additive duy nhất, down_revision = Alembic head thực tế tại preflight (**b2c3d4e5f6a7b**), gồm HAI bảng: `reskin_config` VÀ `apply_checkpoint` (schema-only ĐẦY ĐỦ cho T06 dùng sau này — mọi cột checkpoint cần). Không migration thứ hai trong toàn sprint.

## Exclusive write ownership

| File | Phạm vi |
|---|---|
| app/persistence/models.py | ADDITIVE ONLY — thêm table `reskin_config` + `apply_checkpoint`; KHÔNG sửa/xóa định nghĩa hiện hữu (S07/S08/S11 registrations byte-semantics bảo toàn) |
| migrations/versions/<một-file-s09-mới>.py | NEW — duy nhất 1 revision, down_revision=b2c3d4e5f6a7b |
| app/persistence/reskin_config.py | NEW repository/domain |
| app/schemas/reskin_config.py | NEW typed schemas |
| app/api/routes/reskin_config.py | NEW router (pattern app/api/routes/project_cast.py, prefix /api/v2/reskin-configs + trailing-slash variants) |
| app/api/app.py | ADDITIVE include_router only |
| frontend/src/features/reskin/index.ts | NEW thin exports/API client only |
| tests/test_s09_reskin_config_domain.py | NEW |
| tests/test_s09_reskin_config_api.py | NEW |
| tests/test_s09_reskin_migration.py | NEW |
| output/s09/s09-t01/** | packet/evidence |
| docs/pm/sessions/S09-T01-reskin-mapping-contract/ | LOG.md + REPORT.md của task này |

## Forbidden

legacy CompositeCanvas/Screen*, app/services/compositing.py, app/services/render.py, app/services/video_proxy.py, app/services/object_correction.py, S07/S08 tests+code (chỉ đọc regression), S11 files, bất kỳ migration thứ hai nào, frontend trừ file được phép ở trên, MAIN tree, data/ protected, commit/push/merge. Cần file ngoài allowlist → STOP BLOCKED_SCOPE.

## Required tests (binary)

1. Only published/compatible/complete PackVersion accepted; unpublished/incompatible reject fail-closed.
2. Revision CAS stale → 409 + zero mutation (pattern test_s07_version_isolation.py:374).
3. Idempotent replay equivalent → existing row; conflicting replay → 409.
4. Publishing later pack version does not mutate pinned version_id (chạy lại ≥3 test isolation của tests/test_s07_version_isolation.py làm regression).
5. Migration upgrade→downgrade→upgrade round-trip byte-identical DDL + PRAGMA foreign_key_check = 0; alembic đúng 1 head.
6. OpenAPI diff chỉ additive.
7. Domain validation fail-closed cho mọi param ngoài miền (anchor, scale, fit_mode, clip_mode, rotation, opacity).

## Worker protocol

- Hard worktree guard trước mọi write: pwd phải là worktree trên; sai → BLOCKED_WRONG_WORKTREE exit.
- MOTIONFORGE_DATABASE_URL phải UNSET (`env -u MOTIONFORGE_DATABASE_URL`). Test dùng temp SQLite, basetemp riêng Windows-native path (C:/Users/Admin/AppData/Local/Temp/s09t01-*), `-p no:cacheprovider`.
- Cấm reset/clean/stash/restore/checkout đè file/commit/push/merge; cấm sửa git config; cấm kill process không thuộc ownership mình.
- Focused tests chạy ×2 liên tiếp pass; ruff check app tests; mypy app; git diff --check sạch.
- Kết thúc: REPORT.md status=TASK_SUBMITTED (không tự APPROVED); LOG.md ghi lệnh+output thật; evidence vào output/s09/s09-t01/<run-id>/.
- Model alpha @ custom reasoning max no-fallback; route/model chết → ghi BLOCKED_MODEL_ROUTE vào LOG rồi dừng (Manager xử lý retry).
