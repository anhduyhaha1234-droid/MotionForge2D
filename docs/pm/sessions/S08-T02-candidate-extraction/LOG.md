# S08-T02 — Execution Log

Status: HERMES_RUNNING

Append-only. Record exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

---

## Baseline — 2026-08-16 (Hermes session, S08-T02 fresh worker)

### Hard worktree guard (verified before any write)

| Check | Expected | Actual |
|---|---|---|
| pwd | C:/Users/Admin/MotionForge2D-worktrees/s08-integration | /c/Users/Admin/MotionForge2D-worktrees/s08-integration |
| git rev-parse --show-toplevel | C:/Users/Admin/MotionForge2D-worktrees/s08-integration | C:/Users/Admin/MotionForge2D-worktrees/s08-integration |
| git branch --show-current | codex/s08-integration | codex/s08-integration |
| git rev-parse HEAD | a43b20da742996bafcb2f9d1ac57b10d3f1a5204 | a43b20da742996bafcb2f9d1ac57b10d3f1a5204 |
| git status --short | snapshot dirty state | captured below (S08-P00 integrated base, uncommitted) |

### Baseline dirty state (git status --short, verbatim)

```
 M app/api/app.py
 M app/api/deps.py
 M app/api/routes/projects.py
 M app/persistence/models.py
 M app/workflow/durable_worker.py
 M app/workflow/job_service.py
 M docs/pm/ROADMAP.md
 M docs/pm/sessions/S06-T05-pack-publish-ux/LOG.md
 M docs/pm/sessions/S06-T05-pack-publish-ux/PM_REVIEW.md
 M docs/pm/sessions/S06-T05-pack-publish-ux/REPORT.md
 M docs/pm/sessions/S06-T05-pack-publish-ux/START_PROMPT.md
 M docs/pm/sessions/S06-T05-pack-publish-ux/TASK.md
 M frontend/src/app/(app)/characters/page.tsx
 M frontend/src/components/layout/AppNav.tsx
 M frontend/src/lib/api.ts
 M tests/fixtures/legacy_import/importable/channels.json
 M tests/fixtures/legacy_import/importable/projects/proj_001/project.json
 M tests/fixtures/legacy_import/importable/projects/proj_001/replacement.png
 M tests/fixtures/legacy_import/importable/projects/proj_001/video.mp4
 M tests/test_durable_job_persistence.py
 M tests/test_persistence_bootstrap.py
?? app/api/routes/durable_characters.py
?? app/api/routes/object_intelligence.py
?? app/persistence/characters.py
?? app/persistence/object_intelligence.py
?? app/schemas/characters.py
?? app/schemas/object_intelligence.py
?? app/services/scene_detector.py
?? app/services/timebase.py
?? app/services/video_import.py
?? app/services/video_proxy.py
?? app/workflow/analyze_orchestrator.py
?? app/workflow/character_preset_importer.py
?? app/workflow/character_validator.py
?? app/workflow/preset_layout_manifest.py
?? docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md
?? docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md
?? docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md
?? docs/pm/sessions/S05-C01-approved-pipeline-orchestration/
?? docs/pm/sessions/S05-C02-durable-chain-progression/
?? docs/pm/sessions/S05-C03-final-lifecycle-correction/
?? docs/pm/sessions/S05-C04-production-job-service-wiring/
?? docs/pm/sessions/S05-T01-video-preflight/
?? docs/pm/sessions/S05-T02-managed-import/
?? docs/pm/sessions/S05-T03-canonical-timebase-proxy/
?? docs/pm/sessions/S05-T04-scene-detection/
?? docs/pm/sessions/S05-T05-import-analyze-ui/
?? docs/pm/sessions/S05-T06-golden-integration/
?? docs/pm/sessions/S06-R01-character-domain-integration/
?? docs/pm/sessions/S06-R02-character-artifact-read-api/
?? docs/pm/sessions/S06-T04-character-ui-review/
?? docs/pm/sessions/S06-T05-pack-publish-ux/INCIDENT_REPORT_WORKTREE_MAIN.md
?? docs/pm/sessions/S08-P00-integrated-base/
?? docs/pm/sessions/S08-T01-object-role-domain/
?? docs/pm/sessions/S08-T02-candidate-extraction/
?? docs/pm/sessions/S08-T03-grouping-api/
?? docs/pm/sessions/S08-T04-object-gallery/
?? docs/pm/sessions/S08-T05-targeted-correction/
?? docs/pm/sessions/S08-T06-golden-object-intelligence/
?? docs/pm/sprints/S08-SPRINT_CONTRACT.md
?? frontend/e2e/... (S05/S06/S08-P00 Playwright specs + configs)
?? frontend/src/app/(app)/import-analyze/
?? frontend/src/components/ImportAnalyzePanel.tsx
?? frontend/src/lib/preflightErrors.ts
?? migrations/versions/d5e6f7a8b9c0_character_library_schema.py
?? migrations/versions/e7f8a9b0c1d2_object_intelligence_schema.py
?? tests/fixtures/legacy_import/corrupt/projects/
?? tests/fixtures/legacy_import/valid/projects/
?? tests/test_character_domain.py
?? tests/test_character_preset_importer.py
?? tests/test_character_read_api.py
?? tests/test_character_validator.py
?? tests/test_object_intelligence_domain.py
?? tests/test_publish_rejection.py
?? tests/test_s05_atomic_cancel.py
?? tests/test_s05_chain_progression.py
?? tests/test_s05_golden_integration.py
?? tests/test_s05_lifecycle.py
?? tests/test_s05_orchestration.py
?? tests/test_s05_orchestrator_binding.py
?? tests/test_s05_production_wiring.py
?? tests/test_scene_detection.py
?? tests/test_timebase.py
?? tests/test_video_import.py
?? tests/test_video_proxy.py
```

