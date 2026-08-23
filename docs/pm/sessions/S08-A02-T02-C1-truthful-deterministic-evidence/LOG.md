# S08-A02-T02-C1 — LOG (append-only, local +07:00 / UTC=local-7h)

## 2026-08-20T20:22:00+07:00 / 2026-08-20T13:22:00Z — MANAGER PREFLIGHT (LANE B)
- updater: HERMES MANAGER (ocg/muse-spark-1.2-contributor @ muse, reasoning max, no fallback)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration;
  HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; status ~206; DB UNSET; alembic single a0b1c2d3e4f5;
  MAIN a43b20da (master) protected; no QA listeners.
- Context: Codex CHANGES_REQUESTED for C4 scalability + T02 truthfulness. This is LANE B (T02-C1).
- Baseline hashes (pre-writer):
  - app/services/object_extraction.py = 90b542552b54b4c791b0b82c897d64a34975b9b499c7ae94eb11208c382bb1dc
  - app/schemas/object_extraction.py = 3ac5137153a3d58419c0b36b288761f0907e419f2cadab00b12576c422abeba6
  - app/api/routes/object_extraction.py = c37b7968d67cda8988519e01528b4e81ad1ca6fd6b01121f4e1db6a0611800a2
  - tests/test_object_extraction.py = fa0ef0d42fa6d6ef223acceec60a581729e8b9da776318c552b6c30b16e7171c
  - tests/test_object_extraction_api.py = dae39141e84add83f6fda2cd68ac9df13bfcdef470b7c62f46225b4af22b9acd
  - tests/test_object_extraction_production_wiring.py = bed6d4a28be880de69a367b958078569212ad4bf8fd9e1781bc48df196811a5f
- Confirmed in code: hash(seg_id) ~2339; synthetic motion/occlusion/contact unconditional;
  deterministic-layout in production; bbox fabricate; confidence default 0.7 ~2264; precedence-bug
  "already bound" swallow ~2333/2364/2405/2445.
- Model route: ocg/muse-spark-1.2-contributor via muse/9Router probe OK.
- Evidence: output/s08-a02-t02-c1/20260820_202100_manager_preflight/

[next: dispatch LANE B writer Muse]

## 2026-08-20T20:32:11+07:00 / 2026-08-20T13:32:11Z — WRITER PREFLIGHT (LANE B) BEFORE ANY CHANGE
- writer: Hermes Agent (session 20260820_202903_5d9891)
- Model: ocg/muse-spark-1.2-contributor via provider muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning max, no fallback, fallback=[]
- Config verified: agent.reasoning_effort=max, reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict (not JSON string)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; git status 208 (intentional dirty)
- MOTIONFORGE_DATABASE_URL: UNSET
- Alembic head: a0b1c2d3e4f5 (single)
- Baseline allowlist hashes pre-writer (re-verified):
  - app/services/object_extraction.py = 90b542552b54b4c791b0b82c897d64a34975b9b499c7ae94eb11208c382bb1dc
  - app/schemas/object_extraction.py = 3ac5137153a3d58419c0b36b288761f0907e419f2cadab00b12576c422abeba6
  - app/api/routes/object_extraction.py = c37b7968d67cda8988519e01528b4e81ad1ca6fd6b01121f4e1db6a0611800a2
  - tests/test_object_extraction.py = fa0ef0d42fa6d6ef223acceec60a581729e8b9da776318c552b6c30b16e7171c
  - tests/test_object_extraction_api.py = dae39141e84add83f6fda2cd68ac9df13bfcdef470b7c62f46225b4af22b9acd
  - tests/test_object_extraction_production_wiring.py = bed6d4a28be880de69a367b958078569212ad4bf8fd9e1781bc48df196811a5f
- Confirmed blockers pre-fix: hash(seg_id) at ~2339, synthetic unconditional, deterministic-layout in production, bbox fabricate 10/10/50/50, confidence default 0.7 clamp, precedence bug already bound at ~2333/2364/2405/2445
- Evidence dir to be created: output/s08-a02-t02-c1/<ts>/

