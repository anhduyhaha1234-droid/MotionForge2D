# S10-T01A — Durable FullApply domain + checkpoint contract — TASK

## Task
S10-T01A — Durable FullApply domain + checkpoint contract.

## Outcome
Dau kien domain/persistence/migration cho apply run, chunk state, publication va immutable approval linkage.

## Required reading
- C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 lines, SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25)
- AGENTS.md, SESSION_PROTOCOL.md, ROADMAP.md, TARGET_PROFILE_2D_SOURCE_LOCKED.md (526 lines, 39634 frames, thresholds median 0.5% P95 1.0%)
- docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md (S09 CODEX_APPROVED/CLOSED)
- docs/pm/prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md
- Preflight baseline: worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f79 — MOTIONFORGE_DATABASE_URL UNSET

## Allowed write scope (nghiêm)
- app/persistence/models.py (append S10 enums/tables)
- app/persistence/s10_full_apply.py (new)
- app/schemas/s10_full_apply.py (new)
- dung mot migration moi duoi migrations/versions/
- tests/test_s10_full_apply_domain.py (new)
- tests/test_s10_full_apply_migration.py (new)
- docs/pm/sessions/S10-T01A-durable-domain/** va isolated output output/s10/t01a/**

## Forbidden
renderer J1 files, frontend, app/api/app.py, S11/S13, data/**, channels.json.

## Binary acceptance
- one live migration head; forward + bounded downgrade/upgrade round trip tren isolated DB; existing S09 rows survive;
- immutable foreign linkage to approved ApplyCheckpoint revision/hash; stale/cross-project checkpoint rejected;
- durable states va uniqueness/idempotency ngan duplicate run/chunk/publication lineage;
- no completed publication can reference .partial, missing or unverified artifact;
- domain can represent deterministic shot/layer chunk boundaries, overlap, attempts va resume evidence.

## Execution steps
1. Preflight: git status, git rev-parse HEAD, ls migrations/versions/, kiem tra MOTIONFORGE_DATABASE_URL unset, doc models.py va alembic.ini.
2. Thiet ke domain: FullApplyRun, FullApplyChunk (shot/layer, core range + overlap context, attempt, state), FullApplyPublication (atomic publish, immutable linkage to ApplyCheckpoint id+revision_hash, content_hash, frame metadata), stale guard.
3. Viet migration duy nhat (down_revision = head hien tai), chay alembic upgrade head tren isolated DB va downgrade/upgrade round trip.
4. Viet app/persistence/s10_full_apply.py va app/schemas/s10_full_apply.py.
5. Viet tests/test_s10_full_apply_domain.py va tests/test_s10_full_apply_migration.py cover du 5 bullet tren.
6. Chay Ruff scoped, mypy, pytest targeted x2 voi isolated basetemp; raw evidence vao output/s10/t01a/.
7. Ghi TASK.md, LOG.md, REPORT.md theo template SESSION_PROTOCOL (status SUBMITTED, khong APPROVED, liet ke file changed, test counts, migration head, evidence paths).
8. Append registry neu can nhung khong sua dong task khac.

## Verification
- alembic current hien dung mot head moi.
- pytest tests/test_s10_full_apply_domain.py tests/test_s10_full_apply_migration.py -v --cache-clear --basetemp=$(mktemp -d) PASS x2.
- git diff --check khong bao loi moi trong write-set.
- git status --porcelain chi cham file trong allowlist.

---

## C4a — Correction round (2026-08-30, resumed session 20260827_234001_9d7f39)

- Authority: `C:/Users/Admin/MotionForge2D/docs/pm/reviews/S10_C4_BLOCKER_PM_DECISION_2026-08-30.md` — CONTINUATION_AUTHORIZED / NOT_APPROVED; owner S10-T01A, exact session `20260827_234001_9d7f39`.
- Finding: P2 — Ruff F841 at `tests/test_s10_full_apply_domain.py:172` (`sf = _session_factory(db)` assigned but never read; test uses `Sf2` at 174+). Foreign-owned to T01A → routed here.
- Correction (tối thiểu tuyệt đối): delete ONLY line 172. No rename of `Sf2`, no reformat, no assertion/fixture/behavior change, no app/** or other test touched.
- Binary acceptance C4a: focused domain x2 fresh isolated roots green; migration x1 green; Ruff --select F (9 prod + 8 tests) zero; exact 9-file mypy literal Success; full tests/test_s10*.py green; git diff --check 0; alembic head a10b11c12d3e single; J1-v4 13/13 retained; git status --porcelain no foreign drift.
- Terminal: STATUS: TASK_SUBMITTED (worker stop; no MANAGER_VERIFIED/APPROVED/CLOSED; no commit/push/merge).
