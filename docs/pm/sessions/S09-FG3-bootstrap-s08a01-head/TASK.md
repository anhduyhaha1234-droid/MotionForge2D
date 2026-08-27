# S09-FG3 — Final-gate correction: bootstrap expected-tables + S08-A01 stale head (sau T05A)

## Role
Bạn là WORKER correction hẹp cuối cùng trước sprint handoff. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp `%TEMP%/s09fg3-*`, `-p no:cacheprovider`.

## Findings (Manager đã root-cause — regression run 2 FULL lộ ra vì run1 bị -x dừng sớm)
6 failed, chia 2 nhóm:

### Nhóm A — tests/test_persistence_bootstrap.py (1 file, 3 test)
`S09-T00-I04 adversarial control` comment ở line ~242: `unexpected tables: ['s09_correction']`
- File này đã được I04 normalize nhưng **trước khi T05A thêm bảng `s09_correction`** → set `S08_HEAD_TABLES` thiếu đúng 1 bảng.
- Fix hẹp: thêm `"s09_correction"` vào S08_HEAD_TABLES với comment nguồn (S09-T05A correction persistence). Giữ nguyên mọi assertion + adversarial control (plant fake table vẫn phải fail).
- 3 test failing đều do cùng set này.

### Nhóm B — tests/test_s08_a01_c1_migration_safety.py + tests/test_s08_a01_role_taxonomy.py (2 file, 3 test)
- Line 39 `HEAD = "b2c3d4e5f6a7b"` hard-code stale (cùng pattern FG2 đã normalize cho 4 file khác). Failures: legacy_3_kind_roundtrip_byte_identical, new_kind_rows_refuse_downgrade_atomic, migration_widens_kind_preserving_rows — tất cả assert `_revision(engine) == HEAD`.
- Fix hẹp theo ĐÚNG pattern FG2 đã dùng trong tests/test_s07_project_cast_migration.py (đã PASS — đọc file đó làm mẫu): live-head discovery qua ScriptDirectory.get_heads(); giữ nguyên ý nghĩa assertion; KHÔNG hard-code b3c4d5e6f7a9; revision identity của chính migration đó thì giữ literal.

## Verify bắt buộc
1. Cả 3 file ×2 PASS liên tiếp (basetemp %TEMP%/s09fg3-a, -b).
2. Chạy nhanh các file migration khác confirm không phá: tests/test_s09_t00_structural_lock_migration.py tests/test_s09_reskin_migration.py tests/test_s07_project_cast_migration.py.
3. ruff check 3 files PASS.

## Acceptance
REPORT.md ngắn docs/pm/sessions/S09-FG3-bootstrap-s08a01-head/REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist
CHÍNH XÁC 3 file trên · output/s09/20260823_sprint_full/tfg3/** · docs/pm/sessions/S09-FG3-bootstrap-s08a01-head/{TASK.md đã có, LOG.md, REPORT.md}

## FORBIDDEN
Mọi file khác. MAIN. migrations/**. app/**. git ops. network.
