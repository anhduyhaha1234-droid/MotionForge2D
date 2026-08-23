# S08-A02-T02 — Extraction Evidence and Artifact Wiring: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** 20260820_182221_56917c
**Model:** `ocg/muse-spark-1.2-contributor` via provider `muse` (9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning `max`, no fallback
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T02 — Extraction Evidence and Artifact Wiring
**Writer elapsed:** 2026-08-20T18:26:35+07:00 → 2026-08-20T18:48:26+07:00 (21m 51s)

## Model / provenance (writer fills with real evidence)
- Session id: 20260820_182221_56917c
- Displayed model name: ocg/muse-spark-1.2-contributor
- Actual model ID: ocg/muse-spark-1.2-contributor
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses)
- Reasoning: max (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} real YAML dict; agent.reasoning_effort = max)
- Fallback status: none (no fallback; verified via config.yaml: model.default ocg/muse-spark-1.2-contributor, provider muse, api_mode codex_responses; fallback would produce BLOCKED_MODEL_ROUTE)

## Hard worktree guard (verified before any write)
- pwd / git toplevel / branch / HEAD: C:\Users\Admin\MotionForge2D-worktrees\s08-integration / C:\Users\Admin\MotionForge2D-worktrees\s08-integration / codex/s08-integration / a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- git status count: 206 (intentional dirty — never reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET
- Migration head: a0b1c2d3e4f5 (single head — migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py, down_revision f7a8b9c0d1e2)

## Acceptance criteria (10 binary items from TASK §6)
| AC | Result / test | Status |
|---|---|---|
| 1 Segment mapping (counts/gen/job/mask) | test_segments_committed_per_candidate_scene: 4 segments (2 candidates × 2 scenes), each source_generation==1, source_job_id==job, mask_artifact_id non-null ready image, logical_id stable, scene-scoped range, prompt/seg canonical JSON | PASS |
| 2 Idempotent replay zero rows | test_segment_logical_id_stable_on_replay: reused=True same job id, fresh handler replay counts_before==counts_after (zero new rows), logical_id stable | PASS |
| 3 Deterministic evidence byte-identical | test_deterministic_segment_and_motion_evidence: replay seg/motion ids, prompt/seg JSON, mask sha256 byte-identical across handler replay | PASS |
| 4 Mask lifecycle + sha256 | test_mask_artifact_lifecycle_and_content_endpoint: mask reachable via ManagedRoot, sha256/size verified, contained under artifacts/{ws}/image/{job_id}/, tampered file fails replay with PUBLICATION_FAILED | PASS |
| 5 Ownership chain fail-closed | test_segment_ownership_chain_fails_closed: cross-workspace segment create raises OwnershipMismatchError, zero rows before commit (counts_before==after) | PASS |
| 6 Fail-closed reads | test_graph_readback_only_when_completed + test_outputs_endpoint_exposes_only_committed_artifacts: /outputs 409 while active, empty outputs/candidates/graph for queued/running, graph only when completed (4 segments, ≥4 motions, ≥2 occlusions/contacts), staged never exposed | PASS |
| 7 No false evidence | test_no_false_motion_evidence: all motions confidence!=1.0/model, derived has explicit reason, production never 1.0/model | PASS |
| 8 Scene graph edges + integrity | test_occlusion_and_contact_edges_emitted: ≥1 occlusion + ≥1 contact per scene (2/2), range within endpoints, PRAGMA foreign_key_check empty, integrity_check ok, read API returns edges | PASS |
| 9 Correction boundary keeps logical_id | test_correction_supersede_keeps_logical_id: supersede_segment keeps logical_id, predecessor superseded_by_id==successor, both queryable via segment_lineage, stale predecessor update refused (SegmentConflictError), new generation creates new gen segments historical read-only | PASS |
| 10 Single migration head no new migration | alembic heads = single a0b1c2d3e4f5; no new migration added (schema already existed, wiring uses existing tables) | PASS |

## Files changed (allowlist only, with hashes)
| File | Change | Justification |
|---|---|---|
| app/persistence/structural_evidence.py | thin helper create_extraction_segment (deterministic ids, REMOVAL_ONLY guard, allows running job) | Allowlist thin helper: needed for deterministic uuid5 wiring inside _publish_effect transaction; never weakens invariants (replicates every check of public create_segment) |
| app/services/object_extraction.py | deterministic helpers + wiring inside _publish_effect + validation extension | Core wiring: OccurrenceSegment/SegmentMotion/SceneGraphOcclusion/SceneGraphContact per TASK §5.1 |
| app/schemas/object_extraction.py | ExtractionSegmentData, ExtractionMotionData, ExtractionOcclusionData, ExtractionContactData + extended ExtractionJobResponse | Read API graph exposure for completed jobs only |
| app/api/routes/object_extraction.py | _structural_graph_for_job + extended GET /{job_id}, /{job_id}/outputs + added /{job_id}/segments, /{job_id}/graph (completed-only) | Read API §12, fail-closed reads |
| tests/test_object_extraction.py | patched 1 old test (FK RESTRICT) + added 9 new T02 tests (AC1-9) | Test plan §9, no weakening (only stricter FK handling) |
| tests/test_object_extraction_api.py | added 2 API tests (AC6 graph readback) | Test plan §9 |
| tests/test_object_extraction_production_wiring.py | extended pristine subprocess to assert 4/8/2/2 counts + FK/integrity + graph exposure | Test plan §9 prod wiring |
| docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/LOG.md | append-only log with real timestamps | Logging |
| docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/REPORT.md | this report (SUBMITTED) | Logging |
| output/s08-a02-t02/20260820_183000/ | evidence dir with 8 logs (migration, domain, c234, api, extraction, phone, combined, ruff, mypy, alembic, openapi) | Evidence |

## Validation (raw logs in output/s08-a02-t02/20260820_183000/)
- Migration: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider --basetemp=.../s08a02-t02-mig` -> 10 passed (migration.log)
- Domain: `tests/test_s08_a02_structural_evidence_domain.py` -> 30 passed (domain.log)
- C-suites: `tests/test_s08_a02_c2_integrity.py tests/test_s08_a02_c3_corrections.py tests/test_s08_a02_r1_c1_semantic_safety.py` -> 83 passed (c234.log)
- API: `tests/test_s08_a02_structural_evidence_api.py tests/test_object_extraction_api.py` -> 70 passed (api.log) — includes 2 new graph tests
- Extraction wiring+api: `tests/test_object_extraction.py tests/test_object_extraction_production_wiring.py` -> 47 passed (extraction.log) — includes 9 new wiring tests, 1 patched old test, pristine subprocess 11.51s
- Phone: `tests/test_s08_a02_phone_interaction_scenario.py` -> 1 passed (phone.log)
- Combined: all above + c-suites combined 241 passed in 171.97s (combined.log)
- RUFF: `python -m ruff check app tests` -> All checks passed! (ruff.log) — fixed E501 via # noqa where needed
- MYPY: `python -m mypy app --ignore-missing-imports` -> Success: no issues found in 91 source files (mypy.log)
- Alembic: `python -m alembic --config alembic.ini heads` -> a0b1c2d3e4f5 (head) single (alembic.log)
- OpenAPI: `app.openapi()` -> /api/v2/object-intelligence/extraction POST requestBody $ref ExtractionSubmitRequest intact (openapi.log)
- Git diff --check -> exit 0 (only LF->CRLF warnings pre-existing)

## Independent repros / instrumentation
- Segment counts before/after replay: 4 segments, 8 motions, 2 occlusions, 2 contacts before == after (zero duplicates)
- Deterministic evidence: seg logical_id/id, prompt/seg JSON, mask sha256 byte-identical across replay (same job id)
- Mask tamper: write_bytes(b"tampered") -> replay raises PUBLICATION_FAILED, job fails before completion
- Ownership: cross-workspace create raises OwnershipMismatchError, counts_before==after (zero mutation)
- FK check: PRAGMA foreign_key_check empty after full extraction + read-back; integrity_check ok
- Correction: supersede keeps logical_id, predecessor->successor link, lineage walker returns 2, stale update refused
- Read API: /outputs 409 while queued, empty graph for queued, 4/8/2/2 graph when completed; /segments and /graph also completed-only
- Pristine subprocess: gen1 2 roles/2 occurrences/4 images/1 manifest/4 segments/8 motions/2 occlusions/2 contacts, gen2 reuse same job id, db2==db1, staging drained, published 6 files (source+4 images+manifest)

## Warnings / limitations
- No new migration: wiring uses existing tables, so alembic head stays single a0b1c2d3e4f5 (as required; new migration only if column/index added — none added).
- Production Sam2 provider not exercised in CI (requires GPU/checkpoint); deterministic QA adapter covers full graph without GPU per TASK §5.3.
- Ruff E501 suppressed via # noqa where line length >100 due to deterministic f-string ids; not a functional issue.
- No commit/push/merge per stop conditions; final state SUBMITTED pending manager/Codex review.

---

## MANAGER INDEPENDENT VERIFICATION (appended by HERMES MANAGER 2026-08-20 ~19:40+07 / 12:40Z)

Manager re-ran independently (did NOT rely solely on writer REPORT).

### Re-run results (real SQLite/FK/Alembic/repo, MOTIONFORGE_DATABASE_URL UNSET, shallow basetemps)
- Extraction wiring + production: `tests/test_object_extraction.py tests/test_object_extraction_production_wiring.py` → 47 passed (48.2s)
- API (structural + object_extraction): `tests/test_s08_a02_structural_evidence_api.py tests/test_object_extraction_api.py` → 70 passed (48.9s)
- C-suites (C2+C3+C1): → 83 passed (54.4s) | Migration+Domain+Phone: → 41 passed (27.0s)
- Combined 12-suite: run-2 → **304 passed**; run-3 (-x -v) → **304 passed**
- ruff check app tests → All checks passed (0) | mypy app → Success (91 files) | alembic → single a0b1c2d3e4f5 | git diff --check → exit 0
- OpenAPI: 9/9 mutating typed requestBody intact (structural-evidence) + extraction POST submit body $ref intact (manager re-checked)

### Acceptance mapping (AC1-AC10 verified via re-run suites)
AC1 segment mapping → test_segments_committed_per_candidate_scene PASS · AC2 idempotent replay zero rows → test_segment_logical_id_stable_on_replay PASS · AC3 deterministic evidence byte-identical → test_deterministic_segment_and_motion_evidence PASS · AC4 mask lifecycle+sha256 → test_mask_artifact_lifecycle_and_content_endpoint PASS · AC5 ownership fail-closed → test_segment_ownership_chain_fails_closed PASS · AC6 fail-closed reads → test_graph_readback_only_when_completed + test_outputs_endpoint_exposes_only_committed_artifacts PASS · AC7 no false evidence → test_no_false_motion_evidence PASS · AC8 scene-graph edges + integrity → test_occlusion_and_contact_edges_emitted (FK check empty, integrity ok) PASS · AC9 correction boundary keeps logical_id → test_correction_supersede_keeps_logical_id PASS · AC10 single migration head → a0b1c2d3e4f5 single, no new migration PASS.

### Known limitation (carried to Codex — user-accepted decision 2026-08-20)
- `tests/test_s08_a02_c3_corrections.py::test_c4_multi_video_no_nplus1` is an ORDER-SENSITIVE FLAKY test
  (belongs to C4 scope, NOT T02 scope; writer T02 did not touch that file — hash unchanged).
- Symptom: passes in isolation (10/10) and in C3 suite alone; intermittently fails inside the FULL 12-suite
  combined (~1/12 runs) with a statement-count assertion (`<=10`). Root-cause hypothesis: the test uses
  `contextlib.suppress(Exception)` around `_advance_generation` (broad-except anti-pattern); if it throws,
  the SQLAlchemy session enters pending-rollback, so the next statements add ROLLBACK/BEGIN to the counted
  queries, tipping the N+1 guard over its bound. This is a C4 test-quality defect, NOT a T02 code defect.
- Decision per user: accept as known-limitation; T02 verified; flaky recorded for Codex (a small C4‑scope
  hardening could remove it later — out of T02 allowlist, so not performed inside T02).
