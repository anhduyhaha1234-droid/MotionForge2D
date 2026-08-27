# S09-FG3 — Session LOG

## 2026-08-24 19:35+07 — Preflight
- RULES_LOADED: đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng).
- CODEX_PM_HANDOFF.md + ROADMAP backlog đối chiếu; worktree guard OK:
  cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration, branch codex/s08-integration,
  HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0, dirty 78 (sẵn có của các lane khác, không đụng).
- MOTIONFORGE_DATABASE_URL = UNSET (đã echo kiểm chứng).
- MAIN chỉ đọc (rules + handoff); không ghi MAIN.

## Baseline trước sửa (chứng cứ FAIL thật)
- pytest 3 file target (-p no:cacheprovider, basetemp %TEMP%/s09fg3-baseline):
  **6 failed, 55 passed in 47.40s** — khớp TASK.md từng tên test:
  - Nhóm A (bootstrap): test_no_api_cutover_tables,
    test_s03_head_reuses_s01_channel_schema_no_new_tables, test_s03t02_head_table_set_unchanged.
  - Nhóm B (A01): test_legacy_3_kind_roundtrip_byte_identical,
    test_new_kind_rows_refuse_downgrade_atomic (test_s08_a01_c1_migration_safety.py),
    test_migration_widens_kind_preserving_rows (test_s08_a01_role_taxonomy.py).

## Root cause + fix (đúng 3 file)
1. tests/test_persistence_bootstrap.py — S08_HEAD_TABLES thiếu bảng ``s09_correction``
   do set được normalize ở S09-T00-I04, TRƯỚC khi T05A thêm migration b3c4d5e6f7a9.
   Đã thêm "s09_correction" kèm comment nguồn (S09-T05A correction persistence,
   migration b3c4d5e6f7a9). Mọi assertion + adversarial control giữ nguyên
   (planted sneaky_unknown_table_9d2f vẫn phải fail — đã verify bằng chính lần chạy PASS).
2. tests/test_s08_a01_c1_migration_safety.py — bỏ constant stale HEAD="b2c3d4e5f6a7b",
   thêm _live_head() (ScriptDirectory.get_heads(), assert exactly one head) theo mẫu
   tests/test_s07_project_cast_migration.py; thay 4 chỗ assert `_revision(engine) == HEAD`
   thành `_live_head()`. A01="f7a8b9c0d1e2" và PRE_A01 giữ literal vì là revision identity
   của migration dưới test (assert refused-downgrade dừng đúng tại A01 vẫn nguyên ý nghĩa).
3. tests/test_s08_a01_role_taxonomy.py — cùng pattern: thêm _live_head() helper,
   thay assert hard-code "b2c3d4e5f6a7b" ở test_migration_widens_kind_preserving_rows.
   KHÔNG hard-code head mới; KHÔNG làm yếu assertion nào (single-head assert vẫn có).

## Verify (lệnh thật, output thật)
- Run 1: 61 passed, 49.79s — basetemp %TEMP%/s09fg3-a.
- Run 2: 61 passed, 49.19s — basetemp %TEMP%/s09fg3-b (PASS liên tiếp ×2).
- Adjacent không phá: test_s09_t00_structural_lock_migration.py +
  test_s09_reskin_migration.py + test_s07_project_cast_migration.py = 25 passed, 23.45s.
- ruff check 3 file: All checks passed!
- grep residual 'HEAD\b|b2c3d4e5f6a7b' trong 2 file A01: zero match.

## Fresh-gate re-run (yêu cầu verification evidence mới)
- 2026-08-24 19:50:53+07 — pytest lại cả 3 file sau khi mọi edit đã chốt
  (basetemp %TEMP%/s09fg3-freshgate): **61 passed, 49.45s**.
- ruff check 3 file: **All checks passed!**
- Không có thay đổi code nào giữa run 2 và fresh-gate này; kết quả nhất quán ×3 liên tiếp.
- Re-run lần nữa lúc 19:52:40+07 (basetemp s09fg3-freshgate2): **61 passed, 48.91s**,
  ruff PASS, git status xác nhận write-set không đổi — ×4 liên tiếp nhất quán.

## Trạng thái kết thúc
STATUS: TASK_SUBMITTED — STOP. Chờ Codex review độc lập.
