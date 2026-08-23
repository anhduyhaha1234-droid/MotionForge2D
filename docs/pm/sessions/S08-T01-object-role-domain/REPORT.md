# S08-T01 — Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager/Codex sprint-exit review owns approval)
**Hermes session:** `20260805_235138_61ad7a` (same session across interruption + recovery)
**Started:** 2026-08-05 23:59
**Submitted:** 2026-08-16
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-P00 APPROVED/CLOSED

## Outcome

Durable schema, repository/service and focused API contract for video-global
`ObjectRole` identity and scene/frame evidence in `ObjectOccurrence`, under the
isolated `/api/v2/object-intelligence` namespace. New durable truth lives in
SQLite (two new tables via one reversible Alembic migration); legacy object
data is exposed only through an explicit read-only compatibility mapping that
never writes and never becomes durable truth.

## Interruption / recovery history

1. First run (2026-08-05/06): implementation files were written (models,
   migration, persistence repo, tests, expectation updates); the run was
   interrupted (provider HTTP 502 after retries). An orphaned `codex exec`
   child kept writing files; it was located and terminated (PID 123296, the
   only process killed). All written changes were preserved and reviewed.
2. Recovery run (2026-08-16, same session id): guard re-verified; scope
   audited; 3 implementation incidents fixed (URL alias mismatch, legacy
   mapping payload `mode` field, mypy-typed response pattern); all validation
   gates re-run from scratch with NEW isolated basetemps; S05 production-wiring
   failure classified honestly (harness path-length incident, not a T01
   regression — evidence below); protected state re-verified read-only.

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `app/persistence/models.py` | +`ObjectRole`, +`ObjectOccurrence` ORM models (stable UUID ids, workspace/project/video_item FKs RESTRICT, role self-FK, confidence 0..1 CHECK, status/review-state/confidence-source CHECKs, revision CAS, timestamps, partial unique idempotency index, lookup indexes) + 4 domain constants, `__all__` entries |
| `migrations/versions/e7f8a9b0c1d2_object_intelligence_schema.py` | NEW reversible migration (down_revision `d5e6f7a8b9c0`); upgrade creates both tables + all constraints/indexes; downgrade drops them in reverse FK order |
| `app/persistence/object_intelligence.py` | NEW repository/service: `ObjectIntelligenceRepository` (create/get/list/update role with CAS + idempotency key; create/get/list/update occurrence with natural-key idempotency; fail-closed cross-owner validation; pure read-only `map_legacy_objects`), frozen records, typed exceptions |
| `app/schemas/object_intelligence.py` | NEW Pydantic v2 DTOs: RoleCreate/Update, OccurrenceCreate/Update, BboxInput, RoleData/OccurrenceData (from_record), RoleListResponse, LegacyMappingItemData/Response |
| `app/api/routes/object_intelligence.py` | NEW router `/api/v2/object-intelligence`: POST/GET role collection (with `/roles` aliases), GET/PATCH role, GET/POST occurrences, PATCH occurrence, GET legacy-mapping (read-only). Error mapping 404/409/422; rollback before raise; commit on success only; idempotent replay → 200 |
| `app/api/app.py` | one import + one `include_router` line (no deps.py change needed — `SessionDep`/`get_project_workflow` already exist) |
| `tests/test_object_intelligence_domain.py` | NEW focused suite — 21 tests (migration, constraints, repository, concurrency, zero-mutation, API, legacy mapping) |
| `tests/test_persistence_bootstrap.py` | required exact-schema expectation updates: `S08_HEAD_TABLES`, head revision `e7f8a9b0c1d2`, ancestry assertions (7 sites) |
| `tests/test_durable_job_persistence.py` | required table-set expectation update: +`object_role`, +`object_occurrence` in `test_no_worker_or_api_cutover_tables` |
| `docs/pm/sessions/S08-T01-object-role-domain/LOG.md` | baseline + recovery sections (append-only, real evidence) |
| `docs/pm/sessions/S08-T01-object-role-domain/REPORT.md` | this report |

No changes to: deps.py, frontend/, legacy object code, S05/S06 contracts,
TASK.md, sprint contract, PM_REVIEW.md, channels.json, data/, any database,
fixtures, backups, MAIN or other worktrees.

## Acceptance criteria — evidence

