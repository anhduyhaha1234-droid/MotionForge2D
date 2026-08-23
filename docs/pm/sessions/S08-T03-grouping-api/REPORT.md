# S08-T03 — Cross-scene Grouping and Curation API: Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager/Codex sprint-exit review owns approval)
**Hermes session:** `20260816_151439_21e306` (fresh S08-T03 worker session)
**Started:** 2026-08-16
**Submitted:** 2026-08-16
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-T02 manager-verified (`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`)

## Outcome

Reviewable cross-scene grouping suggestions plus explicit durable
merge/split/confirm operations for Object Roles, under the isolated
`/api/v2/object-intelligence/grouping` namespace.  Suggestions are durable
rows that ALWAYS start `pending` and carry confidence, review reasons and
provenance (algorithm/version); they never auto-confirm.  Merge/split/confirm
are explicit mutations with CAS/revision protection, content-derived natural
keys + optional client idempotency keys (duplicate/concurrent requests and
restart replay the SAME operation — never a second mutation) and a one-row
audit history recording target/sources/created roles and the exact
transferred-occurrence map.  Operations fail closed across workspace/project/
video/source-generation boundaries; superseded roles and evidence stay
traceable (nothing is deleted, occurrence content is never rewritten);
GET/list/detail endpoints are read-only and expose the review reasons.

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `migrations/versions/f3a4b5c6d7e8_object_grouping_schema.py` | NEW reversible migration (down `f2a3b4c5d6e7`): `object_grouping_suggestion` + `object_role_operation` (CHECKs, RESTRICT FKs, partial-unique natural/idempotency indexes, lookup indexes; downgrade drops both in FK order). |
| `app/persistence/models.py` | +`ObjectGroupingSuggestion`, +`RoleOperation` ORM models, +`GROUPING_SUGGESTION_STATUSES`/`GROUPING_SCOPES`/`ROLE_OPERATION_TYPES` constants, `__all__` entries. |
| `app/persistence/object_grouping.py` | NEW repository: suggestions (natural-key idempotent create, list/get, CAS dismiss, stale-set supersede with natural-key detach), merge/split/confirm with atomic CAS predicates, evidence move without content rewrite, collision fail-closed, audit rows, fresh-transaction replay on races, fail-closed ownership, read-only list/get. |
| `app/services/object_grouping.py` | NEW PURE deterministic grouping algorithm (`role-fingerprint` v1): name + IoU rules (0.9/0.65/0.35), cross-name ambiguity (0.55), noise floor 0.35, canonical pairwise output. |
| `app/schemas/object_grouping.py` | NEW DTOs incl. GenerateResult, SuggestionData (confidence/reasons/provenance), OperationData (transfer map), Merge/Split/ConfirmResult. |
| `app/api/routes/object_grouping.py` | NEW router `/api/v2/object-intelligence/grouping` (generate 201/200, read-only suggestions list/detail, dismiss, merge/split/confirm 201/200-replay, read-only operations list/detail; 404/409/422 mapping; rollback before raise). |
| `app/api/app.py` | one import + one `include_router` line. |
| `tests/test_object_grouping.py` | NEW focused suite — 25 tests covering every acceptance item below. |
| `tests/test_persistence_bootstrap.py` | required head-revision/table-set expectation updates (S08_HEAD_TABLES +2, head `f3a4b5c6d7e8`, ancestry) — T01/T02 precedent. |
| `tests/test_durable_job_persistence.py` | required table-set expectation +2 tables — T01/T02 precedent. |
| `tests/test_object_intelligence_domain.py` | required head-string update (`f2a3b4c5d6e7` -> `f3a4b5c6d7e8`) — T02 precedent. |
| `tests/test_object_extraction.py` | required head-string update (same precedent). |

No changes to: deps.py, frontend/, legacy object code, S05/S06 contracts,
TASK.md, sprint contract, PM_REVIEW.md, channels.json, data/, databases,
fixtures, MAIN or other worktrees.  `git status --short` = 119 entries
(baseline 113 + exactly 6 new T03 files); no stray files.

## Acceptance criteria — evidence (test -> what it proves)

