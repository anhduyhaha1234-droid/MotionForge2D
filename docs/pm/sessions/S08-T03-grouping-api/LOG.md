# S08-T03 — Execution Log

Status: HERMES_RUNNING -> SUBMITTED (2026-08-16)

Append-only. Exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

## Baseline

- Session: `20260816_151439_21e306` (fresh S08-T03 worker session, ocg/deepseek-v4-flash)
- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`, branch `codex/s08-integration`
- HEAD at start: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- Worktree guard verified BEFORE any write:
  - `pwd` -> `/c/Users/Admin/MotionForge2D-worktrees/s08-integration` ✓
  - `git rev-parse --show-toplevel` -> `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` ✓
  - `git branch --show-current` -> `codex/s08-integration` ✓
  - `git rev-parse HEAD` -> `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` ✓
  - `git status --short` -> 21 modified + 92 untracked = 113 entries (snapshot taken)
- Required reading completed in order: SESSION_PROTOCOL.md, S08-SPRINT_CONTRACT.md,
  S08-T03 TASK.md + START_PROMPT.md, S08-T01 REPORT.md, S08-T02 REPORT.md (both
  manager-verified), current S08 code (models.py, object_intelligence.py repo/schemas/
  routes, object_extraction.py service).

## Implementation (all within TASK.md allowed write scope)

New files:
- `migrations/versions/f3a4b5c6d7e8_object_grouping_schema.py` — reversible migration
  (down `f2a3b4c5d6e7`); creates `object_grouping_suggestion` +
  `object_role_operation` with CHECKs, FKs, partial-unique natural/idempotency
  indexes, lookup indexes; downgrade drops both (operation first, FK order).
- `app/persistence/object_grouping.py` — `ObjectGroupingRepository`: suggestions
  (create with content-derived natural-key idempotency, list/get, CAS dismiss,
  generate-time stale supersede with natural-key detach, merge-time supersede of
  suggestions referencing merged roles); explicit merge/split/confirm with atomic
  CAS predicates on the ObjectRole rows, per-source supersession
  (`supersedes_role_id`), evidence move that NEVER rewrites occurrence content,
  collision fail-closed, one-row-per-operation audit (`RoleOperation` with exact
  transfer map), natural-key + idempotency-key replay, fresh-transaction replay on
  IntegrityError races; fail-closed ownership across workspace/project/video/
  generation; read-only list/get for suggestions and operations.
- `app/services/object_grouping.py` — PURE deterministic grouping algorithm
  (`role-fingerprint` v1): normalized-name equality + IoU spatial footprint rules
  (0.9 consistent / 0.65 partial / 0.35 disjoint-low-confidence), cross-name
  ambiguity rule (0.55 matching footprint + temporally disjoint), noise floor
  0.35; pairwise canonical ordering; NEVER confirms anything.
- `app/schemas/object_grouping.py` — DTOs (Generate/Suggestion/Dismiss/Merge/Split/
  Confirm requests; SuggestionData/SuggestionList/GenerateResult/OperationData/
  OperationList/Merge/Split/ConfirmResult; review reasons exposed on every read).
- `app/api/routes/object_grouping.py` — router under `/api/v2/object-intelligence/grouping`:
  POST suggestions/generate (201; 200 full replay), GET suggestions list/detail
  (read-only), POST dismiss (CAS, state-idempotent), POST roles/{id}/merge|split|
  confirm (201; 200 replay; 404/409/422 mapping; rollback before raise), GET
  operations list/detail (read-only).
- `tests/test_object_grouping.py` — focused suite, 25 tests (see REPORT).

Modified files:
- `app/persistence/models.py` — +`ObjectGroupingSuggestion`, +`RoleOperation` ORM
  models, +3 domain constants, +`__all__` entries.
- `app/api/app.py` — one import + one `include_router` line.
- `tests/test_persistence_bootstrap.py` — required head-revision/table-set
  expectation updates (S08_HEAD_TABLES +2 tables, head `f3a4b5c6d7e8`, ancestry).
- `tests/test_durable_job_persistence.py` — required table-set expectation +2 tables.
- `tests/test_object_intelligence_domain.py` — required head-string update
  (`f2a3b4c5d6e7` -> `f3a4b5c6d7e8`), same precedent as T01->T02.
- `tests/test_object_extraction.py` — required head-string update (same precedent).

No changes to: deps.py, frontend/, legacy object code, S05/S06 contracts, TASK.md,
sprint contract, PM_REVIEW.md, channels.json, data/, databases, fixtures, MAIN or
other worktrees.

## Key implementation decisions (documented)

1. Suggestions are durable rows, always created `pending`; generation is a
   synchronous deterministic DB computation (no job — grouping is not a media
   recompute; T05 owns recompute jobs).
2. Idempotency: content-derived `natural_key` (workspace-scoped partial unique
   index) for suggestions AND operations; optional client `idempotency_key` as a
   second backstop index. Equivalent replays return 200 + the same durable rows.
3. Replay gating: only `pending`/`dismissed` suggestions and only equivalent
   canonical requests replay; `applied`/`superseded` rows detach their natural key
   (NULL) so history never blocks a fresh review cycle and never replays as live.
4. Supersede-stale semantics: re-generation supersedes ONLY suggestions whose role
   set is no longer fully active (e.g. merged away) — an unchanged set replays
   exactly (reviewer decisions like `dismissed` are never clobbered).
5. Merge: target revision = CAS token; every source atomically superseded
   (terminal, traceable via `supersedes_role_id`); occurrences re-pointed
   (role_id + revision bump only — content untouched); collision on
   (target, scene, frame) aborts the whole operation; audit row records the exact
   transfer map; pending suggestions referencing merged roles are superseded.
6. Split: requires a T03 merge lineage (audit row + original superseded by THIS
   target); creates a NEW suggested role with the original's identity fields and
   moves exactly the recorded occurrences back (content untouched); original stays
   superseded — never a duplicate active role. Split of a plain T01 supersession is
   refused (no transferred evidence).
7. Confirm: CAS + audit; natural-key replay returns the same op while the role is
   confirmed; terminal roles refuse.
8. Read endpoints perform no commit (zero durable mutations proven by tests).

## Debug/fix iterations (real evidence)

1. `NOT NULL constraint failed: project.workspace_id` in `_seed_cluster` — foreign
   project used `workspace_id=other_ws.id` before flush; switched to the
   relationship form. Fixed; suite 8->10 passed.
2. Generate re-run returned 201 instead of 200 — `supersede_stale_suggestions`
   superseded even unchanged sets and `create_suggestion` could replay
   `applied`/`superseded` history. Redesigned (decisions 3+4): only stale sets are
   superseded, natural key detached on apply/supersede, replay gated to
   pending/dismissed. Fixed; suite 10->15 passed.
3. `AttributeError: 'str' object has no attribute 'id'` — `select(ObjectRole.id)`
   returns scalar strings; changed to a plain id set. Fixed; 15->21 passed.
4. Merge 500 — `MergeRequest` had no `video_item_id` though routes read
   `body.video_item_id`; added the field to Merge/Split/ConfirmRequest.
   Fixed; 21->24 passed.
5. `test_split_restores_original_with_evidence` collision — `_same_object_pair`
   already created the scene_b occurrence; seeded the edited occurrence on
   separate roles instead. Fixed.
6. Restart-test leftover cruft (`pytest.raises` on a never-raising expression)
   removed. Fixed; 24->25 passed (25/25).
7. mypy: 10 errors in new files — typed `_evidence(record: RoleRecord)`, direct
   `RoleData` import, `_strict_list`/`_rowcount` helpers, `_json_objects` narrowing.
   `Success: no issues found in 82 source files`.
8. ruff: 18 errors in new files (E501/W292/F401/B904/I001/UP032) — auto-fix +
   manual fixes (join-line comments from part-file concatenation split, long lines
   wrapped). `All checks passed!`.

## Validation — exact commands and results

All runs: `-p no:cacheprovider`, isolated basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t03-*` (MAX_PATH lesson).

