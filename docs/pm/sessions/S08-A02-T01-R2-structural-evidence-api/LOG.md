# S08-A02-T01-R2 — Structural Evidence Schema and API Contract — LOG

## Session metadata

- Session ID (Hermes): `20260820_043341_c2c01a`
- Model (displayed): `ocg/deepseek-v4-flash` via provider `custom` (9Router
  127.0.0.1:20128), reasoning `max`
- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
  (branch `codex/s08-integration`)
- HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (unchanged at finish)
- Dirty baseline: 197 `git status --short` entries at start (INTENTIONAL;
  never reset/clean/stash/restore/checkout/commit/push/merge) -> 200 at
  finish (the 3 R2 files are additions on top of the baseline).
- MOTIONFORGE_DATABASE_URL: UNSET at start and finish (verified)
- Migration head: `a0b1c2d3e4f5` (single head, `down_revision =
  "f7a8b9c0d1e2"`) — UNCHANGED by R2
- writer_started_at_local: 2026-08-20T04:33+07:00 (UTC 2026-08-19T21:33Z)
- writer_finished_at_local: 2026-08-20T05:49+07:00 (UTC 2026-08-19T22:49Z)

## What R2 delivered (write allowlist only)

R2 builds the STABLE, STRICT schema layer + isolated API router on top of the
ALREADY-VERIFIED C1 core.  R2 did NOT touch `app/persistence/*`, migrations,
deps.py or any other schema/route.

- NEW `app/schemas/structural_evidence.py` — strict Pydantic v2 schemas:
  `model_config = ConfigDict(extra="forbid")` on every model (unknown field
  -> 422); finite-only floats (`allow_inf_nan=False`) plus a recursive
  finite walk over JSON-object payloads (reasons/provenance/transform/ref,
  prompt points & boxes); enums/patterns DERIVED from
  `app.persistence.models` constants (`OBJECT_KIND_PATTERN`,
  `OCCURRENCE_SEGMENT_VISIBILITY_PATTERN`, `CONTACT_KIND_PATTERN`,
  `OCCURRENCE_CONFIDENCE_SOURCES`) and from the repository's canonical
  `MOTION_TRANSFORM_TYPES`; frame/time non-negative + `end >= start`;
  confidence 0..1; bounded algorithm/version/key strings; `reasons:
  list[str]` / `provenance: dict[str, Any]`; NO client-controllable
  `logical_id` or `source_generation` (absent from every request model);
  explicit `state: "current"|"historical"` on every segment read.
  Request models: SegmentCreateRequest/SegmentUpdateRequest/
  SegmentSupersedeRequest, MotionCreateRequest/MotionUpdateRequest,
  OcclusionCreate/UpdateRequest, ContactCreate/UpdateRequest.  Read models:
  SegmentData/MotionData/OcclusionData/ContactData, SegmentListResponse,
  LineageResponse, SupersedeResultData.  Prompt point/box strict shapes
  (PromptEvidence).

- NEW `app/api/routes/structural_evidence.py` — isolated router under
  `/api/v2/structural-evidence` (24 paths; disjoint from every legacy route
  and from `/api/v2/object-intelligence`).  Segments: create current, get
  current (404 on superseded/stale — no existence leak), list current
  (current generation + ACTIVE record only), list/get historical (EXPLICIT +
  read-only; refuses non-explicit historical view), update current (CAS),
  manual correction / supersede (CAS), lineage oldest->newest from ANY
  version.  Motion / occlusion / contact: create / get / list / update
  (CAS).  NO DELETE endpoints.
  - `source_generation` is server-owned: the router resolves it from
    `repo.current_generation()` — never from the client.
  - One request = one transaction; commit after success; `session.rollback()`
    before every mapped error; ORM objects never returned (DTO boundary).
  - Stable error mapping: not-found/cross-workspace -> 404; stale CAS /
    ownership / idempotency -> 409; schema/enum/range/ValueError/JSON -> 422;
    unexpected DB error -> rollback + fail closed 500 (no raw SQL).
  - Framework note (documented in code): FastAPI's default 422 handler
    echoes the RAW parsed body and Starlette's JSONResponse uses
    `allow_nan=False`, so a JSON `NaN`/`Infinity` body would crash the 422
    handler into a 500.  Because app.py may only be touched for import +
    registration, every body-taking endpoint declares a plain dict body
    (`_JSON_BODY`) and validates it STRICTLY in the router via
    `_validate_body(...)` (extra="forbid" Pydantic models) -> a non-finite
    number is a clean, stable 422 (never a 500, never a row).

