# S09-FG1 — Correction LOG

Worker correction hẹp theo TASK.md. Provider custom @ 9Router, model alpha, fallback disabled.
Worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration · branch codex/s08-integration · HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0 · MOTIONFORGE_DATABASE_URL=UNSET (guard pass).

## Bước 0

- Đọc TOÀN BỘ docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng) → RULES_LOADED (in ở manager chat đầu turn).
- Worktree guard: branch codex/s08-integration OK; MAIN read-only, không đụng.
- Dirty tree hiện hành là state sprint S09 (preflight ghi nhận, không đụng các file đó).

## Root-cause xác minh (không tin finding mù quáng)

- Chạy file lỗi trước khi sửa: `test_no_worker_or_api_cutover_tables` FAIL vì allowlist inline cứng era S02/S08 thiếu đúng 6 bảng additive: `apply_checkpoint`, `reskin_config` (c9d0e1f2a3b4 — S09-T01), `project_cast_mapping` (b2c3d4e5f6a7b — S07-T01), `s09_correction` (b3c4d5e6f7a9 — S09-T05A), `segment_render_route`, `structural_lock_manifest` (d8e9f0a1b2c3 — S09-T00).
- Xác minh nguồn từng bảng bằng grep `create_table(` trong migrations/versions/* — khớp finding 6/6.
- Pattern chuẩn I04 đọc từ tests/test_persistence_bootstrap.py: hằng số additive module-level S02_HEAD_TABLES → S06 → S08 + adversarial control plant-table-vào-COPY.

## Thay đổi (write-set đúng TASK)

1. tests/test_durable_job_persistence.py:
   - Thêm hằng số additive `S02_HEAD_TABLES` / `S06_HEAD_TABLES` / `S08_HEAD_TABLES` / `S09_HEAD_TABLES` (comment nguồn từng bảng + revision migration), văn bản khớp bootstrap để tránh drift giữa 2 file.
   - `test_no_worker_or_api_cutover_tables`: thay allowlist inline bằng `tables - S09_HEAD_TABLES`; docstring ghi rõ normalization + vẫn fail-closed. KHÔNG đụng logic/assertion khác của file.
2. output/s09/20260823_sprint_full/tfg1/: adversarial_proof.py + adversarial_proof.log (script proof import ĐÚNG hằng số S09_HEAD_TABLES từ file test thật, không tái lập).

## Verify

- Run 1: `pytest tests/test_durable_job_persistence.py -p no:cacheprovider --basetemp=%TEMP%/s09fg1-run1` → **47 passed** (42.66s).
- Run 2: same, basetemp s09fg1-run2 → **47 passed** (42.07s). ×2 PASS liên tiếp.
- Adversarial: clean db upgrade head → unexpected=[] PASS contract; COPY + plant `sneaky_unknown_table_fg1` → cùng logic bắt đúng {'sneaky_unknown_table_fg1'} → FAIL-closed còn nguyên. Log: adversarial_proof.log.
- ruff check tests/test_durable_job_persistence.py → All checks passed!
- Write-set audit: git diff --name-only -- tests/ chỉ có thêm test_durable_job_persistence.py là delta của worker (4 file tests khác đã dirty từ preflight sprint); DB tạm adv_db đã dọn.

STATUS: TASK_SUBMITTED
