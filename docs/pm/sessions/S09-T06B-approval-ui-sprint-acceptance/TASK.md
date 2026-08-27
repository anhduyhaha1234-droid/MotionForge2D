# S09-T06B — Approval UI/sprint acceptance

## Role
Bạn là WORKER CUỐI CÙNG của sprint S09. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp riêng; Playwright ports riêng (:8099 QA backend + :3014 dev pattern từ T04/T05B).

## Context đã verified (toàn bộ sprint)
- T06A: s09_approval services/routes/schemas (30 tests ×2) — đọc REPORT docs/pm/sessions/S09-T06A-immutable-approval-backend/REPORT.md cho exact API payload; KHÔNG migration mới, head b3c4d5e6f7a9.
- T05B: CorrectionPanel.tsx trong frontend/src/features/demo/** + e2e spec pattern + global-setup idempotent.
- T04: CompareViewer/DemoComparePanel/useDemoCompare.

## Outcome bắt buộc
1. S09 approval UI trong frontend/src/features/demo/** (component mới ApprovalPanel hoặc tương tự): explicit confirm UX — hiển thị checkpoint summary (pack versions/policy/routes per segment/manifest ref/warnings/overrides/corrections), blocker list fail-closed (không approve được khi còn blocker), checkbox explicit accept cho từng warning/override trước khi enable nút Approve, checkpoint hash hiển thị + verify status.
2. UI: dark theme; MỖI button helper text tiếng Việt ngay dưới (text-gray-400+, 11px+); loading/error/conflict states; keyboard accessible.
3. Typed client additions additive.
4. E2E Playwright: Demo→correct→approve full flow (dùng global-setup idempotent pattern T05B): tạo job → chạy → correction → approval với blocker → resolve → approve thành công → checkpoint reloadable (reload trang vẫn thấy).
5. Acceptance artifacts output/s09/20260823_sprint_full/t06b/**: reproducible evidence (commands + results + hashes).

## Acceptance gate
- tsc --noEmit EXIT=0; eslint --max-warnings 0 write-set FE.
- Playwright FULL PASS ×2 runs khác seed/timestamp (idempotent setup); skip chỉ by-design có lý do.
- Backend T06A suites rerun 1 lần confirm xanh (30 passed); targeted recompute verified qua test.
- Không approval khi còn blocker (test assert); warnings/overrides explicit.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
frontend/src/features/demo/** (mở rộng) · NEW S09 approval Playwright spec + config + global-setup · feature-scoped FE tests · typed client additions · output/s09/20260823_sprint_full/t06b/** · docs/pm/sessions/S09-T06B-approval-ui-sprint-acceptance/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · mọi backend file (chỉ đọc) · migrations · network/model download · production DB · git history ops · output task khác · sửa feature/component đã verified của task khác.