(21 modified + 84 untracked = S08-P00 integrated base, uncommitted; protected
as-is — never overwritten.)

### Required reading checklist (all read in full, in order)

1. docs/pm/SESSION_PROTOCOL.md (MAIN) — read
2. docs/pm/sprints/S08-SPRINT_CONTRACT.md — read
3. docs/pm/sessions/S08-T02-candidate-extraction/TASK.md — read
4. docs/pm/sessions/S08-T02-candidate-extraction/START_PROMPT.md — read
5. docs/architecture/DURABLE_JOB_CONTRACT.md — read (V1.1, incl. §9 artifacts,
   §14 audit, §15 invariants)
6. docs/architecture/MANAGED_ARTIFACT_CONTRACT.md — read
7. T01 dependency evidence: S08-T01 REPORT.md (incl. correction round C1) +
   LOG.md + app/persistence/object_intelligence.py +
   app/schemas/object_intelligence.py — read

### Pre-change baseline run (T01 suite, fresh isolated basetemp, cache disabled)

```
python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-baseline
-> 36 passed, 37 warnings in 13.74s
```

Head revision before T02: e7f8a9b0c1d2 (T01). Baseline git status count:
105 entries (21 modified + 84 untracked).

---

## Plan (followed in order)

1. Migration f2a3b4c5d6e7: add `artifact.width`/`artifact.height` (nullable,
   non-negative CHECK) and `object_role.source_job_id` (nullable String(36),
   FK job.id RESTRICT); update `app/persistence/models.py` to match.
2. `app/services/object_extraction.py`: DISCOVER_OBJECTS durable service —
   provider abstraction (deterministic CI adapter + explicit production
   capability/provider path, NO mock fallback), deterministic candidate
   algorithm, durable handler (input → extract → stage → publish in one
   transaction; replay-safe; cancel observes; stable error codes),
   `discover_objects_steps()`, `register_discover_objects_handler()`,
   `submit_discover_objects()` (owner-scoped idempotency: video item +
   source SHA + generation + extractor version).
3. `app/schemas/object_extraction.py` DTOs + `app/api/routes/
   object_extraction.py` (POST submit, GET job status, GET outputs only when
   completed; no partial/stale exposure) + `app/api/app.py` registration +
   `app/workflow/job_service.py` handler registration at construction.
4. Head-revision expectation updates (persistence_bootstrap head/anchor:
   e7f8a9b0c1d2 -> f2a3b4c5d6e7; object_intelligence_domain upgrade-preserve
   assertion).