```
1. Focused S08-T03 (25 tests, final):
   python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-focused-r8
   -> 25 passed, 19 warnings in 9.94s

2. Combined fast set (final state):
   python -m pytest tests/test_object_grouping.py tests/test_object_intelligence_domain.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_persistence_bootstrap.py \
     tests/test_durable_job_persistence.py tests/test_project_crud.py \
     tests/test_video_item_crud.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-final-r1
   -> 256 passed, 240 warnings in 116.74s
   (= T03 25 + T01 36 + T02 35 + persistence/project/video 160)

3. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-s05-final
   -> 41 passed, 41 warnings in 87.85s

4. Migration CLI round trip (fresh temp DB):
   upgrade head -> downgrade f2a3b4c5d6e7 -> upgrade head
   -> both tables present, version f3a4b5c6d7e8, downgrade drops both

5. Ruff (12 changed/new Python files):
   -> All checks passed!

6. Mypy: python -m mypy app -> Success: no issues found in 82 source files

7. git diff --check -> exit 0 (pre-existing CRLF advisories only)

8. git status --short -> 119 entries (baseline 113 + exactly 6 new T03 files)
```

## INCIDENT — MAIN motionforge.db touched during debugging and fully restored

- During a debugging reproduction (before the T03 test suite existed), a bare
  `TestClient(app)` (no conftest `_patch_project_root` fixture) was used to
  reproduce a route-level 500. The app lifespan bootstrapped the DEFAULT
  configuration database — the MAIN tree's `C:\Users\Admin\MotionForge2D\data\motionforge.db` —
  and upgraded it: size 311296 -> 417792 bytes, `alembic_version`
  `d5e6f7a8b9c0` -> `f3a4b5c6d7e8`, +4 S08 tables.
