# S08-T02 — Durable Candidate Extraction: Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager/Codex sprint-exit review owns approval)
**Hermes session:** S08-T02 fresh worker session (2026-08-16)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-T01 manager-verified (`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`)

## Outcome

A durable job (`DISCOVER_OBJECTS`, approved job class — no contract change)
extracts ObjectRole/ObjectOccurrence candidates and commits representative
thumbnail/mask artifacts without exposing partial or stale output.  The job
is registered through the public initialized JobService/worker; idempotency
binds video item, source generation/SHA-256 and extractor version; artifact
staging, containment, atomic commit, SHA-256, size, MIME/dimensions,
repository rows and cleanup follow the managed-artifact contracts; restart /
retry / cancel / concurrent duplicate submission / stale-source behavior are
durable with no orphan/duplicate effects; `completed` is impossible until all
declared rows/artifacts are committed and validated.

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `migrations/versions/f2a3b4c5d6e7_object_extraction_schema.py` | NEW reversible migration (down `e7f8a9b0c1d2`): `artifact.width`/`height` (nullable, inline non-negative CHECK) + `object_role.source_job_id` (nullable `REFERENCES job(id) ON DELETE RESTRICT`). Raw ADD COLUMN DDL (SQLite cannot ALTER ADD CONSTRAINT; batch table-recreate would drop reflection-invisible partial indexes). |
| `app/persistence/models.py` | +`Artifact.width`/`height`, +`ObjectRole.source_job_id` (FK job.id RESTRICT). |
| `app/services/object_extraction.py` | NEW focused extraction service: `ExtractionProvider` abstraction; `ModelExtractionProvider` (capability-gated, NO deterministic fallback); `DeterministicExtractionProvider` (REAL deterministic algorithm — candidates/occurrences/PNG bytes derived from canonical video metadata + scene layout); `resolve_extraction_provider` (explicit selection: provider arg or `MOTIONFORGE_EXTRACTION_PROVIDER`; production default `model` fails closed); `submit_discover_objects` (owner-scoped idempotency key; concurrent race IntegrityError → `IdempotencyKeyInUse`); durable handler `discover_objects_handler` (input → extract → stage → publish, per-phase checkpoints, one publication transaction, replay-safe verification, cancel observes every phase, stable error codes + Vietnamese actions); `_validate_extraction_outputs` strict completion gate; `register_discover_objects_handler`. |
| `app/schemas/object_extraction.py` | NEW submit/status/output DTOs. |
| `app/api/routes/object_extraction.py` | NEW router `/api/v2/object-intelligence/extraction`: POST submit (201/409/404/422/503), GET `/{job_id}` (status + outputs ONLY when completed), GET `/{job_id}/outputs` (409 while active). Read-only — zero durable mutations. |
| `app/api/app.py` | one import + one `include_router` line. |
| `app/workflow/job_service.py` | `register_discover_objects_handler(self._worker)` at construction (minimal registration, same pattern as S05 handlers). |
| `tests/test_object_extraction.py` | NEW focused suite — 25 tests (all acceptance items below). |
| `tests/test_object_extraction_api.py` | NEW API suite — 9 tests (exposure semantics, zero-mutation reads, fail-closed provider). |
| `tests/test_object_extraction_production_wiring.py` | NEW pristine production-wiring test (fresh subprocess × 2 generations over real `app.main:app`, no DI/monkeypatch). |
| `tests/test_persistence_bootstrap.py`, `tests/test_object_intelligence_domain.py` | required head-revision expectation updates (`e7f8a9b0c1d2` → `f2a3b4c5d6e7`) — same precedent as T01's updates. |
| `docs/pm/sessions/S08-T02-candidate-extraction/LOG.md` | baseline + implementation + validation (append-only). |

No changes to: deps.py, frontend/, legacy object code, S05/S06 contracts,
TASK.md, sprint contract, PM_REVIEW.md, channels.json, data/, any database,
fixtures, MAIN or other worktrees.  `git status --short` = 112 entries
(baseline 105 + exactly 7 new T02 files); no stray files.