| AC | Evidence |
|---|---|
| Migration round-trip and existing-database upgrade pass in temporary storage | `test_migration_round_trip_upgrade_downgrade_upgrade`, `test_existing_database_upgrade_preserves_rows` + CLI round trip (upgrade → downgrade `d5e6f7a8b9c0` → upgrade; final head `e7f8a9b0c1d2`; seeded workspace/channel rows preserved; all CHECKs/FKs/indexes verified in DDL) |
| Stable identity, ownership, constraints, CAS, idempotency, concurrent creation/update | tests: `test_create_role_stable_uuid_and_defaults`, `test_cross_owner_project_rejected`, `test_cross_owner_scene_rejected`, `test_head_tables_and_constraints_enforced` (FK/confidence/status/natural-key IntegrityErrors), `test_role_cas_stale_revision_conflict`, `test_role_cas_success_bumps_revision`, `test_concurrent_update_cas_last_writer_wins_conflict`, `test_concurrent_create_same_idempotency_key_single_row`, `test_idempotent_create_role_same_key`, `test_idempotent_create_occurrence_natural_key` |
| GET endpoints cause zero durable mutations | `test_get_operations_zero_durable_mutations`, `test_api_get_endpoints_zero_durable_mutations` (revision + row snapshots before/after GETs identical); GET routes perform no commit |
| No production path relies on legacy index/name identity | All production code (models/repo/routes) uses stable UUID `id`; `legacy_object_id`/`legacy_scene_id` are nullable reference columns only; `map_legacy_objects` assigns EPHEMERAL uuid4 ids that are never persisted; legacy records are never written |
| Relevant persistence/project/video/source-supersession regressions pass | 160/160 (persistence_bootstrap + durable_job_persistence + project_crud + video_item_crud); S05 preservation suite 41/41; S05 production-wiring 2 fresh passes (see incident below) |

Status semantics: roles default to `suggested`; `confirmed` is an explicit
user update; `superseded` requires a supersedes target and is terminal —
model suggestions are never silently promoted to user truth.

## Validation — exact commands and results

All runs: `-p no:cacheprovider`, isolated basetemps. Run roots:
`output/s08-sprint/20260806-s08t01-r1/` (first attempt),
`output/s08-sprint/20260806-s08t01-r2/` (recovery), shallow S05 runs under
`C:/Users/Admin/AppData/Local/Temp/s08t01-s05-*`.

```
1. Focused S08-T01 (cache disabled):
   python -m pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider \
     --basetemp=.../output/s08-sprint/20260806-s08t01-r2/t01-focused
   -> 21 passed, 22 warnings in 16.19s
   (re-run after route refactor, new basetemp t01-focused2 -> 21 passed in 8.90s)

2. Migration CLI round trip (fresh temp DB):
   python -m alembic upgrade head && python -m alembic downgrade d5e6f7a8b9c0 \
     && python -m alembic upgrade head
   -> Running upgrade d5e6f7a8b9c0 -> e7f8a9b0c1d2 (x2), downgrade e7f8a9b0c1d2 -> d5e6f7a8b9c0
   -> alembic_version: e7f8a9b0c1d2; object tables present; seeded rows preserved;
      all CHECK/FK/index objects verified (see LOG.md)

3. S05 preservation suite (shallow basetemp):
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
     tests/test_s05_golden_integration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-s05-suite
   -> 41 passed, 41 warnings in 83.09s

4. Persistence/project/video regressions:
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
     tests/test_project_crud.py tests/test_video_item_crud.py -q -p no:cacheprovider \
     --basetemp=.../output/s08-sprint/20260806-s08t01-r2/reg-persistence
   -> 160 passed, 154 warnings in 54.24s

5. Ruff on all changed Python files:
   python -m ruff check app/persistence/models.py app/persistence/object_intelligence.py \
     app/schemas/object_intelligence.py app/api/routes/object_intelligence.py app/api/app.py \
     migrations/versions/e7f8a9b0c1d2_object_intelligence_schema.py \
     tests/test_object_intelligence_domain.py tests/test_persistence_bootstrap.py \
     tests/test_durable_job_persistence.py
   -> All checks passed!

6. Mypy:
   python -m mypy app
   -> Success: no issues found in 75 source files

7. git diff --check -> exit 0 (pre-existing CRLF advisories only)
8. git status --short -> 105 entries (baseline 100 + LOG.md + 4 in-scope files);
   no stray/out-of-scope files (see LOG.md)
```

