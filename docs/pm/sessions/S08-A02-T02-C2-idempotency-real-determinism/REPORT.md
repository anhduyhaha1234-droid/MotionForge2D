# S08-A02-T02-C2 — Idempotency Conflict Safety + Real Cross-Process Determinism: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** 20260820_230743_52c334
**Model:** ocg/muse-spark-1.2-contributor via muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning max, fallback none
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration (codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)

## Model / provenance
- Hermes session: 20260820_230743_52c334
- Model: ocg/muse-spark-1.2-contributor via muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses)
- Reasoning: max, fallback: none (no fallback; mismatch -> BLOCKED_MODEL_ROUTE)
- Verified: 9Router/20128, base_url http://127.0.0.1:20128/v1, api_mode codex_responses; ocg/muse-spark-1.2-contributor OK, meta/... 401 refused
- Logged: 2026-08-20T23:16:45+07:00 (local +07:00) / 2026-08-20T16:16:45Z (UTC, local-7h) — writer start, before any code change

## Hard worktree guard
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- Status: ~211 dirty (intentional, never reset/clean/stash/restore/checkout/commit/push/merge); MAIN protected
- DB: MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite; -p no:cacheprovider; shallow --basetemp
- Alembic: single head a0b1c2d3e4f5 — verified cd worktree && alembic heads -> a0b1c2d3e4f5 (head)
- Allowlist: app/services/object_extraction.py, tests/test_object_extraction.py, tests/test_object_extraction_api.py, tests/test_object_extraction_production_wiring.py, docs/pm/sessions/S08-A02-T02-C2-*, output/s08-a02-t02-c2/ (Lane B only, no persistence/schema/migrations)

## Corrections (per requirement: code + test that fails on pre-fix)
| # | Closure | Status |
|---|---|---|
| 1 remove all try/except around motion/occlusion/contact create | DONE — 4 blocks removed (camera/object motion, occlusion, contact) now direct repo.create_* calls, no wrapping; verified grep -c "already bound" ==0 | PASS |
| 2 use (record, created); replay via created=False | DONE — repository returns (record, created); equivalent replay handled purely by created=False (no exception); second publication via handler returns same manifest, counts unchanged | PASS |
| 3 conflict exceptions propagate + atomic rollback | DONE — MotionConflictError/OcclusionConflictError/ContactConflictError now propagate; outer session.commit() not reached, files not moved, worker marks job failed; verified 6 conflict tests each raise, rollback, no mutation | PASS |
| 4 no substring message classification | DONE — removed isinstance and "already bound" in str(exc); replaced with no classification; test_c2_no_substring_classification_in_service and test_c2_exception_text_independence prove it | PASS |
| 5 delete swallowed-conflict test | DONE — deleted test_c1_typed_idempotency_already_bound_swallowed (was asserting swallow) | PASS |
| 6 real cross-process actual publication path (2 seeds) | DONE — replaced fake SHA recomputation with real handler/worker, fresh isolated SQLite, deterministic QA provider + explicit QA mode, 2 processes PYTHONHASHSEED 1 vs 999, fixed project/video/scene ids, deterministic uuid sequence, query DB after publication, normalize only job_id, compare prompt/seg JSON, mask SHA, transforms, refs, kind+ranges, provenance, ordering; FAILS if hash(seg_id) | PASS |
| 7 QA provenance uses actual provider (deterministic + deterministic-identity) | DONE — 4 provenances now use _actual_provider = str(ctx.input_manifest.get("provider") or ""); added tests for BOTH providers, each verifies provenance provider == actual, synthetic+qa_mode true | PASS |
| 8 production non-QA truthful (no synthetic/flow/algorithm/confidence/bbox) | DONE — production path still zero synthetic motion/contact/occlusion, no fake sparse-flow, actual algorithm, invalid confidence fail closed, no fabricated bbox (68 existing tests still pass) | PASS |