## 2026-08-20T20:35:00+07:00 / 2026-08-20T13:35:00Z — WRITER FIXES START (LANE B)
- Replaced hash(seg_id) with hashlib.sha256 stable digest (tx via digest[:4] %20 -10) — deterministic across PYTHONHASHSEED
- Removed confidence default 0.7 and clamp; now fail closed on missing/NaN/Inf/out-of-range via math.isfinite check
- Removed fabricated bbox 10/10/50/50; now validates bbox {x,y,width,height} finite w/h>0, missing/malformed → prompt=None omit
- Gated synthetic motion/contact/occlusion + fake sparse_flow behind _is_qa_synthetic = qa_mode and provider in (deterministic, deterministic-identity); production has 0 synthetic
- Production segments now use actual candidate algorithm (sam2.1-local), never deterministic-layout fallback; missing algorithm fails closed
- Added QA provenance markers: provider deterministic, qa_mode true, synthetic true, test_adapter true for segments/motions/occlusions/contacts
- Fixed broad except + precedence bug: isinstance(exc, MotionConflictError) and ("already bound" in str(exc)) with explicit parentheses; wrong-type ValueError now propagates
- Updated _verify_structural_evidence: production expects 0 motions/no deterministic-layout, QA expects >= segs, plus provenance checks

## 2026-08-20T21:00:00+07:00 / 2026-08-20T14:00:00Z — TESTS ADDED
- Added 12 new C1 tests to tests/test_object_extraction.py: test_c1_production_no_false_evidence_no_synthetic, test_c1_qa_synthetic_provenance_markers, test_c1_missing_bbox_omit_never_fabricate, test_c1_invalid_confidence_fail_closed_zero_mutation (5 params), test_c1_invalid_confidence_missing_fail_closed, test_c1_wrong_type_already_bound_not_swallowed, test_c1_typed_idempotency_already_bound_swallowed, test_c1_cross_process_deterministic_qa_byte_identical (PYTHONHASHSEED 1 vs 999)
- Imports moved to top, ruff E501 wrapped, imports sorted

## 2026-08-20T21:05:00+07:00 / 2026-08-20T14:05:00Z — VALIDATION
- ruff check app tests → All checks passed! (0) (log 13_ruff.log)
- mypy app → Success: no issues found in 91 source files (14_mypy.log)
- alembic heads → a0b1c2d3e4f5 single (15_alembic.log)
- OpenAPI → /api/v2/object-intelligence/extraction POST requestBody $ref ExtractionSubmitRequest intact (16_openapi.log)
- pytest new C1 → 12 passed (01_new_c1.log)
- pytest extraction → 58 passed (02_extraction.log)
- pytest API → 20 passed (03_api.log)
- pytest production wiring → 1 passed (04_production.log)
- pytest migration → 10 passed (05_migration.log)
- pytest domain → 30 passed (06_domain.log)
- pytest c234 → 89 passed (07_c234.log)
- pytest struct api → 50 passed (08_struct_api.log)
- pytest phone → 1 passed (09_phone.log)
- cross-process repro → byte-identical (10_cross.log)
- combined focused 79 passed x2 (11_combined1.log, 12_combined2.log)
- Evidence dir: output/s08-a02-t02-c1/20260820_205500/ (16 logs)

## 2026-08-20T21:06:00+07:00 / 2026-08-20T14:06:00Z — REPORT SUBMITTED
- REPORT.md set to SUBMITTED (never APPROVED), LOG.md append-only, no commit/push/merge, worktree codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204, MOTIONFORGE_DATABASE_URL UNSET, temp SQLite, -p no:cacheprovider

---

## 2026-08-20T22:00:00+07:00 / 2026-08-20T15:00:00Z — MANAGER INTEGRATION GATE (LANE B) — ALL PASS
- writer session 20260820_202903_5d9891 SUBMITTED; manager re-ran independently
- Manager re-run: object_extraction 58 (12 C1 mới) | obj_ext API+prod 21 | C2/C3/C1 89 | Mig 10 | Dom 30 | Struct API 50 | Phone 1
- Cross-process PYTHONHASHSEED=1 vs 999 byte-identical PASS; Combined ×2 259 passed (no flaky)
- Code review: hash→sha256, QA-gating synthetic, provenance markers, bbox omit (never fabricate), confidence
  fail-closed (no clamp/default), typed idempotency (parenthesized), broad excepts removed, atomic publication
- File ownership: Lane B only touched object_extraction.py / test_object_extraction.py (schemas/routes/api-test/
  wiring unchanged — verified hashes)
- ruff 0 | mypy 0 | alembic single | OpenAPI 9/9 + extraction POST $ref | MAIN protected
- State: MANAGER_VERIFIED_PENDING_CODEX_REVIEW
