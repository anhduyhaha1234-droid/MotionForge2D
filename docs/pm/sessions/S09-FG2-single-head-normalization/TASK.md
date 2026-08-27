# S09-FG2 — Final-gate correction: stale single-head assertions sau T05A migration

## Role
Bạn là WORKER correction hẹp cho final sprint gate. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp `%TEMP%/s09fg2-*`, `-p no:cacheprovider`.

## Finding (Manager đã root-cause)
T05A tạo migration `b3c4d5e6f7a9` (head mới) nhưng 4 test file vẫn assert head cũ:

1. `tests/test_s07_project_cast_migration.py` — line 31: `HEAD = "b2c3d4e5f6a7b"` (stale từ trước, test test_revision_chain_and_single_head fail)
2. `tests/test_s08_a02_structural_evidence_migration.py` — line 43: `HEAD = "b2c3d4e5f6a7b"` (tương tự)
3. `tests/test_s09_reskin_migration.py` — line 31: `HEAD = "d8e9f0a1b2c3"` (test_single_head_via_alembic fail)
4. `tests/test_s09_t00_structural_lock_migration.py` — lines ~91/95/102: hard-code "d8e9f0a1b2c3" trong 3 asserts (revision identity giữ nguyên ĐÚNG vì nó test chính revision đó; NHƯNG assert heads == ["d8e9f0a1b2c3"] và _revision(db) phải đổi sang live-head discovery)

## Việc làm (hẹp)
Áp dụng pattern live-head discovery chuẩn của I04 (`ScriptDirectory.get_heads()`):
- File 1 & 2: thay constant HEAD stale bằng discovery live (hoặc assert chain kết thúc ở live head). Lưu ý ý nghĩa gốc test là revision-chain + single-head — giữ nguyên ý nghĩa, chỉ bỏ hard-code snapshot.
- File 3: `HEAD` constant → dùng `ScriptDirectory.from_config(...).get_heads()[0]`; assertion single-head giữ nguyên.
- File 4: giữ assert `mig.revision == "d8e9f0a1b2c3"` (đúng — revision identity không đổi); đổi assert heads và _revision(db) sang live-head discovery (head hiện tại b3c4d5e6f7a9, nhưng KHÔNG hard-code b3c4... — dùng get_heads()).
- KHÔNG làm yếu assertion nào: adversarial (multi-head scenario) vẫn phải fail.

## Verify bắt buộc
1. Cả 4 file ×2 PASS liên tiếp (basetemp khác nhau).
2. Chạy lại nhanh các migration suites liên quan khác để chắc không phá: tests/test_s09_t05_backend_migration.py, tests/test_s09_reskin_migration.py.
3. ruff check 4 files PASS.

## Acceptance
REPORT.md ngắn trong docs/pm/sessions/S09-FG2-single-head-normalization/ (deliverables, ×2 evidence, self-audit). STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist
CHÍNH XÁC 4 file trên · output/s09/20260823_sprint_full/tfg2/** · docs/pm/sessions/S09-FG2-single-head-normalization/{TASK.md đã có, LOG.md, REPORT.md}

## FORBIDDEN
Mọi file khác. MAIN. migrations/**. app/**. git ops. network.
