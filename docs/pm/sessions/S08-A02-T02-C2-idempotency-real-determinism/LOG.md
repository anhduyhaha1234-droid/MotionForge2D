# S08-A02-T02-C2 — LOG (append-only, local +07:00 / UTC=local-7h)

## 2026-08-20T22:30:00+07:00 / 2026-08-20T15:30:00Z — MANAGER PREFLIGHT (LANE B / T02-C2)
- Worktree s08-integration, codex/s08-integration @ a43b20da7, status ~208, DB UNSET, alembic single
  a0b1c2d3e4f5, MAIN protected. Model route ocg/muse-spark-1.2-contributor @ muse (probe OK).
- Baseline hashes (pre-T02-C2): object_extraction.py=dc78a585..., test_object_extraction.py=9b38ce00...,
  test_object_extraction_api.py=dae39141..., test_object_extraction_production_wiring.py=bed6d4a2...
- Confirmed blockers: try/except swallow typed "already bound" around create_motion/occlusion/contact
  (~2374+); cross-process test recomputes SHA in subprocess instead of actual publication path.
- Evidence: output/s08-a02-t02-c2/20260820_223000_manager_preflight/

[next: dispatch LANE B writer Muse]

## 2026-08-20T23:16:45+07:00 / 2026-08-20T16:16:45Z — LANE B WRITER START (Muse, reasoning max, no fallback)
- Hermes session: 20260820_230743_52c334
- Model: ocg/muse-spark-1.2-contributor via muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses)
- Reasoning: max, fallback: none (no fallback; mismatch -> BLOCKED_MODEL_ROUTE; verified meta/... 401 not used)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; status ~211 dirty (intentional, never reset); MAIN protected
- DB: MOTIONFORGE_DATABASE_URL UNSET (isolated temp SQLite, -p no:cacheprovider, shallow --basetemp)
- Alembic: single head a0b1c2d3e4f5 verified via `cd worktree && alembic heads` -> a0b1c2d3e4f5 (head)
- Provider verification: muse re-label DeepSeek via 9Router/20128; meta/... -> 401 confirmed; ocg/muse-spark-1.2-contributor verified by VietAPI probe (Muse contributor high, DeepSeek max) — no model downgrade
- TASK.md read FULL (blockers 1+2, allowlist Lane B, validation gates); object_extraction.py FULL (QA ~2360-2513, 4 swallowed try/except); structural_evidence.py READ-ONLY verified (create_* returns (record,created), conflict "already bound"); tests read FULL + C1 REPORT/TASK
- Plan: Step1 TARGET done; Step2 SOLVE: fix C2 — remove 4 swallowed try/except, provenance->actual provider, delete swallowed test, replace fake cross-process with real 2-seed publication, add conflict matrix + both QA providers; evidence dir output/s08-a02-t02-c2/<ts>/

