# S09-T06A — Immutable approval/checkpoint backend

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; SQLite temp basetemp riêng `%TEMP%/s09t06a-*`, `-p no:cacheprovider`.

## Context đã verified
- T05A: correction services/routes/schemas + migration `b3c4d5e6f7a9` (head hiện tại — discover live khi cần).
- T01: ApplyCheckpoint ORM ĐÃ CÓ từ foundation (models.py) + pin structural_lock_manifest_id + lock_policy_version. ĐỌC kỹ hiện trạng trước khi quyết định additive gì.
- T02: renderer routes adaptive + provenance per segment.
- I01: StructuralLockManifest repo CAS pattern.

## Outcome bắt buộc
1. ApplyCheckpoint persistence/service/schema/routes hoàn chỉnh: Pin pack versions · CompatibilityPolicy evidence/version · renderer routes per segment · StructuralLockManifest ref · accepted warnings/overrides · demo artifacts refs · correction history refs.
2. Nếu còn field thiếu trong ApplyCheckpoint hiện có → additive models.py + ĐÚNG MỘT migration mới (live head discover). Nếu đủ thì KHÔNG migration, ghi rõ quyết định.
3. Immutable semantics: checkpoint tạo xong KHÔNG được mutate bởi source/pack/route changes sau đó — hash verified, later changes không ảnh hưởng stored snapshot.
4. Blockers fail closed: approval bị chặn khi còn blocker chưa resolve; warnings/overrides phải explicit (không implicit accept).
5. Equivalent replay idempotent; conflict/CAS zero mutation.

## Acceptance gate
- Focused/adversarial ×2 PASS: blockers fail-closed, replay idempotent, conflict zero mutation ×2 chiều, checkpoint hash verify pass/fail đúng, later-source-change không mutate.
- Nếu migration mới: single head, round-trip head↔parent, FK check=0, ORM parity, models.py zero-removed vs pre-state.
- OpenAPI removed=0; ruff app+tests; mypy app; git diff --check sạch.
- Self-audit write-set. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
app/persistence/models.py (additive only nếu cần) · migrations/versions/** (max MỘT file mới) · NEW app/services/s09_approval*.py · NEW app/api/routes/s09_approval*.py · NEW app/schemas/s09_approval*.py · tests/test_s09_t06_backend_*.py · output/s09/20260823_sprint_full/t06a/** · docs/pm/sessions/S09-T06A-immutable-approval-backend/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · frontend/** · structural_lock.py · renderer_* files · reskin_* files · s09_demo_jobs.py / s09_correction*.py (chỉ import) · scripts/benchmark · network/model download · production DB · git history ops · output task khác.
