# S09-T00-I04 — Cross-sprint migration-head normalization

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback DISABLED. Route sai → BLOCKED_MODEL_ROUTE.

## Bước 0 — bắt buộc trước mọi hành động
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md → báo RULES_LOADED trong LOG.
2. HARD WORKTREE GUARD: pwd = C:/Users/Admin/MotionForge2D-worktrees/s08-integration; toplevel khớp; branch = codex/s08-integration; pin HEAD + dirty count vào LOG.
3. MOTIONFORGE_DATABASE_URL UNSET kiểm tra lệnh thật.

## Outcome
Bỏ hard-coded Alembic head `b2c3d4e5f6a7b` trong 6 test file regression cross-sprint; thay bằng live contract ScriptDirectory.get_heads() (hoặc cơ chế tương đương đọc runtime); thêm expected additive S09 tables (reskin_config, apply_checkpoint, structural_lock manifest + bảng mới nếu có) vào assertion "unexpected tables" mà KHÔNG làm yếu schema checks.

## EXCLUSIVE WRITE ALLOWLIST (duy nhất 6 file)
- tests/test_s07_version_isolation.py
- tests/test_persistence_bootstrap.py
- tests/test_object_correction.py
- tests/test_object_extraction.py
- tests/test_object_grouping.py
- tests/test_object_intelligence_domain.py

## FORBIDDEN
Sửa bất kỳ production file nào (app/**, frontend/**, migrations/**). Sửa assertion theo hướng yếu đi (ví dụ bỏ hẳn check unknown table) là vi phạm acceptance. Không đụng task/output khác. Không network/DB thật/commit/push/reset.

## Acceptance (binary)
- Adversarial: tạo migration/table giả tên lạ trong DB temp → test VẪN fail đúng (chứng minh normalization không nuốt lỗi); xóa giả → xanh.
- Head mới xuất hiện (mô phỏng bằng get_heads()) → assertions không hard-code fail.
- Cả 6 file regression pass ×2 liên tiếp trên DB temp cô lập (basetemp riêng %TEMP%/s09t00i04-*).
- Zero production write (git diff chỉ chạm đúng 6 file).
- ruff check tests sạch; git diff --check sạch.

## Deliverables evidence
output/s09/20260823_sprint_full/t00-i04/** : LOG.md (+07), REPORT.md STATUS: TASK_SUBMITTED + self-audit, test logs ×2, adversarial proof log.

## Protocol
Task này chạy SONG SONG với I01 — write-set disjoint đã chứng minh (6 test files vs app/+migration). KHÔNG đọc/đụng output của I01. Nếu cần biết bảng S09 hiện có, dùng models.py READ-ONLY như tại thời điểm bạn start (không chờ I01). Final assertions về head-count có thể tạm chấp nhận head hiện hành c9d0e1f2a3b4; khi I01 merge head mới, head-discovery tự thích ứng là mục tiêu thiết kế. Dừng sau TASK_SUBMITTED.