5. Focused suite `tests/test_object_extraction.py` covering every validation
   item (happy, deterministic evidence, source-generation isolation,
   idempotency, concurrent submit, restart at staging/commit boundaries,
   retry, cancel, corrupt/missing artifacts, containment, orphan cleanup,
   zero-mutation reads).
6. Pristine production-wiring test (fresh subprocess, real app.main:app, no
   DI/monkeypatch) `tests/test_object_extraction_production_wiring.py`.
7. Full validation: focused + T01 + S05 regressions (shallow basetemps) +
   ruff + mypy + git diff --check + final git status; protected-data
   comparison (MAIN channels.json SHA, MAIN motionforge.db size).

---

## Implementation — 2026-08-16 (append-only entries below)

## Implementation log — 2026-08-16 (append-only)

### Files written (all within TASK.md allowed write scope)

1. `migrations/versions/f2a3b4c5d6e7_object_extraction_schema.py` — new
   revision (down_revision e7f8a9b0c1d2): `artifact.width`/`artifact.height`
   (nullable, inline CHECK non-negative) + `object_role.source_job_id`
   (nullable VARCHAR(36) REFERENCES job(id) ON DELETE RESTRICT).  Raw
   ADD COLUMN DDL because Alembic's SQLite dialect cannot ALTER ADD
   CONSTRAINT and batch mode would recreate tables (losing
   reflection-invisible partial indexes like uq_object_role_workspace_idempotency).
   Round trip verified: upgrade head -> downgrade e7f8a9b0c1d2 -> upgrade head.
2. `app/persistence/models.py` — Artifact.width/height, ObjectRole.source_job_id
   ORM columns (FK job.id RESTRICT).
3. `app/services/object_extraction.py` — DISCOVER_OBJECTS durable service:
   provider abstraction (ModelExtractionProvider capability-gated, NO
   fallback; DeterministicExtractionProvider real algorithm, explicit CI
   selection), `submit_discover_objects` (owner-scoped idempotency key
   binding video item + source SHA + generation + extractor version;
   IntegrityError race -> IdempotencyKeyInUse), durable handler
   (input -> extract -> stage -> publish; per-phase checkpoints; one
   publication transaction; replay-safe row/file verification;
   cancel observes; stable error codes + Vietnamese actions),
   `_validate_extraction_outputs` strict completion gate, registration.
4. `app/schemas/object_extraction.py` — submit/status/output DTOs.
5. `app/api/routes/object_extraction.py` — POST submit (201/409/404/422/503),
   GET status (outputs only when completed), GET outputs (409 while active).
6. `app/api/app.py` — include_router (one import + one line).
7. `app/workflow/job_service.py` — register_discover_objects_handler at
   construction (minimal registration, same pattern as S05 handlers).
8. `tests/test_object_extraction.py` — focused suite (25 tests).
9. `tests/test_object_extraction_api.py` — API suite (9 tests).
10. `tests/test_object_extraction_production_wiring.py` — pristine
    production-wiring test (fresh subprocess, real app.main:app, no DI).
11. `tests/test_persistence_bootstrap.py`, `tests/test_object_intelligence_domain.py`
    — head-revision expectation updates (e7f8a9b0c1d2 -> f2a3b4c5d6e7).

### Design decisions (recorded for review)

- Job class `DISCOVER_OBJECTS` (approved list, DURABLE_JOB_CONTRACT §3) —
  no contract change needed; step code `extract`.
- Idempotency key:
  `DISCOVER_OBJECTS:video_item:<video_item_id>:<source_sha256|no-sha>:<generation>:<extractor_version>`.
- Deterministic CI adapter selected ONLY explicitly (provider arg or
  `MOTIONFORGE_EXTRACTION_PROVIDER`); production default `model` fails
  closed `PROVIDER_UNAVAILABLE` at submit AND at run time.
- Checkpoint stores candidate METADATA (no binary bytes); resume
  regenerates identical deterministic bytes and verifies metadata equality
  (drift -> INPUT_CHANGED).
