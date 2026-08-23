# S08-A02-T01-C3 — Project-Role Guard, Historical Pagination Fix, Exactly-One Selector, Test-Quality Correction

Normative correction cycle for MotionForge2D task **S08-A02-T01** (structural evidence,
supersede/lineage/API).  NARROW correction only — do NOT refactor beyond the listed scope.

## 1. Mandatory model configuration (BLOCKED on mismatch)

- Provider: `muse` (Meta Muse via 9Router — base_url `http://127.0.0.1:20128/v1`, api_mode `codex_responses`).
  DO NOT call any Meta provider directly.
- Model: `ocg/muse-spark-1.2-contributor` (verified PROBE_OK on 9Router 2026-08-20T16:28+07,
  session `20260820_162838_2ef763`).  `meta/muse-spark-1.2-contributor` returns 401 — do NOT use.
- Reasoning: `max` (config `agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max}`,
  real YAML dict, `agent.reasoning_effort: max`). Verified in `C:\Users\Admin\AppData\Local\hermes\config.yaml`.
- No fallback.  If the runtime reports a different model/provider or rejects this model,
  STOP with `REPORT.md = BLOCKED_MODEL_ROUTE` and paste the exact error.
- Record actual Hermes session ID, displayed model name, actual model ID, provider, reasoning
  level, fallback status in LOG.md and REPORT.md BEFORE any code change.

## 2. Worktree guard

- ONLY worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
- Branch: `codex/s08-integration`; HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- MAIN protected: `C:\Users\Admin\MotionForge2D` — never modify.
- Worktree is INTENTIONALLY dirty (~202 entities).  Never reset/clean/stash/restore/checkout/
  commit/push/merge.
- `MOTIONFORGE_DATABASE_URL` must stay UNSET; tests use fresh isolated SQLite under
  `C:/Users/Admin/AppData/Local/Temp/`, `-p no:cacheprovider`, shallow unique `--basetemp`.
- Never use `data/motionforge.db` or any user DB.

## 3. Baseline hashes (verified by manager preflight 2026-08-20T16:30+07 — do NOT regress)

- app/persistence/structural_evidence.py: d480428ba39df118f074e081f0eefba431087b7f0d40b523c4804127d9a815e0
- app/api/routes/structural_evidence.py: 04fc4451165492ed70b90b9f89176a2c54ac031634db11e150e6d14e8873af22
- app/schemas/structural_evidence.py: 9a97855e482e649939e2d763a27c9f7a8b6c49730ef69c7ee6f1fdcb9244de87
- app/persistence/models.py: de4546832cf4d15151f936ebe4fddcd4f49a38857c678cc486bd949bc619d8e5
- migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py: 16b31c444547ffcfad28e28bf9652285effea32ac31b64627690a7dfb22dfb71
- tests/test_s08_a02_c2_integrity.py: 7186614b673037a222c2f1c23f1d768928de59e23647b51f159a95ab38ac5308
- tests/test_s08_a02_structural_evidence_api.py: ad7aef4d00a6bb9c7e8be60cdb6db5cd952c9398a0eec497a4c592d9c4e83bea
- tests/test_s08_a02_r1_c1_semantic_safety.py: 1c1e488d400d52e242fae5dddbc7cdb45da260c5a61d4cc6035bc88f561852ae
- Alembic head: `a0b1c2d3e4f5` (single).  Do NOT create a new migration — expected no migration needed.

## 4. Required reading (read FULLY before editing)

- `docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/TASK.md` + `REPORT.md` (prior cycle contract)
- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
- `app/persistence/structural_evidence.py` (FULL, ~3048 lines) — especially `_assert_role_ownership`
  (~684-698), `_assert_role_compatible` (~700-722), `_assert_full_ownership` (~820-844),
  `supersede_segment` (~1621-1944), `list_segments` (~1363-1405), `segment_lineage` (~1946+)