- Detection: protected-data comparison after implementation showed the drift.
- Restoration: the S01 pre-upgrade backup policy had created
  `motionforge.db.bak-20260816T091802-4174cef8` (311296 bytes) at the moment of
  the first upgrade. Verified the backup is the exact protected baseline
  (`alembic_version = d5e6f7a8b9c0`, 17 tables, no S08 tables) and restored it
  byte-exact over `motionforge.db`.
- Post-restore verification: 311296 bytes, version `d5e6f7a8b9c0`, 17 tables —
  identical to the T01/T02 protected baseline. The backup file itself was created
  by the app's own backup policy (a pre-existing artifact), not by this session.
- Root cause of the incident: debugging outside the pytest fixture. The fixture
  exists precisely to prevent this; all subsequent reproduction used pytest
  fixtures (isolated temp DBs). No production database was ever targeted after
  the restore, and the task's final protected-data gates pass (see below).

## Protected state (final comparison)

- MAIN `channels.json` SHA-256 (certutil):
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — IDENTICAL to T01/T02 recorded value. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes, `alembic_version = d5e6f7a8b9c0`,
  17 tables — UNCHANGED (restored, see incident above).
- MAIN git status: 48 entries (T02 end state 47 + the manager's
  `scripts/watch-s08-t03.sh` watcher script — not created by this session).
- No commit/push/deploy/merge/reset/checkout/restore/clean/stash/delete;
  all pre-existing uncommitted changes preserved.
- Worktree status: 119 entries = baseline 113 + exactly 6 new T03 files
  (3 app modules, 1 migration, 1 test suite, 1 route module); no stray files.

## Deviations and risks

1. Pairwise suggestions only (2 roles each). Cross-scene objects spanning 3+
   scenes yield one suggestion per pair; the reviewer merges incrementally.
   Deterministic, canonical ordering.
2. Split restores the original identity fields but creates a NEW role with
   status `suggested` (never auto-confirmed) — the superseded original stays
   terminal/traceable.
3. The T02 deterministic extractor names candidates by scene order
   (`subject_01`, `subject_02`, ...), so same-name grouping does not fire on
   its raw output; the cross-name spatial rule and future uniform naming
   exercise the high-confidence path. Extractor redesign is out of scope
   (forbidden by TASK.md).
4. `list_suggestions`/`list_operations` role filters are applied in Python
   after SQL filtering (JSON role sets cannot be SQL-indexed); fine for review
   queues, documented.
5. T01/T02 head-string expectation updates are required consequences of the
   T03 migration (same precedent as T01->T02).