## S05 production-wiring incident (observed, classified, NOT a T01 regression)

- Symptom: with DEEP basetemps under `output/s08-sprint/<run-id>/...`,
  `test_default_production_wiring_chain_completes_and_resumes` failed —
  ANALYZE_MEDIA job `INPUT_UNREADABLE` on `...artifacts/staging/<job>/import/.cfr_cut.mp4.<uuid>.staging`.
- Root cause (proven by standalone reproduction): the managed staging path is
  271 characters > Windows MAX_PATH (260); `open("xb")` fails with
  `[Errno 2] No such file or directory` — byte-identical to the job error.
- Fresh verification, two runs on NEW shallow basetemps:
  - run1: `1 passed in 23.66s`
  - run2: `1 passed in 24.38s`
- Classification: transient regression-harness/runtime incident caused by
  basetemp path depth, not by T01 schema/router changes. No S05 code modified.
  (Full S05 suite with shallow basetemp: 41/41 — parity with P00.)

## Isolation and protected state

- All tests/runtime/migrations used NEW isolated roots and databases under
  `output/s08-sprint/20260806-s08t01-r1/` and `-r2/` (plus shallow temp roots
  for the MAX_PATH-sensitive S05 wiring test). No production database was ever
  targeted; worktree `alembic.ini` intentionally sets no URL.
- MAIN `channels.json` SHA-256 (certutil): `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  == `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555` — UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes (unchanged); read-only inspection:
  `alembic_version = d5e6f7a8b9c0`, 17 tables, `object_role` ABSENT — the S08
  migration never ran on MAIN; content preserved.
- MAIN/S06 status: MAIN 46 entries (P00 reference 45; +1 =
  `scripts/watch-s08-t01.sh`, a sprint-launcher artifact not created by this
  session); `s06-t01-review` 45 (unchanged).
- No commit/push/deploy/merge/reset/checkout/restore/clean/stash/delete;
  all pre-existing uncommitted changes preserved.

## Deviations and risks

1. MAIN `data/motionforge.db` mtime is 2026-08-06 00:15:10 vs the P00
   reference 2026-08-04 18:24:36. Size/schema/version verified unchanged;
   suspected no-op open/touch by an external process. Recorded honestly;
   no content change detected.
2. `test_durable_job_persistence.py` and `test_persistence_bootstrap.py`
   expectation updates are required consequences of the S08 migration
   (head `d5e6f7a8b9c0` → `e7f8a9b0c1d2`, +2 tables) — same precedent as the
   S06 table-set additions.
3. Deep basetemp paths (>260 chars) trigger a Windows MAX_PATH failure in the
   S05 production-wiring harness (managed `artifacts/staging/<job>/import/`
   chain). Future S05 wiring runs in this sprint MUST use shallow basetemps
   (e.g. `C:/Users/Admin/AppData/Local/Temp/s08t01-*`).
4. Legacy-mapping endpoint returns 500 for a legacy project.json that fails
   Pydantic validation (e.g., missing `selection.mode`); acceptable for the
   T01 read-only compatibility surface (S05 preflight owns validation) and
   covered by the corrected test payload.
5. No frontend/UI work was in scope for T01 (T04 owns gallery UI); the API is
   the contract for later tasks.

## Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` — T01 deliverables complete and
verified; Codex review at sprint exit owns APPROVED/CLOSED.

---

## CORRECTION ROUND C1 — 2026-08-16 (Codex CHANGES_REQUESTED)

Status remains **SUBMITTED** (never APPROVED). All 5 findings fixed in the same
Hermes session `20260805_235138_61ad7a`; full history preserved (baseline +
recovery + correction in LOG.md).

### Finding 1 — Occurrence route ownership (FIXED)

`PATCH /api/v2/object-intelligence/roles/{role_id}/occurrences/{occurrence_id}`
previously discarded `role_id`. Now the repository requires the exact role:
`get_occurrence`/`update_occurrence` are scoped by (id, workspace_id, role_id)
and the atomic UPDATE predicate includes `role_id`. A role-A URL targeting a
role-B occurrence fails closed (404 OccurrenceNotFoundError, no existence
leak, no mutation).
Evidence: `test_occurrence_role_mismatch_read_fails_closed`,
`test_occurrence_role_mismatch_update_fails_closed`,
`test_api_role_a_url_cannot_read_or_update_role_b_occurrence` — role-B list
excludes role-A's occurrence; role-B PATCH on role-A occurrence returns 404
and the occurrence stays untouched (confidence still 0.5).