| AC | Evidence |
|---|---|
| Deterministic grouping | `test_grouping_algorithm_deterministic_same_inputs` (identical inputs -> identical suggestions), `test_algorithm_output_is_pairwise_and_canonical`, `test_normalize_name_folds_whitespace_and_case` |
| Same object across scenes | `test_same_object_across_scenes_high_confidence` (0.9, reasons carry `same-normalized-name` + `spatial-footprint-consistent-across-scenes`) |
| Different object across scenes | `test_different_object_across_scenes_low_confidence` (same name, disjoint footprints -> 0.35 low-confidence suggestion, never confirmed); `test_different_names_distinct_footprints_no_suggestion` (below threshold -> no row) |
| Ambiguity | `test_ambiguity_different_names_matching_footprint` (0.55, `occurrences-temporally-disjoint-ambiguity`) |
| Suggestions carry confidence/reasons/provenance, never auto-confirm | `test_generate_durable_pending_and_idempotent` (status `pending`, confidence 0.9, reasons non-empty, algorithm/version exposed; roles stay `suggested` after generation); `test_split_restores_original_with_evidence` (split role is `suggested`, not confirmed) |
| Generation idempotent + stale supersede | `test_generate_durable_pending_and_idempotent` (re-run -> 200, same suggestion ids, created_count 0); `test_generate_supersedes_stale_pending_when_roles_change` (dismissed row preserved on identical re-run; merged-away set -> superseded + natural-key detached; no fresh pair) |
| Merge explicit mutation + CAS + audit | `test_merge_moves_evidence_supersedes_source_and_audits` (target revision 1->2, source superseded with `supersedes_role_id`, occurrences re-pointed with content identical, op row with exact transfer map, exactly one op); `test_merge_cas_stale_revision_conflict` (stale CAS -> 409) |
| Evidence never rewritten/deleted | same merge test (confidence/bbox/review_state/reasons_json byte-identical after move) |
| Merge fail-closed boundaries | `test_merge_cross_project_video_generation_fail_closed` (409 x4), `test_merge_self_and_terminal_conflicts` (409), `test_merge_occurrence_collision_fails_closed` (409, zero mutations) |
| Merge idempotency/concurrency/restart | `test_merge_cas_stale_revision_conflict` (natural-key replay -> 200 same op), `test_concurrent_merge_single_operation_and_single_active_role` (2 threads + barrier -> exactly 1 op row, 1 active role), `test_restart_replay_never_duplicates_active_roles` (fresh sessions replay merge AND split; active-role count stays 1; op count stays 2) |
| Split explicit + lineage + no duplicate active roles | `test_split_restores_original_with_evidence` (new suggested role, original identity, occurrence moved back content-identical, original stays superseded, exactly one active "Hero"); `test_split_requires_merge_lineage` (plain T01 supersession refused 409); `test_split_stale_revision_and_duplicate_replay` (stale 409; replay 200 same created role; op count 2) |
| Confirm explicit + audit + idempotent | `test_confirm_durable_audited_and_idempotent` (confirmed + op row; replay 200 same op, zero new rows); `test_confirm_stale_revision_and_terminal_conflict` (terminal role 409) |
| Duplicate/concurrent/restart never duplicate active roles | concurrency + restart tests above; op/suggestion counts asserted after every replay |
| Read-only GET + review reasons | `test_get_endpoints_zero_durable_mutations` (suggestion/operation counts + role revisions identical before/after GETs; detail exposes `reasons`; unknown id 404) |
| Ownership fail-closed | `test_repo_cross_workspace_fails_closed` (SuggestionNotFoundError / RoleNotFoundError), cross-project/video/generation merge tests |
| Migration | `test_migration_round_trip_grouping_surfaces` (upgrade/downgrade/upgrade; CHECKs + partial unique index present; head `f3a4b5c6d7e8`); `test_grouping_constraints_real` (bad status CHECK fires); CLI round trip (see LOG) |

## Validation — exact commands and results

All runs: `-p no:cacheprovider`, isolated basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t03-*` (Windows MAX_PATH lesson).

```
1. Focused S08-T03:
   python -m pytest tests/test_object_grouping.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-focused-r8
   -> 25 passed, 19 warnings in 9.94s

2. T01 + T02 + S03 persistence suites (final state):
   python -m pytest tests/test_object_grouping.py tests/test_object_intelligence_domain.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py tests/test_persistence_bootstrap.py \
     tests/test_durable_job_persistence.py tests/test_project_crud.py \
     tests/test_video_item_crud.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-final-r1
   -> 256 passed, 240 warnings in 116.74s
   (T03 25 + T01 36 + T02 35 + persistence/project/video 160)

