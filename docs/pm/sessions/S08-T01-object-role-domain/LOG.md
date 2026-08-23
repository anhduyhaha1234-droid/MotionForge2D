# S08-T01 — Execution Log

Status: NOT_STARTED

Append-only. Record exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

---

## Baseline — 2026-08-05 23:59 (Hermes session 20260805_235138_61ad7a)

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
?? app/persistence/characters.py
?? app/schemas/characters.py
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
?? frontend/e2e/characters-library.spec.ts
?? frontend/e2e/fixtures/s05t05-corrupt.mp4
?? frontend/e2e/fixtures/s05t05-import-4s.mp4
?? frontend/e2e/fixtures/s05t05-import-60s.mp4
?? frontend/e2e/import-analyze-c04-r3-visual.spec.ts
?? frontend/e2e/import-analyze-c04-visual.spec.ts
?? frontend/e2e/import-analyze-visual.spec.ts
?? frontend/e2e/import-analyze.spec.ts
?? frontend/e2e/pack-publish-ux-visual.spec.ts
?? frontend/e2e/pack-publish-ux.spec.ts
?? frontend/e2e/s08-p00-import-analyze-visual.spec.ts
?? frontend/e2e/s08-p00-import-analyze.spec.ts
?? frontend/e2e/s08-p00-pack-publish-ux-visual.spec.ts
?? frontend/e2e/s08-p00-pack-publish-ux.spec.ts
?? frontend/playwright.s05-c04-r3-visual.config.ts
?? frontend/playwright.s05-c04-visual.config.ts
?? frontend/playwright.s05t05-visual.config.ts
?? frontend/playwright.s05t05.config.ts
?? frontend/playwright.s06t04.config.ts
?? frontend/playwright.s06t05.config.ts
?? frontend/playwright.s08-p00.config.ts
?? frontend/src/app/(app)/import-analyze/
?? frontend/src/components/ImportAnalyzePanel.tsx
?? frontend/src/lib/preflightErrors.ts
?? migrations/versions/d5e6f7a8b9c0_character_library_schema.py
?? tests/fixtures/legacy_import/corrupt/projects/
?? tests/fixtures/legacy_import/valid/projects/
?? tests/test_character_domain.py
?? tests/test_character_preset_importer.py
?? tests/test_character_read_api.py
?? tests/test_character_validator.py
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

All uncommitted changes are preserved untouched. No commit/push/reset/clean/checkout.

### Toolchain baseline

```
python 3.11.9 (C:/Users/Admin/AppData/Local/Programs/Python/Python311)
ruff 0.16.0
mypy 2.3.0
alembic 1.18.5
pytest 9.1.1
Migration head (pre-S08): d5e6f7a8b9c0 (character_library_schema)
```

### Plan (≤7 steps)

1. Add ObjectRole + ObjectOccurrence ORM models to app/persistence/models.py (stable UUID ids, workspace/project/video/source-generation ownership, FK constraints, confidence 0..1, status/review-state checks, revision CAS, timestamps, indexes).
2. Add one S08 migration (revision e7f8a9b0c1d2, down_revision d5e6f7a8b9c0) with working upgrade AND downgrade.
3. Implement app/persistence/object_intelligence.py repository/service: create/list/get/update roles (CAS + idempotency key), occurrence create/list (natural-key idempotency), fail-closed cross-owner validation, read-only legacy compatibility mapping (pure function, never writes legacy).
4. Implement app/schemas/object_intelligence.py DTOs + app/api/routes/object_intelligence.py under /api/v2/object-intelligence; register router in app/api/app.py (deps.py needs no change: SessionDep/get_project_workflow already exist).
5. Add focused tests tests/test_object_intelligence_domain.py: migration round-trip + existing-db upgrade, identity/ownership/constraints/CAS/idempotency/concurrency, GET zero-mutation, API contract, legacy mapping read-only.
6. Update stale exact-schema expectations in tests/test_persistence_bootstrap.py (S06_HEAD_TABLES → S08 head set, head revision d5e6f7a8b9c0 → e7f8a9b0c1d2) — required because the S08 migration legitimately changes head.
7. Validate: focused tests (cache disabled, output/s08-sprint/<run-id> basetemp), migration round-trip CLI, S01/S03/S05 regressions, ruff, mypy app, git diff --check, final git status. Append LOG evidence, write REPORT.md, status SUBMITTED.