## MANAGER VERIFICATION — 2026-08-16

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence (re-run by manager, not worker):
- `python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-mgr-focused2` -> **25 passed** in 9.86s
  (NOTE: first manager run showed 18 failed — root cause was MANAGER-side env contamination: MOTIONFORGE_DATABASE_URL was exported for a T02 migration check and persisted in the terminal session, redirecting test migrations. After `unset`, 25/25. Not a worker defect.)
- T01+T02 suites (s08t03-mgr-t01t02) -> **71 passed** in 42.96s
- S05 41-suite (s08t03-mgr-s05) -> **41 passed** in 86.51s
- Persistence/project/video regressions (s08t03-mgr-reg) -> **160 passed** in 64.42s
- Migration CLI round-trip (isolated subshell env, s08t03-mgr-migration.db): upgrade head -> downgrade f2a3b4c5d6e7 -> upgrade head -> final head **f3a4b5c6d7e8**; object_grouping_suggestion + object_role_operation present

Code audit (manager):
- Suggestions always created `pending`, never auto-confirmed; regeneration supersedes (never deletes) stale rows.
- Merge/split/confirm carry CAS/revision protection + operation audit rows with exact occurrence-transfer maps.
- Routes: 5 commit() sites all inside POST handlers (generate/dismiss/merge/split/confirm); GET suggestion/operation endpoints have zero commits (read-only).

INCIDENT (recorded honestly, worker self-reported in LOG/REPORT): during 500-debugging, a bare TestClient(app) repro (outside the conftest client fixture) let the lifespan run migrations against MAIN data/motionforge.db (311296 -> 417792 B). The worker detected it via the protected-data gate and restored byte-exact from the pre-run backup motionforge.db.bak-20260816T091802-4174cef8. Manager independently re-verified: current MAIN DB SHA-256 67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6 == backup SHA; content = alembic d5e6f7a8b9c0, 17 tables, object_role absent, 311296 B (matches P00 baseline). channels.json SHA dd7aae26...555 UNCHANGED. This is a process-safety deviation, fully remediated; all later repros used the pytest fixture. The lesson is enforced in T04-T06 prompts (never bare TestClient(app); always the conftest client fixture).

Protected state (manager re-verified): channels.json SHA dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555; MAIN DB content/bytes baseline-identical after restore.

Decision: T03 dependency released for S08-T04 under full-sprint manager protocol.

## CORRECTION ROUND C1 (Codex CHANGES_REQUESTED, finding C) — 2026-08-17

Same session lineage (fresh C1 worker session).  Worktree guard re-verified
(pwd/toplevel/branch codex/s08-integration/HEAD a43b20d...); status baseline
150 entries captured.  Fixes applied in THIS session; history preserved.

### What changed (finding C items)

1. **Current-generation grouping**: generation runs already filter roles by
   the explicit (video, source_generation) via `list_active_roles` and the
   suggestion natural key embeds the generation; added
   `test_cross_generation_isolation` proving gen-1/gen-2 runs never mix role
   sets and each suggestion row records its own `source_generation`.
2. **Stable role IDs**: suggestions and operations were already id-keyed;
   the advisory-content refresh on re-derivation now explicitly preserves
   role ids (only confidence/reasons follow changed evidence).
   `test_renamed_role_stable_id_preserved` proves: rename -> same suggestion
   id, same role ids, exact id-based replay (200), merge after rename still
   references the same stable ids, and the advisory content re-derives at
   the evidence band (0.6, different-names reason).
3. **Name never identity authority** (`app/services/object_grouping.py`
   calibration v2, evidence-first): a same-name pair that CO-OCCURS in time
   with a different footprint is NOT suggested; a disjoint-footprint pair is
   suggested only at low advisory 0.45 when temporally disjoint; different
   names with matching footprint + temporal disjointness -> 0.6; missing
   occurrence evidence -> no suggestion.  Tests: duplicate-name
   co-occurring/temporal-disjoint, adversarial name-spoof, adversarial
   different-names co-occurring, evidence-first different-name, missing
   evidence.
4. **Policy metadata exposed**: `GET /api/v2/object-intelligence/grouping/policy`
   (read-only) returns algorithm, algorithm_version, calibration_version
   (now "2"), review_threshold (0.35), advisory flag, confidence semantics
   and the advisory note; `GenerateResultData` carries
   `calibration_version` + the full `policy` object.
   Test: `test_policy_metadata_exposed`.