- Completion gate = custom output_validator re-verifying every artifact row
  (ready + sha256 + size + dimensions) + file on disk + role rows, inside
  the worker's completion path (no static declared_outputs because the
  output set is per-job).
- Artifact purposes: `result` (manifest), `thumbnail`, `mask`; owners are
  video_item links; MIME image/png; dimensions recorded on the artifact row.

### Validation — exact commands and results (all `-p no:cacheprovider`, isolated shallow basetemps)

```
1. Focused S08-T02 (3 files):
   python -m pytest tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-full-r2
   -> 35 passed, 33 warnings in 25.58s
   (earlier isolated runs: focused 25/25, API 9/9, wiring 1/1)

2. T01 suite:
   python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-t01-r1
   -> 36 passed, 37 warnings in 14.66s

3. S05 preservation suite (SHALLOW basetemp - MAX_PATH lesson):
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

5. Ruff (all changed Python files, 13 files):
   -> All checks passed!

6. Mypy:
   python -m mypy app
   -> Success: no issues found in 78 source files

7. git diff --check -> exit 0 (pre-existing CRLF advisories only)

8. Migration round trip (standalone):
   upgrade head -> f2a3b4c5d6e7; artifact {width,height} + object_role
   source_job_id present; PRAGMA foreign_key_list(object_role) shows the
   job FK; downgrade e7f8a9b0c1d2 removes all three; upgrade head restores.

9. git status --short -> 112 entries = baseline 105 + exactly 7 new T02
   files (migration, service, schemas, route, 3 test files); no stray
   files; all pre-existing user changes preserved.

10. Protected data (unchanged):
    MAIN channels.json SHA-256 (certutil):
      dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
      (identical to T01 recorded value)
    MAIN data/motionforge.db: 311296 bytes (identical to T01 recorded value)
    MAIN git status: 47 entries (T01 end state 46 + known sprint watcher
    script scripts/watch-s08-t01.sh, unchanged since T01)
```

### Incidents / notes

- Base-engine behavior observed (NOT fixed — S05-owned): a cancel while a
  Job is still `queued` transitions to `cancelling` but the base worker
  only claims `queued` jobs and the reconciler only fences leased
  running/cancelling jobs, so a queued-cancel never drains to terminal
  `cancelled`.  Applies to every job type (ANALYZE_MEDIA included), not
  specific to T02; documented in REPORT as a production note.  T02 cancel
  tests therefore cover the base-supported cooperative cancel path
  (cancel during running -> drain -> terminal cancelled, zero effects).
- Concurrent duplicate submit races surfaced a raw IntegrityError from the
  base JobRepository.create_job (its partial-index backstop is not wrapped);
  submit_discover_objects now maps that race to the stable
  IdempotencyKeyInUse (409) — service-scoped fix, base repo untouched.
- One handler bug found by the focused suite and fixed during the run:
  the checkpoint once carried full candidate objects (binary bytes) ->
  JSON-serialization failure; the checkpoint now carries metadata only and
  resume regenerates deterministic bytes.

