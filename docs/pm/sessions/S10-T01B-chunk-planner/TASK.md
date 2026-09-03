# S10-T01B — Deterministic shot/layer chunk planner — TASK

## Task
S10-T01B — Deterministic shot/layer chunk planner (pure planner, no DB/IO).

## Outcome
Pure planner generates stable full-video work graph from approved source/scene/route/mapping contracts.
Worker writes only allowed scope, satisfies all 6 binary acceptance bullets.

## Required reading
- C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 lines, SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25)
- AGENTS.md, SESSION_PROTOCOL.md, ROADMAP.md, TARGET_PROFILE_2D_SOURCE_LOCKED.md (526 lines, 39634 frames, thresholds median 0.5% P95 1.0%)
- docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md (S09 CODEX_APPROVED/CLOSED)
- docs/pm/prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md
- Preflight baseline: worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f79 — MOTIONFORGE_DATABASE_URL UNSET

## Allowed write scope
- app/services/s10_chunk_plan.py (new, pure)
- tests/test_s10_chunk_plan.py (new)
- docs/pm/sessions/S10-T01B-chunk-planner/** (TASK.md, LOG.md, REPORT.md)
- output/s10/t01b/** (isolated evidence)

## Forbidden
persistence/models/migration, app/api/**, frontend, renderer J1 files, S11/S13, data/**, channels.json

## Binary acceptance
- Same canonical inputs produce byte-identical canonical plan/hash/IDs twice
- Every source frame covered exactly once as core; overlap is explicit context only, never duplicated
- No gap/cut drift/off-by-one across shot and chunk boundaries, including 1-frame shots and final partial chunks
- Layer/role routes and structural dependencies pinned per chunk
- Changing one pinned input changes plan identity; ambient path/time/process data does not
- Malformed/non-monotonic/overlapping manifests fail closed

## Execution steps
1. Preflight: git status, HEAD, TARGET_PROFILE thresholds, no persistence/migration touch
2. Design pure function plan_full_apply(...) -> canonical plan dict with plan_id=sha256(canonical_json)
3. Implement app/services/s10_chunk_plan.py (pure, no DB/IO/time/path, hash from pinned only)
4. Write tests/test_s10_chunk_plan.py covering all 6 bullets (26 tests)
5. Run Ruff scoped, mypy strict, pytest x2 with isolated basetemp; evidence to output/s10/t01b/
6. Write TASK.md, LOG.md, REPORT.md STATUS TASK_SUBMITTED and STOP for manager verification

## Verification
- pytest tests/test_s10_chunk_plan.py -v --cache-clear --basetemp=$(mktemp -d) PASS x2 (26 passed)
- Ruff scoped write-set exit 0
- mypy strict exit 0
- git status only app/services/s10_chunk_plan.py + tests/test_s10_chunk_plan.py + task-owned docs/output