- `app/persistence/models.py` — A02 block: `ObjectRole` (~1006-1080, has `project_id`),
  `OccurrenceSegment` (~1500-1640)
- `app/api/routes/structural_evidence.py` (FULL) — especially `list_historical_segments` (~496-595)
- `app/schemas/structural_evidence.py` (FULL) — field types for NaN/Infinity tests
- All five existing A02 test files + `tests/test_s08_a02_c2_integrity.py`

## 5. BLOCKER 1 — TARGET ROLE BELONGING TO THE WRONG PROJECT IS STILL ACCEPTED

**Location:** `app/persistence/structural_evidence.py` — `supersede_segment` workflow B.

The supersede-to-`target_role_id` workflow checks `workspace_id`, `video_item_id` (in
`_assert_role_ownership` / inline ~1819-1828) and `_assert_role_compatible` (generation + kind,
~1829), but it NEVER verifies the target role's `project_id` against the predecessor/current
evidence.  `ObjectRole.project_id` exists (models.py:1052) and a role from a DIFFERENT project can
currently be bound as successor target.

Requirements:
- A target role is valid ONLY when:
  - `workspace_id` == predecessor/current evidence (`prior.workspace_id`);
  - `project_id` == predecessor/current evidence (`prior.project_id`);
  - `video_item_id` == predecessor/current evidence (`prior.video_item_id`);
  - `source_generation` == the requested/correct generation;
  - `kind` compatible with the successor kind.
- A wrong-project role MUST be rejected with a clear, stable error BEFORE any successor row is
  created (zero mutation of predecessor + zero successor rows).
- Do NOT mutate the predecessor when validation fails.
- Equivalent guard should also hold for the workflow-A prior-role path for symmetry (prior role
  must match prior project) — keep behavior strict and consistent.
- **Production-realistic test** (repo + real SQLite+FK+Alembic, NOT mocked repository) proving:
  - same workspace; same video; valid generation & kind; **different `project_id`**;
  - `supersede_segment` MUST fail (stable `OwnershipMismatchError` or documented stable error);
  - predecessor still ACTIVE (`superseded_by_id IS NULL`), no junk successor row;
  - DB lineage holds (still exactly the original rows, PRAGMA foreign_key_check empty).

## 6. BLOCKER 2 — HISTORICAL API TRUNCATED AT 10,000 ROWS

**Locations:** `app/api/routes/structural_evidence.py` `list_historical_segments`
~lines 550-583 (source_generation branch), and the repository/query layer.

Current behavior: for the `source_generation` selector the route calls
`repo.list_segments(..., limit=10000, offset=0)`, then filters "truly historical"
(superseded OR stale generation) IN PYTHON, computes `total = len(filtered2)` and slices
`filtered2[offset:offset+limit]` in memory.  When there are >10,000 matching rows the cap
corrupts BOTH `total` and pagination.

Confirmed repro: 10,001 valid historical rows → API reports `total=10000`;
`offset=9900, limit=200` returns 100 rows instead of 101.

Requirements:
- Remove the hard 10,000 cap from correctness logic.
- Push filtering DOWN into the SQL/repository layer (a repository method that applies the
  business filter — superseded OR stale generation — as SQL predicates before COUNT and
  before OFFSET/LIMIT).
- `total` MUST be a COUNT of rows after ALL business filters.
- `offset`/`limit` MUST be applied AFTER the correct filter (in SQL/repository).
- Do NOT load the entire history into Python memory just to paginate.
- API MUST still exclude the current ACTIVE successor per the existing contract
  (historical == superseded OR stale-generation; active current successor excluded).
- Deterministic results with explicit ordering (stable tie-breaker, e.g. existing
  `start_frame, end_frame, z_order, id` or a documented deterministic key).