- MODIFIED `app/api/app.py` — ONLY the import of the new router and one
  `include_router(structural_evidence.router)` statement (+2-line comment).
  No other change.

- NEW `tests/test_s08_a02_structural_evidence_api.py` — **50 tests**: the
  full 46-test API matrix (items 1-45 covering the brief §24 30-item matrix
  plus explicit sub-cases) + 4 schema unit tests.  Real isolated SQLite via
  the conftest durable DB (alembic head, FK/CHECK/partial-unique-enforced),
  no mocks anywhere.

## Design decisions / deviations

1. Body validation moved INTO the router for body-taking endpoints (see
   framework note above) — the only way to satisfy "NaN/Infinity reject ->
   stable 422" without editing app.py past import+registration or
   app/api/deps.py.  All request models remain the same strict Pydantic
   models; only the wiring changed (dict in -> `_validate_body` -> model).
2. Active-only current list is implemented in the router via a scoped ORM
   read (`_active_segments`) because the VERIFIED core repository lists by
   source generation only and R2 may not modify core; this keeps the
   "current generation + active record only" / "historical never mixed with
   current" contract without touching persistence.
3. `video_item_id` is REQUIRED for the current-list endpoint (the current
   generation is inherently per-video; without it there is no single backend
   current to scope to) and required for motion-list.

## Validation (verbatim commands + real counts; MOTIONFORGE_DATABASE_URL unset; `-p no:cacheprovider`)

