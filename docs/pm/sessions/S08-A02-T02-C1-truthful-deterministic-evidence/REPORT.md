# S08-A02-T02-C1 — Truthful Evidence + Determinism: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** 20260820_202903_5d9891
**Model:** ocg/muse-spark-1.2-contributor via muse (9Router), reasoning max, no fallback
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration (codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)

## Model / provenance
- Session id: 20260820_202903_5d9891
- Displayed model name: ocg/muse-spark-1.2-contributor
- Actual model ID: ocg/muse-spark-1.2-contributor
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses)
- Reasoning: max (agent.reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict; agent.reasoning_effort=max)
- Fallback status: none (no fallback; mismatch would be BLOCKED_MODEL_ROUTE)
- Probe: 9Router 127.0.0.1:20128 available; model verified; meta/... returns 401 do NOT use

## Hard worktree guard
- pwd/git/branch/HEAD/status: C:/Users/Admin/MotionForge2D-worktrees/s08-integration / codex/s08-integration / a43b20da742996bafcb2f9d1ac57b10d3f1a5204 / 208 (intentional dirty — never reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET
- Migration head: a0b1c2d3e4f5 single (alembic heads)
- MAIN protected C:/Users/Admin/MotionForge2D never modified

## Corrections (per requirement: code + test that fails on pre-fix)
| # | Closure | Status |
|---|---|---|
| 1 stable digest instead of hash() | Replaced hash(seg_id) %20 at ~2339 with hashlib.sha256(seg_id.encode("utf-8")).digest()[:4] stable digest; old hash randomized by PYTHONHASHSEED, new is deterministic byte-identical. Test test_c1_cross_process_deterministic_qa_byte_identical fails on old (different tx) passes on new. | PASS |
| 2 deterministic across PYTHONHASHSEED | Two subprocesses PYTHONHASHSEED=1 vs 999 run deterministic QA provider + stable tx, compare normalized prompt/seg JSON, mask sha256, tx — byte-identical. Pre-fix hash differs. | PASS |
| 3 synthetic only in QA+QA-mode | Gated create_motion/create_occlusion/create_contact + fake sparse-flow refs behind _is_qa_synthetic = qa_mode and provider in (deterministic, deterministic-identity). Production skips. Old code created unconditionally. Test test_c1_production_no_false_evidence_no_synthetic fails on old (had motions), passes on new (0). | PASS |
| 4 production truthful (no inferred/fake edges/flow) | Production: no synthetic motion/contact/occlusion, no fake sparse_flow ref, no fake observation when no estimator. QA still creates. Verification _verify_structural_evidence now enforces production has 0 motions, QA has >= segs. | PASS |
| 5 QA provenance markers | QA synthetic records now carry provenance={provider:"deterministic", qa_mode:true, synthetic:true, test_adapter:true}. Production provenance is truthful without synthetic. Test test_c1_qa_synthetic_provenance_markers checks. | PASS |
| 6 production uses actual provider algorithm | Segments now use _candidate_algorithm from occurrence actual algorithm (sam2.1-local for production), never fallback to deterministic-layout. Old fallback or "deterministic-layout" removed; missing algorithm fails closed. Test test_c1_production_no_false_evidence_no_synthetic asserts algorithm == sam2.1-local and != deterministic-layout. | PASS |
| 7 missing bbox fail-closed/omit (never fabricate) | Removed fabricated {"x":10,"y":10,"width":50,"height":50} fallback. Now validates bbox shape {x,y,width,height} finite, w/h>0; missing/malformed → prompt=None, segmentation=None (omit), never fabricate. Test test_c1_missing_bbox_omit_never_fabricate fails on old (had 10/10/50/50), passes on new (omit or fail closed, never fabricate). | PASS |
| 8 NaN/Inf/range confidence fail-closed | Removed cand.get("confidence",0.7) default and if not 0<=conf<=1: conf=0.7 clamp. Now _raw_conf = cand.get("confidence"); if None or not math.isfinite or not 0<=conf<=1 → raise ExtractionError CODE_PUBLICATION_FAILED with zero partial mutation (atomic rollback). Tests test_c1_invalid_confidence_* fail on old (clamped), pass on new (failed, 0 segments). | PASS |
| 9 remove broad exceptions | Removed except Exception broad catches that swallowed real errors; now only typed MotionConflictError/OcclusionConflictError/ContactConflictError with explicit check, other errors propagate. | PASS |
| 10 typed idempotency only; others propagate | if isinstance(exc, MotionConflictError) and ("already bound" in str(exc)) with correct parentheses; wrong-type exception (ValueError with "already bound") now propagates and fails job. Test test_c1_wrong_type_already_bound_not_swallowed fails on old (swallowed), passes on new (failed). Correct typed replay still swallowed (test_c1_typed_idempotency...). | PASS |
| 11 explicit parentheses | Fixed operator-precedence bug isinstance(...) and "already bound" in str(exc) or "already bound" in str(exc) → isinstance(...) and ("already bound" in str(exc)) with explicit parentheses. | PASS |
| 12 atomic+idempotent publication | Publication stays in ONE transaction; any failure (confidence, bbox, wrong-type) rolls back roles/occurrences/segments/motions/edges (zero partial). Replay via discover_objects_handler with same ctx returns same manifest, counts unchanged. Verified via test_c1_invalid_confidence_* zero segments and test_c1_typed_idempotency replay. | PASS |

## Files changed (allowlist only, hashes)
| File | Before (baseline) | After | Change |
|---|---|---|---|
| app/services/object_extraction.py | 90b542552b54b4c791b0b82c897d64a34975b9b499c7ae94eb11208c382bb1dc | dc78a585dbf2cedea01f7e3b2b5dff4c9126a34bc277a29592aa8d4741813f8c | Truthful + deterministic fixes (hash→sha256, confidence fail-closed, bbox omit, QA gating, typed exceptions, provenance) |
| tests/test_object_extraction.py | fa0ef0d42fa6d6ef223acceec60a581729e8b9da776318c552b6c30b16e7171c | 9b38ce00cf8f92622cee0971eec933cdd15c4b8dc63f61e693d990805b939c7e | Added 12 new C1 tests (cross-process, production no-false, QA provenance, missing bbox, invalid confidence x6, wrong-type, typed idempotency, cross-process) |
| app/schemas/object_extraction.py | 3ac5137153a3d58419c0b36b288761f0907e419f2cadab00b12576c422abeba6 | 3ac5137153a3d58419c0b36b288761f0907e419f2cadab00b12576c422abeba6 | Unchanged (Lane B allowlist but no change needed) |
| app/api/routes/object_extraction.py | c37b7968d67cda8988519e01528b4e81ad1ca6fd6b01121f4e1db6a0611800a2 | c37b7968d67cda8988519e01528b4e81ad1ca6fd6b01121f4e1db6a0611800a2 | Unchanged |
| tests/test_object_extraction_api.py | dae39141e84add83f6fda2cd68ac9df13bfcdef470b7c62f46225b4af22b9acd | dae39141e84add83f6fda2cd68ac9df13bfcdef470b7c62f46225b4af22b9acd | Unchanged |
| tests/test_object_extraction_production_wiring.py | bed6d4a28be880de69a367b958078569212ad4bf8fd9e1781bc48df196811a5f | bed6d4a28be880de69a367b958078569212ad4bf8fd9e1781bc48df196811a5f | Unchanged (existing pristine QA wiring still passes) |
| docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/LOG.md | — | appended | Append-only with real timestamps |
| docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/REPORT.md | — | this file | SUBMITTED |
| output/s08-a02-t02-c1/20260820_205500/ | — | 16 logs | Evidence dir |

FORBIDDEN files untouched: app/persistence/structural_evidence.py, app/persistence/object_intelligence.py, app/persistence/models.py, tests/test_s08_a02_c3_corrections.py (no functional change), migrations, frontend, S07/S09, MAIN, data/motionforge.db

## Validation (raw logs in output/s08-a02-t02-c1/20260820_205500/)
- 01_new_c1.log: pytest tests/test_object_extraction.py -k test_c1_ -p no:cacheprovider -v → 12 passed (cross-process, production no-false, QA provenance, missing bbox, invalid confidence 5+1, wrong-type, typed idempotency, cross-process)
- 02_extraction.log: pytest tests/test_object_extraction.py -p no:cacheprovider -q → 58 passed (46 existing +12 new, 111 warnings)
- 03_api.log: pytest tests/test_object_extraction_api.py -p no:cacheprovider -q → 20 passed
- 04_production.log: pytest tests/test_object_extraction_production_wiring.py -p no:cacheprovider -q → 1 passed (pristine QA 4/8/2/2, FK ok, staging drained)
- 05_migration.log: pytest tests/test_s08_a02_structural_evidence_migration.py -p no:cacheprovider -q → 10 passed
- 06_domain.log: pytest tests/test_s08_a02_structural_evidence_domain.py -p no:cacheprovider -q → 30 passed
- 07_c234.log: pytest tests/test_s08_a02_c2_integrity.py tests/test_s08_a02_c3_corrections.py tests/test_s08_a02_r1_c1_semantic_safety.py -p no:cacheprovider -q → 89 passed
- 08_struct_api.log: pytest tests/test_s08_a02_structural_evidence_api.py -p no:cacheprovider -q → 50 passed
- 09_phone.log: pytest tests/test_s08_a02_phone_interaction_scenario.py -p no:cacheprovider -q → 1 passed
- 10_cross.log: cross-process PYTHONHASHSEED=1 vs 999 deterministic QA evidence byte-identical (via test_c1_cross_process...), plus direct hashlib tx check → CROSS_HASHSEED_EQUAL True
- 11_combined1.log: pytest tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_extraction_production_wiring.py -p no:cacheprovider -q → 79 passed (1st)
- 12_combined2.log: same combined → 79 passed (2nd, >=2x)
- 13_ruff.log: python -m ruff check app tests → All checks passed! (0)
- 14_mypy.log: python -m mypy app → Success: no issues found in 91 source files
- 15_alembic.log: python -m alembic heads → a0b1c2d3e4f5 (head) single
- 16_openapi.log: app.openapi() → /api/v2/object-intelligence/extraction POST requestBody $ref ExtractionSubmitRequest intact, OPENAPI OK
- Shallow unique --basetemp under C:/Users/Admin/AppData/Local/Temp/, MOTIONFORGE_DATABASE_URL UNSET, temp SQLite, -p no:cacheprovider, FK+CHECK enforced
- Combined extraction+structural at least twice: 79 passed x2, plus individual suites all green

## Independent repros / instrumentation
- Cross-process determinism: PYTHONHASHSEED=1 vs 999 subprocesses produce identical JSON (ids, prompt/seg, mask sha256, tx via sha256 digest) — old hash() would differ, new sha256 identical.
- Production no-QA: segments 4 saved, motions 0, occlusions 0, contacts 0, algorithm sam2.1-local, no deterministic-layout, no fake sparse_flow.
- QA deterministic: segments 4, motions 8, occlusions 2, contacts 2, each provenance has provider deterministic, qa_mode true, synthetic true, test_adapter true.
- Missing bbox: job either completed with prompt None (omit) or failed closed (0 segments), never 10/10/50/50 fabricated.
- Invalid confidence: NaN, +Inf, -Inf, 1.5, -0.1, missing → each fails closed, 0 segments, 0 motions, counts_before == counts_after (atomic rollback).
- Wrong-type already bound: ValueError("already bound") propagates → job failed, 0 segments (not swallowed); correct typed MotionConflictError with "already bound" is swallowed on replay (idempotent).
- Existing replay/idempotency/API tests still pass (58, 20, 1).

## Warnings / limitations
- No new migration: wiring uses existing tables, alembic stays single a0b1c2d3e4f5.
- Production Sam2 provider not exercised in CI (requires GPU/checkpoint); deterministic QA adapter covers full graph without GPU per TASK 5.3; production truthful path tested via fake prod provider (sam2.1-local) with qa_mode False.
- Worktree intentionally dirty (~208) — never reset/clean; only allowlisted files touched.
- No commit/push/merge per stop conditions; final state SUBMITTED pending manager/Codex review.
- Output evidence dir is NEW (output/s08-a02-t02-c1/20260820_205500/), not reused from prior T02.
