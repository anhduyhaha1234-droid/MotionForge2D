# S09-FG1 — Final-gate correction: test_durable_job_persistence expected-tables normalization

## Role
Bạn là WORKER correction hẹp cho final sprint gate. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp `%TEMP%/s09fg1-*`, `-p no:cacheprovider`.

## Finding (Manager đã root-cause)
`tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables` FAIL:
- Test giữ allowlist bảng cứng (S02/S08 era) — thiếu các bảng additive từ foundation cũ + S09: `apply_checkpoint`, `reskin_config`, `project_cast_mapping`, `s09_correction`, `segment_render_route`, `structural_lock_manifest`
- Đây là cùng pattern I04 đã normalize cho 6 file khác (dùng live head contract + expected tables additive) nhưng file này KHÔNG nằm trong allowlist I04 → sót.
- Attribution: gap pre-existing (reskin_config/apply_checkpoint có trước S09) NHƯNG vẫn phải fix trước final gate — không dùng "pre-existing" làm lý do bỏ qua.

## Việc làm (hẹp)
1. Áp dụng đúng pattern I04: đọc tests/test_persistence_bootstrap.py (đã normalized) để copy cách làm chuẩn — expected tables set mở rộng ADDITIVE với comment nguồn từng bảng, KHÔNG làm yếu assertion (unexpected-tables check phải vẫn fail-closed với bảng lạ).
2. Chỉ sửa tests/test_durable_job_persistence.py phần allowlist + comment. Không đụng logic test khác.
3. Verify: chạy file này ×2 PASS; adversarial control: plant fake table vào DB temp copy → assertion vẫn FAIL đúng (chạy script proof nhỏ trong output lane).
4. ruff check file đó PASS.

## Acceptance
- ×2 PASS liên tiếp + adversarial proof log.
- REPORT.md ngắn gọn trong docs/pm/sessions/S09-FG1-durable-tables-normalization/ (deliverable, evidence, self-audit). STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist
tests/test_durable_job_persistence.py · output/s09/20260823_sprint_full/tfg1/** · docs/pm/sessions/S09-FG1-durable-tables-normalization/{TASK.md đã có, LOG.md, REPORT.md}

## FORBIDDEN
Mọi file khác. MAIN. migrations. app/**. git ops. network.
