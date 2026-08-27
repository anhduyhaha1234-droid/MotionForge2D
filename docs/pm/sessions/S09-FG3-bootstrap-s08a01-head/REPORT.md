# S09-FG3 — REPORT

STATUS: TASK_SUBMITTED

## Scope đã làm (đúng 3 file, không hơn)
| File | Thay đổi |
|---|---|
| tests/test_persistence_bootstrap.py | +1 entry "s09_correction" trong S08_HEAD_TABLES kèm comment nguồn S09-T05A (migration b3c4d5e6f7a9) |
| tests/test_s08_a01_c1_migration_safety.py | Bỏ HEAD="b2c3d4e5f6a7b" stale; thêm _live_head() theo mẫu test_s07_project_cast_migration.py; 4 assert `_revision(engine) == _live_head()` |
| tests/test_s08_a01_role_taxonomy.py | Thêm _live_head(); 1 assert head thay literal "b2c3d4e5f6a7b" |

Không đụng: MAIN, migrations/**, app/**, assertion/adversarial control, git ops.

## Acceptance criteria — bằng chứng lệnh thật
1. Baseline trước fix: **6 failed, 55 passed** (47.40s) — đúng 6 finding của TASK.md.
2. Run 1 sau fix: **61 passed** (49.79s, basetemp %TEMP%/s09fg3-a).
3. Run 2 sau fix: **61 passed** (49.19s, basetemp %TEMP%/s09fg3-b) → ×2 PASS liên tiếp.
4. Adjacent migration suites (structural_lock, reskin, s07_project_cast): **25 passed** (23.45s).
5. `python -m ruff check` 3 file: **All checks passed!**
6. Residual scan `grep 'HEAD\b|b2c3d4e5f6a7b'` trong 2 file A01: **0 match** — không còn
   hard-code head; single-head discovery giữ nguyên độ mạnh assertion (assert exactly one head).

## Ghi chú kỹ thuật cho reviewer
- Nhóm A: nguyên nhân là thứ tự thời gian — I04 normalize S08_HEAD_TABLES trước khi T05A
  thêm bảng. Fix chỉ bổ sung bảng vào expected set; adversarial control (plant
  sneaky_unknown_table_9d2f phải fail) vẫn chạy và vẫn có teeth trong cả 2 lần PASS.
- Nhóm B: A01="f7a8b9c0d1e2" / PRE_A01="f6a7b8c9d0e1" được giữ literal ĐÚNG như yêu cầu
  ("revision identity của chính migration đó thì giữ literal"); chỉ các assert mang nghĩa
  "sau upgrade head" mới chuyển sang live discovery.
- Session: session mới dành riêng cho Task ID S09-FG3 (task mới = session mới theo rules §4);
  không resume session nào vì đây là task ID riêng biệt, không phải correction của task cũ.

## Trạng thái kết thúc
TASK_SUBMITTED — dừng tại đây, chờ Codex review độc lập. Không tự ghi APPROVED.