5. **Advisory only**: unchanged — suggestions stay `pending`; never
   auto-confirm/auto-merge (existing tests re-run green).
6. **Dismiss/merge/split/confirm/restart/concurrency/read-only GET**: all
   existing T03 tests re-run green (34/34) — no behavior removed.
7. **Repository replay semantics** (needed by item 2): suggestion
   equivalence now compares IDENTITY fields only (video/generation/role-id
   set/algorithm/version/scope/target); a pending suggestion whose derived
   confidence/reasons changed is refreshed in place (stable ids), while
   dismissed rows are NEVER refreshed (reviewer decision preserved) and
   applied/superseded rows stay non-replayable.

### Files touched this round (all already in T03 write scope)

- `app/services/object_grouping.py` — calibration v2 evidence-first rules,
  `GroupingPolicy` + `grouping_policy()` + `DEFAULT_CALIBRATION_VERSION`.
- `app/schemas/object_grouping.py` — `GroupingPolicyData`;
  `GenerateResultData` + `calibration_version` + `policy`.
- `app/api/routes/object_grouping.py` — GET `/grouping/policy`; generate
  response includes the policy.
- `app/persistence/object_grouping.py` — identity-only equivalence +
  pending advisory refresh (populate_existing re-read).
- `tests/test_object_grouping.py` — 2 expectation updates (0.35->0.45,
  0.55->0.6) + 9 new C1 tests (34 total).

No schema/migration change this round (policy is metadata; no DDL touched),
so no migration round-trip was required.

### Debug iterations (real evidence)

1. `test_renamed_role_stable_id_preserved` failed 409 — re-generation after
   rename conflicted because the equivalence check compared derived
   confidence/reasons.  Fix: identity-only equivalence + pending refresh.
2. mypy `"None" has no attribute "id"` at the refresh re-read — narrowed
   `existing` to None; introduced a `refreshed` local.  `Success: no issues
   found in 86 source files`.
3. Replay re-read staleness: direct UPDATE followed by ORM select could
   return the stale identity-mapped row — re-read uses
   `populate_existing=True`.

### Validation (fresh isolated roots, cache disabled, shallow basetemps)

```
1. Focused T03 (34 tests):
   python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-focused-r4
   -> 34 passed, 22 warnings in 12.57s

2. T01 + T02 suites:
   python -m pytest tests/test_object_intelligence_domain.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-t01t02
   -> 80 passed, 79 warnings in 44.11s

3. S03 project/video regressions (head f5a6b7c8d9e0):
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
     tests/test_project_crud.py tests/test_video_item_crud.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-reg-s03
   -> 160 passed, 154 warnings in 74.10s

4. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-s05
   -> 41 passed, 41 warnings in 92.10s

5. Ruff (5 changed files) -> All checks passed!
6. Mypy -> Success: no issues found in 86 source files
7. git diff --check -> exit 0 (pre-existing CRLF advisories only)
8. git status --short -> 150 entries (identical to the C1 session-start
   baseline; no new files, no strays)
```

### Protected state (unchanged, re-verified)

- MAIN channels.json SHA-256:
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db: 311296 bytes, alembic_version d5e6f7a8b9c0,
  17 tables.
- No commit/push/reset/checkout/restore/clean/stash/delete; MAIN and other
  worktrees untouched.  No bare TestClient used outside pytest fixtures.

## MANAGER VERIFICATION — T03 C1 (2026-08-17)

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW**

Manager independent: focused T03 34/34 (12.55s, s08t03c1-mgr-focused); T01+T02 80/80 (43.50s); S03 project/video 160/160 (72.80s); S05 41/41 (92.63s). Code audit: GET /policy exposes algorithm/calibration version + confidence semantics + review threshold (backend-authoritative); suggestions filter by explicit source_generation; stable role ids preserved in suggestions/operations; duplicate-name/renamed-role/cross-generation/adversarial tests present in suite (34 total). No schema change (no migration needed - noted). Protected unchanged (channels.json dd7aae...555, MAIN DB 311296 B). Scope: INTEG 150 unchanged (0 new files).

