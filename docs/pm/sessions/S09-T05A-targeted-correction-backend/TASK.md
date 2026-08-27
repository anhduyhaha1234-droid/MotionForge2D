# S09-T05A — Targeted correction backend

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; SQLite temp basetemp riêng `%TEMP%/s09t05a-*`, `-p no:cacheprovider`.

## Context đã verified
- T03: s09_demo_jobs.py planner/handler + `/api/v2/s09-demo-loops` + fixtures 6/6 classes.
- T02/T01: renderer route per segment (SegmentRenderRoute) + RendererRouteEvidence; reskin pin manifest.
- I01: structural_lock repo CAS/idempotency pattern — tái sử dụng cho correction CAS.

## Outcome bắt buộc
Corrections cho: masks · z-order · contacts · mesh/parts · route override. Chỉ regenerate affected loop/layer/segment (KHÔNG full-video rerun).

1. Additive S09 correction persistence/model trong app/persistence/models.py CHỈ nếu thật sự cần bảng mới; nếu có thì ĐÚNG MỘT migration mới (down_revision = live head runtime-discovered, hiện d8e9f0a1b2c3). Nếu dùng được bảng hiện có (segment_render_route history / job tables) thì không tạo migration và ghi lý do.
2. NEW S09 correction services/routes/schemas: submit correction (mỗi loại một endpoint hoặc một endpoint typed payload), conflict/CAS fail-closed, idempotency key workspace-scoped.
3. Route override correction PHẢI persist provenance (route_from/route_to/reason/evidence) qua SegmentRenderRoute history — không mutate row cũ.
4. Regeneration scope: chỉ affected loop/layer/segment — test unaffected hashes byte-identical trước vs sau correction.
5. Correction counts phải flow vào benchmark results schema (đếm được khi chạy harness sau correction).

## Acceptance gate
- Focused/adversarial ×2 PASS (basetemp khác nhau): CAS/idempotency conflict zero mutation ×2 chiều; restart/cancel safe; unaffected hashes byte-identical; provenance persisted.
- Nếu có migration mới: single head, round-trip byte-identical empty graph, downgrade fail-closed khi có row, FK check=0, ORM parity, models.py zero-removed proof so với state trước sửa.
- OpenAPI removed=0; ruff app+tests; mypy app; git diff --check sạch.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
app/persistence/models.py (additive only) · migrations/versions/** (max MỘT file mới) · NEW app/services/s09_correction*.py · NEW app/api/routes/s09_correction*.py · NEW app/schemas/s09_correction*.py · tests/test_s09_t05_backend_*.py · output/s09/20260823_sprint_full/t05a/** · docs/pm/sessions/S09-T05A-targeted-correction-backend/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · frontend/** · structural_lock.py · renderer_* files · reskin_* files · s09_demo_jobs.py (chỉ import) · scripts/benchmark harness · network/model download · production DB · git history ops · output task khác.