### Protected state (pre-change)

- No channels.json / data/ / databases / MAIN tree / other worktrees touched.
- MAIN channels.json hash was verified by S08-P00 (DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555) — not re-touched by this session.

---

## RECOVERY — 2026-08-16 13:2x (same Hermes session 20260805_235138_61ad7a)

Provider interruption (HTTP 502 after retries) killed the first run after the
implementation files were written; an orphaned `codex exec` child from the
first attempt kept writing files until it was located and terminated
(`taskkill /PID 123296 /T /F` — the ONLY process killed; all other node/claude
processes were left untouched). All changes written before the interruption
were preserved and reviewed. This section records the completed recovery run.

### Hard worktree guard re-verified (2026-08-16, before any write)

- pwd = /c/Users/Admin/MotionForge2D-worktrees/s08-integration ✓
- git rev-parse --show-toplevel = C:/Users/Admin/MotionForge2D-worktrees/s08-integration ✓
- git branch --show-current = codex/s08-integration ✓
- git rev-parse HEAD = a43b20da742996bafcb2f9d1ac57b10d3f1a5204 ✓
- git status --short = 105 lines (baseline 100 + LOG.md + 4 in-scope files); no competing writer (verified no `codex exec` CLI process remained).

### Scope compliance

All T01 changes confirmed inside the TASK.md allowed write scope:
app/persistence/models.py, migrations/versions/e7f8a9b0c1d2_object_intelligence_schema.py,
app/persistence/object_intelligence.py, app/schemas/object_intelligence.py,
app/api/routes/object_intelligence.py, app/api/app.py (one import + one
include_router), tests/test_object_intelligence_domain.py (new focused tests),
plus the required exact-schema expectation updates in
tests/test_persistence_bootstrap.py and tests/test_durable_job_persistence.py
(the new S08 head/table set — mechanical expectation maintenance, same
precedent as S06). No deps.py change was needed (SessionDep +
get_project_workflow already exist). No frontend/legacy/protected files touched.

### Implementation incidents fixed during recovery

1. Routes/tests URL mismatch: tests used /api/v2/object-intelligence/roles as
   the collection; routes registered it at "" only. Added /roles + /roles/
   aliases to create_role and list_roles (kept "" + "/" too). Focused suite
   went 15/21 → 21/21.
2. Legacy-mapping 500: the test's legacy object payloads lacked the required
   SelectionInput "mode" field. Fixed test payloads (mode: bounding_box);
   also hardened map_legacy_objects against Pydantic enum kind values.
3. mypy (strict) 3 errors in routes: replaced Response-return hacks with the
   standard FastAPI `response: Response` status override (idempotent replay
   returns the DTO with 200) and typed the legacy-mapping DTO list with
   LegacyMappingItemData. mypy app → Success (75 files).
4. ruff E501 (2) in the test file after the mode fix → reformatted. ruff → All checks passed.

### Focused T01 suite (cache disabled, isolated basetemp)

Command:
```
python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/MotionForge2D-worktrees/s08-integration/output/s08-sprint/20260806-s08t01-r2/t01-focused
```
Result (first run):
```
21 passed, 22 warnings in 16.19s
```
Result (after route refactor, second isolated basetemp):
```
21 passed, 22 warnings in 8.90s
```

Coverage: migration round-trip upgrade→downgrade→upgrade; existing-database
upgrade preserves rows (workspace/project/video/scene/character); constraint
enforcement (FK, confidence 1.5, invalid review_state, duplicate natural key);
stable UUID identity + defaults; cross-owner project/scene rejection
(OwnershipMismatchError); role CAS stale-revision conflict + success bump;
status transitions (suggested→confirmed→superseded with target; superseded
terminal; superseded-without-target rejected); idempotent role create by
idempotency key; idempotent occurrence create by (role, scene, frame) natural
key; concurrent create same key → single row; concurrent CAS update
last-writer-wins; GET operations zero durable mutations (revision snapshots);
legacy mapping pure read-only (ephemeral uuid ids, never persisted); API CRUD
+ CAS (409 stale), API idempotency (201→200 same id), API cross-owner 409,
API GET zero-mutation, API legacy-mapping read-only (project.json byte-identical
after GET).