### Finding 2 — Supersession ownership/validity (FIXED)

`update_role` supersede transitions now validate the target through
`_validate_supersession_target`: target must exist in the SAME workspace,
project, video item and source generation; self-reference, missing target and
terminal (already-superseded) targets are rejected. All violations raise the
stable `RoleConflictError` → HTTP 409. Codex's reproduced cross-workspace
supersession now returns 409.
Evidence: `test_supersession_cross_workspace_rejected`,
`test_supersession_cross_project_rejected`,
`test_supersession_cross_video_rejected`,
`test_supersession_cross_generation_rejected`,
`test_supersession_self_rejected`, `test_supersession_terminal_target_rejected`
(+ `test_status_transitions` updated so its target shares the source
generation, which the new rule correctly requires).

### Finding 3 — Real atomic CAS (FIXED)

Read-compare-write replaced by a database-atomic predicate for BOTH role and
occurrence mutations:
`UPDATE ... WHERE id = ? AND workspace_id = ? [AND role_id = ?] AND revision = ?`
with `revision = revision + 1` and exactly one affected row required
(`UPDATE ... RETURNING`, `scalar_one()`; zero rows → conflict). Domain
validation (terminal status, supersession target) is read-side only; the write
decision is the DB predicate.
Genuine concurrency test added: `test_concurrent_cas_atomic_exactly_one_writer_wins`
— two threads, separate sessions/engines over the same SQLite file, both
read revision 1, `threading.Barrier` synchronization, both attempt the CAS at
revision 1; exactly one commits, the other receives RoleConflictError; final
revision 2. Ran green 5/5 consecutive times.

### Finding 4 — Idempotency collision semantics (FIXED)

A reused idempotency key (roles) or natural key (occurrences) now replays ONLY
an equivalent canonical request. `_assert_equivalent_role_request` compares
project/video/generation/name/kind/status/description/legacy refs;
`_assert_equivalent_occurrence_request` compares time_ms/bbox/confidence/
source/algorithm/version/reasons/review_state. Materially different payloads →
stable 409 (RoleConflictError/OccurrenceConflictError) — never a replay of
another resource. Applies to both the direct-hit and concurrent
IntegrityError paths. Routes map the new conflicts to 409.
Evidence: `test_idempotency_key_different_project_conflict`,
`test_idempotency_key_different_generation_conflict`,
`test_idempotency_key_different_payload_conflict`,
`test_occurrence_natural_key_different_payload_conflict`,
`test_api_idempotency_collision_conflict` (key-reuse with different project →
409; natural-key reuse with different confidence → 409). Equivalent replays
unchanged (201 → 200, same id).

### Finding 5 — Preservation (VERIFIED)

No assertions weakened, no skips/ignores. Migration round-trip, read-only GET
zero-mutation, stable UUID identity, source supersession, S05 lifecycle and
S06 behavior re-verified in full (below).

### Validation results (correction round; cache disabled, fresh isolated basetemps)

| Gate | Command | Result |
|---|---|---|
| Focused S08-T01 (36 tests) | `pytest tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=.../20260816-s08t01-c1/focused4` | `36 passed, 37 warnings in 16.52s` (final re-run 13.95s) |
| Genuine concurrent CAS | same test x5 fresh basetemps | `1 passed` x5 |
| Migration CLI round trip | `alembic upgrade head` → `downgrade d5e6f7a8b9c0` → `upgrade head` (fresh temp DB) | version `e7f8a9b0c1d2`; both tables; seeded row preserved |
| Persistence/project/video regressions | `pytest test_persistence_bootstrap test_durable_job_persistence test_project_crud test_video_item_crud` | `160 passed, 154 warnings in 53.97s` |
| S05 targeted 41-test suite | `pytest <7 s05 files> --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t01-c1-s05` (SHALLOW) | `41 passed, 41 warnings in 84.18s` |
| Ruff (all changed files) | `python -m ruff check <9 files>` | `All checks passed!` |
| Mypy | `python -m mypy app` | `Success: no issues found in 75 source files` |
| git diff --check | `git diff --check` | exit 0 (CRLF advisories only) |
| Final git status | `git status --short` | 105 entries (scope unchanged, no new files) |
| Protected data | certutil MAIN channels.json; MAIN db stat | SHA-256 `dd7aae...555` unchanged; motionforge.db 311296 bytes unchanged |