Decision: T03-C1 released; S08-T05 correction may open.

## CORRECTION ROUND C1 — PASS 2 (Codex re-review of finding C, sprint exit) — 2026-08-17

Same worker lineage; worktree guard re-verified (pwd/toplevel/branch
codex/s08-integration/HEAD a43b20d...; status baseline 150 entries).
Append-only; status stays SUBMITTED.  No PM_REVIEW.md changes.

### Audit result: items already satisfied by pass 1 (re-verified green)

1. Current-generation grouping: `list_active_roles` filters by the explicit
   (video, source_generation); natural key embeds the generation;
   `test_cross_generation_isolation` re-run green.
2. Stable role IDs: suggestions/operations keyed by uuid5 role ids
   (T02-C1 B5 surface); `test_renamed_role_stable_id_preserved` green.
3. Policy metadata via API: `GET /grouping/policy` + generate payload
   (algorithm/version, calibration_version=2, review_threshold 0.35,
   advisory, semantics) — `test_policy_metadata_exposed` green.
4. Advisory only: generation creates `pending` rows only; split creates
   `suggested`; no auto-confirm path (all 36 tests re-run green).
5. Adversarial/duplicate/renamed/cross-generation tests: present from
   pass 1 (9 tests), re-run green.
6. Merge/split/confirm explicit + CAS + idempotency + audit: green
   (stale->409, replay->same op row, one audit row, transfer map exact).
7. Read-only GET: `test_get_endpoints_zero_durable_mutations` green.
8. Evidence never rewritten/deleted: occurrence content byte-identical
   after merge/split; supersedes_role_id kept; no DELETE paths (green).
9. Duplicate/concurrent/restart: concurrent merge + restart replay green.
10. R01/T02/SAM2.1 surfaces preserved: full suites re-run green (below).

### New work in pass 2 (real gaps found)

A. **Concurrent-duplicate CAS races now replay deterministically.**
   `apply_merge`/`apply_split`/`apply_confirm` previously caught only
   `IntegrityError` in the race path; a loser whose CAS UPDATE hit the
   winner's already-bumped revision raised `RoleConflictError` (409)
   instead of replaying the committed operation.  The three handlers now
   catch `(RoleConflictError, IntegrityError)`, roll back, and replay the
   committed operation when its natural key exists; a genuine stale
   revision with no operation still re-raises -> 409.
   New test: `test_concurrent_split_single_operation_and_single_active_role`
   (two threads + barrier; outcomes exactly {created, replayed}; exactly
   one split op row; exactly one created role; active roles == 2).

B. **Cross-boundary ownership now proven ZERO-MUTATION.**
   New test `test_boundary_violations_zero_mutation`: cross-workspace,
   cross-project, cross-video and cross-source-generation merge attempts +
   a cross-generation split attempt all return 409 and leave op counts,
   suggestion counts, every role (status, revision) and every occurrence
   (role_id, revision) byte-identical to the pre-attempt snapshot.

### Files touched (all within T03 write scope, no new files)

- `app/persistence/object_grouping.py` — 3 race handlers extended to
  (RoleConflictError, IntegrityError) with replay fallback.
- `tests/test_object_grouping.py` — +2 tests (36 total); 3 E501 line wraps.

### Validation — exact commands and verbatim results (fresh roots, cache disabled)