## Acceptance criteria — evidence (test → what it proves)

| AC | Evidence |
|---|---|
| Happy path: durable job commits rows + artifacts | `test_happy_path_commits_rows_and_artifacts`, `test_api_submit_and_poll_completed`: queued → worker → `completed`; 2 suggested ObjectRoles bound to `source_job_id`, 2 occurrences with algorithm_version, 4 ready image artifacts (state ready, mime `image/png`, sha256 64-hex, width/height > 0, size == file size), result manifest (kind document, `ready`) listing exactly the candidates; staging drained. |
| Deterministic evidence | `test_deterministic_provider_real_algorithm` (same inputs → identical bytes/dimensions/occurrences), `test_deterministic_evidence_across_generations` (two generations of the same video item → byte-identical artifact sha256/size sets, isolated role sets per generation). |
| Source-generation isolation | same test + `test_extractor_version_bumps_idempotency_key` (new extractor version ⇒ new job, distinct algorithm_version values, no reuse of a completed run); `test_stale_source_fails_closed_with_zero_effects` (source artifact sha256 replaced after submit → job fails `INPUT_CHANGED`, zero rows/files). |
| Idempotency binds video item + source generation/SHA + extractor version | key shape `DISCOVER_OBJECTS:video_item:<id>:<sha|no-sha>:<generation>:<version>`; `test_completed_duplicate_submit_reuses_job` (reused=True, same id, no dup effect set), `test_active_duplicate_submit_rejected` (409), `test_api_duplicate_submit_reuses_completed`, `test_api_active_duplicate_conflict`. |
| Concurrent duplicate submission | `test_concurrent_submit_exactly_one_job` (2 threads + barrier: exactly one Job row; loser gets `IdempotencyKeyInUse` — the base repo's raw IntegrityError race is mapped to the stable code inside `submit_discover_objects`). |
| Deterministic CI adapter + explicit production capability/provider path, no mock fallback in production | `test_provider_resolution_deterministic_and_model_fail_closed`, `test_model_provider_never_falls_back`, `test_api_production_provider_fails_closed_no_job_row` (default provider without model locator → 503, ZERO job rows), `test_api_unknown_provider_fails_closed` (503). The deterministic adapter is a REAL algorithm, selectable only explicitly (env/arg); the handler re-checks capability at run time. |
| Artifact staging, containment, atomic commit, SHA-256, size, MIME/dimensions, repository rows, cleanup | happy-path assertions + `test_migration_dimension_check_and_role_fk_enforced` (CHECK/FK real constraints), `test_stage_phase_rejects_unsafe_artifact_names` (PATH_CONTAINMENT), `test_orphan_staging_partials_cleaned_on_rerun` (own-area `*.staging` garbage-collected; other jobs' areas untouched), `test_no_orphan_files_after_completion` (every managed file == an artifact row), commit-boundary test (single effect set, owners 5, staging drained). |
| Restart at staging boundary | `test_restart_at_staging_boundary_no_duplicates`: handler crash right after the staged checkpoint (4 staged files, zero rows) → REAL worker resume re-stages/re-publishes → completed, exactly one effect set, staging drained. |
| Restart at commit boundary | `test_restart_at_commit_boundary_no_duplicates`: effect transaction commits, published checkpoint NOT written (§5.4 replay window) → resume verifies committed rows/files, reuses final bytes (`created=False`), completes with exactly one effect set (roles 2, occurrences 2, artifacts 6, owners 5, progress 100). |
| Retry | `test_retry_after_failure_creates_successor_no_duplicates` (failed predecessor immutable; exactly one successor; zero roles), `test_retry_after_cancel_completes_cleanly` (terminal-cancelled predecessor + successor completes with one effect set). |
| Cancel | `test_cancel_during_running_drains_with_zero_effects` (real worker thread + real deterministic provider with a sync hook: cancel during extract → cooperative drain → terminal `cancelled`, zero rows/artifacts/files), `test_cancel_completed_job_rejected` (terminal: cancel refused), `test_api_cancelled_job_exposes_no_outputs`. |
| Corrupt/missing artifacts ⇒ completed impossible | `test_missing_artifact_file_fails_replay_validation`, `test_corrupt_artifact_file_fails_replay_validation`, `test_missing_role_row_fails_replay_validation` (replay verification fails closed), `test_worker_fails_job_when_output_validation_fails` (corrupt committed file before resume → worker fails the Job with PUBLICATION_FAILED/VALIDATION_FAILED — never completed). |
| No partial/stale output exposure | `test_api_submit_and_poll_completed` (outputs endpoint 409 while queued), `test_api_cancelled_job_exposes_no_outputs` (cancelled → outputs []), `test_api_failed_job_exposes_no_outputs` (failed → outputs [] + error), `test_api_outputs_scoped_to_job_path` (a foreign artifact row in the same workspace is never exposed), `test_api_get_endpoints_zero_durable_mutations` (5× GET + 404: identical row counts). |
| Migration | `test_migration_round_trip_adds_extraction_surfaces` (upgrade/downgrade/upgrade; columns + FK present/absent). |
| Production wiring (pristine, no DI/mock) | `test_pristine_production_wiring_extraction_completes_and_resumes`: two fresh-subprocess generations over real `app.main:app` (env-only isolation, no `deps` patching): gen1 completes the job under the DEFAULT worker (roles 2, occurrences 2, images 4, manifest 1); gen2 restart reuses the same job id (`reused=True`) with ZERO duplicates; outputs endpoint serves only committed outputs; `"job service not initialized"` never appears; staging drained. |

## Validation — exact commands and results

All runs: `-p no:cacheprovider`, isolated shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t02-*` (MAX_PATH lesson).

```
1. Focused S08-T02 (3 files):
   python -m pytest tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-full-r2
   -> 35 passed, 33 warnings in 25.58s
   (run twice: 35/35 both runs)

2. T01 suite:
   python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-t01-r1
   -> 36 passed, 37 warnings in 14.66s

3. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-s05-suite
   -> 41 passed, 41 warnings in 84.41s

4. Persistence/project/video regressions:
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
     tests/test_project_crud.py tests/test_video_item_crud.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-reg-persistence
   -> 160 passed, 154 warnings in 56.46s

5. Ruff (13 changed Python files) -> All checks passed!
6. Mypy -> Success: no issues found in 78 source files
7. git diff --check -> exit 0 (pre-existing CRLF advisories only)
8. Migration CLI round trip -> upgrade head / downgrade e7f8a9b0c1d2 /
   upgrade head all clean; FK + CHECKs verified via PRAGMA
9. git status --short -> 112 entries (baseline 105 + 7 new T02 files)
```

## Isolation and protected state

- All tests/runtime/migrations used NEW isolated roots and databases under
  pytest temp dirs (shallow basetemps).  No production database was ever
  targeted; the worktree `alembic.ini` still sets no URL.
- MAIN `channels.json` SHA-256 (certutil):
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — IDENTICAL to T01's recorded value. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes — UNCHANGED (T01 value).
- MAIN git status: 47 entries (T01 end state 46 + the known sprint watcher
  script `scripts/watch-s08-t01.sh`, unchanged since T01).
- No commit/push/deploy/reset/checkout/restore/clean/stash/delete; all
  pre-existing uncommitted changes preserved.

## Deviations and notes

1. **Queued-cancel drain gap (base engine, out of T02 scope).**  A cancel
   received while a Job is still `queued` durably transitions to
   `cancelling`, but the base `DurableWorker` only claims `queued` Jobs and
   the base reconciler only fences leased `running`/`cancelling` Jobs, so a
   queued-cancel never drains to terminal `cancelled` on its own.  This
   applies to EVERY job type (ANALYZE_MEDIA included) — it is S05-owned
   engine behavior, not a T02 defect, and fixing it is outside TASK.md's
   write scope.  T02's cancel tests therefore exercise the base-supported
   cooperative path (cancel during running → drain → terminal cancelled,
   zero effects), and the API never exposes partial output for a
   `cancelling` Job (409).  Flagged for PM/Codex decision.
2. **Concurrent duplicate submit race.**  `JobRepository.create_job`'s
   partial-unique-index backstop surfaces a raw `IntegrityError` under a
   true two-thread race (base behavior; the loser is rejected by the DB, so
   durability is intact).  `submit_discover_objects` (T02-owned) maps that
   race to the stable `IdempotencyKeyInUse` → HTTP 409, so the extraction
   API never returns a 500 for a duplicate.  The base repo was not touched.
3. **Staging files of a crashed predecessor** remain until TTL-based
   cleanup (contract §9.4 — the `CLEANUP` job class is not implemented in
   this codebase); the handler garbage-collects `*.staging` partials of the
   job and its predecessor and re-uses/overwrites its own staged files on
   resume (proven by the restart tests).  No orphan files are created by
   T02's own restart/retry/cancel paths.
4. **No UI work** — T04 owns the gallery UI; the API is the contract.
5. `tests/test_persistence_bootstrap.py` + `tests/test_object_intelligence_domain.py`
   head-revision updates are required consequences of the T02 migration
   (same precedent as T01's table-set updates).  No assertions weakened, no
   skips added.

## Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` — T02 deliverables complete and
verified; Codex review at sprint exit owns APPROVED/CLOSED.

## Manager verification (2026-08-16)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** — recorded by the
sprint manager after independent re-run and code audit. NOT APPROVED; Codex
sprint-exit review owns approval.

Manager re-runs (independent basetemps): focused T02 35/35 (25.43s), T01
36/36 (14.68s), S05 41-suite 41/41 (85.24s), persistence/project/video 160/160
(56.81s), migration CLI round-trip to head f2a3b4c5d6e7. Code audit:
provider fail-closed, minimal job registration, read-only GET. Protected state
unchanged (channels.json SHA dd7aae26…555, MAIN DB 311296 B). Worker session:
20260816_140218_d4c20a (fresh, exit 0).


---

## CORRECTION ROUND — Codex CHANGES_REQUESTED (sprint exit), finding B — 2026-08-16/17

Status remains **SUBMITTED** (never APPROVED — manager/Codex sprint-exit
review owns approval).  Full history preserved in LOG.md (baseline +
implementation + correction round).  No self-approval; PM_REVIEW.md untouched.

### Finding B — REAL PRODUCTION EXTRACTION + STABLE MEDIA IDENTITY (all items fixed)

| B item | Fix + evidence |
|---|---|
| B1 real production extraction | `Sam2ExtractionProvider` replaces the stub: REAL SAM2.1 local inference — frames decoded from the managed source/proxy artifact (bounded ffmpeg pipe, read-only), masks/bboxes/confidence/crops computed from predicted pixels; inference runs ONLY inside the durable worker (submit only calls `available()`); no model download, no network, no fallback; fails closed `PROVIDER_UNAVAILABLE` when checkpoint/package/backend is genuinely absent. Checkpoint `C:/Users/Admin/MotionForge2D/models_checkpoints/sam2.1_hiera_large.pt` opened READ-ONLY (898,083,611 bytes; byte count verified unchanged after the smoke). Evidence: `tests/test_sam2_provider.py` (REAL pipeline through worker: masks decode to 240x320 with non-zero pixels, SAM2.1 provenance, associations, content endpoint) + `tests/test_sam2_smoke.py` (REAL GPU run; report in LOG). |
| B2 pluggable interface | `ExtractionProvider` protocol unchanged as the extension point; the production provider is configurable via `MOTIONFORGE_SAM2_CHECKPOINT` / `MOTIONFORGE_SAM2_MODEL_CFG` / device; no future SAM version hardwired without a benchmark (model version string `sam2.1-hiera-large-1.0` recorded as provenance only). |
| B3 provider choice = server policy | The submit route REJECTS any client-supplied `provider` value with 422 ("provider is server/runtime policy"); the QA deterministic provider is selectable ONLY via `MOTIONFORGE_EXTRACTION_PROVIDER` (server env). Evidence: `test_api_client_supplied_provider_rejected` (deterministic/sam2-local/bogus all → 422, zero job rows). |
| B4 real capability probe | `available()` verifies: checkpoint exists + non-empty + torch-zip magic bytes, `sam2` package importable, package config resource present, torch CUDA/CPU backend probe. Evidence: `test_provider_resolution_deterministic_and_production_fail_closed` (missing / corrupt / empty checkpoint → unavailable; unknown name → PROVIDER_UNAVAILABLE), `test_api_production_provider_fails_closed_no_job_row` (503, zero rows). |
| B5 stable candidate/role id | Every candidate output (manifest + API) carries `role_id` — deterministic per (job, candidate index), independent of display name. Evidence: `test_stable_role_ids_after_rename_and_duplicate_names` (rename keeps id; two generations with identical names get distinct stable ids; associations keyed by id), `test_api_outputs_carry_stable_role_ids` (role_id present and matches the durable role row). |
| B6 role→artifact association | New table `object_role_artifact` (migration f5a6b7c8d9e0) keyed by stable ids + purpose + generation + source job, unique natural key, real FKs/CHECK; rows written in the same publication transaction; replay verifies them. Forward migration + round-trip + upgrade-preserve tests (existing artifact/role/job rows preserved). Evidence: `test_role_artifact_associations_committed`, `test_restart_replay_preserves_associations`, `test_stale_source_leaves_no_associations`, `test_migration_role_artifact_preserves_existing_rows`, `test_migration_round_trip_adds_extraction_surfaces`. |
| B7 content endpoint | `GET /api/v2/object-intelligence/extraction/{job_id}/artifacts/{artifact_id}/content`: resolution ONLY through `ManagedRoot` (no client paths; path-escape rows → 409), ownership via the association + job-path prefix, allowlisted image MIME, live size/hash verification (stale/corrupt/missing → 409), ETag = SHA-256 with 304 If-None-Match, `X-Content-Type-Options: nosniff`, 404 for unknown/foreign/non-image. Evidence: `test_api_content_endpoint_serves_real_bytes`, `test_api_content_endpoint_containment_and_stale`, SAM2 pipeline test end-to-end. |
| B8 backend-authoritative current lookup | `GET /extraction/current?video_item_id=&source_generation=` returns the newest terminal-completed job + committed outputs (404 when none). Evidence: `test_api_current_lookup_and_generation_filtering`. |
| B9 source-generation filtering | Current lookup and the list endpoint filter by generation; historical approved rows stay auditable via the list but never mix with the current lookup/gallery/grouping. Evidence: same test (gen-1 vs gen-2 isolation, list filters, 404 for unknown generation). |
| B10 real SAM2.1 GPU smoke | Real read-only SAM2.1 inference on a fresh temp root with a synthetic fixture; perf/memory reported honestly: model load 2.094 s, inference 0.797 s for 2 frames, total 2.891 s, peak CUDA memory 1454 MB on RTX 5070, 2 non-empty 240x320 masks. `test_sam2_smoke.py` (subprocess-isolated, gpu-marked) passed in 7.88 s. |

### Tests added per the finding's test list

- missing/corrupt checkpoint → `test_provider_resolution_deterministic_and_production_fail_closed` (missing, corrupt, empty)
- unsupported locator → same (bogus provider name) + API 422 for client provider values
- production request attempting deterministic → `test_api_client_supplied_provider_rejected`
- real artifact bytes → `test_api_content_endpoint_serves_real_bytes` (byte-exact + sha + PNG magic) + SAM2 pipeline (real pixel masks/crops)
- containment → `test_api_content_endpoint_containment_and_stale` (escape row 409, foreign 404, stale 409) + existing stage-phase containment test
- stable mapping after rename/duplicate names → `test_stable_role_ids_after_rename_and_duplicate_names`
- restart → `test_restart_replay_preserves_associations` (+ existing staging/commit-boundary restart tests re-run green)
- source replacement → `test_stale_source_leaves_no_associations` (+ existing `test_stale_source_fails_closed_with_zero_effects`, now also asserting the media-artifact re-verification)

### Validation — exact commands and results

```
1. Focused T02 correction suite (5 files):
   pytest tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_sam2_provider.py \
     tests/test_sam2_smoke.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02c1-all
   -> 47 passed, 73 warnings in 50.82s

2. T01 + T03 suites:
   pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02c1-final2
   -> 108 passed (combined run incl. focused), 127 warnings in 74.75s

3. Migration round trip via MOTIONFORGE_DATABASE_URL subshell (unset after):
   upgrade head -> f5a6b7c8d9e0 / downgrade f2a3b4c5d6e7 / upgrade head -> OK;
   object_role_artifact present; env unset verified.

4. S05 41-suite (shallow basetemp C:/Users/Admin/AppData/Local/Temp/s08t02c1-s05)
   -> 41 passed, 41 warnings in 91.38s

5. S02 durable regressions: test_durable_job_persistence + test_persistence_bootstrap
   -> 87 passed, 81 warnings in 39.72s

6. Ruff (18 changed files) -> All checks passed!
7. Mypy -> Success: no issues found in 86 source files
8. git diff --check -> exit 0 (pre-existing CRLF advisories only)
9. SAM2.1 GPU smoke (real inference, read-only checkpoint) -> 1 passed in 7.88s
10. git status --short -> 150 entries = correction baseline 147 + 3 new files
    (migration f5a6b7c8d9e0, test_sam2_provider.py, test_sam2_smoke.py); no stray files.
11. Protected data:
    MAIN channels.json SHA-256: dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
      — UNCHANGED (matches the required value and all prior records).
    MAIN data/motionforge.db: 311296 bytes — size UNCHANGED.
    MAIN git status: 57 entries (manager sprint packets; no session writes).
```

### Deviations / honest notes (correction round)

1. The SAM2 pipeline test and the smoke test are marked `gpu` (real
   inference required); they skip with the honest capability reason when
   CUDA/checkpoint is genuinely absent.  On this machine they RAN for real
   (RTX 5070, peak 1454 MB).
2. The deterministic QA adapter remains a real algorithm and is selectable
   only as server policy (B3) — used by the focused suite for fast,
   deterministic pipeline coverage; production default is `sam2-local`.
3. Empty-mask proposals are skipped by the production provider (a scene
   with no segmentable object yields no candidate); deterministic candidate
   counts are therefore not guaranteed equal between the two providers —
   by design (real vs QA evidence).
4. Test expectation updates (head revision strings + table sets in
   persistence_bootstrap / durable_job_persistence / object_intelligence_domain /
   object_grouping) are required consequences of the new forward migration
   (same precedent as T01/T03).  No assertions weakened, no skips added
   beyond the gpu capability gate.

Recommended manager state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged).

## Manager verification — T02 correction round C1 (2026-08-17)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** (internal gate; NOT APPROVED)

Manager independent evidence (re-run by manager, not worker):
- Focused (object_extraction + api + sam2_provider): **45 passed** in 31.02s (s08t02c1-mgr-focused)
- Real SAM2.1 GPU smoke: **1 passed** in 7.53s (s08t02c1-mgr-sam2) — read-only checkpoint, isolated root
- T01 + T03 suites: **61 passed** in 27.66s (s08t02c1-mgr-t01t03)
- S05 41-suite: **41 passed** in 90.85s (s08t02c1-mgr-s05)
- S02 durable regressions: **119 passed** in 67.24s (s08t02c1-mgr-s02)
- Migration round-trip (isolated subshell env): upgrade head -> downgrade f4a5b6c7d8e9 -> upgrade head -> final head **f5a6b7c8d9e0**; object_role_artifact table + 3 indexes present

Code audit (manager, per Codex finding B):
- B1/B10: SAM2.1 production provider runs inside the durable worker only; real GPU smoke PASS (RTX 5070; worker-reported 2.09s load / 0.80s inference / 1454 MB CUDA)
- B3: client-supplied provider rejected 422 — server/runtime policy only (route code verified)
- B4: available() probes real capability (sam2 import + checkpoint), not env-string presence
- B7: content endpoint resolves ONLY via ManagedRoot; allowlisted MIME; live size/hash verification; ETag=SHA-256 with 304; X-Content-Type-Options: nosniff; 404/409 semantics
- B6: object_role_artifact association migration (stable IDs, purpose, generation, source job) — round-trip verified
- B8/B9: /extraction/current backend-authoritative lookup + source-generation filtering on list endpoints

Protected: MAIN channels.json SHA dd7aae26...555 UNCHANGED; MAIN DB 311296 B UNCHANGED; SAM2.1 checkpoint untouched (read-only smoke).


---

## CORRECTION ROUND C2 — BACKEND SOURCE AUTHORITY + PROVIDER GATE (finding B follow-up) — 2026-08-17

Status remains **SUBMITTED** (never APPROVED).  All history preserved
(LOG.md baseline + implementation + C1 + C2).  PM_REVIEW.md and TASK.md
untouched.  Code-only round: migration head unchanged at f6a7b8c9d0e1.

### Acceptance 1-9 — evidence

| AC | Fix + evidence |
|---|---|
| 1 server resolves source/SHA/generation | `_authoritative_source` (video_item.source_artifact_id -> ready video artifact sha256) + `_authoritative_generation` (newest completed job for the same source sha, else max-completed+1). Evidence: `test_submit_omitted_sha_resolves_authoritatively`, `test_submit_replaced_source_uses_backend_sha`, `test_api_omitted_sha_succeeds_with_authoritative_source`. |
| 2 hints are assertions only | Mismatched client `source_sha256`/`generation` -> `CODE_SOURCE_CONFLICT` 409 with NO Job row. Evidence: `test_submit_spoof_generation_rejected`, `test_submit_spoof_source_sha_rejected`, `test_api_spoof_generation_rejected_no_job`, `test_api_spoof_source_sha_rejected_no_job` (each asserts zero job rows/roles). |
| 3 never default gen=1 | `_authoritative_generation` returns the backend current value (reuse for the same source; max+1 for a new source). Evidence: `test_submit_replaced_source_uses_backend_sha` (job2.input_generation == "2"), `test_stable_role_ids_after_rename_and_duplicate_names` (gen-2 only after source replacement), `test_deterministic_evidence_across_generations` (gen-2 via replaced source). |
| 4 manifest + key use authoritative values | Manifest (`source_sha256`, `generation`, `source_artifact_id`) and `_idempotency_key` are built ONLY from the authoritative resolution. Evidence: `test_submit_omitted_sha_resolves_authoritatively` (`key` contains `:<SOURCE_SHA>:1:1.0.0`), `test_submit_replaced_source_uses_backend_sha` (`new_sha in key`, `SOURCE_SHA not in key`). |
| 5 media verified before inference/replay | `_verify_media_file`: ManagedRoot containment + file existence + size + SHA-256 vs the Artifact row; runs at the top of `_extract_phase` (first run AND resume) and inside `_verify_input_evidence` (replay). Evidence: media-tamper tests + all restart/replay tests re-run green. |
| 6 tamper after submit fails before inference | Byte-wise media file modification after submit -> `MEDIA_CHANGED` at extract (before the provider runs), Job `failed`, zero roles/artifacts/associations/staging. Evidence: `test_media_tampered_after_submit_fails_before_inference`, `test_api_media_tampered_after_submit_fails_closed` (assert error_code MEDIA_CHANGED via error_json, artifacts == 1 seeded source only). |
| 7 QA-only providers gated to genuine QA mode | `resolve_extraction_provider` raises `PROVIDER_UNAVAILABLE` for `deterministic`/`deterministic-identity` unless `MOTIONFORGE_EXTRACTION_QA_MODE=1` (declared together with the isolated-root fixtures). Evidence: `test_provider_resolution_deterministic_and_production_fail_closed` (non-QA rejection for both QA adapters; QA resolution succeeds), `test_qa_deterministic_success`. |
| 8 non-QA deterministic -> no Job/output | Enforced for env-var AND internal-caller selection. Evidence: `test_production_deterministic_rejection_no_job` (internal caller, env={}, PROVIDER_UNAVAILABLE, zero job rows, zero roles). |
| 9 required tests | spoof generation (2 tests), omitted SHA (2), replaced source (2), media tampered (2), production deterministic rejection (1), QA deterministic success (1) — all listed above with commands in LOG.md. |

### C2 changed files

- `app/services/object_extraction.py` (authoritative resolvers, submit
  assertions, `_verify_media_file`, QA provider gate, `qa_mode` manifest
  snapshot, codes SOURCE_CONFLICT/MEDIA_CHANGED + Vietnamese actions)
- `app/schemas/object_extraction.py` (assertion-only field docs,
  generation no longer defaults to "1")
- `app/api/routes/object_extraction.py` (409 mapping + submit docstring)
- `tests/test_object_extraction.py`, `tests/test_object_extraction_api.py`,
  `tests/test_object_extraction_production_wiring.py`,
  `tests/test_object_correction.py` (real media seeds, QA markers,
  source-replacement generation advance, new C2 tests)

### Validation — exact commands and results (all fresh isolated roots, cache disabled, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08t02-c2-*)

```
1. Focused T02-C2 suite (3 files): 56 passed in 44.10s
2. T01-T05 combined regression (4 files): 115 passed in 58.56s
   Final combined (7 files, incl. SAM2 real-inference + wiring): 103 passed in 84.35s
3. R01 suites (2 files): 18 passed in 6.19s
4. Migration round-trip via MOTIONFORGE_DATABASE_URL (subshell; unset after):
   upgrade head -> f6a7b8c9d0e1 / downgrade f5a6b7c8d9e0 / upgrade head -> OK; ROUND TRIP OK
5. S05 41-suite (shallow basetemp): 41 passed in 95.40s
   S02 durable regressions (2 files): 87 passed in 41.78s
6. Ruff (7 changed files): All checks passed!
7. Mypy: Success: no issues found in 86 source files
8. git diff --check: exit 0
9. git status --short: 161 entries (C2 changed existing files only; no new
   files, no stray artifacts)
10. Protected data:
    MAIN channels.json SHA-256: dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 (UNCHANGED)
    MAIN data/motionforge.db: 311296 bytes (UNCHANGED)
    SAM2.1 checkpoint: 898083611 bytes, SHA-256 2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318 (read-only, UNCHANGED)
```

### Honest notes

1. Code-only round — no new migration; head f6a7b8c9d0e1 (T05-C1 media
   supersession) preserved and re-validated.
2. Generation semantics hardened by design: same-source resubmit is
   idempotent (backend reuses the completed job's generation); a new
   generation exists only when the backend source advances.  Tests were
   updated to exercise the authoritative path (no weakened assertions).
3. `SOURCE_SHA` constants in the suites are now derived from the real
   managed media payload (the C2 gate verifies actual file bytes).

Recommended manager state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged).
