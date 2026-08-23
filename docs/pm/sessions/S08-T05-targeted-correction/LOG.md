# S08-T05 — Execution Log

Append-only. Record exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

## BASELINE (before any code change)

### Required-reading checklist (all read in full)
- [x] MAIN `C:/Users/Admin/MotionForge2D/docs/pm/SESSION_PROTOCOL.md`
- [x] `docs/pm/sprints/S08-SPRINT_CONTRACT.md` (worktree)
- [x] `docs/pm/sessions/S08-T05-targeted-correction/TASK.md`
- [x] `docs/pm/sessions/S08-T05-targeted-correction/START_PROMPT.md`
- [x] T01 REPORT, T02 REPORT, T03 REPORT, T04 REPORT (manager-verified evidence)
- [x] Current S08 code: `app/persistence/object_intelligence.py`,
      `app/persistence/object_grouping.py`, `app/services/object_grouping.py`,
      `app/api/routes/object_grouping.py`, `app/api/routes/object_extraction.py`,
      `app/services/object_extraction.py`, `frontend/src/app/(app)/object-gallery/`,
      `frontend/src/lib/api.ts` (+ models/job_service/durable_worker for the
      durable job contracts)

### Hard worktree guard (verified BEFORE any write)
```
pwd                                -> /c/Users/Admin/MotionForge2D-worktrees/s08-integration  OK
git rev-parse --show-toplevel      -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration OK
git branch --show-current          -> codex/s08-integration                                  OK
git rev-parse HEAD                 -> a43b20da742996bafcb2f9d1ac57b10d3f1a5204               OK
git status --short                 -> 126 entries (dirty snapshot taken; see below)          OK
```
All five checks PASSED.  No write to MAIN or any other worktree.