## MANAGER VERIFICATION — 2026-08-16

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence (re-run by manager, not worker):
- `python -m pytest tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-mgr-focused` -> **35 passed** in 25.43s
- T01 suite (s08t02-mgr-t01) -> **36 passed** in 14.68s
- S05 41-suite (s08t02-mgr-s05) -> **41 passed** in 85.24s
- Persistence regressions (s08t02-mgr-reg) -> **160 passed** in 56.81s
- Migration CLI round-trip (MOTIONFORGE_DATABASE_URL=sqlite:///C:/Users/Admin/AppData/Local/Temp/s08t02-mgr-migration.db): upgrade head -> downgrade e7f8a9b0c1d2 -> upgrade head -> final head **f2a3b4c5d6e7**, object_role + object_occurrence present

Code audit (manager):
- `resolve_extraction_provider`: explicit selection only; production default = model; unknown -> PROVIDER_UNAVAILABLE (fail closed); deterministic adapter is a REAL algorithm, never a silent fallback. OK.
- `register_discover_objects_handler(self._worker)` in JobService constructor — same minimal registration pattern as S05 handlers. OK.
- GET routes read-only (2 GETs, no commit in route module). OK.

Scope audit: INTEG 112 = baseline 105 + exactly 7 new T02 files (object_extraction service/schema/route/migration + 3 test files) + models.py/app.py/job_service.py/test_persistence_bootstrap.py expectation updates — all within TASK.md allowed scope. Writer exited (exit 0) before this review.

Protected state (manager re-verified): MAIN channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED; MAIN data/motionforge.db 311296 bytes UNCHANGED.

Decision: T02 dependency released for S08-T03 under full-sprint manager protocol.


---

## CORRECTION ROUND (Codex CHANGES_REQUESTED, finding B) — 2026-08-16/17

Same session continuation.  Fixes ONLY finding B items B1-B10 + its test list.

### Changes made

1. `migrations/versions/f5a6b7c8d9e0_object_role_artifact_schema.py` (NEW,
   down f4a5b6c7d8e9): `object_role_artifact` table — durable id-based
   Role->Artifact association keyed by (role_id, artifact_id, purpose,
   source_generation, source_job_id) with unique natural key, real FKs
   (role CASCADE, artifact RESTRICT, job RESTRICT), purpose CHECK
   (thumbnail|mask), revision + timestamps (B6).  Additive — existing rows
   preserved (verified by test).
2. `app/persistence/models.py`: +`ObjectRoleArtifact` ORM.
3. `app/services/object_extraction.py`:
   - `Sam2ExtractionProvider` (production, name `sam2-local`) REPLACES the
     stub: REAL capability probe (checkpoint file + size + torch-zip magic,
     sam2 package import, package config resource, CUDA/CPU backend probe —
     never a bare env string, B4); real pixel inference inside the worker
     only: bounded ffmpeg frame decode from the managed source/proxy
     artifact (read-only), SAM2.1 image predictor with layout point+box
     prompts, masks/bboxes/confidence from predicted pixels, real crop
     thumbnails (B1); checkpoint opened read-only, never copied/modified;
     pluggable provider interface preserved (B2); provider_stats
     (load/inference seconds, peak CUDA MB) recorded for honest reporting
     (B10).
   - `_layout_proposals` shared by the deterministic QA adapter and SAM2.
   - Deterministic provider = QA/test-only (B3); server policy only.
   - `_candidate_meta` now carries the STABLE `role_id` (B5).
   - Input evidence resolves the managed media (proxy preferred, else
     source) as RELATIVE paths only (no absolute paths persisted); replay
     re-verifies the media artifact (B1/B9 stale-source protection).
   - Publication transaction additionally writes the ObjectRoleArtifact
     rows; replay verifies them row-by-row (B6).
4. `app/schemas/object_extraction.py`: `provider` field documented as
   RESERVED; `ExtractionCandidateData.role_id` (B5).
5. `app/api/routes/object_extraction.py`:
   - submit REJECTS any client-supplied `provider` (422 — server/runtime
     policy only, B3);
   - `GET /extraction/current` — backend-authoritative current completed
     extraction for video_item_id (+ source_generation filter) (B8/B9);
   - `GET /extraction` — list with source_generation filtering (B9);
   - `GET /extraction/{job_id}/artifacts/{artifact_id}/content` —
     contained image endpoint: ManagedRoot-only resolution, ownership via
     the role-artifact association, allowlisted image MIME, live
     size/hash verification, ETag=sha256 + 304 If-None-Match,
     X-Content-Type-Options: nosniff, 404/409 semantics (B7).
6. Tests: +migration round-trip/preserve (B6), association commit/replay/
   stale-source (B6), stable role ids after rename + duplicate names (B5),
   provider capability (missing/corrupt/empty checkpoint, bogus name)
   (B4), production request attempting deterministic => 422 (B3),
   content endpoint real bytes/ETag/nosniff/containment/stale (B7),
   current lookup + generation filtering + zero-mutation reads (B8/B9),
   REAL SAM2.1 pipeline through the durable worker (`test_sam2_provider.py`,
   gpu-marked, B1), REAL read-only SAM2.1 GPU smoke (`test_sam2_smoke.py`,
   subprocess-isolated, B10).  Head-revision expectation updates in
   persistence_bootstrap / durable_job_persistence / object_intelligence_domain /
   object_grouping (f4a5b6c7d8e9 -> f5a6b7c8d9e0; S08_HEAD_TABLES +
   cutover-table set + object_role_artifact).

### SAM2.1 GPU smoke — REAL run (read-only checkpoint, fresh temp root)

Runner: fresh subprocess; checkpoint C:/Users/Admin/MotionForge2D/
models_checkpoints/sam2.1_hiera_large.pt opened READ-ONLY (898,083,611
bytes; byte-count verified unchanged after the run); synthetic 2s 320x240
cut video generated by ffmpeg into the temp root.

Verbatim report (JSON)::

    capability_ok: true, capability_reason: "sam2.1 local backend ready"
    device: NVIDIA GeForce RTX 5070, cuda_available: true
    model_load_seconds: 2.094
    inference_seconds: 0.797 (2 frames)
    extract_total_seconds: 2.891
    gpu_mem_peak_mb: 1454.0 (torch.cuda.max_memory_allocated)
    candidate_count: 2, masks_nonempty: [true, true], mask_shape: [240, 320]
    thumbnail_magic_png: true

Performance/memory honest summary: SAM2.1-hiera-large loads in ~2.1s and
runs ~0.4s/frame on the RTX 5070 at 320x240 input (1024x1024 internal),
peaking at ~1.45 GB of CUDA memory — comfortably within the 12 GB card.
Full durable-pipeline run (submit -> worker -> publish -> content endpoint)
passed in 7.28s including model load.

### Validation — exact commands and results (all `-p no:cacheprovider`, fresh shallow basetemps)

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
   -> 108 passed (combined with focused, 127 warnings) in 74.75s

3. Migration round trip via MOTIONFORGE_DATABASE_URL (subshell; unset after):
   MOTIONFORGE_DATABASE_URL=sqlite:///.../roundtrip.db alembic upgrade head
     -> upgrade ... f4a5b6c7d8e9 -> f5a6b7c8d9e0 OK
   MOTIONFORGE_DATABASE_URL=... alembic downgrade f2a3b4c5d6e7
     -> downgrade f4a5b6c7d8e9 -> f3a4b5c6d7e8 -> f2a3b4c5d6e7 OK
   MOTIONFORGE_DATABASE_URL=... alembic upgrade head
     -> upgrade back to f5a6b7c8d9e0 OK
   final head f5a6b7c8d9e0; object_role_artifact present; ROUND TRIP OK
   (env unset verified: ${MOTIONFORGE_DATABASE_URL:-<unset>})

4. S05 41-suite (SHALLOW basetemp):
   pytest <7 s05 files> -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02c1-s05
   -> 41 passed, 41 warnings in 91.38s

5. S02 durable + persistence regressions:
   pytest tests/test_durable_job_persistence.py tests/test_persistence_bootstrap.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02c1-s02j
   -> 87 passed, 81 warnings in 39.72s

6. Ruff (18 changed files) -> All checks passed!
7. Mypy -> Success: no issues found in 86 source files
8. git diff --check -> exit 0 (pre-existing CRLF advisories only)
9. SAM2.1 GPU smoke (real inference) -> 1 passed in 7.88s (report above)
10. git status --short -> 150 entries = 147 (correction baseline) + 3 new
    files (migration f5a6b7c8d9e0, test_sam2_provider.py, test_sam2_smoke.py)
11. Protected data:
    MAIN channels.json SHA-256 (certutil):
      dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
      — IDENTICAL to the required value / T01-T02 records. UNCHANGED.
    MAIN data/motionforge.db: 311296 bytes — size UNCHANGED (mtime moved to
    2026-08-16 17:25; same observation as T01 — external no-op touch; size/
    schema/version verified unchanged, alembic head of MAIN db not touched
    by any test).
    MAIN git status: 57 entries (sprint progression by manager packets;
    no writes from this session).

## MANAGER VERIFICATION — T02 C1 (2026-08-17)

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW**

- Focused 45/45 (31.02s); SAM2 GPU smoke 1/1 (7.53s); T01+T03 61/61 (27.66s); S05 41/41 (90.85s); S02 durable 119/119 (67.24s); migration round-trip head f5a6b7c8d9e0 with object_role_artifact + indexes.
- Code audit: B1/B10 SAM2 in-worker GPU smoke PASS; B3 provider 422-rejected in request JSON; B4 real capability probe; B6 association migration; B7 content endpoint (ManagedRoot-only, allowlist, size/hash live check, ETag+304, nosniff, 404/409); B8 current lookup; B9 generation filtering.
- Protected unchanged (channels.json dd7aae…555, MAIN DB 311296 B, checkpoint read-only).

Decision: T02-C1 released; S08-T03 correction may open.


---

## CORRECTION ROUND C2 (Codex CHANGES_REQUESTED after C1, finding B follow-up:
BACKEND SOURCE AUTHORITY + PROVIDER GATE) — 2026-08-17