3. S05 preservation suite (SHALLOW basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-s05-final
   -> 41 passed, 41 warnings in 87.85s

4. Migration CLI round trip (fresh temp DB):
   upgrade head -> downgrade f2a3b4c5d6e7 -> upgrade head
   -> both grouping tables present; version f3a4b5c6d7e8; downgrade drops both.

5. Ruff (all changed/new Python files) -> All checks passed!
6. Mypy -> Success: no issues found in 82 source files
7. git diff --check -> exit 0 (pre-existing CRLF advisories only)
8. git status --short -> 119 entries (baseline 113 + 6 new T03 files), no strays
```

## Isolation and protected state

- All tests/migrations used NEW isolated roots and databases (pytest tmp /
  shallow basetemps).  The worktree `alembic.ini` still sets no URL.
- MAIN `channels.json` SHA-256 (certutil):
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — IDENTICAL to the T01/T02 recorded value. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes, `alembic_version = d5e6f7a8b9c0`,
  17 tables — matches the T01/T02 protected baseline (see incident below).
- MAIN git status: 48 entries (T02 end state 47 + the manager's
  `scripts/watch-s08-t03.sh` watcher script, not created by this session).
- No commit/push/deploy/reset/checkout/restore/clean/stash/delete; all
  pre-existing uncommitted changes preserved.

## Incident (recorded honestly, fully remediated)

A debugging reproduction of a route-level 500 ran a bare `TestClient(app)`
without the conftest `_patch_project_root` fixture; the app lifespan
bootstrapped the DEFAULT configuration database — the MAIN tree's
`data/motionforge.db` — and upgraded it (311296 -> 417792 bytes,
`d5e6f7a8b9c0` -> `f3a4b5c6d7e8`, +4 S08 tables).  The S01 pre-upgrade
backup policy artifact (`motionforge.db.bak-20260816T091802-4174cef8`,
311296 bytes) was verified to be the exact protected baseline and restored
byte-exact over the live file.  Post-restore: 311296 bytes, version
`d5e6f7a8b9c0`, 17 tables — identical to the T01/T02 baseline.  All
subsequent debugging used pytest fixtures (isolated temp DBs).  Full detail
in LOG.md "INCIDENT" section.  The final protected-data gates pass.

## Deviations and risks

1. **Pairwise suggestions only** (2 roles per suggestion).  Objects spanning
   3+ scenes yield one suggestion per pair; the reviewer merges
   incrementally.  Deterministic canonical ordering; documented in the
   service module.
2. **Split creates a NEW suggested role** with the original's identity
   fields; the superseded original stays terminal (traceable).  Split never
   auto-confirms; the reviewer confirms explicitly.  Split of a plain T01
   supersession (no T03 merge lineage / no transferred evidence) is refused
   with 409 — it would otherwise create an empty duplicate role.
3. **T02 extractor naming** (`subject_01`, `subject_02` by scene order) means
   same-name grouping does not fire on raw T02 output; the cross-name spatial
   rule (0.55) covers matching footprints and future uniform naming exercises
   the high-confidence path.  Extractor redesign is FORBIDDEN by TASK.md.
4. **Role filters on list endpoints** are applied in Python after SQL
   filtering (JSON role sets are not SQL-indexable); appropriate for review
   queues, documented in the repository.
5. **No UI work** — T04 owns the gallery; this API is the contract.
6. Head-string updates in T01/T02 test files are required consequences of
   the T03 migration (same precedent as T01->T02).

## Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` — T03 deliverables complete and
verified; Codex sprint-exit review owns APPROVED/CLOSED.


## CORRECTION ROUND C1 — Codex CHANGES_REQUESTED (sprint exit), finding C — 2026-08-17

Status remains **SUBMITTED** (never APPROVED).  All finding-C items fixed in
this session; full history preserved (LOG.md is append-only).

### Finding C — current-generation grouping policy

| Item | Fix + evidence |
|---|---|
| C1 group ONLY the explicit current video/source generation | Generation runs filter roles by (video, `source_generation`) in `list_active_roles`; the suggestion natural key embeds the generation. `test_cross_generation_isolation`: gen-1 and gen-2 runs each produce exactly their own pair, suggestion rows record their own `source_generation`, and the role sets never mix. |
| C2 preserve stable role IDs in every suggestion and operation | Suggestions/operations were already id-keyed (uuid5 role ids from T02-C1 B5). `test_renamed_role_stable_id_preserved`: after a rename the SAME suggestion row replays (200), role ids unchanged, merge after rename references the same stable ids; `test_api_outputs_carry_stable_role_ids` (T02) still green. |
| C3 appearance/track evidence may influence; display name never identity authority | Calibration v2 evidence-first rules in `app/services/object_grouping.py`: same-name pairs that CO-OCCUR with different footprints are NOT suggested; disjoint-footprint pairs suggested only at advisory 0.45 when temporally disjoint; different-name + matching footprint + temporal disjointness -> 0.6; missing occurrence evidence -> no suggestion. Tests: `test_duplicate_name_cooccurring_no_suggestion`, `test_adversarial_name_spoof_cannot_force_merge`, `test_adversarial_different_names_cooccurring_no_suggestion`, `test_evidence_first_different_name_consistent_footprint`, `test_missing_occurrence_evidence_no_suggestion`, `test_duplicate_name_temporal_disjoint_low_confidence`. |
| C4 expose grouping policy metadata | `GET /api/v2/object-intelligence/grouping/policy` (read-only): algorithm `role-fingerprint`, algorithm_version `1`, calibration_version `2`, review_threshold `0.35`, advisory `true`, confidence semantics, note. `GenerateResultData` carries `calibration_version` + `policy`. `test_policy_metadata_exposed`. |
| C5 advisory only, never auto-confirm/auto-merge | Unchanged behavior; all existing never-auto-confirm assertions re-run green (34/34). |
| C6 preserve dismiss/merge/split/confirm/restart/concurrency/read-only GET | All 25 original tests re-run green in the 34-test suite (no behavior removed). |
| C7 new tests | duplicate-name (2), renamed-role (1), cross-generation (1), adversarial (2), evidence-first (1), missing-evidence (1), policy (1) — 9 new tests. |

### Supporting repository semantics (enabler for C2/C3)

- Suggestion equivalence now compares IDENTITY fields only
  (video/generation/role-id set/algorithm/version/scope/target).  Derived
  confidence/reasons are refreshed in place for a `pending` suggestion when
  re-derived evidence changes (stable ids; advisory content follows
  evidence); `dismissed` rows are never refreshed (reviewer decisions
  preserved); `applied`/`superseded` rows remain non-replayable.
- Re-read after the refresh uses `populate_existing` (no stale
  identity-map values).

### Validation — exact commands and results (fresh isolated roots, cache disabled)

```
1. Focused T03 (34): 34 passed, 22 warnings in 12.57s
   --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-focused-r4
2. T01+T02 (3 files): 80 passed, 79 warnings in 44.11s
   --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-t01t02
3. S03 project/video (4 files, head f5a6b7c8d9e0): 160 passed, 154 warnings in 74.10s
   --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-reg-s03
4. S05 suite (7 files, SHALLOW basetemp): 41 passed, 41 warnings in 92.10s
   --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t03-c1-s05
5. Ruff (5 changed files): All checks passed!
6. Mypy: Success: no issues found in 86 source files
7. git diff --check: exit 0 (pre-existing CRLF advisories only)
8. git status --short: 150 entries (identical to C1 baseline; no new files)
```

No schema/migration change this round (policy metadata only) — migration
round-trip not required.

### Protected state (re-verified, unchanged)

- MAIN channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db 311296 bytes, d5e6f7a8b9c0, 17 tables
- No commit/push/reset/checkout/restore/clean/stash/delete; no bare
  TestClient outside the conftest fixture; no background children.

### Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged) — C1 correction round
complete; Codex sprint-exit review owns APPROVED/CLOSED.


## CORRECTION ROUND C1 — PASS 2 — Codex re-review of finding C (sprint exit) — 2026-08-17

Status remains **SUBMITTED** (never APPROVED).  Full history preserved
(LOG.md append-only).  This pass closed the two remaining gaps found in the
re-review; every other finding-C item was already implemented in pass 1 and
is re-verified green below.

### Gap A — concurrent-duplicate CAS race could 409 instead of replay (FIXED)

`apply_merge`/`apply_split`/`apply_confirm` race handlers caught only
`IntegrityError`.  Under a genuine two-thread duplicate, the loser could hit
the winner's already-bumped CAS revision and raise `RoleConflictError`
(409) instead of replaying the committed operation.  All three handlers now
catch `(RoleConflictError, IntegrityError)`, roll back to a fresh
transaction, and replay the committed operation when its natural key exists;
a genuine stale revision with no operation still re-raises `RoleConflictError`
-> 409 (existing stale-revision tests unchanged, green).
Evidence: `test_concurrent_split_single_operation_and_single_active_role`
(threads + barrier; outcomes exactly {created, replayed}; exactly one split
op row; exactly one created role; active roles == 2) and the existing
concurrent-merge + restart-replay tests (exactly one op, one active role).

### Gap B — cross-boundary ownership now proven zero-mutation (FIXED)

New `test_boundary_violations_zero_mutation`: cross-workspace,
cross-project, cross-video and cross-source-generation merge attempts plus a
cross-generation split attempt all return 409, and the post-attempt durable
state (operation count, suggestion count, every role status/revision, every
occurrence role_id/revision) is byte-identical to the pre-attempt snapshot —
fail-closed with ZERO mutation.

### Re-verified (finding-C items 1-10, pass-1 implementation)

| Item | Evidence (re-run green in the 36-test suite) |
|---|---|
| 1 current-generation only | `test_cross_generation_isolation` — gen-1/gen-2 sets never mix; suggestion rows carry their own `source_generation` |
| 2 stable ids; names never joins/authority | `test_renamed_role_stable_id_preserved`, `test_duplicate_name_*`, `test_adversarial_*`, `test_evidence_first_different_name_consistent_footprint`, `test_missing_occurrence_evidence_no_suggestion` |
| 3 policy metadata via API | `test_policy_metadata_exposed` (GET /grouping/policy + generate payload: algorithm, algorithm_version=1, calibration_version=2, review_threshold=0.35, advisory, semantics) |
| 4 advisory only, no auto-confirm/merge | `test_generate_durable_pending_and_idempotent` (roles stay suggested), `test_split_restores_original_with_evidence` (created role suggested) |
| 5 adversarial tests | duplicate names (2), renamed (1), cross-generation (1), cross-boundary zero-mutation (1), name-spoof (1), co-occurring different names (1), evidence-first (1), missing evidence (1) |
| 6 explicit mutations + CAS + idempotency + audit | stale->409 (merge/split/confirm), replay->same op row, exactly one audit row per op, transfer map exact (merge/split tests) |
| 7 read-only GET + review reasons | `test_get_endpoints_zero_durable_mutations` (counts + revisions identical; reasons exposed; 404 for unknown) |
| 8 evidence never rewritten/deleted | occurrence content byte-identical after merge (`test_merge_moves_evidence_supersedes_source_and_audits`) and split (`test_split_restores_original_with_evidence`); supersedes_role_id kept; no DELETE paths |
| 9 duplicate/concurrent/restart -> no duplicate active roles | `test_concurrent_merge_...`, `test_concurrent_split_...`, `test_restart_replay_never_duplicates_active_roles` |
| 10 preserve R01/T02/SAM2.1 | R01 18/18, T02 3 suites green, SAM2.1 checkpoint read-only verified (below) |

### Validation — exact commands and results (fresh isolated roots, cache disabled, shallow basetemps)

```
1. Focused T03 (36): 36 passed, 24 warnings in 13.86s   [s08t03-c1b-focused-r4]
2. T01 + T02 (4 files): 81 passed, 79 warnings in 54.04s [s08t03-c1b-t01t02]
3. R01 (2 files): 18 passed, 9 warnings in 5.91s        [s08t03-c1b-r01]
4. Migration round-trip (isolated subshell, MOTIONFORGE_DATABASE_URL set
   inside subshell only, unset verified after): upgrade head ->
   downgrade f4a5b6c7d8e9 -> upgrade head; final head f5a6b7c8d9e0;
   object_role_artifact + grouping tables present
5. S05 (7 files, SHALLOW): 41 passed, 41 warnings in 90.44s [s08t03-c1b-s05]
6. S02 durable: 47 passed, 47 warnings in 22.55s        [s08t03-c1b-s02]
7. Ruff (5 files): All checks passed!
8. Mypy: Success: no issues found in 86 source files
9. git diff --check: exit 0 (pre-existing CRLF advisories only)
10. git status --short: 150 entries (baseline identical; no new files)
```

### Protected data (re-verified, unchanged)

- MAIN channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db 311296 bytes, d5e6f7a8b9c0, 17 tables
- SAM2.1 checkpoint read-only never touched:
  `C:\Users\Admin\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt`
  (898083611 bytes, mtime 2026-07-29 21:06)
- No commit/push/reset/checkout/restore/clean/stash/delete; no bare
  TestClient outside the conftest fixture; no background children.

### Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged) — pass 2 of the C1
correction round complete; Codex sprint-exit review owns APPROVED/CLOSED.

## CORRECTION ROUND C2 — Codex CHANGES_REQUESTED (sprint exit), finding: CURRENT-GENERATION GROUPING SUGGESTIONS — 2026-08-18

Status remains **SUBMITTED** (never APPROVED).  All history preserved
(LOG.md append-only); PM_REVIEW.md / TASK.md untouched.  No schema change.

### The gap (what C2 found)

The public suggestion list did not filter by generation: after a source
replacement (generation 1 -> 2) the stale generation-1 suggestions would
still list in the current view, and stale suggestions/roles remained
actionable.

### Fixes (all within T03 write scope)

| Acceptance item | Implementation + evidence |
|---|---|
| 1 public list defaults to ONLY current generation | `list_suggestions(source_generation=None, only_current=False)`; route defaults `only_current=True` when no explicit generation. Cross-video currentness resolved per video item (mirrors T01-C2 `list_roles`). `GET /suggestions` -> `scope=current` + `current_generation` echoed. |
| 2 source replacement 1 -> 2 hides gen-1 | `test_suggestion_list_current_only_and_source_replacement` drives real backend source replacement (video source artifact SHA + completed DISCOVER_OBJECTS jobs advance `current_generation` 1 -> 2); the current list shows ONLY the gen-2 suggestion; the gen-1 suggestion is absent. |
| 3 stale suggestion/role actions fail closed ZERO mutation | `dismiss_suggestion` asserts suggestion current; `apply_merge` asserts target + every source (+ optional suggestion) current; `apply_split`/`apply_confirm` assert target/role current — ALL before any write. `test_stale_suggestion_and_role_fail_closed_zero_mutation`: stale dismiss / merge / merge-by-suggestion / confirm all 409 with an identical durable-state snapshot; current actions still succeed. |
| 4 historical = explicit separate contract | `GET /suggestions?source_generation=N` (`scope=historical`, the ONLY way to inspect a non-current generation); stale detail -> 404 under current scope unless explicit matching generation (no existence leak); never mixed. |
| 5 generate filters by explicit current generation | `assert_generation_current` + route gate: `POST /suggestions/generate` for a non-current generation -> 409 with ZERO mutation (`test_generate_stale_generation_fails_closed`). |
| 6 T03-C1 guarantees preserved | Stable role IDs remain identity authority; policy metadata still exposed (/grouping/policy + generate payload: algorithm v1, calibration v2, threshold 0.35, advisory); everything advisory — no auto-confirm/auto-merge. All re-run green. |

### Validation — exact commands and results (fresh isolated roots, cache disabled)

```
1. Focused T03 (39): 39 passed, 53 warnings in 16.11s   [s08t03-c2-focused-r4]
2. T01-T05 combined (8 files incl sam2):
   186 passed, 370 warnings in 112.48s                [s08t03-c2-t01t05]
3. R01 (2 files): 18 passed, 18 warnings in 6.11s      [s08t03-c2-r01]
4. Migration round-trip (isolated subshell MOTIONFORGE_DATABASE_URL, unset
   verified after): upgrade head -> downgrade f5a6b7c8d9e0 -> upgrade head;
   final head f6a7b8c9d0e1; object_role_artifact + grouping tables present.
   No schema change by C2 itself.
5. S05 (7 files, SHALLOW basetemp): 41 passed, 81 warnings in 93.02s [s08t03-c2-s05]
6. S02 durable: 47 passed, 94 warnings in 24.16s       [s08t03-c2-s02]
7. Ruff (4 changed files): All checks passed!
8. Mypy: Success: no issues found in 86 source files
9. git diff --check: exit 0 (pre-existing CRLF advisories only)
10. git status --short: 161 entries (baseline identical; no new files)
```

### Protected data (re-verified, unchanged)

- MAIN channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- MAIN data/motionforge.db 311296 bytes, d5e6f7a8b9c0, 17 tables
- SAM2.1 checkpoint read-only never touched:
  `C:\Users\Admin\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt`
  (898083611 bytes, SHA-256
  `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318`,
  mtime 2026-07-29 21:06)
- No commit/push/reset/checkout/restore/clean/stash/delete; no bare
  TestClient outside pytest fixtures; no background children.

### Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged) — C2 correction round
complete; Codex sprint-exit review owns APPROVED/CLOSED.