- **Regression test** that genuinely crosses the 10,000 boundary — bulk fixture/insert is fine,
  but it must PROVE the boundary (not a fake test that avoids it):
  - `total` == 10,001;
  - `offset=9900&limit=200` returns exactly 101 rows.
  - Use real repo/DB (SQLite + FK + Alembic); the test must FAIL on the pre-fix code.

## 7. CONTRACT FIX — EXACTLY ONE SELECTOR

**Location:** `app/api/routes/structural_evidence.py` `list_historical_segments` (~line 517).

Historical list endpoint must accept EXACTLY ONE of:
- `logical_id`
- `source_generation`

Requirements:
- No selector provided → HTTP 422.
- BOTH provided → HTTP 422.
- Exactly one provided → normal processing.
- Keep OpenAPI and runtime behavior consistent.
- Add tests for all three cases (no selector / both / exactly-one-succeeds).

## 8. TEST QUALITY FIXES

### 8.1 Dedicated concurrency test (REAL concurrency)
- Existing `test_c2f4_concurrent_supersede_single_winner_db`
  (`tests/test_s08_a02_c2_integrity.py:725`) is named “concurrent” but actually runs TWO
  SEQUENTIAL supersede calls.  Rewrite it as REAL concurrency.
- Use two (or more) independent transactions/sessions plus a synchronization barrier
  (`threading.Barrier` — reuse the proven pattern from
  `tests/test_s08_a02_r1_c1_semantic_safety.py::test_c1f2_concurrent_supersede_single_winner`
  ~line 767).
- Prove exactly ONE supersede wins and DB keeps valid lineage (2 rows: predecessor→successor,
  successor active; single `ok:` outcome).
- Do NOT simply rename the test to dodge the requirement.

### 8.2 NaN / Infinity test (real schema field, each value separately)
- Current `test_c2f6_rejects_nan_inf` uses `MotionCreateRequest` with `transform_type` +
  `transform_json` — the 422 may be caused by an unrelated reason (wrong field / transform
  validation), not by non-finite-number validation.  Rework it.
- Use a REAL schema/field of the endpoint (e.g. a float field with `allow_inf_nan=False` from
  the actual request DTO, such as a start/end coordinate or confidence field) and a payload that
  is VALID in every other respect.
- For `NaN`, `+Infinity`, and `-Infinity`, prove each value is rejected with 422 BECAUSE of
  non-finite-number validation (stable location/reason).
- If asserting detail, avoid over-coupling to internal message format, but confirm the correct
  location/reason.

### 8.3 Assertions
- Do NOT use broad `try/except Exception` to turn unexpected errors into PASS.
- Every test must FAIL if the named behavior is not actually executed.

## 9. NARROW CLEANUP (in touched files only)

- Remove dead helper/validation code no longer used after the typed request DTO refactor, ONLY
  when certain there is no remaining consumer.
- Fix the stale comment in `supersede_segment` (~lines 1860-1867) that describes a
  "transient SELF-reference" — the implementation actually uses a DEFERRED PLACEHOLDER id
  (`placeholder_superseded_by_id=_new_id()`, retargeted to NULL after the predecessor CAS).
- No refactoring beyond scope.  No public API change beyond the contract fixes above.

## 10. DB/ENV requirements

- `MOTIONFORGE_DATABASE_URL` UNSET before running tests.
- Only temporary SQLite/test DBs.  Never MAIN/user DB.
- Verify ONE Alembic head (`a0b1c2d3e4f5`).
- Do NOT create a new migration (the two main blockers need none).

## 11. Allowlist (exact)

Production:
- app/persistence/structural_evidence.py
- app/api/routes/structural_evidence.py
- app/schemas/structural_evidence.py (only if genuinely required by the fraction of contract fixes)
- app/persistence/models.py (A02 block ONLY if a DB constraint change is genuinely required — expected NO change)