```
1. Focused T03 (36 tests):
   python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1b-focused-r4
   -> 36 passed, 24 warnings in 13.86s

2. T01 + T02 (4 files):
   python -m pytest tests/test_object_intelligence_domain.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1b-t01t02
   -> 81 passed, 79 warnings in 54.04s

3. R01 suites:
   python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py \
     tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1b-r01
   -> 18 passed, 9 warnings in 5.91s

4. Migration round-trip (isolated subshell, MOTIONFORGE_DATABASE_URL set
   only inside the subshell, then unset; verified unset afterwards):
   export MOTIONFORGE_DATABASE_URL=sqlite:///.../s08t03-c1b-mig/mig.db
   python -m alembic upgrade head
     -> Running upgrade f2a3b4c5d6e7 -> f3a4b5c6d7e8 (S08-T03 grouping)
     -> Running upgrade f3a4b5c6d7e8 -> f4a5b6c7d8e9 (S08-T05 correction)
     -> Running upgrade f4a5b6c7d8e9 -> f5a6b7c8d9e0 (T02-C1 artifact)
   python -m alembic downgrade f4a5b6c7d8e9
     -> Running downgrade f5a6b7c8d9e0 -> f4a5b6c7d8e9
   python -m alembic upgrade head
     -> Running upgrade f4a5b6c7d8e9 -> f5a6b7c8d9e0
   -> final version f5a6b7c8d9e0; object_role_artifact present;
      object_grouping_suggestion + object_role_operation present;
      env var unset (grep count 0).

5. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1b-s05
   -> 41 passed, 41 warnings in 90.44s

6. S02 durable regressions:
   python -m pytest tests/test_durable_job_persistence.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1b-s02
   -> 47 passed, 47 warnings in 22.55s

7. Ruff (5 changed files) -> All checks passed!
8. Mypy -> Success: no issues found in 86 source files
9. git diff --check -> exit 0 (pre-existing CRLF advisories only)
10. git status --short -> 150 entries (identical to baseline; no new files,
    no strays)
```

### Protected state (re-verified, unchanged)

- MAIN channels.json SHA-256:
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db: 311296 bytes, alembic_version d5e6f7a8b9c0,
  17 tables (mtime no-op touch by external process; size/content identical).
- SAM2.1 checkpoint read-only, never touched:
  `C:\Users\Admin\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt`
  898083611 bytes, mtime 2026-07-29 21:06 (pre-sprint).
- No commit/push/reset/checkout/restore/clean/stash/delete; no bare
  TestClient outside pytest fixtures; no background children.

## CORRECTION ROUND C2 — Codex CHANGES_REQUESTED (sprint exit), finding: CURRENT-GENERATION GROUPING SUGGESTIONS — 2026-08-18

Same worker lineage; worktree guard re-verified (pwd/toplevel/branch
codex/s08-integration/HEAD a43b20d...; status baseline 161 entries
INTENTIONAL dirty set — never reset/checkout/restore/clean/stash).
Append-only; status stays SUBMITTED.  PM_REVIEW.md / TASK.md untouched.

### Acceptance — mapping to changes

1. Public suggestion list defaults to ONLY current-generation suggestions:
   `ObjectGroupingRepository.list_suggestions` gained `source_generation`
   (exact view) + `only_current` (backend-authoritative current default;
   cross-video current resolution per video item, mirroring T01-C2
   `list_roles`).  `GET /grouping/suggestions` defaults `only_current=True`
   when no explicit `source_generation` is supplied.
2. Source replacement 1 -> 2 hides generation-1 suggestions:
   `test_suggestion_list_current_only_and_source_replacement` drives a real
   source artifact + completed DISCOVER_OBJECTS job per generation (backend
   `current_generation` advance 1 -> 2); the current list shows ONLY the
   gen-2 suggestion, and the gen-1 suggestion is absent.
3. Stale suggestion/role actions fail closed ZERO mutation:
   `dismiss_suggestion` now asserts the suggestion is current;
   `apply_merge` asserts target/sources (and the optional suggestion) are
   current; `apply_split`/`apply_confirm` assert the target/role is current.
   All guards run BEFORE any write.
   `test_stale_suggestion_and_role_fail_closed_zero_mutation`: stale dismiss /
   stale merge / stale merge-by-suggestion / stale confirm all return 409 with
   an identical durable-state snapshot (zero mutation); current actions still
   succeed (guard is generation-specific).
4. Historical inspection = explicit separate contract:
   `GET /grouping/suggestions?source_generation=N` (scope `historical`, the
   ONLY way to view a non-current generation); suggestion detail returns 404
   under the current scope for a stale suggestion unless an explicit matching
   `source_generation` is supplied (no existence leak).  Never mixed.
5. Generate is current-generation gated:
   `ObjectGroupingRepository.assert_generation_current` + route enforcement —
   `POST /grouping/suggestions/generate` for a non-current generation returns
   409 with ZERO mutation (`test_generate_stale_generation_fails_closed`).