### Migration verification (fresh temp DB under the run dir)

Command sequence:
```
export MOTIONFORGE_DATABASE_URL="sqlite:///.../output/s08-sprint/20260806-s08t01-r2/migration.db"
python -m alembic upgrade head        # full chain -> e7f8a9b0c1d2
# seeded workspace+channel rows
python -m alembic downgrade d5e6f7a8b9c0
python -m alembic upgrade head        # again
```
Result:
- alembic_version: e7f8a9b0c1d2 (final)
- object tables present: ['object_occurrence', 'object_role']
- seeded rows preserved across downgrade/upgrade: channel ('ch1','C'), workspace ('ws1')
- role indexes: uq_object_role_workspace_idempotency, ix_object_role_video_status, ix_object_role_legacy_object, ix_object_role_supersedes
- occurrence indexes: ix_object_occurrence_role, ix_object_occurrence_scene, ix_object_occurrence_video_frame
- all CHECK constraints present in DDL: ck_object_role_{status,kind,name_len,source_generation_nonempty,source_generation_len,idempotency_key_len,revision_positive}; ck_object_occurrence_{frame_index_nonneg,time_ms_nonneg,bbox_x/y/w/h_nonneg,confidence_range,confidence_source,review_state,algorithm_len,algorithm_version_len,revision_positive}
- FKs: object_role → workspace/project/video_item + self supersedes; object_occurrence → workspace/project/video_item/object_role(CASCADE)/scene(RESTRICT)
- UNIQUE(role_id, scene_id, frame_index) present

### S05 production-wiring failure — honest classification (NOT a T01 regression)

Observed: `test_default_production_wiring_chain_completes_and_resumes` failed
twice when run with deep basetemps under
`output/s08-sprint/<run-id>/...` — ANALYZE_MEDIA job failed INPUT_UNREADABLE:
"failed reading source during copy: [Errno 2] No such file or directory:
'...artifacts\staging\<job>\import\.cfr_cut.mp4.<uuid>.staging'".

Root cause (proven, not assumed):
- The failing staging path is 271 characters — above the Windows MAX_PATH
  limit (260). Standalone reproduction of the exact same operation at the
  same depth:
  ```
  path len: 271
  OPEN FAILED: [Errno 2] No such file or directory: '...import\\.cfr_cut.mp4...staging'
  ```
  — byte-identical error to the job failure. The S05 test creates a
  pristine/artifacts/staging/<job>/import/... chain; the deep sprint basetemp
  pushes the managed staging path over MAX_PATH, and `open("xb")` in
  ManagedRoot.atomic_write_stream fails with ENOENT.
- The P00 quality run used a shallow basetemp and passed (41/41 S05).

Fresh verification (two runs, NEW shallow basetemps under AppData/Local/Temp):
```
python -m pytest tests/test_s05_production_wiring.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-s05-wiring-run1
1 passed in 23.66s
python -m pytest tests/test_s05_production_wiring.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-s05-wiring-run2
1 passed in 24.38s
```
Classification: observed transient regression-harness/runtime incident caused
by basetemp path depth (Windows MAX_PATH), NOT a T01 schema/router regression.
No S05 code was modified. Evidence recorded verbatim below.

### S05 preservation suite (shallow basetemp)

```
python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
  tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
  tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
  tests/test_s05_golden_integration.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-s05-suite
41 passed, 41 warnings in 83.09s (0:01:23)
```
(Parity with the P00 Codex rerun: 41/41 in 82.10s.)

### Persistence/project/video regressions

```
python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
  tests/test_project_crud.py tests/test_video_item_crud.py -q -p no:cacheprovider \
  --basetemp=.../output/s08-sprint/20260806-s08t01-r2/reg-persistence
160 passed, 154 warnings in 54.24s
```
Includes the updated S08 exact-schema expectations (S08_HEAD_TABLES, head
revision e7f8a9b0c1d2, object_role/object_occurrence in
test_no_worker_or_api_cutover_tables).

### Static gates

```
python -m ruff check <9 changed python files>   -> All checks passed!
python -m mypy app                              -> Success: no issues found in 75 source files
git diff --check                                -> exit 0 (pre-existing CRLF advisories only)
```