### Deviations / notes (correction round)

1. One pre-existing test fixture was corrected, not weakened:
   `test_status_transitions` created its supersession target with a different
   source generation ("g" vs "gen-1"); the new F2 validation correctly rejects
   that, so the fixture now uses the same generation.
2. The two API routes gained `except RoleConflictError/OccurrenceConflictError
   → 409` mappings for the new conflict paths (previously unhandled → 500).
3. Windows MAX_PATH lesson applied: the S05 suite used a shallow basetemp
   (`C:/Users/Admin/AppData/Local/Temp/s08t01-c1-s05`), never a deep
   `output/s08-sprint/...` path.

### Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged) — correction round
complete; Codex sprint-exit review owns APPROVED/CLOSED.

---

## CORRECTION ROUND C2 — 2026-08-16 (Codex CHANGES_REQUESTED: CURRENT-GENERATION ROLE LISTING)

Status remains **SUBMITTED** (never APPROVED). Same Hermes session
`20260805_235138_61ad7a`; all history preserved (baseline + recovery + C1 + C2
in LOG.md). No migration (head `f6a7b8c9d0e1` unchanged). Uses the
backend-authoritative current source generation (T02-C2 in tree).

### Acceptance evidence

| AC | Fix + evidence |
|---|---|
| 1 list defaults to current generation | Public `GET /roles` returns ONLY roles whose `source_generation` equals the backend current generation of their video item (`scope="current"`, `current_generation` echoed). `test_api_list_defaults_current_generation_historical_explicit`, `test_list_roles_current_only_and_explicit_generation` (incl. cross-video no-filter case). |
| 2 source replacement 1→2 hides gen-1 | `current_generation()` is authoritative: `video_item.source_artifact_id → Artifact.sha256`, then newest COMPLETED `DISCOVER_OBJECTS` job whose manifest `source_sha256` matches (else max completed generation + 1). After the source advances, gen-1 roles drop out of the default list and appear ONLY via explicit `generation=1`. `test_api_source_replacement_hides_generation1_roles` (Gen1 Hero hidden after replace), `test_current_generation_advances_with_completed_jobs` (different-source job never advances current). |
| 3 stale-role apply/correction fail closed, ZERO mutation | `update_role` and `update_occurrence` enforce `_assert_role_current` before any write → `RoleConflictError` (409), revision/fields unchanged. `test_stale_role_update_fails_closed_zero_mutation`, `test_stale_role_occurrence_update_fails_closed`, `test_api_stale_role_detail_and_patch_fail_closed`, golden-path post-replacement stale-correction rejected. |
| 4 historical = explicit separate contract | `GET /roles?generation=N` is the only way to view a non-current generation; response `scope` is `"current"` (N == backend current) or `"historical"` (explicit, never mixed); role detail is 404 under the current scope unless an explicit matching `generation` is supplied. |
| 5 list/detail filter by explicit current generation | Server resolves current generation (never from client hints) and applies it as the default filter; `current_generation` returned for client assertion. |
| 6 stable role IDs remain authority | Filter is by generation value, never name/index. All T01-C1 guarantees preserved (read-only GET zero-mutation, atomic CAS, idempotency equivalence, ownership, concurrency) — re-verified by the full 45-test focused suite. |
| 7 repo + API tests | 8 new C2 tests (resolver ×2, list/detail scope ×2, stale-mutation ×2, API ×3 of the 8) under `tests/test_object_intelligence_domain.py` (45 total). |

### Files changed

- `app/persistence/object_intelligence.py` — `current_generation()` +
  `_current_generation_for_source()` + `_current_generation_map()` +
  `_assert_role_current()` (fail-closed stale guard on `update_role` /
  `update_occurrence`); `list_roles(source_generation=…, only_current=…)`
  (incl. per-video currentness without a video filter); `get_role(
  only_current=…, source_generation=…)`.