6. T03-C1 guarantees preserved (all re-run green): stable role IDs remain
   the identity authority; policy metadata still exposed (/grouping/policy +
   generate payload); advisory only — no auto-confirm/auto-merge.

### Files touched (all in T03 write scope; no new files, no schema change)

- `app/persistence/object_grouping.py` — `current_generation` /
  `assert_generation_current` / `_assert_suggestion_current` /
  `_assert_role_current` helpers (reuse the T01-C2 `ObjectIntelligenceRepository`
  current-generation surface over the SAME session); `list_suggestions`
  (`source_generation`/`only_current` incl. cross-video current map);
  `get_suggestion` (`only_current`/`source_generation`, stale -> 404);
  `dismiss_suggestion` + `apply_merge` + `apply_split` + `apply_confirm`
  stale current-guards (zero mutation).
- `app/api/routes/object_grouping.py` — generate current-gate; list
  current-default + scope/current_generation echo + explicit generation;
  get detail generation param.
- `app/schemas/object_grouping.py` — `SuggestionListResponse` + `scope`,
  `source_generation`, `current_generation`.
- `tests/test_object_grouping.py` — 36 -> 39 tests: seed helpers
  (`_seed_video_source`, `_seed_completed_discover_job`), rewritten
  `test_cross_generation_isolation` (source-replacement model), +3 C2
  acceptance tests (list current-only/source-replacement,
  stale-fail-closed-zero-mutation, generate-stale-409).

### Debug iterations (real evidence)

1. `test_cross_generation_isolation` first failed 409 after the current-gate —
   expected: generating for the stale gen-2 with current gen-1; rewrote the
   test to drive backend source replacement (artifact sha + completed job).
2. `KeyError: 'scope'` — the schema edit script was written but not executed;
   re-ran it, `scope: str` present in SuggestionListResponse, suite 39/39.
3. ruff SIM102 nested-if — restructured the stale/current role scan to flat
   elif; All checks passed.

### Validation — exact commands and verbatim results (fresh roots, cache disabled)

```
1. Focused T03 (39 tests):
   python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c2-focused-r4
   -> 39 passed, 53 warnings in 16.11s

2. T01-T05 combined regression (8 files incl sam2):
   python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_object_correction.py \
     tests/test_object_correction_api.py tests/test_sam2_provider.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c2-t01t05
   -> 186 passed, 370 warnings in 112.48s

3. R01 suites:
   python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py \
     tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c2-r01
   -> 18 passed, 18 warnings in 6.11s

4. Migration round-trip (isolated subshell, MOTIONFORGE_DATABASE_URL set only
   inside the subshell, unset verified after):
   python -m alembic upgrade head
     -> Running upgrade f5a6b7c8d9e0 -> f6a7b8c9d0e1 (S08-T05-C1 media supersession)
   python -m alembic downgrade f5a6b7c8d9e0
     -> Running downgrade f6a7b8c9d0e1 -> f5a6b7c8d9e0
   python -m alembic upgrade head
     -> Running upgrade f5a6b7c8d9e0 -> f6a7b8c9d0e1
   -> final version f6a7b8c9d0e1; object_role_artifact + grouping tables
      present; env var unset (grep count 0).  No schema change by C2 itself.

5. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c2-s05
   -> 41 passed, 81 warnings in 93.02s

6. S02 durable regressions:
   python -m pytest tests/test_durable_job_persistence.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c2-s02
   -> 47 passed, 94 warnings in 24.16s

7. Ruff (4 changed files) -> All checks passed!
8. Mypy -> Success: no issues found in 86 source files
9. git diff --check -> exit 0 (pre-existing CRLF advisories only)
10. git status --short -> 161 entries (identical to baseline; no new files,
    no strays)
```

### Protected state (re-verified, unchanged)

- MAIN channels.json SHA-256:
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db: 311296 bytes, alembic_version d5e6f7a8b9c0,
  17 tables.
- SAM2.1 checkpoint read-only, never touched:
  `C:\Users\Admin\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt`
  898083611 bytes, SHA-256
  `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318`,
  mtime 2026-07-29 21:06.
- No commit/push/reset/checkout/restore/clean/stash/delete; no bare
  TestClient outside pytest fixtures; no background children.