### Protected state (re-verified 2026-08-16)

- MAIN channels.json SHA-256 (certutil):
  dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
  == DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555 ✓ (unchanged)
- MAIN data/motionforge.db: size 311296 bytes ✓; read-only inspection
  (sqlite3 URI mode=ro): alembic_version = d5e6f7a8b9c0, 17 tables,
  object_role ABSENT → S08 migration NEVER ran on MAIN; content preserved.
  NOTE: file mtime is 2026-08-06 00:15:10 local, differing from the P00
  reference mtime 2026-08-04 18:24:36. Size/schema/version are unchanged;
  the mtime delta appears to be a no-op open/touch by an external process
  (worktree alembic.ini intentionally sets NO sqlalchemy.url, so no migration
  can run without an explicit URL). Recorded as an observed stat deviation
  with content-preservation evidence.
- MAIN git status = 46 entries (P00 reference 45): the +1 is
  scripts/watch-s08-t01.sh (sprint launcher artifact, not created by this
  session). S06 tree s06-t01-review = 45 (unchanged).
- No commit/push/reset/checkout/restore/clean/stash/delete was executed.
- No channels.json, data/, database, fixture, backup or old evidence was
  modified by this session.

### Run artifacts (isolated, under output/s08-sprint/)

- output/s08-sprint/20260806-s08t01-r1/ (first attempt; migration.db + basetemps)
- output/s08-sprint/20260806-s08t01-r2/ (recovery: migration.db, t01-focused,
  t01-focused2, reg-persistence)
- Shallow S05 runs under C:/Users/Admin/AppData/Local/Temp/s08t01-s05-*

---

## CORRECTION ROUND C1 — 2026-08-16 (Codex CHANGES_REQUESTED; same Hermes session 20260805_235138_61ad7a)

Manager supplied 5 findings. Guard re-verified before any write (pwd/toplevel/branch/HEAD all match; status 105 lines). All changes remain inside the TASK.md allowed write scope (same 9 files + packet LOG/REPORT). PM_REVIEW.md untouched. No commit/destructive operations. Run root: `output/s08-sprint/20260816-s08t01-c1/`.

### F1 — Occurrence route ownership (fail closed)
- `app/persistence/object_intelligence.py`: `get_occurrence` and `update_occurrence` now REQUIRE `role_id`; lookups are scoped by (id, workspace_id, role_id); a role-A caller targeting a role-B occurrence gets OccurrenceNotFoundError (404 — no existence leak, no update).
- `app/api/routes/object_intelligence.py`: PATCH occurrence passes the path `role_id` to the repository (the `del role_id` discard was removed).
- Tests: `test_occurrence_role_mismatch_read_fails_closed`, `test_occurrence_role_mismatch_update_fails_closed`, `test_api_role_a_url_cannot_read_or_update_role_b_occurrence` (role-B list excludes role-A occurrence; role-B URL PATCH on role-A occurrence -> 404; occurrence untouched).

### F2 — Supersession ownership/validity
- `update_role`: when transitioning to `superseded`, `_validate_supersession_target` rejects: missing target, cross-workspace, cross-project, cross-video-item, cross-source-generation, self-reference, and terminal (already-superseded) targets — all as stable `RoleConflictError` -> 409.
- Tests: `test_supersession_cross_workspace_rejected`, `test_supersession_cross_project_rejected`, `test_supersession_cross_video_rejected`, `test_supersession_cross_generation_rejected`, `test_supersession_self_rejected`, `test_supersession_terminal_target_rejected`. Existing `test_status_transitions` updated so the supersession target shares the same source generation (the previous "g" vs "gen-1" fixture now correctly conflicts).
- Codex-reproduced cross-workspace supersession now raises RoleConflictError (verified by the cross-workspace test).

