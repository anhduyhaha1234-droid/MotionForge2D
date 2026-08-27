# S09-T05B — Correction UI/E2E

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp riêng; Playwright port riêng (:8099 backend QA + :3014 dev đã dùng ở T04 — tái sử dụng pattern đó).

## Context đã verified (T04 pattern chuẩn)
- T05A: correction API `/api/v2/s09-corrections*` (masks, z-order, contacts, mesh/parts, route override) + CAS/idempotency fail-closed + provenance history + migration `b3c4d5e6f7a9`. Đọc REPORT tại docs/pm/sessions/S09-T05A-targeted-correction-backend/REPORT.md để biết exact API payload.
- T04: frontend/src/features/demo/** (CompareViewer/DemoComparePanel/useDemoCompare), Playwright spec e2e/s09-t04-demo-compare.spec.ts, QA run script output/s09/20260823_sprint_full/t04/run-qa-backend.sh — tái sử dụng pattern.

## Outcome bắt buộc
1. Correction UI trong `frontend/src/features/demo/**` (thêm component mới hoặc mở rộng DemoComparePanel): chọn segment/layer → submit correction từng loại (mask, z-order, contact, mesh/part, route override) → hiển thị affected layer/reason sau regenerate → KHÔNG full-video rerun indicator.
2. UI PHẢI: dark theme; MỖI button có helper text tiếng Việt ngay dưới nút (text-gray-400+, min 11px); loading/error/conflict states (CAS conflict hiện rõ); route override form có dropdown 5 routes enum + reason bắt buộc.
3. S09 Playwright spec: E2E Demo→correct→approve-flow-prep: submit correction qua UI → thấy conflict khi replay same idempotency key → override route thành công với provenance hiển thị.
4. Exact API payload: đúng schema T05A (đọc schemas/s09_correction.py).

## Acceptance gate
- tsc --noEmit EXIT=0; eslint --max-warnings 0 (write-set FE).
- Playwright FULL spec PASS (desktop + mobile nếu có; skip phải by-design có lý do).
- Feature-scoped frontend tests pass; backend T05A suites vẫn xanh (chạy lại 1 lần confirm không phá).
- Accessibility cơ bản: keyboard navigation cho correction form.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
frontend/src/features/demo/** (mở rộng) · NEW S09 Playwright spec files · feature-scoped frontend test files · typed client additions (additive) · output/s09/20260823_sprint_full/t05b/** · docs/pm/sessions/S09-T05B-correction-ui-e2e/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · mọi backend file (T05A owned — chỉ đọc) · migrations · network/model download · production DB · git history ops · output task khác · sửa feature khác.
