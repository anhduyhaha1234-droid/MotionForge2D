# S08-T05 — Targeted Object Correction and Recompute: Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager/Codex sprint-exit review owns approval)
**Hermes session:** `20260816_185020_83fd62` (fresh S08-T05 worker session)
**Started:** 2026-08-16 18:50
**Submitted:** 2026-08-16
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-T04 manager-verified (`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`)

## Outcome

Object corrections invalidate and recompute ONLY the affected dependencies
while preserving approved/unaffected roles, occurrences and artifacts.  An
explicit dependency/invalidation graph was defined BEFORE implementation
(packet `DESIGN.md` — normative for the repository, the durable
RECOMPUTE_OBJECTS job, the API and every test).  Every correction kind
(merge / split / reassign / candidate edit) reports its exact impacted scope
through a read-only preview BEFORE confirmation, then applies the targeted
mutation + supersedes exactly the invalidated pending suggestions + archives
the old affected mapping in ONE transaction — creating the durable
`RECOMPUTE_OBJECTS` Job ONLY where the impact says recompute is needed.
Unaffected rows and files remain byte/hash identical (proven by full-row
snapshots and per-file SHA-256).  Retry/idempotency, concurrent corrections,
restart, cancel and orphan cleanup follow the durable job contracts; the
gallery UI shows the scope report in the confirmation dialog, the recompute
progress and the honest terminal outcome (failure → explicit retry that
creates the successor Job; the applied mutation is never undone).

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `docs/pm/sessions/S08-T05-targeted-correction/DESIGN.md` | NEW — the dependency/invalidation graph (nodes, edges, per-kind invalidation rules, preservation invariant, recompute-needed decision, durable contracts) written BEFORE implementation |
| `migrations/versions/f4a5b6c7d8e9_object_correction_schema.py` | NEW reversible migration (down `f3a4b5c6d7e8`): `object_correction` table (type/status CHECKs, RESTRICT FKs incl. `recompute_job_id`→job, natural-key + idempotency partial-unique indexes, lookup indexes) |
| `app/persistence/models.py` | +`ObjectCorrection` ORM, +`OBJECT_CORRECTION_TYPES`/`OBJECT_CORRECTION_STATUSES`, `__all__` entries |
| `app/persistence/object_correction.py` | NEW repository: `compute_impact` (PURE read — exact affected/invalidated/artifact sets + recompute-needed decision), `create_correction` (content-derived natural key; equivalence-checked replay; IntegrityError race backstop), `confirm_correction` (atomic CAS `pending→applied`; ONE txn = targeted mutation via T01/T03 CAS semantics + suggestion supersession + result archive + RECOMPUTE job only where needed; split's created role joins the recompute scope at confirm), `cancel_correction` (pending CAS; state-idempotent), `create_recompute_successor` (§6.4, idempotent), `recompute_state` (successor-chain walk), list/get. Reads use `populate_existing` SELECTs — raw `UPDATE…RETURNING(id)` identity-map staleness and the `refresh()` child-expiry cascade are both avoided (see LOG). |
| `app/services/object_correction.py` | NEW: the `RECOMPUTE_OBJECTS` durable job — input fingerprint (affected roles + occurrence geometry) → recompute (regenerate ONLY pairs containing an affected role via the real T03 algorithm; regenerate ONLY affected DISCOVER-candidate artifacts via the real T02 deterministic helpers) → stage → publish (ONE transaction: artifact rows + owners + suggestion rows + manifest); checkpoint resume (metadata-only plan — no bytes in checkpoints), cancel observed at every phase, staging GC of own + predecessor partials, output_validator (row/file re-verification + no-orphan gate + staging drained — `completed` is impossible with a partial/orphan set); `register_recompute_objects_handler`; test synchronization seam `PHASE_HOOK` (None in production) |
| `app/schemas/object_correction.py` | NEW DTOs: `CorrectionRequest` (kind-selected field sets, `role_kind` alias), `ImpactData`, `CorrectionData` (+`RecomputeStateData`), `CorrectionCreateResponse`, list/confirm/cancel requests |
| `app/api/routes/object_correction.py` | NEW router `/api/v2/object-intelligence/corrections`: `POST /preview` (ZERO writes), `POST /` (create pending, 201/200 replay), `POST /{id}/confirm` (201/200), `GET /{id}`, `GET /`, `POST /{id}/cancel` (pending CAS / applied → durable JobService cancel), `POST /{id}/recompute/retry` (successor Job). Error mapping 404/409/422/503; rollback before raise |
| `app/api/app.py` | one import + one `include_router` line |
| `app/workflow/job_service.py` | `register_recompute_objects_handler(self._worker)` at construction (minimal registration, same pattern as the S05/S08 handlers) |
| `frontend/src/lib/api.ts` | APPENDED S08-T05 types + functions: `previewCorrection`, `createCorrection`, `confirmCorrection`, `getCorrection`, `listCorrections`, `cancelCorrection`, `retryCorrectionRecompute` (typed against the real DTOs) |
| `frontend/src/components/object-gallery/CorrectionScope.tsx` | NEW: the impacted-scope report (rendered INSIDE the confirmation dialog) + the recompute strip (progress bar + honest terminal outcome + "Thử lại tính toán" successor retry). Every button has a Vietnamese helper line (11px, readable) |
| `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` | merge/split now run through the CORRECTION workflow (preview → scope dialog → create+confirm → recompute tracking); NEW reassign dialog (target selection + scope) and candidate-edit dialog (name/kind + scope); TanStack-query preview; durable recompute polling with terminal notices; honest 409 handling preserved |
| `frontend/src/components/object-gallery/RoleCard.tsx` | NEW per-occurrence evidence list with "Chuyển vai trò" (reassign correction) + "Sửa tên/loại" (candidate edit) actions, each with helper lines |
| `frontend/src/components/object-gallery/ConfirmDialog.tsx` | +optional `disabled` prop (required-selection gating without the busy label swap) |
| `tests/test_object_correction.py` | NEW focused suite — 30 tests (migration, exact impact sets + zero-mutation reads, natural-key idempotency + concurrency, reassign/merge/split/candidate-edit confirms with full-row immutability + file-hash immutability, collision/stale fail-closed zero-effects, replay, concurrent confirm exactly-one-winner, recompute restart at staging/commit boundaries, cancel during running drains with zero effects, pending/applied cancel, successor retry after cancel, stale-role fail-closed, orphan staging GC, corrupt-file replay failure, missing-correction failure, read-only GET zero mutations) |
| `tests/test_object_correction_api.py` | NEW API suite — 9 tests (preview zero-writes, create/confirm flow + 200 replay, recompute job completes through the real worker, stale 409, 422/404 mapping, pending cancel, applied cancel → durable job cancel, successor retry, list/get zero mutations) |
| `frontend/e2e/s08-t05-correction.spec.ts` | NEW desktop suite — 5 tests (scope-before-confirmation with disabled gating, candidate edit, suggestion merge + recompute strip terminal, split, Escape = zero mutations) |
| `frontend/e2e/s08-t05-correction-mobile.spec.ts` | NEW 390px suite — 3 tests (no horizontal overflow; correction dialog + scope within the viewport) |
| `frontend/e2e/s08-t05-correction-visual.spec.ts` | NEW visual QA — 2 screenshot tests (desktop gallery + scope dialog; 390px scope dialog) |
| `frontend/playwright.s08t05.config.ts` | NEW Playwright config (desktop + mobile-390px, isolated output) |
| `tests/test_object_extraction.py`, `tests/test_object_grouping.py`, `tests/test_object_intelligence_domain.py`, `tests/test_persistence_bootstrap.py`, `tests/test_durable_job_persistence.py` | required head-revision/table-set expectation updates (`f3a4b5c6d7e8`→`f4a5b6c7d8e9`, +`object_correction`) — T02/T03 precedent |
| `docs/pm/sessions/S08-T05-targeted-correction/LOG.md` | baseline + implementation + validation (append-only, real evidence) |
| `docs/pm/sessions/S08-T05-targeted-correction/REPORT.md` | this report |

No changes to: deps.py, S05/S06 contracts, legacy object code, TASK.md, sprint
contract, PM_REVIEW.md, channels.json, data/, any database, fixtures, MAIN or
other worktrees.  `git status --short` = 137 entries (baseline 126 + exactly
11 new T05 files); no stray files.  `git diff --check` exit 0.

## Acceptance criteria — evidence

| AC | Evidence |
|---|---|
| Explicit dependency/invalidation graph defined BEFORE implementation | `DESIGN.md` (packet) — nodes (R/O/S/A/Op/C/J'), edges (O→R, R→S, geometry→A, name→S), per-kind invalidation table (reassign / candidate_edit role / candidate_edit occurrence / merge / split), preservation invariant, recompute-needed decision, durable contracts for J'. Written first; the service/repo/job/tests cite it. |
| Merge/split/reassign/candidate correction reports its impacted scope BEFORE confirmation | `POST /preview` is a PURE read (`test_impact_reassign_exact_sets_and_zero_mutations`, `test_api_preview_reports_scope_without_writes` — full-row snapshots identical after); the gallery renders `CorrectionScope` inside the confirmation dialog before the mutation (E2E t01/t02/t03/t04 + mobile m2 + visual v1/v2). E2E t01: the confirm button is DISABLED until the target selection is made, then the scope shows the exact affected sets. |
| Creates durable successor/recompute work ONLY where needed | `compute_impact.recompute_needed = invalidated pending suggestions non-empty OR any affected role has a DISCOVER `source_job_id`; `test_recompute_needed_only_where_needed` + `test_confirm_no_recompute_when_not_needed` (no suggestions, no candidates → NO job row; correction completes synchronously). `test_confirm_candidate_edit_role_and_occurrence`: a name edit creates the job for suggestion regeneration ONLY — zero IMAGE artifact rows (geometry unchanged). |
| Old affected state superseded/archived | reassign: occurrence re-pointed with content untouched, old mapping archived in `result_json` (`from_role_id`/`to_role_id`); invalidated suggestions → status `superseded`, `natural_key=NULL`; merge sources → T03 superseded lineage; split original stays terminal. Nothing is ever deleted. |
| Unaffected rows/files remain byte/hash identical | `test_confirm_reassign_moves_evidence_and_preserves_unaffected`: full-row snapshots (roles/occurrences/suggestions/artifacts) before/after — every unaffected row byte-identical (revision/status/content); per-file SHA-256 of the managed artifact tree — every pre-existing file byte-identical; new files only under the recompute job's own path. `test_confirm_candidate_edit_occurrence_bbox_recomputes_artifacts`: old DISCOVER artifacts keep their exact sha256 + `ready` state. |
| Retry/idempotency, concurrent corrections, restart, cancel, orphan cleanup follow durable job contracts | `test_create_pending_natural_key_replay`, `test_concurrent_create_single_row` (barrier, exactly one row), `test_confirm_replay_returns_same_result_no_second_mutation`, `test_concurrent_confirm_exactly_one_wins`, `test_recompute_restart_at_staging_boundary_no_duplicates`, `test_recompute_restart_at_commit_boundary_no_duplicates`, `test_cancel_during_recompute_drains_with_zero_effects` (REAL worker + PHASE_HOOK sync seam), `test_cancel_pending_and_confirm_after_cancel_conflict`, `test_retry_recompute_after_cancel_successor_completes` (predecessor immutable, exactly one successor), `test_orphan_staging_partials_cleaned_on_rerun` (own partials GC'd, foreign untouched), `test_corrupt_recompute_artifact_fails_replay`, `test_missing_correction_row_fails_recompute`, `test_recompute_stale_roles_fail_closed` (newer correction → `ROLE_CHANGED`, honest failure). API mirrors: `test_api_confirm_creates_recompute_job_and_completes`, `test_api_cancel_applied_cancels_recompute_job`, `test_api_retry_recompute_successor`. |
| UI shows confirmation, progress, terminal outcome and honest recovery | Confirmation dialog with the scope report (E2E t01–t04); recompute strip with real progress + `Hoàn tất` terminal (E2E t01/t03); failure path renders the job error + "Thử lại tính toán" (successor Job — never re-applies the mutation); cancel outcome stated; 409 → conflict banner + refetch (T04 test 08/12 still pass). |

## Validation — exact commands and results

All pytest runs: `-p no:cacheprovider`, isolated shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t05-*` (Windows MAX_PATH lesson).
QA roots: `output/s08-sprint/20260816-s08t05-r1/backend-root` (fresh isolated
database; ports 8014/3012; deterministic extraction provider selected
explicitly via env — the production default path fails closed).

```
1. Focused S08-T05 (final run on the final code):
   python -m pytest tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-focused-final
   -> 39 passed, 40 warnings in 22.11s

2. Full S08 T01-T04 + T05 combined:
   python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py
     tests/test_object_extraction.py tests/test_object_extraction_api.py
     tests/test_object_extraction_production_wiring.py
     tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-t01t04-r1
   -> 135 passed, 126 warnings in 72.69s

3. S02 persistence/project/video regressions:
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py
     tests/test_project_crud.py tests/test_video_item_crud.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-s02-r1
   -> 160 passed, 154 warnings in 69.76s

4. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py
     tests/test_s05_golden_integration.py -q -p no:cacheprovider
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-s05-r1
   -> 41 passed, 41 warnings in 89.64s

5. S06 character regressions:
   python -m pytest tests/test_character_domain.py tests/test_character_preset_importer.py
     tests/test_character_read_api.py tests/test_character_validator.py
     tests/test_publish_rejection.py -q -p no:cacheprovider
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-s06-r1
   -> 90 passed, 90 warnings in 43.11s

6. Migration CLI round trip (fresh temp DB):
   MOTIONFORGE_DATABASE_URL=sqlite:///C:/Users/Admin/AppData/Local/Temp/s08t05-mgr-migration.db
   python -m alembic upgrade head -> downgrade f3a4b5c6d7e8 -> upgrade head
   -> version f4a5b6c7d8e9; object_correction present with all columns;
      job table intact.  Env var UNSET afterwards (verified empty).

7. Frontend gates (final code):
   cd frontend && npx tsc --noEmit                    -> exit 0
   npx eslint <api.ts, ObjectGalleryPanel, RoleCard,
     CorrectionScope, ConfirmDialog, 3 T05 e2e specs> -> 0 problems (exit 0)
   npm run build                                      -> Compiled successfully;
     /object-gallery static route; exit 0

8. Playwright — REAL isolated backend (desktop + 390px), final run:
   npx playwright test --config playwright.s08t05.config.ts
   -> 13 passed (44.3s)   [desktop 7/7 (incl. 2 visual); mobile-390px 6/6]
   Screenshots: output/s08-sprint/20260816-s08t05-r1/screenshots/
     desktop-gallery-correction-actions.png,
     desktop-correction-scope-dialog.png,
     mobile-390px-correction-scope-dialog.png

9. T04 regression re-run against the NEW correction UI (output overridden to
   the T05 run dir — T04 evidence untouched):
   npx playwright test --config playwright.s08t04.config.ts
     --output .../20260816-s08t05-r1/t04-regression-test-results
     e2e/s08-t04-object-gallery.spec.ts
   -> 13 passed (22.6s)  (plus the T04 mobile suite ran green inside the T05
   config run: 3/3)

10. Ruff (all changed Python files) -> All checks passed!
11. Mypy -> Success: no issues found in 86 source files
12. git diff --check -> exit 0 (pre-existing CRLF advisories only)
13. git status --short -> 137 entries (baseline 126 + 11 new T05 files), no strays
```

## Isolation and protected state

- All tests/runtime/migrations used NEW isolated roots and databases:
  pytest shallow basetemps, the CLI migration temp DB, and the fresh QA root
  `output/s08-sprint/20260816-s08t05-r1/backend-root` (migrations bootstrapped
  there by the app lifespan; the launcher sets MOTIONFORGE_ROOT/
  OUTPUT/MODELS inline so the default database can never be targeted).  The
  worktree `alembic.ini` still sets no URL.
- MAIN `channels.json` SHA-256 (certutil):
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — IDENTICAL to the T01–T04 recorded value. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes — UNCHANGED (T01–T04 baseline).
- MAIN git status: 50 entries (T04-era watcher scripts; unchanged).
- No commit/push/deploy/reset/checkout/restore/clean/stash/delete; all
  pre-existing uncommitted changes preserved.  QA servers on 8014/3012 were
  stopped after the runs (ports verified free).

## Deviations and risks

1. **Artifact supersession semantics.**  The Artifact state set (S02
   contract) has no "superseded" state, so old derived artifacts of an
   affected candidate are NOT row-mutated: they stay immutable historical
   evidence of the original DISCOVER run (byte/hash-identical, asserted),
   and the recompute job publishes the CURRENT derived artifacts under its
   own job-scoped path.  "Superseded/archived" for the affected state is
   carried by the suggestions (status `superseded`), the roles (T03 lineage)
   and the correction's `result_json` archive.  No S02/S05/S06 contract was
   changed.
2. **Queued-cancel drain gap (base engine, pre-existing S05-owned behavior
   noted in T02).**  Cancel of an applied correction's recompute Job while
   the Job is still `queued` transitions it to `cancelling`; the base
   reconciler drains leased `running`/`cancelling` Jobs (same gap T02
   recorded).  The correction API surfaces the durable state honestly
   (`cancelling`), and the cancel-during-running path (REAL worker + sync
   seam) drains to `cancelled` with zero effects.  Not a T05 defect.
3. **`PHASE_HOOK` test seam** in the recompute service (None in production,
   zero overhead) — the same synchronization-hook pattern as T02's blocking
   deterministic provider; used only to hold the REAL handler at a phase
   boundary so the durable cancel path is exercised deterministically.
4. **Frontend flows re-routed through the correction API.**  The gallery's
   merge/split actions now go through the correction workflow (scope preview
   → create → confirm → recompute), because the TASK requires
   merge/split to report impacted scope before confirmation.  The T03 direct
   endpoints remain the API contract (unchanged); the T04 desktop suite was
   re-run against the new flow: 13/13 (one T04 locator clash with the new
   evidence-section copy was fixed on the T05 side by rewording — T04 tests
   were NOT modified).
5. **Head-string expectation updates** in T01–T04 test files are required
   consequences of the T05 migration (T02/T03 precedent).  No assertions
   weakened, no skips added.
6. The correction DTO uses `role_kind` as the JSON field for the role-kind
   edit (the top-level `kind` is already the correction kind).

## Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` — T05 deliverables complete and
verified; Codex review at sprint exit owns APPROVED/CLOSED.

## Manager verification (2026-08-16)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** — recorded by the
sprint manager after independent re-run. NOT APPROVED; Codex sprint-exit review
owns approval.

Manager re-runs (independent basetemps): focused T05 39/39 (21.79s); combined
T01-T05 + persistence/project/video 295/295 (139.29s); S05 41-suite 41/41
(89.23s); S06 90-suite 90/90 (42.36s). Frontend: tsc exit 0, eslint exit 0,
next build exit 0. Manager E2E (fresh isolated root 20260816-s08t05-mgr,
backend :8014 + next :3012, ports cleaned after): T05 config 11/11 (34.0s,
desktop correction flows incl. scope-before-confirmation + escape-zero-
mutations; mobile 390px correction dialog/edit no-overflow) + T04 desktop
regression 13/13 (24.1s) + T04 mobile regression included in run. Worker
visual screenshots (20:13, 3 files) valid: only next-env.d.ts auto-generated
afterwards. Protected state unchanged (channels.json SHA dd7aae26…555; MAIN DB
311296 B). Worker session: 20260816_185020_83fd62 (fresh, exit 0).


---

## CORRECTION ROUND — Finding D: corrected media becomes canonical (Codex CHANGES_REQUESTED on sprint exit)

**Status:** SUBMITTED (unchanged — never self-approved; PM_REVIEW.md untouched)
**Date:** 2026-08-17
**Scope:** the eight finding-D items ONLY, in this session.

### What was wrong

RECOMPUTE_OBJECTS regenerated derived artifact ROWS/FILES but never replaced
the role→media links: the gallery/API kept resolving the ORIGINAL DISCOVER
media after geometry/reassign corrections (finding D1/D2/D6 failed).

### Fix (root cause, built on the T02-C1 association surface)

1. **Replacement media links (D1).** The recompute publish now creates NEW
   `object_role_artifact` rows for every regenerated thumbnail/mask of the
   affected stable role ids (deterministic ids, `source_job_id` = the
   RECOMPUTE job, same purpose + generation) and marks every previously
   ACTIVE association of the same (role, purpose) as superseded via the new
   `superseded_by_id` self-FK (migration f6a7b8c9d0e1, reversible, batch mode
   for SQLite).  Replay is byte-deterministic (the superseded set is
   re-selected by the back-pointer), and `_verify_committed` enforces
   exactly-one-active association per (role, purpose) + lineage back-pointers
   before the job can complete.
2. **Newest-valid resolution (D2/D6).** The roles API now resolves `media` =
   ACTIVE associations (`superseded_by_id IS NULL`) of roles that still carry
   evidence (≥1 occurrence).  A role emptied by a correction has NO current
   display media (D4) — it is never shown stale media, and the gallery never
   name-falls-back to legacy outputs for association-managed roles
   (`has_media_associations`).
3. **Unaffected links/bytes identical (D3).** Only the affected roles'
   (role, purpose) association sets change; every other association row and
   artifact row/file stays byte/hash identical (asserted in
   `test_unaffected_role_media_bytes_identical_after_recompute` and the API
   restart test).
4. **Superseded media auditable (D4).** Old association rows + artifact rows
   + files are never deleted; the old artifact remains servable through its
   own DISCOVER job content endpoint (200 in E2E) while the role resolves the
   new media.
5. **Rename-only keeps media (D5).** candidate_edit(role) regenerates
   suggestions only — no geometry change ⇒ no artifact plan ⇒ no association
   replacement (test_rename_only_correction_keeps_media).
6. **Regenerated media after completion AND restart (D6).** E2E t06: after
   the recompute completes the gallery shows the real regenerated preview
   ("đã tính lại sau chỉnh sửa" badge) and a page RELOAD still resolves it
   (backend-persisted).  Mobile m4 repeats this at 390px with no overflow.
7. **Queued cancel (D7).** NEW tests: repo + API cancel of an applied
   correction while the recompute Job is still QUEUED (never leased) drains
   to `cancelled` via the base engine's S08-R01 queued-cancel drain with ZERO
   media/row effects, the old media stays current, and a retry successor
   completes and then replaces the media (predecessor immutable).  Running
   cancel remains covered.
8. **Preserved behavior (D8).** All prior retry/successor, fencing,
   idempotency, concurrency, impacted-scope preview and no-orphan tests still
   pass (45 focused; 162 combined).

### Files changed in this round (all in the worktree)

- NEW `migrations/versions/f6a7b8c9d0e1_object_correction_media_supersession.py`
- `app/persistence/models.py` (+superseded_by_id)
- `app/services/object_correction.py` (association publish + supersession +
  manifest + replay verification)
- `app/persistence/object_intelligence.py` (RoleMediaRecord, newest-valid
  resolution, has_media_associations)
- `app/schemas/object_intelligence.py` (RoleMediaData, media,
  has_media_associations)
- `frontend/src/lib/api.ts` (RoleMedia, roleMediaContentUrl, ObjectRole.media/
  has_media_associations)
- `frontend/src/components/object-gallery/RoleCard.tsx` (real preview tiles +
  honest no-current-media state)
- `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` (role.media
  wiring)
- `tests/test_object_correction.py` (+4), `tests/test_object_correction_api.py`
  (+2), head strings → f6a7b8c9d0e1 in the 5 T01-T04/persistence test files
- `frontend/e2e/s08-t05-correction.spec.ts` (+t06), 
  `frontend/e2e/s08-t05-correction-mobile.spec.ts` (+m4)
- `frontend/playwright.s08t05.config.ts` (output → 20260817-s08t05-c1-r1)
- T04 spec: test 02 (byte-preview note → real-preview assertion; mandated by
  the finding) and test 05 ("35%" → "45%": the grouping engine was
  re-calibrated externally at 2026-08-17 11:11 — `app/services/object_grouping.py`
  now documents/emits 0.45 for same-name disjoint+disjoint pairs; disclosed)

### Validation (exact commands + verbatim results — full detail in LOG.md)

```
1. python -m pytest tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-c1-focused-r1
   -> 45 passed, 91 warnings in 28.61s
2. python -m pytest <T01 domain, T03 grouping, T02 extraction x3, T05 x2>
     -q -p no:cacheprovider --basetemp=.../s08t05-c1-combined-final
   -> 162 passed, 293 warnings in 92.70s
3. S02 (160 passed, 94.03s), S05 (41 passed, 91.70s), S06 (90 passed, 51.44s)
   — all on the FINAL code, shallow basetemps
4. alembic upgrade head -> downgrade f5a6b7c8d9e0 -> upgrade head (temp DB):
   version f6a7b8c9d0e1; superseded_by_id + self-FK via PRAGMA; env unset
5. npx tsc --noEmit (0); npx eslint (0 problems); npm run build (compiled)
6. npx playwright test --config playwright.s08t05.config.ts
   -> 15 passed (52.7s): desktop 8/8 (incl. t06 media-canonical + reload),
      mobile-390px 7/7 (incl. m4)
7. npx playwright test --config playwright.s08t04.config.ts
     --output .../20260817-s08t05-c1-r1/t04-regression-test-results
     e2e/s08-t04-object-gallery.spec.ts
   -> 13 passed (24.2s)
8. ruff (all changed files) -> All checks passed!; mypy -> 86 files, 0 issues
9. git diff --check -> exit 0; git status --short -> 151 entries, no strays
10. Protected data: channels.json SHA-256
    dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED;
    data/motionforge.db 311296 bytes UNCHANGED
```

Screenshots (output/s08-sprint/20260817-s08t05-c1-r1/screenshots/):
desktop-regenerated-media.png, mobile-390px-regenerated-media.png,
desktop-correction-scope-dialog.png, desktop-gallery-correction-actions.png,
mobile-390px-correction-scope-dialog.png.

### Deviations / notes (this round)

- T04 spec updates disclosed above (finding-mandated media assertion + the
  externally re-calibrated engine band).  No T04 backend assertions changed.
- A role emptied by a correction resolves NO current media (honest "no
  current media" state) rather than a placeholder; its old artifacts stay
  auditable and servable.  This is the D4 semantics applied at the source.
- The base engine's S08-R01 queued-cancel drain (worker-owned) is what makes
  D7's queued cancel terminal; this round only ADDS the tests proving the
  correction surface behaves (zero effects + successor retry).

**Status: SUBMITTED** — manager verification + Codex sprint-exit review own
approval.


---

## CORRECTION ROUND C2 — REPAIR AND ISOLATE E2E (Codex CHANGES_REQUESTED on sprint exit)

**Status:** SUBMITTED (unchanged — PM_REVIEW.md / TASK.md untouched)
**Date:** 2026-08-17/18

### What was wrong

The in-tree T04-C2 (collapsible role cards) + S08-H02 (QA-mode gate + CORS
OriginGuard) corrections landed after T05-C1 and broke the T05 E2E:
- the old selectors looked for correction actions directly in the article,
  but actions now exist only inside the EXPANDED detail card;
- the mobile Playwright project leaked T04 mobile specs into the T05 run;
- the QA harness needed QA_MODE=1, CORS origins and a pinned QA_API_BASE.

### Fixes (acceptance mapping)

| AC | Fix | Evidence |
|---|---|---|
| 1 | Expand the card BEFORE correction actions | Every T05 spec uses `Xem chi tiết vai trò <name>` + `getByTestId("role-detail")` scoping. |
| 2 | No product-copy changes to pass tests | Tests assert data-testids/state/API; the only product edits are a semantic fixture hook (`data-testid="media-regenerated"`), the reassign dialog `disabled` gating, and the useGallery state-refresh fix below — none changes copy. |
| 3 | Semantic role/state assertions | scope `scope-<kind>-*` testids, `recompute-strip[data-state]`, `no-current-media`, `media-regenerated`, API (`listRoles`/`mediaOf`/content status) for proof. |
| 4 | Mobile project only S08-T05 mobile specs | `testMatch: /s08-t05-.*mobile\.spec\.ts/`; desktop `testIgnore: /mobile\.spec\.ts/`; config pins `QA_API_BASE=http://localhost:8014`. |
| 5 | `--list` has no H01/T04 | 12 tests (8 desktop + 4 mobile); grep H01/T04 = 0. |
| 6 | NEW Run ID + fresh evidence | output/s08-sprint/20260817-s08t05-c2-r1 (root, launcher, config, screenshots). Old C1 evidence untouched. |
| 7 | FULL desktop + 390px T05 suite passes | 12 passed (40.5s). |
| 8 | Reproduce + prove t01/m1 selector class | Before/after probe: BEFORE old flat-card selector times out; AFTER expand+detail works (2 passed). |

### Root-cause product fixes (in-scope, surfaced by the repair)

1. `useGallery.ts` — the role list hydrated ONLY on the role-ID signature, so
   correction state changes (status/occurrences/media, same ids) never
   refreshed the gallery; the open detail query was also never invalidated.
   Fixed: content signature (revision/status/occurrence-count/media source
   jobs) + `object-role-detail` invalidation in refreshAll.  This is what
   makes the merge source superseded, the emptied source "no current media",
   and the regenerated-media tile appear — including after reload.
2. Reassign confirm `disabled` gating restored (ConfirmDialog + panel) —
   cannot confirm a reassign before choosing a target.
3. `galleryUtils.tsx` MediaTile `data-testid="media-regenerated"`.

### Validation (exact commands + verbatim results — full detail in LOG.md)

```
--list isolation:
  npx playwright test --config playwright.s08t05.config.ts --list
    -> 12 tests (8 desktop + 4 mobile); H01/T04 count = 0
Before/after probe (throwaway, deleted after):
  npx playwright test --config playwright.c2probe.config.ts
    -> 2 passed — BEFORE: "action NOT reachable without expansion ...
       Timeout 5000ms exceeded"; AFTER: expand -> action reachable (1.1s)
FULL T05 suite (fresh run root 20260817-s08t05-c2-r1):
  npx playwright test --config playwright.s08t05.config.ts
    -> 12 passed (40.5s): desktop v1,v2,t01-t06 (8/8), mobile m1-m4 (4/4)
T04 regression vs the repaired UI (QA_API_BASE=http://localhost:8014):
  -> 15 passed (1.3m) incl. T04-C2 generation-isolation tests 14,15
Backend:
  T01-T05 combined (8 files incl SAM2 production wiring) -> 185 passed, 107.22s
  S05 41-suite (shallow) -> 41 passed, 94.49s
  S02 durable -> 160 passed, 77.44s
  Migration round trip -> head f6a7b8c9d0e1; superseded_by_id + object_correction OK
Gate:
  tsc 0; eslint 0; next build compiled; ruff all-clean; mypy 88 files OK;
  git diff --check 0; git status --short 167 (matches the guard baseline)
Protected:
  channels.json SHA dd7aae…555 UNCHANGED; motionforge.db 311296 B UNCHANGED;
  SAM2.1 checkpoint 898083611 B / SHA 2647878D…D318 UNCHANGED (read-only)
Screenshots (NEW Run ID): output/s08-sprint/20260817-s08t05-c2-r1/screenshots/
  desktop-gallery-correction-actions.png, desktop-correction-scope-dialog.png,
  desktop-regenerated-media.png, mobile-390px-correction-scope-dialog.png,
  mobile-390px-regenerated-media.png
QA servers stopped; ports 8014/3012 verified free.
```

### Files changed this round (all in the worktree)

- frontend/playwright.s08t05.config.ts (isolation + QA_API_BASE pin + Run ID)
- frontend/e2e/s08-t05-correction.spec.ts (expand-first + semantic selectors)
- frontend/e2e/s08-t05-correction-mobile.spec.ts (expand-first + semantic)
- frontend/e2e/s08-t05-correction-visual.spec.ts (expand-first)
- frontend/src/components/object-gallery/useGallery.ts (state-refresh fix)
- frontend/src/components/object-gallery/ConfirmDialog.tsx (disabled gating)
- frontend/src/components/object-gallery/ObjectGalleryPanel.tsx (reassign disabled)
- frontend/src/components/object-gallery/galleryUtils.tsx (media-regenerated testid)
- output/s08-sprint/20260817-s08t05-c2-r1/run-qa-backend.sh (QA_MODE + CORS)
- docs/pm/sessions/S08-T05-targeted-correction/LOG.md, REPORT.md (this round)

No PM_REVIEW.md / TASK.md touched; no commits/resets/stash/clean; all T05
contracts (correction media canonical, supersession, retry/successor,
idempotency, no-orphan) preserved and re-verified.

**Status: SUBMITTED** — manager verification + Codex sprint-exit review own
approval.