### F3 — Real atomic CAS
- `update_role` and `update_occurrence` no longer read-compare-write: both execute a single `UPDATE ... WHERE id = ? AND workspace_id = ? [AND role_id = ?] AND revision = ?` with `revision = revision + 1`, requiring exactly one affected row (`.returning()` / `scalar_one()`); zero rows => RoleConflictError (fresh revision fetched with `populate_existing` for an accurate message). Domain validations (terminal check, supersession target) happen before the atomic predicate; the write decision is the DB predicate.
- Genuine concurrency test `test_concurrent_cas_atomic_exactly_one_writer_wins`: two THREADS, separate engines/sessions over the same SQLite file, both read revision 1, `threading.Barrier` synchronizes them, both attempt the CAS with expected revision 1; exactly one commits ("ok"), the other receives RoleConflictError ("conflict"); final revision == 2. Stable across 5 consecutive runs (1 passed each).
- Occurrence mutations use the same atomic predicate (scoped by role too).

### F4 — Idempotency collision semantics
- `create_role` (idempotency key) and `create_occurrence` (natural key) replay ONLY an equivalent canonical request: `_assert_equivalent_role_request` compares project_id, video_item_id, source_generation, name, kind, status, description, legacy refs; `_assert_equivalent_occurrence_request` compares time_ms, bbox, confidence, confidence_source, algorithm, algorithm_version, reasons, review_state. A materially different payload with a reused key raises RoleConflictError / OccurrenceConflictError (409) — never a replay of another resource. Applies on the direct-hit path AND the concurrent IntegrityError path.
- Routes: `create_role` now maps RoleConflictError -> 409; `create_occurrence` maps OccurrenceConflictError -> 409.
- Tests: `test_idempotency_key_different_project_conflict`, `test_idempotency_key_different_generation_conflict`, `test_idempotency_key_different_payload_conflict`, `test_occurrence_natural_key_different_payload_conflict`, `test_api_idempotency_collision_conflict` (same key different project -> 409; same natural key different confidence -> 409). Equivalent replay tests unchanged and still green (201 -> 200 same id).

### F5 — preservation
- No assertions weakened, no skips/ignores added. Migration round-trip, read-only GET zero-mutation, stable UUID identity, source supersession, S05 lifecycle and S06 behavior all re-verified (below).

### Validation — exact commands and verbatim results (cache disabled, isolated basetemps)

1. Focused suite (new isolated basetemps under output/s08-sprint/20260816-s08t01-c1/):
   `python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=.../focused4`
   -> `36 passed, 37 warnings in 16.52s`
   Final re-run after B904 fix: `36 passed, 37 warnings in 13.95s`
   Genuine concurrent CAS stability (5 fresh basetemps):
   `1 passed` x5 (2.39-2.42s each)
2. Migration CLI round trip (fresh temp DB output/s08-sprint/20260816-s08t01-c1/migration.db):
   `python -m alembic upgrade head` -> full chain incl. `d5e6f7a8b9c0 -> e7f8a9b0c1d2`
   `python -m alembic downgrade d5e6f7a8b9c0` -> `e7f8a9b0c1d2 -> d5e6f7a8b9c0`
   `python -m alembic upgrade head` -> `d5e6f7a8b9c0 -> e7f8a9b0c1d2`
   verify: version `e7f8a9b0c1d2`; tables `['object_occurrence','object_role']`; seeded `ws1` preserved.
3. Persistence/project/video regressions:
   `python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py tests/test_project_crud.py tests/test_video_item_crud.py -q -p no:cacheprovider --basetemp=.../reg-persistence`
   -> `160 passed, 154 warnings in 53.97s`
4. Complete S05 targeted suite (SHALLOW basetemp, Windows MAX_PATH lesson):
   `python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-c1-s05`
   -> `41 passed, 41 warnings in 84.18s (0:01:24)`
5. Ruff on all changed Python files -> `All checks passed!` (B904 fixed with `raise ... from None`)
6. Mypy: `python -m mypy app` -> `Success: no issues found in 75 source files`
7. `git diff --check` -> exit 0 (pre-existing CRLF advisories only)
8. `git status --short` -> 105 entries (unchanged scope; no new files)
9. Protected data (read-only): MAIN channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (== DD7AAE...55EB555, unchanged); MAIN data/motionforge.db 311296 bytes (unchanged).

