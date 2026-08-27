# S09-FG1 — REPORT

Task: final-gate correction — test_durable_job_persistence expected-tables normalization.
Worker session: S09-FG1 (provider custom @ 9Router, model alpha, reasoning max, fallback disabled).
Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration · codex/s08-integration · HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0.

## Deliverable

tests/test_durable_job_persistence.py — normalize allowlist của `test_no_worker_or_api_cutover_tables` theo đúng pattern I04 (tests/test_persistence_bootstrap.py):

- Bộ hằng số additive module-level `S02_HEAD_TABLES` → `S06_HEAD_TABLES` → `S08_HEAD_TABLES` → `S09_HEAD_TABLES`, mỗi bảng additive có comment nguồn + revision migration:
  - `project_cast_mapping` — b2c3d4e5f6a7b (S07-T01)
  - `reskin_config`, `apply_checkpoint` — c9d0e1f2a3b4 (S09-T01)
  - `structural_lock_manifest`, `segment_render_route` — d8e9f0a1b2c3 (S09-T00)
  - `s09_correction` — b3c4d5e6f7a9 (S09-T05A)
- Test đổi từ inline set cứng era S02/S08 sang `tables - S09_HEAD_TABLES`. Assertion unexpected-tables GIỮ NGUYÊN tính fail-closed — không làm yếu.
- Không đụng logic test khác trong file; không đụng file nào ngoài write-set (MAIN read-only, migrations/app không đụng).

## Evidence

| Check | Kết quả |
|---|---|
| Run 1 toàn bộ file (`--basetemp=%TEMP%/s09fg1-run1`, `-p no:cacheprovider`, env guard) | 47 passed (42.66s) |
| Run 2 liên tiếp (basetemp riêng s09fg1-run2) | 47 passed (42.07s) |
| Adversarial control | Clean DB pass contract (unexpected=[]); COPY plant `sneaky_unknown_table_fg1` → cùng logic bắt đúng {'sneaky_unknown_table_fg1'} → FAIL đúng |
| ruff check tests/test_durable_job_persistence.py | All checks passed! |

Proof files (output lane): output/s09/20260823_sprint_full/tfg1/adversarial_proof.py, adversarial_proof.log. Script proof import ĐÚNG hằng số `S09_HEAD_TABLES` từ file test thật qua importlib — không phải bản tái lập.

## Self-audit

- Root-cause tự xác minh trước khi sửa: chạy file lỗi thấy FAIL thật với đúng 6 bảng thiếu; grep nguồn từng bảng trong migrations/versions khớp finding 6/6.
- Attribution gap: pre-existing từ foundation cũ (reskin_config/apply_checkpoint có trước S09) nhưng đã fix trước final gate như TASK yêu cầu.
- Write-set audit bằng git: delta của worker trong tests/ chỉ test_durable_job_persistence.py (các file dirty khác thuộc state sprint S09 từ preflight); output lane chỉ chứa proof files; DB tạm adversarial đã dọn khỏi output lane.
- ×2 PASS dùng 2 basetemp độc lập, MOTIONFORGE_DATABASE_URL UNSET kiểm tra lại mỗi lần chạy.

STATUS: TASK_SUBMITTED