- `app/schemas/object_intelligence.py` — `RoleListResponse.scope` +
  `current_generation`.
- `app/api/routes/object_intelligence.py` — `list_roles(generation=…)` with
  current/default + explicit historical scope resolution; `get_role(
  generation=…)` current-scope fail-closed detail.
- `tests/test_object_intelligence_domain.py` — 8 new C2 tests; generation
  strings canonicalized (`"gen-1"→"1"`, `"g"→"1"`, `"gen-2"→"2"`).
- REQUIRED sibling fixture alignment (no assertion weakened, each disclosed):
  `tests/test_object_correction.py` + `tests/test_object_correction_api.py`
  seed source jobs now carry the real `source_sha256` (and the API file's
  `_seed_video` wires the source Artifact) so gen-1 roles are genuinely
  current under the backend authority; `tests/test_object_grouping.py`
  generation labels normalized to the authoritative numeric namespace.

### Deviations / notes (C2)

1. Scope decision: `create_occurrence` is NOT treated as a stale-role
   operation — evidence CREATION is the T02 extraction pipeline's contract
   (the worker attaches evidence to roles it created for the current run).
   The fail-closed stale guard targets APPLY/CORRECTION-style mutations
   (`update_role`, `update_occurrence`) per AC3. Documented in code and LOG.
2. Three sibling test files were fixture-aligned (not weakened): their seeds
   now match the backend-authoritative current generation. Every change is
   listed above; a T05 concurrent-confirm failure observed in one combined
   run passed in isolation and in the final combined run (timing flake —
   investigated, not a T01 regression).
3. One `test_concurrent_confirm_exactly_one_wins` flake observed during the
   combined run then passed standalone + in the final combined run — recorded
   honestly; no code change made for it.

### Validation results (C2; fresh isolated roots, cache disabled, shallow basetemps)

| Gate | Command | Result |
|---|---|---|
| Focused T01-C2 (45) | `pytest tests/test_object_intelligence_domain.py` | `45 passed, 91 warnings in 24.36s` (final 24.24s) |
| T01-T05 combined (6 files) | `pytest test_object_intelligence_domain test_object_grouping test_object_extraction test_object_extraction_api test_object_correction test_object_correction_api` | `181 passed, 333 warnings in 99.81s` |
| R01 suites | `pytest test_s08_r01_queued_cancel_lifecycle test_s08_r01_root_resolution` | `18 passed, 18 warnings in 6.26s` |
| Migration round-trip | isolated subshell `upgrade head` → `downgrade f5a6b7c8d9e0` → `upgrade head` | head `f6a7b8c9d0e1`; object tables present; env unset after |
| S05 41-suite (shallow) | `pytest <7 s05 files> --basetemp=...s08t01-c2-s05` | `41 passed, 81 warnings in 94.28s` |
| S02 durable regressions | `pytest test_durable_job_persistence test_durable_job_api` | `63 passed, 121 warnings in 38.69s` |
| Ruff (7 changed files) | `python -m ruff check <7 files>` | `All checks passed!` |
| Mypy | `python -m mypy app` | `Success: no issues found in 86 source files` |
| git diff --check | `git diff --check` | exit 0 |
| Final git status | `git status --short` | 161 entries (no new files) |
| Protected data | certutil + read-only DB + checkpoint | channels.json `dd7aae...555` UNCHANGED; MAIN DB 311296 B / `d5e6f7a8b9c0` UNCHANGED; SAM2.1 898083611 B / `2647878d...` UNCHANGED |

### Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (unchanged) — C2 complete; Codex
sprint-exit review owns APPROVED/CLOSED.

## Manager verification (2026-08-16, post-C1)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** — recorded by the
sprint manager after independent re-run and code audit. NOT APPROVED; Codex
sprint-exit review owns approval.

Manager re-runs (independent basetemps): focused T01 36/36 (13.81s), S05
41-suite 41/41 (81.72s, shallow basetemp), persistence/project/video 160/160
(53.45s). Code audit confirmed all 5 Codex findings addressed (see LOG.md
MANAGER VERIFICATION section for per-finding detail). Protected state
re-verified unchanged (channels.json SHA dd7aae26…555, MAIN DB 311296 B, S06
tree 45 entries). Writer session lineage: 20260805_235138_61ad7a
(first run -> resume -> C1 correction round, all same session).