Tests:
- tests/test_s08_a02_r1_c1_semantic_safety.py
- tests/test_s08_a02_structural_evidence_api.py
- tests/test_s08_a02_structural_evidence_domain.py
- tests/test_s08_a02_structural_evidence_migration.py
- tests/test_s08_a02_phone_interaction_scenario.py
- tests/test_s08_a02_c2_integrity.py (new dedicated C3 tests may be added here or in a new
  `tests/test_s08_a02_c3_*.py` within the A02 test scope)

Evidence:
- docs/pm/sessions/S08-A02-T01-C3-project-role-historical/
- output/s08-a02-t01-c3/

FORBIDDEN without BLOCKED_SCOPE + one question:
- app/persistence/object_intelligence.py (authority — read-only reference)
- any other migration, frontend, A02-T02, S07/S09, renderer/dense-flow/video regeneration
- existing unrelated dirty files, MAIN, any file outside allowlist, commit/push/merge
- using data/motionforge.db or user DBs
- deleting/weakening tests, changing expected values to force a pass

## 12. TEST INTEGRITY

- Do NOT delete/weaken tests; do NOT change expected values to obtain a pass.
- Correct coercion-dependent old tests only to the stricter contract and DOCUMENT the change.
- New tests MUST FAIL on the pre-fix (current) code — run them first to prove RED, then GREEN.
- Use real SQLite, FK, Alembic, repo, router.  No mocked repository/DB for blocker tests.
- Green suite is NOT approval; manager verifies independently.

## 13. Validation commands (run and CAPTURE raw logs — evidence dir is NEW, do not reuse old logs)

Run SEPARATELY (each in its own log file):
1. Dedicated C2 tests: `python -m pytest tests/test_s08_a02_c2_integrity.py -p no:cacheprovider -q`
2. C1 regression: `python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py -p no:cacheprovider -q`
3. Structural evidence API: `python -m pytest tests/test_s08_a02_structural_evidence_api.py -p no:cacheprovider -q`
4. Migration/constraint: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -p no:cacheprovider -q`
5. Domain: `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -p no:cacheprovider -q`
6. Phone smoke: `python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -p no:cacheprovider -q`

Then COMBINED focused suite:
`python -m pytest tests/test_s08_a02_c2_integrity.py tests/test_s08_a02_r1_c1_semantic_safety.py tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_structural_evidence_api.py tests/test_s08_a02_phone_interaction_scenario.py -p no:cacheprovider -q`

Quality gates (log each):
- `python -m ruff check app tests` → 0 errors
- `python -m mypy app` → Success
- `python -m alembic heads` → single `a0b1c2d3e4f5`
- OpenAPI: all 9 mutating ops still have concrete typed requestBody
  (inspect `app.openapi()`; assert $ref/properties, not generic `{type:object, additionalProperties:true}`)

REQUIRED independent repros (each with its own logged assertion):
- Wrong-project target role rejected; predecessor active; no successor junk row.
- Historical dataset of 10,001 rows reports total=10,001.
- offset=9900 & limit=200 returns exactly 101 rows.
- Both logical_id + source_generation present → 422.
- Real concurrent supersede → exactly one winner.
- NaN/+Inf/-Inf rejected via an otherwise-valid payload.

## 14. Output / evidence

- Create a NEW evidence dir (not reused): `output/s08-a02-t01-c3/<writer-timestamp>/`
- Writer fills `docs/pm/sessions/S08-A02-T01-C3-project-role-historical/REPORT.md` as **SUBMITTED**
  (never APPROVED) with: session ID, actual model route, reasoning level, changed files with
  hashes, per-correction description, commands run with exit codes, passed/failed counts,
  raw-log paths, post-correction hashes, warnings/limitations.
- Append real-timestamped entries (local +07:00 and UTC=local−7h at write time) to LOG.md.

## 15. Do NOT claim PASS if any of:
- hardcoded 10,000 still affects correctness;
- project_id check missing;
- dedicated tests pass for an unrelated reason;
- evidence empty or counts don't match logs;
- any focused regression fails.