## MANAGER VERIFICATION — 2026-08-16 (C1 correction round)

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence (re-run by manager, not worker):
- `python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-mgr-focused` -> **36 passed** in 13.81s
- S05 41-suite shallow basetemp `C:/Users/Admin/AppData/Local/Temp/s08t01-mgr-s05` -> **41 passed** in 81.72s
- Persistence regressions `s08t01-mgr-reg` (test_persistence_bootstrap + test_durable_job_persistence + test_project_crud + test_video_item_crud) -> **160 passed** in 53.45s

Codex findings verification (code audit by manager):
1. F1 route ownership: PATCH route binds role_id and repo.update_occurrence asserts exact role+workspace ownership; tests `test_api_role_a_url_cannot_read_or_update_role_b_occurrence`, `test_occurrence_role_mismatch_read_fails_closed`, `test_occurrence_role_mismatch_update_fails_closed` PASS.
2. F2 supersession: `_validate_supersession_target` rejects self-ref, missing/cross-workspace, terminal target, cross-project, cross-video, cross-generation; 6 dedicated tests PASS.
3. F3 atomic CAS: UPDATE ... WHERE id + workspace_id + revision, scalar_one (NoResultFound -> RoleConflictError); `test_concurrent_cas_atomic_exactly_one_writer_wins` (genuine two-writer sync) PASS.
4. F4 idempotency collision: replay requires `_assert_equivalent_role_request`; different project/video/generation/payload -> 409; 5 dedicated tests PASS.
5. F5 preserve: migration round-trip PASS, 160/160 persistence regressions PASS, S05 41/41 PASS, no skips/ignores.

Scope audit (C1 window mtimes 13:40-14:00): only app/api/routes/object_intelligence.py, app/persistence/object_intelligence.py, tests/test_object_intelligence_domain.py modified — all in allowed scope. INTEG count 105 unchanged after C1. Writer exited (exit 0) before this review.

Protected state (manager re-verified): MAIN channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED; MAIN data/motionforge.db 311296 bytes; S06 worktree 45 entries unchanged.

Decision: T01 dependency released for S08-T02 under full-sprint manager protocol.

---

## CORRECTION ROUND C2 — 2026-08-16 (Codex CHANGES_REQUESTED at sprint exit; finding: CURRENT-GENERATION ROLE LISTING; same Hermes session 20260805_235138_61ad7a)

Guard re-verified before any write (pwd/toplevel/branch/HEAD all match; status 161 entries — intentional dirty sprint base). T02-C2 (backend source authority) and T03-C2 corrections are in tree; this round implements T01-C2 using the backend-authoritative current generation. Files touched stay inside the T01 allowed scope (persistence/schemas/routes + focused tests) plus REQUIRED fixture alignment in three sibling test files (each documented below; no assertion weakened). No migration (head remains f6a7b8c9d0e1). PM_REVIEW.md / TASK.md untouched. Run roots: output/s08-sprint/20260816-s08t01-c2/ + C:/Users/Admin/AppData/Local/Temp/s08t01-c2-*.

### Acceptance 1-7 — implementation and evidence