Same session continuation; fixes ONLY the C2 acceptance list (1-9).

### Changes made (code-only; migration head unchanged at f6a7b8c9d0e1)

1. `app/services/object_extraction.py`:
   - `_authoritative_source(session, workspace, video_item)` — the server
     resolves the CURRENT source artifact + SHA from durable state
     (video_item.source_artifact_id -> ready video Artifact with sha256);
     never trusts client input (acceptance 1).
   - `_authoritative_generation(session, video_item, sha)` — backend-derived
     CURRENT generation: reuses the generation of the newest COMPLETED job
     whose manifest sha equals the current source (idempotent identity);
     otherwise the next integer above the highest completed generation —
     NEVER silently "1" when the backend differs (acceptance 3).
   - `submit_discover_objects` reworked: client `source_sha256`/`generation`
     are ASSERTIONS ONLY; a mismatch raises `CODE_SOURCE_CONFLICT`
     (409) and NO Job row is created (acceptance 2).  Manifest and
     idempotency key ALWAYS use the backend-authoritative values
     (acceptance 4); `input_generation` uses the authoritative value.
   - `_verify_media_file(ctx, evidence)` — BEFORE inference AND on every
     replay the selected managed media FILE is verified against its
     Artifact row: ManagedRoot containment (PATH_CONTAINMENT on escape),
     file existence, size and SHA-256 (`CODE_MEDIA_CHANGED` on any
     mismatch — fail before inference, publish nothing; acceptance 5/6).
     Wired at the top of `_extract_phase` and at the end of
     `_verify_input_evidence` (replay path).  Input evidence now records
     `media_sha256`/`media_size_bytes` for row-level re-verification.
   - QA/provider gate (acceptance 7/8): `resolve_extraction_provider` raises
     `PROVIDER_UNAVAILABLE` for `deterministic`/`deterministic-identity`
     unless the runtime declares genuine QA mode
     (`MOTIONFORGE_EXTRACTION_QA_MODE=1` — the marker accompanies the
     isolated-root fixtures).  Enforced for BOTH env-var and internal-caller
     selection.  The submit records `manifest["qa_mode"]` as the runtime
     policy snapshot; the worker re-resolves the recorded provider with the
     SAME authorization (never stronger/weaker at run time).
   - New stable codes `CODE_SOURCE_CONFLICT` (409) + `CODE_MEDIA_CHANGED`,
     with Vietnamese suggested actions, exported in `__all__`.