```text
1. C1 focused regression
   python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py \
     tests/test_s08_a02_structural_evidence_migration.py \
     tests/test_s08_a02_structural_evidence_domain.py \
     tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-c1
   -> 92 passed in 58.66s  (C1 51 + migration 10 + domain 30 + phone 1)

2. Schema unit tests
   python -m pytest tests/test_s08_a02_structural_evidence_api.py -q -p no:cacheprovider \
     -k schema --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-schema
   -> 4 passed (46 deselected) in 1.75s

3. API focused tests
   python -m pytest tests/test_s08_a02_structural_evidence_api.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-api
   -> 50 passed in 32.38s

4. Phone graph API round-trip
   python -m pytest tests/test_s08_a02_structural_evidence_api.py -q -p no:cacheprovider \
     -k phone_interaction --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-phone
   -> 1 passed

5. Combined A02 focused
   python -m pytest tests/test_s08_a02_structural_evidence_migration.py \
     tests/test_s08_a02_structural_evidence_domain.py \
     tests/test_s08_a02_phone_interaction_scenario.py \
     tests/test_s08_a02_r1_c1_semantic_safety.py \
     tests/test_s08_a02_structural_evidence_api.py \
     tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-focused
   -> 205 passed in 126.97s

6. Object-intelligence / grouping / correction regression
   python -m pytest tests/test_s08_a01_c1_merge_kind_safety.py tests/test_s08_a01_c1_migration_safety.py \
     tests/test_s08_a01_c1_reclassify_source_overlay.py tests/test_s08_a01_role_taxonomy.py \
     tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
     tests/test_object_correction.py tests/test_object_correction_api.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_s08_golden_object_intelligence.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-oireg
   -> 217 passed in 188.43s   (IDENTICAL count to the C1 step-6 run -> no regression)

7. Full S08 relevant regression (17 suites)
   python -m pytest tests/test_s08_a01_role_taxonomy.py tests/test_s08_a01_c1_merge_kind_safety.py \
     tests/test_s08_a01_c1_migration_safety.py tests/test_s08_a01_c1_reclassify_source_overlay.py \
     tests/test_s08_golden_object_intelligence.py tests/test_object_grouping.py \
     tests/test_object_correction.py tests/test_object_correction_api.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_object_intelligence_domain.py \
     tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py \
     tests/test_s08_a02_phone_interaction_scenario.py tests/test_s08_a02_r1_c1_semantic_safety.py \
     tests/test_s08_a02_structural_evidence_api.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-s08full2
   -> 359 passed, 0 failed in 277.87s  (fresh clean re-run; an earlier run had
      1 flake in test_golden_vertical_run2_repeatability because ruff+mypy were
      running concurrently -> golden passed 2/2 standalone and in this clean run)

8. Persistence bootstrap + durable job
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r2-boot
   -> 87 passed in 55.50s   (IDENTICAL count to C1 -> no regression)

9. python -m ruff check app tests
   -> All checks passed! (exit 0)

10. python -m mypy app
    -> Success: no issues found in 91 source files (89 pre-existing + the 2 new
       R2 files, zero new issues)

11. git diff --check
    -> exit 0 (pre-existing LF->CRLF advisories only)

12. OpenAPI / import smoke
    python -c "from app.api.app import app; app.openapi()"
    -> 24 /api/v2/structural-evidence paths; NO DELETE on any path; import OK

13. Quality baseline (fresh, ONE run)
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
    -> Run ID **20260820-053350** — 7/7 PASS (overall exit 0)
       Gate 1 preflight PASS · Gate 2 Python tests PASS: **1273 passed, 19
       skipped, 9 deselected** in 826.19s · Gate 3 ruff PASS · Gate 4 mypy
       PASS · Gate 5 tsc PASS · Gate 6 eslint PASS · Gate 7 frontend build
       PASS.
       summary: output/quality-baseline/20260820-053350/summary.json
       NOTE: the FIRST fresh baseline run (20260820-051859) reported
       1 failed / 1272 passed on the pre-existing timing-sensitive S05 test
       `test_s05_atomic_cancel_during_transition_gap_materializes_and_cancels`
       (unrelated to R2 — no touched code path; it passes standalone in 3.33s
       and passed in the clean re-run).  The recorded 7/7 run is the fresh
       Run ID 20260820-053350.

14. Protected hashes — see REPORT.md

15. NO_LISTENERS
    netstat -ano | LISTENING on 3012/3013/8000/8025/8026/8027/8028/8014/8888/
    3000/5173/8002/3010/9495 -> 0 listeners at finish.
```

## Files changed (R2 allowlist)

- Created `app/schemas/structural_evidence.py`
- Created `app/api/routes/structural_evidence.py`
- Created `tests/test_s08_a02_structural_evidence_api.py` (50 tests)
- Modified `app/api/app.py` (ONLY import + include_router)
- Created packet `docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/{LOG,REPORT}.md`
- Created evidence `output/s08-a02-t01-r2/20260820-r2-final/`

No `app/persistence/*`, no `migrations/*`, no `app/api/deps.py`, no other
schema/route, no frontend, no S07/S09 modified.  No MAIN file touched.  No
commit/push/merge/reset/stash/clean/restore/checkout.

## Writer finish (SUBMITTED)

REPORT.md = SUBMITTED (never self-APPROVED) with full validation log, real
counts, fresh baseline Run ID, protected-hash comparison, files-changed
list, session id + model/provider (ocg/deepseek-v4-flash, custom, reasoning
max), local + UTC timestamps.  No R2 / S08-A02-T02 / S07 / S09 started
beyond R2 scope; no second writer spawned.
