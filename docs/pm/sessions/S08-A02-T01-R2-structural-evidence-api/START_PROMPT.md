You are the ONLY code writer for MotionForge2D task S08-A02-T01-R2 (Structural Evidence Schema and API Contract).

MANDATORY MODEL CONFIGURATION:
- Provider: custom
- Model: ocg/deepseek-v4-flash
- Reasoning: max
- Do NOT switch model/provider/fallback. If the runtime reports a different model/provider or rejects this model, STOP with REPORT.md = BLOCKED and paste the exact error.
- Record actual Hermes session ID, actual displayed model ID/name, provider and reasoning in REPORT.md.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (do NOT modify, ever)

TASK:
Read FULLY and execute ONLY:
docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/TASK.md

Also read (context only):
- docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md + REPORT.md + LOG.md (C1 = verified core)
- docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md + REPORT.md (R1)

REPORT/LOG:
- Append to docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/LOG.md
- Fill docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/REPORT.md to SUBMITTED

R2 SCOPE (SCHEMA + API ONLY — core persistence is ALREADY verified, do NOT modify it):
- Create app/schemas/structural_evidence.py (strict Pydantic v2, extra="forbid", derived enums from
  models.py constants, finite-only, no client-controlled logical_id/source_generation).
- Create app/api/routes/structural_evidence.py (router /api/v2/structural-evidence; segments current/
  historical/lineage; motion; occlusion; contact; CAS updates; manual correction/supersede; NO DELETE).
- Modify app/api/app.py ONLY for router registration.
- Create tests/test_s08_a02_structural_evidence_api.py covering the full 30-item test matrix (real
  SQLite/FK/CHECK/index/transaction, NO mocks; OpenAPI generation; object-intelligence unchanged).
- Transaction: SessionDep/repository pattern; one request = one transaction; commit after success;
  rollback on any exception; no ORM leakage; idempotent replay no second row; stable error mapping
  (422/404 no-existence-leak/409/stable 4xx; no raw SQL errors).
- Historical = explicit + read-only. Defaults = current generation + active record.

STRICT RULES:
- Do NOT modify app/persistence/* (models.py, structural_evidence.py, object_intelligence.py, etc.),
  migrations/*, alembic, frontend, app/api/deps.py, other schemas/routes, extraction/grouping/
  correction code, S07/S09, the 8 pre-existing head-bump test files, MAIN, scripts/quality-baseline.ps1.
- If R2 exposes a CORE bug: do NOT silently edit core from R2 — STOP with a C1-core-correction finding.
- Single writer only. Do not spawn another code writer. Do not start S08-A02-T02 / S07 / S09.
- No commit/push/merge/stash/reset/clean/checkout/restore. Do not edit MAIN.
- No mock/stub/fake data to satisfy tests. Real SQLite/FK/migration paths in isolated temp DBs.
- MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-*.
- Run the full §7 validation order (15 steps); paste verbatim commands + real counts; run the fresh 7/7 quality baseline.
- Do NOT weaken/delete old tests; do NOT adjust expected results to match wrong code.

STOP CONDITION:
When TASK.md requirements pass and REPORT.md is SUBMITTED, exit. Manager then verifies independently;
final R2 manager state = MANAGER_VERIFIED_PENDING_CODEX_REVIEW (A02-T01 NOT APPROVED until Codex).