2. `app/schemas/object_extraction.py`: `source_sha256`/`generation` fields
   documented as ASSERTIONS ONLY; `generation` no longer defaults to "1"
   at the schema level.
3. `app/api/routes/object_extraction.py`: `CODE_SOURCE_CONFLICT` mapped to
   409; submit docstring documents the backend-authority semantics.
4. Tests:
   - Focused suite: seeds now write a REAL managed media payload
     (`SOURCE_MEDIA_BYTES`, `SOURCE_SHA = sha256(payload)`); `_submit`
     omits client hints (server-authoritative) and passes the QA marker;
     `_replace_source` helper advances the backend source/generation.
     New tests: spoof generation rejected, spoof source sha rejected,
     omitted sha resolves authoritatively, replaced source uses backend
     sha + advanced generation, media tampered after submit fails with
     MEDIA_CHANGED before inference (zero roles/artifacts/associations),
     production deterministic rejection (no Job), QA deterministic success.
     Provider-resolution test extended: non-QA deterministic +
     deterministic-identity => PROVIDER_UNAVAILABLE; QA mode resolves.
   - API suite: `_qa_policy` declares QA mode; seeds write real media;
     generation-filtering test advances gen-2 via source replacement;
     new API tests: spoof generation/sha => 409 no Job, omitted sha
     succeeds with authoritative source, media tamper fails closed.
   - Wiring test: subprocess runner declares QA mode, writes the real
     managed media file at the service-root/artifacts convention, computed
     SOURCE_SHA; published-file count 5 -> 6 (source media now under the
     managed root).
   - Correction suite (T05): `_seed_discover_artifacts` submits with the QA
     marker; `_seed_video` writes the real managed media file; SOURCE_SHA
     derived from the real payload.

