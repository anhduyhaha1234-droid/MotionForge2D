# S09-T03 — Risk-selected loops/proxy jobs

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md — §4 risk classes, §8 thresholds.
3. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
4. `MOTIONFORGE_DATABASE_URL` UNSET; SQLite temp basetemp riêng `%TEMP%/s09t03-*`, `-p no:cacheprovider`.

## Context đã verified
- T01: reskin persistence/schemas/routes pin manifest + RendererRouteEvidence (OpenAPI 221 paths).
- T02: `app/services/renderer_routes/adaptive_pose_swap.py` + adapters pose_swap/sprite_affine (NVENC thật) + benchmark_results.py; router wiring additive.
- I03/I05: harness + fixtures 6 risk classes (tests/fixtures/s09_renderer/**) — measured pose_swap smallest-passing cả 6.
- Existing durable job infra: app/workflow/durable_worker.py, job_service.py, job_reconciler.py (đọc để tái sử dụng pattern; KHÔNG sửa).

## Outcome bắt buộc
1. Additive models (app/persistence/models.py) + ĐÚNG MỘT migration mới dưới migrations/versions/** CHỈ nếu thật sự cần bảng mới cho demo-loop jobs (down_revision = live head runtime-discovered — hiện là d8e9f0a1b2c3). Nếu dùng được job/step tables hiện có thì KHÔNG tạo migration và ghi rõ quyết định trong REPORT.
2. NEW `app/workflow/s09_demo_jobs.py`: risk-selected demo loop jobs — chọn loop theo risk class từ SegmentRenderRoute/benchmark evidence; durable restart/cancel-safe proxy jobs theo pattern durable_worker hiện có.
3. NEW S09 demo-loop routes/schemas (additive OpenAPI): tạo job, xem status/cancel/replay.
4. `tests/test_s09_t03_*.py` + NEW `tests/fixtures/s09_demo/**`: 3–5 stable-frame loops cover JOINTLY: hard cut · mouth/expression swap · phone contact · whole-body rotation/bed contact · group occlusion · semantic graphic replacement.
5. Idempotent replay: same input → no duplicate artifact; restart/cancel → zero orphan/residue (test kill-mid-run rồi replay).

## Acceptance gate
- Focused ×2 PASS (basetemp khác nhau) + legacy suites liên quan PASS.
- Nếu có migration mới: single head, upgrade→downgrade→upgrade byte-identical empty graph, downgrade fail-closed khi có row, FK check=0, ORM parity, zero-removed models.py proof vs current state trước khi sửa.
- ruff app+tests, mypy app, git diff --check sạch. OpenAPI removed=0.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
app/persistence/models.py (additive only) · migrations/versions/** (max MỘT file mới) · NEW app/workflow/s09_demo_jobs.py · NEW S09 demo-loop routes/schemas files · tests/test_s09_t03_*.py · NEW tests/fixtures/s09_demo/** · output/s09/20260823_sprint_full/t03/** · docs/pm/sessions/S09-T03-risk-loops-proxy-jobs/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · frontend/** · structural_lock.py · renderer_* files · reskin_* files · scripts/s09_renderer_benchmark.py · network/model download · production DB · git history ops · output task khác.