## 2026-08-20T23:38:00+07:00 / 2026-08-20T16:38:00Z — LANE B WRITER FINAL (Muse, reasoning max, no fallback) — SOLVE→RUN→FIX→GATE complete
- Fix Blocker 1: REMOVED all 4 try/except around repo.create_motion (camera/object) / create_occlusion / create_contact; now direct calls `repo.create_motion(...)` etc. with no wrapping; repository returns (record, created) and handles equivalent replay via created=False; EVERY conflict exception (MotionConflictError/OcclusionConflictError/ContactConflictError) now propagates and rolls back publication atomically (outer session not committed, files not moved on failure); DELETED substring check `and ("already bound" in str(exc))` — verified `grep -c "already bound" app/services/object_extraction.py` == 0; provenance now uses `_actual_provider = str(ctx.input_manifest.get("provider") or "")` instead of hardcoded "deterministic" (4 provenances fixed); confirmed `grep -c "repo.create_motion" ==2, "repo.create_occlusion"==1, "repo.create_contact"==1`
- Fix Blocker 2: DELETED fake test `test_c1_typed_idempotency_already_bound_swallowed` and fake `test_c1_cross_process_deterministic_qa_byte_identical` (recomputed SHA in subprocess); REPLACED with REAL cross-process test `test_c1_cross_process_deterministic_qa_byte_identical(tmp_path)` that runs ACTUAL handler path: each subprocess creates fresh isolated SQLite + managed_root, deterministic uuid sequence, fixed project/video/scene ids (111.../222.../333.../444...), submits via `submit_discover_objects` with PROVIDER_DETERMINISTIC + env MOTIONFORGE_EXTRACTION_QA_MODE=1, runs `svc.worker.run_once()` (real DurableWorker + StructuralEvidenceRepository), queries DB AFTER publication, normalizes only job_id in provenance, compares prompt/segmentation JSON, mask SHA256, camera/object transforms, motion refs, occlusion/contact kind+ranges, synthetic provenance, ordering; FAILS if implementation reverts to hash(seg_id) (verified by checking motion ref determinism across PYTHONHASHSEED 1 vs 999)
- Added mandatory REAL tests (not monkeypatch-only, but real DB + repo):
  - `test_c2_idempotent_replay_byte_identical`: publish QA, replay byte-identical via `discover_objects_handler` → counts unchanged, completed, manifest present
  - `test_c2_conflict_motion_transform_raises_and_rolls_back`: same idempotency key, mutated transform → MotionConflictError, rollback, no mutation
  - `test_c2_conflict_motion_ref_raises_and_rolls_back`: mutated point_track_flow_ref → MotionConflictError
  - `test_c2_conflict_occlusion_endpoint_raises_and_rolls_back`: swapped occluder/occludee → OcclusionConflictError
  - `test_c2_conflict_occlusion_range_raises_and_rolls_back`: mutated start_frame/end_frame → OcclusionConflictError
  - `test_c2_conflict_contact_kind_raises_and_rolls_back`: mutated contact_kind → ContactConflictError
  - `test_c2_conflict_contact_range_raises_and_rolls_back`: mutated range → ContactConflictError
  - `test_c2_exception_text_independence_propagates_regardless_of_message`: correct type with custom text "no magic substring" still propagates (proves no substring classification)
  - `test_c2_qa_provenance_uses_actual_provider_deterministic` + `test_c2_qa_provenance_uses_actual_provider_deterministic_identity`: both providers verified, provenance provider == actual, synthetic+qa_mode true
  - `test_c2_no_substring_classification_in_service`: asserts "already bound" not in service file and exactly 2/1/1 direct create calls
- Additional truthfulness: QA provenance uses actual provider for both deterministic and deterministic-identity; production non-QA still zero synthetic (verified via existing tests: test_c1_production_no_false_evidence, missing bbox, invalid confidence etc. still pass)
- Validation (separate logs in NEW evidence dir output/s08-a02-t02-c2/20260820_233534/):
  - C2 tests: 11 passed (c2_tests.log)
  - Cross-process real: PASSED with PYTHONHASHSEED 1 vs 999 (cross_process.log) — both produced identical mask_shas 2a83.../8c8e..., motions, occlusions, contacts after normalization
  - Full extraction suite: 68 passed (object_extraction_suite.log)
  - API: 20 passed (api.log)
  - Production wiring: 1 passed (production_wiring.log)
  - Structural regression (read-only): 91 passed (structural_regression.log) — migration/domain/API/phone
  - Combined focused (extraction+structural domain) ≥2 runs: 98 passed each (combined1.log, combined2.log)
  - Gates: ruff check app tests → All checks passed! (ruff.log); mypy app → Success: no issues found in 91 source files (mypy.log); alembic heads → a0b1c2d3e4f5 (single head) (alembic_heads.log); OpenAPI → typed requestBody intact, ExtractionSubmitRequest present (openapi.log)
- Worktree guard: FORBIDDEN files untouched (app/persistence/*, migrations, frontend, etc. — verified git diff -- app/persistence/structural_evidence.py empty); allowlist only: object_extraction.py, test_object_extraction.py, LOG/REPORT, output
- No new migration, no commit/push/merge, no MAIN, no data/motionforge.db; MOTIONFORGE_DATABASE_URL UNSET; -p no:cacheprovider; shallow --basetemp used
- Exit cleanly with all evidence; status SUBMITTED (never APPROVED)

---

## 2026-08-21T00:40:00+07:00 / 2026-08-21T17:40:00Z — MANAGER INTEGRATION GATE (LANE B) — ALL PASS
- writer session 20260820_230743_52c334 SUBMITTED; manager re-ran independently
- object_extraction 68 (11 C2 mới), obj_ext API+prod 21, C2 conflict matrix 11, cross-process 1
- Mig 10 Dom 30 Struct API 50 Phone 1; Combined 277 ×2; ruff 0; mypy 0; alembic single; OpenAPI 9/9 + $ref
- State: MANAGER_VERIFIED_PENDING_CODEX_REVIEW