### Protected user changes snapshot (pre-existing dirty state, preserved)
Worktree dirty state at start: 126 entries — 21 modified (app/api/app.py,
app/api/deps.py, app/api/routes/projects.py, app/persistence/models.py,
app/workflow/durable_worker.py, app/workflow/job_service.py, docs/pm/ROADMAP.md,
S06-T05 packet files, frontend/src/app/(app)/characters/page.tsx,
frontend/src/components/layout/AppNav.tsx, frontend/src/lib/api.ts,
tests/fixtures/legacy_import/*, tests/test_durable_job_persistence.py,
tests/test_persistence_bootstrap.py) + 105 untracked (S05/S06/S08 packets,
migrations, app/services|schemas|routes|persistence S08 modules, tests/*,
frontend object-gallery + e2e + playwright configs).  These are the
manager-approved T01–T04 artifacts I extend; nothing is overwritten without
reason, and every required expectation update is disclosed in REPORT.

### Protected-data baseline (MAIN tree)
```
certutil -hashfile C:/Users/Admin/MotionForge2D/channels.json SHA256
  -> dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
     (IDENTICAL to T01/T02/T03/T04 recorded value)
C:/Users/Admin/MotionForge2D/data/motionforge.db
  -> 311296 bytes (IDENTICAL to T01–T04 baseline)
MAIN git status --short -> 50 entries (T04-era watcher scripts included)
```

### Plan (7 steps)
1. DESIGN.md: dependency/invalidation graph defined BEFORE implementation
   (this packet; normative for service/repo/job/tests).  DONE above.
2. Migration `f4a5b6c7d8e9_object_correction_schema.py` (down `f3a4b5c6d7e8`):
   `object_correction` table + models.py (+ObjectCorrection, constants,
   `__all__`) + required head-string/table-set expectation updates in the
   T01–T04 test files (T02/T03 precedent).
3. `app/persistence/object_correction.py`: repository — natural-key idempotent
   create, CAS confirm (one txn: targeted mutation via T01/T03 repos +
   suggestion supersession + result archive + RECOMPUTE job creation only
   where needed), get/list, cancel, successor retry.
4. `app/services/object_correction.py`: impact computation (read-only,
   exact sets) + submit/confirm workflow + RECOMPUTE_OBJECTS durable job
   (submit, handler with input/recompute/stage/publish phases, checkpoint
   resume, cancel-observing, staging GC, output validator) + minimal
   registration in `app/workflow/job_service.py`.
5. `app/schemas/object_correction.py` + `app/api/routes/object_correction.py`
   + `app/api/app.py` registration: preview/create/confirm/get/list/cancel/
   recompute-retry.
6. Frontend: api.ts types+functions; CorrectionImpactDialog (scope before
   confirmation, progress, terminal outcome, honest recovery); gallery
   merge/split/confirm/reassign/candidate-edit routed through the correction
   flow; RoleCard per-occurrence reassign + edit actions (Vietnamese helper
   lines, 11px, readable on dark theme).
7. Validation: focused S08-T05 suite; full T01–T04 suites; S02/S05/S06
   regressions (shallow basetemps); tsc/eslint/next build; desktop + 390px
   E2E on a fresh isolated backend root with new screenshots; ruff/mypy/
   diff-check/status; protected-data comparison; REPORT = SUBMITTED.

No commit/push/deploy/reset/checkout/restore/clean/stash/delete.  No
channels.json / data/ / MAIN-tree writes.



## IMPLEMENTATION (backend)

Files created/changed (all within TASK.md allowed write scope):

- migrations/versions/f4a5b6c7d8e9_object_correction_schema.py (NEW, reversible,
  down f3a4b5c6d7e8): ``object_correction`` table — durable archive of one
  targeted correction (type/status CHECKs, natural-key + idempotency partial
  unique indexes, recompute_job_id FK job RESTRICT).
- app/persistence/models.py: +ObjectCorrection ORM, +OBJECT_CORRECTION_TYPES,
  +OBJECT_CORRECTION_STATUSES, __all__ entries.
- app/persistence/object_correction.py (NEW repository): compute_impact (pure
  read, exact affected/invalidated/artifact sets), create_correction
  (natural-key idempotent + equivalence + IntegrityError race), 
  confirm_correction (atomic CAS pending->applied; ONE txn = targeted
  mutation via T01/T03 repos + suggestion supersession + result archive +
  RECOMPUTE_OBJECTS job only where needed), cancel (pending CAS / durable job
  cancel), create_recompute_successor (§6.4, idempotent), recompute_state
  (successor-chain walk), list/get.  populate_existing reads (identity-map
  staleness from raw UPDATE...RETURNING(id) is avoided; refresh() would
  cascade-expire loaded child occurrences).
- app/services/object_correction.py (NEW): RECOMPUTE_OBJECTS durable job
  (input fingerprint -> recompute -> stage -> publish; checkpoint resume;
  cancel-observing; staging GC; one publication txn; output_validator =
  row/file verification + no-orphan gate + staging drained); register hook;
  compute_correction_impact.
- app/schemas/object_correction.py (NEW): CorrectionRequest (kind-selected
  field sets), ImpactData, CorrectionData (+RecomputeStateData),
  CorrectionCreateResponse, list/confirm/cancel DTOs.
- app/api/routes/object_correction.py (NEW): /preview (read-only impact),
  POST / (create pending, 201/200 replay), /{id}/confirm (201/200), GET /{id},
  GET /, /{id}/cancel, /{id}/recompute/retry. Error mapping 404/409/422/503.
- app/api/app.py: one import + one include_router line.
- app/workflow/job_service.py: register_recompute_objects_handler (minimal
  durable job registration, same pattern as S05/S08 handlers).
- tests/test_object_correction.py (NEW, 30 tests), tests/test_object_correction_api.py
  (NEW, 9 tests).
- Required head-string/table-set expectation updates (T02/T03 precedent):
  tests/test_object_extraction.py, test_object_grouping.py,
  test_object_intelligence_domain.py, test_persistence_bootstrap.py
  (S08_HEAD_TABLES +object_correction, head f4a5b6c7d8e9), 
  test_durable_job_persistence.py (+object_correction).

## VALIDATION RUNS (backend, cache disabled, isolated basetemps)

1. Focused S08-T05 (r9, final):
   python -m pytest tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-focused-r9
   -> 39 passed, 40 warnings in 26.13s

2. T01-T04 + T05 combined:
   python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py
     tests/test_object_extraction.py tests/test_object_extraction_api.py
     tests/test_object_extraction_production_wiring.py
     tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-t01t04-r1
   -> 135 passed, 126 warnings in 72.69s

3. Ruff (all changed Python files) -> All checks passed!
4. Mypy -> Success: no issues found in 86 source files
5. Frontend: npx tsc --noEmit -> exit 0; npx eslint (api.ts, ObjectGalleryPanel,
   RoleCard, CorrectionScope) -> 0 problems; npm run build -> Compiled
   successfully, /object-gallery static route, exit 0.

(debugging history: FK failure from seeded fake source_job_id -> real seed
jobs; checkpoint JSON serialization of binary plan -> metadata-only plan;
output_validator read stale ctx.checkpoint -> handler result; multi-column
scalar() char-indexing bug in the successor walk; refresh() cascade-expiring
loaded occurrences -> populate_existing reads. All fixed; every fix verified
by the re-run above.)



## FINAL VALIDATION (final code state)

- Focused S08-T05: 39 passed in 22.11s
  (--basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-focused-final)
- S08 T01-T04+T05 combined: 135 passed in 72.69s
  (--basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-t01t04-r1)
- S02: 160 passed in 69.76s (--basetemp=.../s08t05-s02-r1)
- S05: 41 passed in 89.64s (--basetemp=.../s08t05-s05-r1, SHALLOW)
- S06: 90 passed in 43.11s (--basetemp=.../s08t05-s06-r1)
- Migration CLI round trip: upgrade head -> downgrade f3a4b5c6d7e8 ->
  upgrade head on a fresh temp DB; version f4a5b6c7d8e9; table + columns +
  job table verified via sqlite3.  MOTIONFORGE_DATABASE_URL UNSET after.
- Frontend gates (final): tsc exit 0; eslint 0 problems; next build
  compiled successfully (/object-gallery static route).
- Playwright T05 (final): 13 passed (44.3s) — desktop 7/7 (2 visual),
  mobile-390px 6/6.  Screenshots:
    output/s08-sprint/20260816-s08t05-r1/screenshots/
      desktop-gallery-correction-actions.png
      desktop-correction-scope-dialog.png
      mobile-390px-correction-scope-dialog.png
- T04 regression re-run against the NEW correction UI (output overridden to
  the T05 run dir; T04 packet evidence untouched):
  T04 desktop interaction suite 13 passed (22.6s); T04 mobile suite ran green
  inside the T05 config run (3/3).
- Ruff (all changed Python files): All checks passed!
- Mypy: Success: no issues found in 86 source files
- git diff --check: exit 0 (pre-existing CRLF advisories only)
- git status --short: 137 entries (baseline 126 + 11 new T05 files), no strays
- Protected data (MAIN): channels.json SHA-256
  dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED;
  data/motionforge.db 311296 bytes UNCHANGED; MAIN status 50 entries.
- QA servers stopped (ports 8014/3012 verified free after taskkill by PID).

Status: SUBMITTED (manager verification pending; Codex owns sprint-exit approval).

## FRESH GATE RE-RUN (final tree, post-REPORT, new basetemps)

- Focused S08-T05:
  python -m pytest tests/test_object_correction.py tests/test_object_correction_api.py
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-gate-fresh
  -> 39 passed, 40 warnings in 21.82s
- Combined S08 T01-T05 + persistence/project/video:
  python -m pytest <T01 domain + T03 grouping + T02 extraction x3 + T05 x2 +
    persistence_bootstrap + durable_job_persistence + project_crud + video_item_crud>
    -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t05-gate-combined
  -> 295 passed, 279 warnings in 142.65s
Status remains SUBMITTED.

## MANAGER VERIFICATION — 2026-08-16

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence:
- Focused T05: 39 passed in 21.79s (s08t05-mgr-focused)
- Combined T01-T05 + persistence/project/video: 295 passed in 139.29s (s08t05-mgr-combined)
- S05 41-suite: 41 passed in 89.23s; S06 90-suite: 90 passed in 42.36s
- Frontend: tsc exit 0, eslint exit 0, next build exit 0
- Manager E2E (isolated root 20260816-s08t05-mgr): T05 config 11/11 (34.0s) + T04 desktop regression 13/13 (24.1s); worker visual screenshots valid (only next-env.d.ts regenerated after)
- Protected: channels.json SHA dd7aae26...555 UNCHANGED; MAIN DB 311296 B UNCHANGED
- Scope audit: 137 = 126 + 11 T05 files (correction service/schema/route/persistence + migration f4a5b6c7d8e9 + 3 e2e specs + gallery component updates + DESIGN.md in packet). DESIGN.md in packet folder is a minor addition beyond LOG/REPORT — normative design doc for the required invalidation graph; TASK.md/PM_REVIEW.md untouched.

Decision: T05 dependency released for S08-T06 under full-sprint manager protocol.


## CORRECTION ROUND (Codex CHANGES_REQUESTED on sprint exit — finding D: corrected media becomes canonical)

Session: 20260816_185020_83fd62 (same worker session, fresh correction round).
History preserved above; status stays SUBMITTED (no self-approval).

### Root cause (from the finding)

RECOMPUTE_OBJECTS published regenerated ARTIFACT rows but never REPLACED the
role->media links, so the gallery/API kept resolving the ORIGINAL DISCOVER
media after a geometry/reassign correction.

### Changes (all in the worktree; write scope = S08-T05 packet + code/tests)

- migrations/versions/f6a7b8c9d0e1_object_correction_media_supersession.py (NEW,
  reversible, down f5a6b7c8d9e0): ``object_role_artifact.superseded_by_id``
  (nullable self-FK RESTRICT) + ix_object_role_artifact_current(role_id,
  purpose, superseded_by_id) — batch mode (SQLite cannot ALTER constraints).
- app/persistence/models.py: ObjectRoleArtifact.superseded_by_id column.
- app/services/object_correction.py: recompute publish now (a) creates a NEW
  ObjectRoleArtifact row per regenerated thumbnail/mask (deterministic id
  ``recompute:<job>:role:<role_id>:artifact:<name>``, source_job_id = the
  RECOMPUTE job), (b) supersedes every previously ACTIVE association of the
  same (role, purpose) via the self-FK (replay-deterministic), (c) records the
  superseded lineage in the result manifest; ``_verify_committed`` enforces
  exactly-one-active association per (role, purpose) + lineage back-pointers.
- app/persistence/object_intelligence.py: NEW RoleMediaRecord + media
  resolution = ACTIVE associations (superseded_by_id IS NULL) of roles that
  still carry evidence (>=1 occurrence — a role emptied by a correction has
  NO current display media, finding D4/D6); get_role/list_roles expose
  ``media`` + ``has_media_associations`` (association-managed marker so the
  gallery never name-falls-back to stale outputs).
- app/schemas/object_intelligence.py: RoleMediaData + RoleData.media +
  has_media_associations.
- Frontend: api.ts RoleMedia + roleMediaContentUrl; RoleCard renders the REAL
  preview image (contained endpoint) per current media with an honest
  "đã tính lại sau chỉnh sửa" badge for recompute artifacts and a
  no-current-media note for evidence-emptied roles (no legacy fallback for
  association-managed roles); gallery panels pass role.media.
- Tests: +4 repo tests (replacement links + supersession + immutability,
  rename keeps media, queued cancel + successor retry, unaffected role
  byte-identical) and +2 API tests (newest-valid resolution + restart,
  queued-cancel via API + retry); migration head expectations updated to
  f6a7b8c9d0e1 in the 5 T01-T04/persistence test files.
- E2E: t06 (desktop) + m4 (390px) correction-media-refresh flows incl. page
  reload (restart) persistence; T04 spec test 02 updated (the pre-C1
  "API chưa phục vụ xem trước byte" note is replaced by the real-preview
  assertion — the finding's mandate) and test 05 confidence updated to the
  current engine band 0.45 (grouping engine recalibrated externally at
  2026-08-17 11:11 — see REPORT deviations).

### Validation (fresh isolated roots, cache disabled, shallow basetemps C:/Users/Admin/AppData/Local/Temp/s08t05-c1-*)

1. Focused T05 (45 tests): 45 passed, 91 warnings in 28.61s
   (--basetemp=.../s08t05-c1-focused-r1)
2. T01-T04 + T05 combined (final code): 162 passed, 293 warnings in 92.70s
   (--basetemp=.../s08t05-c1-combined-final)
3. S02 final: 160 passed in 94.03s; S05 final: 41 passed in 91.70s;
   S06 final: 90 passed in 51.44s (shallow basetemps, final code)
4. Migration CLI round trip (fresh temp DB):
   upgrade head -> f6a7b8c9d0e1; downgrade f5a6b7c8d9e0; upgrade head;
   superseded_by_id present + self-FK verified via PRAGMA; env var unset.
5. Frontend gates: tsc exit 0; eslint 0 problems (all changed files incl.
   specs); next build compiled successfully (final run).
6. Playwright T05 (fresh root output/s08-sprint/20260817-s08t05-c1-r1,
   QA launcher sets isolated root inline + cd's into the run root):
   15 passed (52.7s) — desktop 8/8 (incl. t06 media-canonical + reload),
   mobile-390px 7/7 (incl. m4 regenerated media).  Screenshots:
   desktop-regenerated-media.png, mobile-390px-regenerated-media.png,
   desktop-correction-scope-dialog.png, desktop-gallery-correction-actions.png,
   mobile-390px-correction-scope-dialog.png (all under
   output/s08-sprint/20260817-s08t05-c1-r1/screenshots/).
7. T04 desktop regression vs the new UI (output overridden to the C1 dir):
   13 passed (24.2s).
8. ruff (all changed files): All checks passed!  mypy: Success in 86 files.
9. git diff --check exit 0; git status --short: 151 entries (150 baseline +
   the new C1 files; no strays).
10. Protected data: MAIN channels.json SHA-256
    dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED;
    MAIN data/motionforge.db 311296 bytes UNCHANGED.  (MAIN git dirty count
    changed 50 -> 60 by an EXTERNAL writer during this round — not touched
    by this session.)
Status: SUBMITTED.


## CORRECTION ROUND C2 (Codex CHANGES_REQUESTED on sprint exit — REPAIR AND ISOLATE E2E)

Session: 20260816_185020_83fd62 (same worker session). History preserved.

### Operational notes (this round)

- The guard baseline was 167 dirty entries (INTENTIONAL — never reset).
- The in-tree T04-C2 / S08-H02 corrections landed after T05-C1 and changed
  three things that broke the old T05 E2E selectors/harness:
  1. Gallery renders COLLAPSIBLE role cards (expand → detail card
     `data-testid="role-detail"`); correction actions live ONLY in the
     expanded detail card.
  2. The shared helpers retargeted `QA_API_BASE` (default 8025).
  3. The backend now enforces `MOTIONFORGE_EXTRACTION_QA_MODE=1` for the
     deterministic provider and an `OriginGuard` CORS allowlist
     (`MOTIONFORGE_CORS_ORIGINS`).
  The T05 QA launcher was updated accordingly (isolated root inline + cd into
  the run root + QA_MODE + CORS origins for http://localhost:3012).  A stale
  orphan uvicorn on :8014 (verified CommandLine identity) was killed before
  the clean stack boot.

### Fixes (AC1-AC8)

- AC1 selectors: every T05 E2E now EXPANDS the card
  (`getByRole('button', { name: 'Xem chi tiết vai trò <name>' })`) and
  interacts with `getByTestId('role-detail')` before locating correction
  actions.  Before/after PROBE (throwaway spec, since deleted):
    BEFORE reproduced — action NOT reachable without expansion:
      TimeoutError: locator.waitFor: Timeout 5000ms exceeded.
    AFTER — expand card → action reachable (1.1s).  2 passed.
- AC2/AC3 semantic assertions: tests now assert data-testids / state
  attributes / API state instead of brittle display copy:
    - scope report lines: `scope-<kind>-role-count`, `-occurrence-count`,
      `-suggestion-count`, `-artifact-count`, `recompute-not-needed-<kind>`;
    - recompute strip terminal: `data-testid="recompute-strip"` +
      `data-state="completed"` (polled);
    - regenerated media: `data-testid="media-regenerated"` (product
      fixture, not a copy change); honest empty: `data-testid="no-current-media"`.
  Terminal-outcome and mutation proofs additionally call the REAL API
  (listRoles/mediaOf/contentStatus).  No product copy was changed to make
  tests green.
- AC4/AC5 project isolation: mobile project testMatch is now
  `/s08-t05-.*mobile\.spec\.ts/`; desktop testIgnore `/mobile\.spec\.ts/`;
  config pins `QA_API_BASE=http://localhost:8014` (hermetic).  `--list`:
  12 tests (8 desktop + 4 mobile), H01/T04 count = 0.
- AC6 NEW Run ID: output/s08-sprint/20260817-s08t05-c2-r1 (new root,
  launcher, config outputDir, SHOT_DIR in specs, fresh backend DB).  Old
  C1 evidence untouched.
- AC7 full suite: desktop + 390px all pass (see below).
- AC8 reproduction: probe above proves desktop t01 + mobile m1 selector
  class (expand-then-act) vs the current UI.

### Product-code fixes surfaced by the repair (root cause, in-scope)

- `frontend/src/components/object-gallery/ConfirmDialog.tsx`,
  `ObjectGalleryPanel.tsx` (T05 reassign dialog): restore the semantic
  `disabled` gating — the confirm button must stay disabled until a target
  role is chosen (the in-tree refactor had dropped the prop from the
  reassign dialog); confirm uses `disabled={busy || disabled}`.
- `frontend/src/components/object-gallery/useGallery.ts` (T04-C2 refactor
  bug): the role-list hydration signature ignored ROLE STATE — after a
  correction the same role ids were kept and status/occurrences/media never
  refreshed.  Signature now includes revision/status/occurrence-count/media
  source jobs; `refreshAll` also invalidates `object-role-detail` so an OPEN
  detail card shows the post-correction state (this is what makes
  merge-source superseded, emptied-source "no current media" and the
  regenerated-media tile appear/refresh, incl. after reload).
- `galleryUtils.tsx` MediaTile: `data-testid="media-regenerated"` (product
  fixture hook, no copy change).

### Validation (exact commands + verbatim results; fresh isolated roots,
cache disabled, shallow basetemps C:/Users/Admin/AppData/Local/Temp/s08t05-c2-*)

1. npx playwright test --config playwright.s08t05.config.ts --list
   -> 12 tests (8 desktop + 4 mobile); H01/T04 count = 0 (project isolation)
2. Before/after probe (throwaway) -> 2 passed (BEFORE: old flat-card selector
   times out; AFTER: expand+detail actions reachable)
3. npx playwright test --config playwright.s08t05.config.ts (FULL suite,
   fresh run root 20260817-s08t05-c2-r1)
   -> 12 passed (40.5s): desktop v1,v2,t01-t06 (8/8) + mobile m1-m4 (4/4)
4. npx playwright test --config playwright.s08t04.config.ts
     --output .../20260817-s08t05-c2-r1/t04-regression-test-results
     e2e/s08-t04-object-gallery.spec.ts   (QA_API_BASE=http://localhost:8014)
   -> 15 passed (1.3m) — includes T04-C2 generation-isolation tests 14,15
5. T01-T05 combined (8 files incl SAM2 production wiring):
   python -m pytest tests/test_object_intelligence_domain.py
     tests/test_object_grouping.py tests/test_object_extraction.py
     tests/test_object_extraction_api.py
     tests/test_object_extraction_production_wiring.py
     tests/test_object_correction.py tests/test_object_correction_api.py
     -q -p no:cacheprovider --basetemp=.../s08t05-c2-t01t05
   -> 185 passed, 339 warnings in 107.22s
6. S05 41-suite: 41 passed in 94.49s (--basetemp=.../s08t05-c2-s05, SHALLOW)
7. S02 durable: 160 passed in 77.44s (--basetemp=.../s08t05-c2-s02)
8. Migration round trip (temp DB): upgrade head -> f6a7b8c9d0e1;
   downgrade f5a6b7c8d9e0; upgrade head; superseded_by_id + object_correction
   verified via PRAGMA; MOTIONFORGE_DATABASE_URL UNSET afterwards.
9. Frontend gates: npx tsc --noEmit (0); npx eslint (0 problems on all
   changed files + specs); npm run build (compiled successfully).
10. ruff (all changed Python files) -> All checks passed!; mypy ->
    Success: no issues found in 88 source files; git diff --check -> exit 0.
11. git status --short: 167 entries (matches the intentional guard baseline);
    no probe strays; no commits/resets.
12. Protected data (MAIN):
    - channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 UNCHANGED
    - data/motionforge.db 311296 bytes UNCHANGED
    - SAM2.1 checkpoint models_checkpoints/sam2.1_hiera_large.pt
      898083611 bytes; SHA-256
      2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318
      (read-only, untouched — matches the mandated value)
13. Screenshots (NEW Run ID, never overwrote old): output/s08-sprint/
    20260817-s08t05-c2-r1/screenshots/ desktop-gallery-correction-actions.png,
    desktop-correction-scope-dialog.png, desktop-regenerated-media.png,
    mobile-390px-correction-scope-dialog.png,
    mobile-390px-regenerated-media.png.
14. QA servers stopped after the runs; ports 8014/3012 verified free.

Status: SUBMITTED (unchanged).