## Files changed (allowlist only, hashes)
- app/services/object_extraction.py — 78b1fd74ad210a9ed7d4ded8b02274374047da0735b5b2a4ca99a8095e702bf1 (short 78b1fd74ad21) — Blocker 1: removed 4 swallowed try/except, provenance -> _actual_provider, no substring
- tests/test_object_extraction.py — fabad7b4b0f04312a8ecccf4268cb11252fc7e110f384306276125ffabc377aa (short fabad7b4b0f0) — deleted swallowed test, replaced fake cross-process with real 2-seed publication, added 11 C2 tests (7+ per above)
- tests/test_object_extraction_api.py — unchanged (allowlist, no edits)
- tests/test_object_extraction_production_wiring.py — unchanged (allowlist, no edits)
- docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/LOG.md — appended writer start + final entries (local +07:00 / UTC)
- docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/REPORT.md — filled to SUBMITTED (this file)
- output/s08-a02-t02-c2/20260820_233534/ — NEW evidence dir with separate logs (see Validation)
- FORBIDDEN untouched: app/persistence/structural_evidence.py (read-only), app/persistence/object_intelligence.py, app/persistence/models.py, app/schemas/*, tests/test_s08_a02_c3_corrections.py, migrations/*, frontend/*, S07/*, S09/*, MAIN, data/motionforge.db — verified git diff -- app/persistence/structural_evidence.py empty

## Validation (raw logs in output/s08-a02-t02-c2/20260820_233534/)
- c2_tests.log — 11 passed (test_c2_*): idempotent replay + 6 conflict matrix + text independence + both QA providers + no-substring
- cross_process.log — PASSED (test_c1_cross_process_deterministic_qa_byte_identical with PYTHONHASHSEED 1 vs 999; identical mask_shas 2a83.../8c8e..., motions, occlusions, contacts)
- object_extraction_suite.log — 68 passed (full suite, includes production truthful + deterministic QA)
- api.log — 20 passed (test_object_extraction_api.py)
- production_wiring.log — 1 passed (pristine production wiring)
- structural_regression.log — 91 passed (s08_a02_migration/domain/api/phone, read-only, no edits)
- combined1.log + combined2.log — 98 passed each (extraction + structural domain, >=2 runs as required)
- ruff.log — All checks passed! (python -m ruff check app tests -> 0)
- mypy.log — Success: no issues found in 91 source files (python -m mypy app)
- alembic_heads.log — a0b1c2d3e4f5 (head) (single head, no new migration)
- openapi.log — typed requestBody intact (ExtractionSubmitRequest #/components/schemas/ExtractionSubmitRequest)
- Also: output/s08-a02-t02-c2/20260820_232954/ (earlier partial) + 20260820_223000_manager_preflight/

## Independent repros / instrumentation
- Conflicting-idempotency payload repro (real DB, not monkeypatch-only):
  - Published QA evidence (deterministic, qa_mode=1) -> 4 segments, 8 motions, 2 occlusions, 2 contacts, completed
  - Same idempotency key, mutated motion transform {"tx_mutated":999} -> MotionConflictError, rollback, existing row unchanged (verified via get_motion)
  - Mutated motion ref {"tracks":["mutated-track"]} -> MotionConflictError
  - Swapped occlusion endpoints (occluder<->occludee) -> OcclusionConflictError
  - Mutated occlusion range start_frame+1 -> OcclusionConflictError
  - Mutated contact kind hand_phone->character_phone -> ContactConflictError
  - Mutated contact range start_frame+1 -> ContactConflictError
  - Each verified counts unchanged (_structural_counts before==after) and existing row not mutated
- Real cross-process repro (TWO PYTHONHASHSEED):
  - Seed 1 and 999 each: fresh isolated SQLite, deterministic uuid counter, fixed project 111..., video 222..., scenes 333.../444..., provider deterministic, qa_mode 1, real worker
  - After publication, queried DB: segments ordered z_order/start_frame, motions transform_type/start_frame, occlusions/contacts start_frame
  - Compared: prompt_json, segmentation_json, mask artifact SHA256 (2a83... etc.), camera_relative matrix, object_relative tx (sha256 digest), point_track_flow_ref tracks, occlusion/contact kind+ranges, synthetic provenance {job_id:"<JOB_ID>", provider:"deterministic", qa_mode:true, synthetic:true}, ordering
  - Result: byte-identical JSON after normalizing only job_id (allowed to differ); FAILS if implementation reverts to hash(seg_id) (would diverge across seeds)
- Exception text independence: patched create_motion to raise MotionConflictError("custom text — no magic substring") -> still propagated, job failed, zero mutation (proves no substring matching)
- QA provenance both providers: deterministic -> provenance provider == "deterministic"; deterministic-identity -> "deterministic-identity" (both with synthetic true)

## Warnings / limitations
- No new migration created; alembic single head a0b1c2d3e4f5 preserved (verified alembic heads from worktree root)
- No commit/push/merge, no MAIN, no data/motionforge.db (verified MOTIONFORGE_DATABASE_URL UNSET)
- Worktree intentionally dirty (~211) — never reset/clean/stash/restore/checkout/commit/push/merge per guard; only allowlist files were edited, all other dirty is pre-existing
- Output evidence is in NEW dir output/s08-a02-t02-c2/20260820_233534/ (plus earlier 20260820_232954 and manager preflight); all logs are separate and tee'd
- Cross-process test uses deterministic uuid counter and fixed project/video/scene ids to ensure byte-identical evidence despite random job_id; this is the minimal normalization the contract allows (job-specific identifiers)
- Production non-QA truthfulness still enforced: existing tests for no synthetic, no fake sparse-flow, actual algorithm, fail-closed confidence, no bbox fabrication all pass (68 suite)
- If persistence change were required for blocking, would have STOPPED with BLOCKED_SCOPE (not needed — all fixes were in allowed service/tests)
