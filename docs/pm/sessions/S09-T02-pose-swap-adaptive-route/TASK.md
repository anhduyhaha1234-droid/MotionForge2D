# S09-T02 — Pose-swap/affine adaptive route

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md — §4 P0-7, §5 route priority, §8 thresholds.
3. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
4. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp riêng `%TEMP%/s09t02-*`, `-p no:cacheprovider`.

## Context đã verified (24/08 01:50+07)
- I01: StructuralLockManifest/SegmentRenderRoute ORM + repo `app/persistence/structural_lock.py` (record_render_route, anchors [0,1], route enum exact 5).
- I02-T00: `app/services/renderer_router.py` + `app/services/renderer_contract.py` + adapters FFmpeg/NVENC thật (h264_nvenc RTX 5070 OK, probe min-dim đã fix 256×256). Route selection/override/provenance/failure taxonomy fail-closed.
- T01 verified: reskin persistence/schemas/routes pin StructuralLockManifest + RendererRouteEvidence; OpenAPI 221 paths additive.
- I05 measured: pose_swap smallest-passing ở cả 6 risk classes (output/s09/20260823_sprint_full/t00-i05/measured_seed20260823/benchmark_results_seed20260823.json); reference VERIFIED.

## Outcome bắt buộc
1. NEW renderer implementation files (app/services/renderer_routes/** hoặc app/adapters/renderer/ mở rộng — KHÔNG sửa renderer_router.py/contract.py trừ wiring point được phép theo ownership transfer bên dưới): pose_swap adaptive implementation dùng NVENC pipeline thật; sprite_affine path tối ưu từ measured baseline (0.90–6.15ms/fr).
2. Adaptive logic: chọn route theo measured error per segment dựa trên benchmark results schema (không hard-code kết quả — đọc results JSON runtime hoặc re-run harness khi cần); mọi escalation qua router provenance API, không silent.
3. Ownership transfer ĐƯỢC PHÉP duy nhất cho wire point: thêm import/registration của implementation mới vào `app/services/renderer_router.py` (additive lines only — zero removed, giữ nguyên behavior hiện có).
4. Backend anchor parity: SegmentRenderRoute rows (route/anchors/provenance) khớp output thực tế của renderer — test round-trip.
5. `tests/test_s09_t02_*.py`: applicable golden classes đạt thresholds (dùng fixtures s09_renderer), hai-run determinism, không silent/unmeasured escalation, legacy regressions xanh (chạy ít nhất test_s09_t00_renderer_router_* + test_s09_reskin_config_*).

## Acceptance gate
- Focused ×2 PASS (basetemp khác nhau) + legacy suites PASS.
- Benchmark smoke: chạy scripts/s09_renderer_benchmark.py với implementation mới trên ≥1 golden fixture, kết quả ghi evidence (frozen SHA phải còn khớp nếu harness/fixtures không đổi; nếu harness cần mở rộng thì bump schema_version=2 và giải trình trong REPORT).
- ruff app+tests, mypy app, git diff --check sạch; frontend không đụng.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
NEW app/services/renderer_routes/** · app/adapters/renderer/** (thêm file mới; nvenc.py chỉ được sửa nếu fix bug thật có evidence) · app/services/renderer_router.py (ADDITIVE wiring only) · tests/test_s09_t02_*.py · output/s09/20260823_sprint_full/t02/** · docs/pm/sessions/S09-T02-pose-swap-adaptive-route/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · frontend/** · migrations/** · models.py · structural_lock.py · reskin_* files (T01 owned) · benchmark harness/scripts (I03 owned — đọc thôi) · network/model download · production DB · git history ops · output task khác.