1. Public role list defaults to ONLY current-generation roles: `list_roles` gains `source_generation` (exact explicit view) + `only_current` (default). The route resolves the backend current generation and returns ONLY those roles (`scope="current"`). Evidence: `test_api_list_defaults_current_generation_historical_explicit`, `test_list_roles_current_only_and_explicit_generation` (incl. cross-video no-filter case resolved per role's own video).
2. Source replacement 1->2 hides gen-1 roles: `current_generation` is backend-authoritative (video.source_artifact_id -> artifact sha256; newest COMPLETED DISCOVER_OBJECTS job whose manifest source sha matches, else max completed generation + 1). After a source advance, gen-1 roles drop out of the default list and surface ONLY via explicit `generation=1`. Evidence: `test_api_source_replacement_hides_generation1_roles`, `test_current_generation_advances_with_completed_jobs` (incl. a different-source job never advancing current).
3. Apply/correction on a stale role fails closed ZERO mutation: `update_role` and `update_occurrence` enforce `_assert_role_current` BEFORE any write (RoleConflictError -> 409; revision/name unchanged). Evidence: `test_stale_role_update_fails_closed_zero_mutation`, `test_stale_role_occurrence_update_fails_closed`, API `test_api_stale_role_detail_and_patch_fail_closed`, plus the golden path where a stale-correction post-replacement is rejected. SCOPE NOTE: `create_occurrence` (evidence CREATION) is NOT a stale-op — it is the T02 extraction pipeline's contract (the worker attaches evidence to the roles it created in the current run), so it stays unguarded (see REPORT deviations).
4. Historical inspection is an explicit separate contract: `GET /roles?generation=N` is the ONLY way to view a non-current generation; response carries `scope="current"|"historical"` + `current_generation`; current and historical results are never mixed. Role detail is 404 under the current scope unless an explicit matching `generation` is supplied. Evidence: `test_get_role_current_scope_and_explicit_historical`, API tests above.
5. List/detail filter by the explicit current source generation: the route resolves the current generation server-side (never from client hints) and applies it as the default filter; `current_generation` is echoed in the response for client assertions.
6. Stable role IDs remain the identity authority: identities are unchanged; the current-gen filter is by generation value, never by name/index. The T01-C1 guarantees (read-only GET, atomic CAS, idempotency equivalence, ownership, concurrency) are untouched and re-verified by the full focused suite (45 tests).
7. Repository + API tests for source replacement / current-only listing: 8 new focused tests (C2-A..C2-D section: 2 resolver, 2 list/detail scope, 2 stale-mutation, 3 API) — 45 total in tests/test_object_intelligence_domain.py.

### Required sibling fixture alignment (disclosed; no assertions weakened)

- `tests/test_object_correction.py` `_seed_source_job`: the completed DISCOVER_OBJECTS manifest now carries `source_sha256=SOURCE_SHA` so the backend authority links the gen-1 job to the video's real source artifact (roles gen-1 are genuinely current). Without this the fixture was internally inconsistent with T02-C2 authority (current resolved to "2" while roles were "1").
- `tests/test_object_correction_api.py` `_seed_video` + `_seed_source_job`: added the real source video Artifact (SOURCE_SHA constant) and the matching manifest sha, same reason.
- `tests/test_object_grouping.py`: generation fixtures normalized from the non-canonical `"gen-1"`/`"gen-2"` labels to the authoritative numeric `"1"`/`"2"` (distinctions preserved; the T01 PATCH-role path and my current-gen default now recognize them). No assertion changed.
- My own T01 tests: generation helper strings normalized `"gen-1"->"1"`, `"g"->"1"`, `"gen-2"->"2"` for the same canonical namespace (C1 fixtures used non-numeric labels).

### Validation — exact commands and verbatim results (fresh isolated roots, cache disabled, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08t01-c2-*)

1. Focused T01-C2: `python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=...s08t01-c2-focused6` -> `45 passed, 91 warnings in 24.36s` (final re-run: 45 passed in 24.24s)
2. T01-T05 combined regression (6 files): `python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_correction.py tests/test_object_correction_api.py -q -p no:cacheprovider --basetemp=...combined5` -> `181 passed, 333 warnings in 99.81s`
3. R01 suites (2 files): `python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py tests/test_s08_r01_root_resolution.py -q ...` -> `18 passed, 18 warnings in 6.26s`
4. Migration round-trip to head f6a7b8c9d0e1 (isolated subshell, env unset after):
   `alembic upgrade head` (10 upgrades) / `alembic downgrade f5a6b7c8d9e0` / `alembic upgrade head` -> version `f6a7b8c9d0e1`; object_role/object_occurrence/object_grouping_suggestion/object_correction/object_role_artifact tables present; parent-shell `MOTIONFORGE_DATABASE_URL` verified unset after.
5. S05 41-suite (shallow basetemp): `41 passed, 81 warnings in 94.28s`. S02 durable regressions (test_durable_job_persistence + test_durable_job_api): `63 passed, 121 warnings in 38.69s`.
6. Ruff (7 changed files): `All checks passed!` (SIM102 combined, I001 imports moved to top, E501 broken). Mypy: `Success: no issues found in 86 source files`. `git diff --check`: exit 0. Final `git status --short`: 161 entries (no new files, no stray artifacts).
7. Protected data (read-only): MAIN channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (UNCHANGED); MAIN data/motionforge.db 311296 bytes, alembic_version `d5e6f7a8b9c0` (no object_role — S08 migration never ran on MAIN); SAM2.1 checkpoint 898083611 bytes, SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (UNCHANGED, read-only).
