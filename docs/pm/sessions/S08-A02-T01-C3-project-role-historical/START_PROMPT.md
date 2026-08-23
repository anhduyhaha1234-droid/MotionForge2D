You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C3 (Project-Role Guard, Historical Pagination Fix, Exactly-One Selector, Test-Quality Correction).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call any Meta provider directly.
- Model: ocg/muse-spark-1.2-contributor (verified PROBE_OK on 9Router 2026-08-20T16:28+07, session 20260820_162838_2ef763; meta/muse-spark-1.2-contributor returns 401 — do NOT use it).
- Reasoning: max (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} — real YAML dict; agent.reasoning_effort = max). Verified in C:\Users\Admin\AppData\Local\hermes\config.yaml.
- No fallback (hermes fallback list empty — verified). Do NOT switch model/provider/fallback. If runtime reports a different model/provider or rejects this model, STOP with REPORT.md = BLOCKED_MODEL_ROUTE and paste the exact error.
- Record actual Hermes session ID, displayed model name, actual model ID, provider, reasoning level, and fallback status in LOG.md and REPORT.md BEFORE any code change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify). Worktree intentionally dirty (~202 entries) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). Do NOT create a new migration — blockers need none.

TASK:
Read FULLY and execute ONLY:
docs/pm/sessions/S08-A02-T01-C3-project-role-historical/TASK.md (normative)

ALSO READ (context only — do NOT trust at face value; re-audit current code):
- docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/TASK.md + REPORT.md (prior cycle)
- docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md
- app/persistence/structural_evidence.py (FULL ~3048 lines)
- app/persistence/models.py (A02 block: ObjectRole ~1006-1080, OccurrenceSegment ~1500-1640)
- app/api/routes/structural_evidence.py (FULL — list_historical_segments ~496-595)
- app/schemas/structural_evidence.py (FULL)
- tests/test_s08_a02_r1_c1_semantic_safety.py, tests/test_s08_a02_structural_evidence_api.py,
  tests/test_s08_a02_structural_evidence_domain.py, tests/test_s08_a02_structural_evidence_migration.py,
  tests/test_s08_a02_phone_interaction_scenario.py, tests/test_s08_a02_c2_integrity.py

SCOPE OF THIS CORRECTION (narrow):
1. BLOCKER 1 — supersede_segment workflow B (and A prior-role path) must reject a target_role_id whose ObjectRole.project_id differs from prior.project_id (project guard), with a clear stable error BEFORE any successor row is created; predecessor not mutated; production-realistic test (same workspace+video+gen+kind, different project) proving rejection + still-active predecessor + no junk successor.
2. BLOCKER 2 — list_historical_segments source_generation branch must NOT fetch limit=10000 then filter/count/paginate in Python. Push business filtering (superseded OR stale generation) into SQL/repository: total = COUNT after all business filters, offset/limit applied after filter in SQL, no full-history load into RAM, exclude current active successor, deterministic ordering. Regression test crossing 10,000 boundary: total=10,001, offset=9900&limit=200 returns exactly 101 rows; test must FAIL on pre-fix code.
3. CONTRACT — historical list endpoint must accept EXACTLY ONE selector (logical_id XOR source_generation): none → 422, both → 422, exactly one → normal. Tests for all three cases.
4. TEST QUALITY — (a) rewrite test_c2f4_concurrent_supersede_single_winner_db as REAL concurrency with independent sessions + threading.Barrier (reuse proven C1 pattern at test_s08_a02_r1_c1_semantic_safety.py::test_c1f2_concurrent_supersede_single_winner) proving ONE winner + valid lineage; (b) rework test_c2f6_rejects_nan_inf to use a REAL DTO float field with allow_inf_nan=False in an otherwise-valid payload, proving NaN/+Inf/-Inf each rejected 422 for non-finite-number reason; (c) no broad try/except Exception turning unexpected errors into PASS.
5. NARROW CLEANUP — remove dead validation helper only if no consumer remains; fix stale "transient SELF-reference" comment (implementation uses deferred placeholder id placeholder_superseded_by_id=_new_id() retargeted to NULL). No refactor beyond scope.

LOGGING:
- Append to docs/pm/sessions/S08-A02-T01-C3-project-role-historical/LOG.md (append-only, real timestamps local +07:00 and UTC=local-7h at write time).
- Fill docs/pm/sessions/S08-A02-T01-C3-project-role-historical/REPORT.md to SUBMITTED (never APPROVED).

BEFORE CHANGING CODE: verify and record pwd, git toplevel, branch, HEAD, git status count, MOTIONFORGE_DATABASE_URL UNSET, alembic heads, and the model provenance block above.

DB/ENV: unset MOTIONFORGE_DATABASE_URL before any test; use only fresh isolated SQLite under C:/Users/Admin/AppData/Local/Temp/ with -p no:cacheprovider and a shallow unique --basetemp per run; never MAIN/user DB.

VALIDATION (capture raw logs in NEW evidence dir output/s08-a02-t01-c3/<your-timestamp>/):
- Run each suite separately (C2 dedicated, C1, API, migration, domain, phone), then the COMBINED focused suite.
- Quality gates: python -m ruff check app tests → 0; python -m mypy app → Success; python -m alembic heads → single a0b1c2d3e4f5; OpenAPI all 9 mutating ops still have concrete typed requestBody.
- REPRO/assertions (log each): wrong-project rejected + no lineage mutation; 10,001 total; offset=9900&limit=200 → 101 rows; both selectors → 422; real concurrent supersede single winner; NaN/+Inf/-Inf rejected via otherwise-valid payload.

TEST INTEGRITY:
- Do NOT delete/weaken tests or change expected values to force a pass. Correct coercion-dependent old tests only to the stricter contract and document it.
- New tests MUST FAIL on current code first (RED) then pass after fix (GREEN).
- Real SQLite/FK/Alembic/repo/router — no mocked repository for blocker tests.

STOP CONDITIONS:
- Do NOT open A02-T02. Do NOT commit/push/merge. Do NOT write MAIN.
- Do NOT self-approve; set REPORT.md = SUBMITTED only, never APPROVED.
- If blocked, set REPORT.md = BLOCKED with exact error/question.