### Validation — exact commands and results (fresh isolated roots, `-p no:cacheprovider`, shallow basetemps `s08t02-c2-*`)

```
1. Focused T02-C2 (new/corrected tests):
   pytest tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-c2-all
   -> 56 passed, 107 warnings in 44.10s

2. T01-T05 combined regression:
   pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
     tests/test_object_correction.py tests/test_object_correction_api.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t02-c2-reg10
   -> 115 passed, 209 warnings in 58.56s (after C2 fixes: 45 passed in corr2 run)
   Final combined with focused + SAM2 + wiring:
   pytest <7 files> -q -p no:cacheprovider --basetemp=...s08t02-c2-final
   -> 103 passed, 228 warnings in 84.35s

3. R01 suites:
   pytest tests/test_s08_r01_queued_cancel_lifecycle.py \
     tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider \
     --basetemp=...s08t02-c2-r01
   -> 18 passed, 18 warnings in 6.19s

4. Migration round-trip via MOTIONFORGE_DATABASE_URL (subshell; unset after):
   upgrade head -> f6a7b8c9d0e1 / downgrade f5a6b7c8d9e0 / upgrade head -> OK
   final head f6a7b8c9d0e1; object_role_artifact present; ROUND TRIP OK
   env unset verified: <unset>

5. S05 41-suite (shallow basetemp ...s08t02-c2-s05):
   -> 41 passed, 81 warnings in 95.40s
   S02 durable + persistence regressions (...s08t02-c2-s02):
   -> 87 passed, 162 warnings in 41.78s

6. Ruff (7 changed files): All checks passed!
7. Mypy: Success: no issues found in 86 source files
8. git diff --check -> exit 0 (pre-existing CRLF advisories only)
9. Final git status --short -> 161 entries (C2 changed existing files only;
   no new files, no strays; +1 vs session start is a manager packet file)
10. Protected data:
    MAIN channels.json SHA-256 (certutil):
      dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
      — IDENTICAL to the required value. UNCHANGED.
    MAIN data/motionforge.db: 311296 bytes — UNCHANGED.
    SAM2.1 checkpoint: 898083611 bytes, SHA-256
      2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
      — IDENTICAL to the required value; read-only, never touched.
    MAIN git status: 64 entries (manager sprint progression; no session writes).
```

### Deviations / honest notes (C2)

1. No schema migration was needed for C2 (code-only hardening); the
   migration round-trip re-validates the existing chain at head
   f6a7b8c9d0e1.
2. The focused/API/correction/wiring suites now seed a REAL managed media
   payload because the C2 media gate verifies the actual file; `SOURCE_SHA`
   constants were re-derived from the real payload bytes (identical
   assertions semantics — the value is computed, not a magic string).
3. The generation semantics changed by design (acceptance 3): a same-source
   resubmit is IDEMPOTENT (reuses the completed job); a NEW generation is
   only created when the backend source advances (replaced artifact).  The
   two generation-filtering tests were updated to advance the source.
4. Worker-side provider re-resolution uses the manifest `qa_mode` snapshot
   so a QA-authorized job runs exactly as authorized at submit; a
   non-QA job can never resolve the QA-only adapters.
