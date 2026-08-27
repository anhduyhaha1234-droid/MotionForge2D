# S09-T04 — Demo comparison API/UI

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp riêng `%TEMP%/s09t04-*`, `-p no:cacheprovider`; Playwright port riêng (không trùng 5173/8000 mặc định nếu có server khác).

## Context đã verified
- T03: `/api/v2/s09-demo-loops` submit/status/cancel/replay; s09_demo_jobs.py planner + handler; fixtures tests/fixtures/s09_demo/** (4 loops, 6/6 risk classes).
- T02: renderer routes adaptive pose_swap/sprite_affine; RendererRouteEvidence per segment.
- T01: reskin API pin manifest + route evidence (OpenAPI 229 paths hiện tại).
- Frontend stack: xem frontend/src/features/** hiện có để theo đúng pattern (React + typed client). UI preference của user: dark theme, mọi button PHẢI có helper text tiếng Việt ngắn NGAY DƯỚI nút (text-gray-400 trở lên, min 11px).

## Outcome bắt buộc
1. NEW `frontend/src/features/demo/**`: Demo comparison UI với modes Original/result/split/wipe/blink; hiển thị renderer route per segment; compatibility/QC reason; affected layer/segment khi correction. Loading/error/empty states đầy đủ. KHÔNG fabricated fallback data — mọi số liệu từ API thật.
2. Typed client additions (theo pattern client hiện có).
3. S09 comparison API files backend (nếu cần endpoint riêng cho demo artifacts so sánh) — additive OpenAPI only.
4. `tests/test_s09_t04_*.py` backend + feature-scoped frontend tests.
5. Playwright flow xanh: tạo job → chạy → xem comparison → đổi mode.

## Acceptance gate
- Backend: focused ×2 PASS; OpenAPI removed=0; ruff/mypy sạch.
- Frontend: tsc --noEmit EXIT=0; eslint --max-warnings 0 EXIT=0; feature tests pass.
- Keyboard accessible, mobile responsive, dark theme đúng chuẩn dự án.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
NEW frontend/src/features/demo/** · typed client file(s) theo pattern hiện có (additive) · NEW backend S09 comparison API files (nếu cần) · tests/test_s09_t04_*.py · feature-scoped frontend tests · output/s09/20260823_sprint_full/t04/** · docs/pm/sessions/S09-T04-demo-comparison-api-ui/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · app/persistence/models.py · migrations/** · structural_lock.py · reskin_* · renderer_* · s09_demo_jobs.py (đọc thôi) · network/model download · production DB · git history ops · output task khác · sửa feature reskin đã verified.
